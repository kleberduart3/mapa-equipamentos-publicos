"""Cadastro de equipamentos: conferência e ajustes da prefeitura.

    GET    /api/{cod}/ajustes/equipamentos?tipo=creche   lista do tipo (oficial × ajustado); todas as contas
    POST   /api/{cod}/ajustes/equipamentos               inclui uma unidade nova (só gestor)
    PUT    /api/{cod}/ajustes/equipamentos/{chave}       altera nome, endereço, local, capacidade,
                                                         equipes ou situação (só gestor)
    DELETE /api/{cod}/ajustes/equipamentos/{chave}       desfaz os ajustes de uma unidade oficial
                                                         ou apaga uma unidade incluída (só gestor)

A chave é inep:{código}, cnes:{código} ou pref:{n} (ver analise/ajustes.py).
Toda escrita grava o arquivo de ajustes do município, limpa os caches (o mapa e o
relatório passam a usar os números novos) e fica na trilha de atividade.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import servicos
from ..acesso import credenciais as cr
from ..acesso.modelos import nova_sessao_db
from ..acesso.web import gerir_municipio, ip_cliente, ver_municipio
from ..analise import ajustes as aj
from ..analise.contexto import base
from ..config import municipio

rotas = APIRouter(prefix="/api/{cod}/ajustes/equipamentos", tags=["equipamentos"])

MAX_UNIDADES_NOVAS = 500
REDES = Literal["Municipal", "Estadual", "Federal"]


class _Rigido(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Alteracao(_Rigido):
    """Campos ausentes ficam como estão; null num campo devolve o dado oficial."""
    tipo: str = Field(pattern=r"^[a-z0-9_]{1,40}$")           # a lista em que a pessoa está editando
    nome: str | None = Field(default=None, min_length=2, max_length=160)
    endereco: str | None = Field(default=None, max_length=240)
    lat: float | None = Field(default=None, ge=-35, le=6)
    lon: float | None = Field(default=None, ge=-75, le=-28)
    capacidade: int | None = Field(default=None, ge=0, le=1_000_000)
    equipes: int | None = Field(default=None, ge=0, le=60)
    excluida: bool | None = None

    @field_validator("lon")
    @classmethod
    def _par(cls, v, info):
        if (v is None) != (info.data.get("lat") is None):
            raise ValueError("informe latitude e longitude juntas")
        return v


class Nova(_Rigido):
    tipo: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    nome: str = Field(min_length=2, max_length=160)
    endereco: str | None = Field(default=None, max_length=240)
    lat: float = Field(ge=-35, le=6)
    lon: float = Field(ge=-75, le=-28)
    capacidade: int | None = Field(default=None, ge=0, le=1_000_000)
    equipes: int | None = Field(default=None, ge=0, le=60)
    rede: REDES = "Municipal"


def _tipo(cod: str, t: str) -> dict:
    try:
        servicos.checa_tipo(cod, t)
    except servicos.TipoDesconhecido:
        raise HTTPException(404, "Tipo de equipamento desconhecido.") from None
    return servicos.tipos(cod)[t]


def _dentro(cod: str, lat: float, lon: float) -> None:
    from shapely.geometry import Point
    import geopandas as gpd

    b = base(cod)
    p = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326").to_crs(b.limite.crs).iloc[0]
    if not b.limite.geometry.iloc[0].buffer(1000).contains(p):
        raise HTTPException(400, "O local fica fora do município. Confira o ponto no mapa.")


def _autor(acesso) -> str:
    u = acesso[0]
    return u.email


def _registrar(request: Request, acesso, acao: str, detalhe: str) -> None:
    with nova_sessao_db() as s:
        cr.registrar(s, acao, acesso[0].id, detalhe=detalhe, ip=ip_cliente(request))
        s.commit()


def _depois_de_gravar(cod: str) -> None:
    servicos.esquecer(cod)


@rotas.get("")
def listar(cod: str, tipo: str = Query(..., max_length=40), acesso=Depends(ver_municipio)):
    _tipo(cod, tipo)
    return {**servicos.lista_equipamentos(cod, tipo), "pode_editar": acesso[1] == "gestor"}


@rotas.put("/{chave}")
async def alterar(cod: str, chave: str, dados: Alteracao, request: Request, acesso=Depends(gerir_municipio)):
    if not aj.CHAVE.match(chave):
        raise HTTPException(404, "Unidade não encontrada.")
    cfg = _tipo(cod, dados.tipo)
    enviados = dados.model_fields_set - {"tipo"}
    if not enviados:
        raise HTTPException(400, "Nada para alterar.")
    if dados.lat is not None:
        await run_in_threadpool(_dentro, cod, dados.lat, dados.lon)
    ubs = cfg["fonte_dados"] == "cnes"
    if "equipes" in enviados and not ubs:
        raise HTTPException(400, "Equipes só valem para unidades de saúde.")
    # a unidade precisa existir na lista deste tipo (impede editar chaves inventadas)
    lista = await run_in_threadpool(servicos.lista_equipamentos, cod, dados.tipo)
    if not any(l["chave"] == chave for l in lista["linhas"]):
        raise HTTPException(404, "Unidade não encontrada nesta lista.")
    autor = _autor(acesso)

    def mudar(d: dict):
        a = d["unidades"].setdefault(chave, {})
        for campo in ("nome", "endereco", "equipes", "excluida"):
            if campo in enviados:
                v = getattr(dados, campo)
                if v is None or (campo == "excluida" and v is False and not chave.startswith("pref:")):
                    a.pop(campo, None)
                else:
                    a[campo] = v
        if "lat" in enviados or "lon" in enviados:
            if dados.lat is None:
                if chave.startswith("pref:"):
                    raise HTTPException(400, "Unidade incluída pela prefeitura precisa ter local no mapa.")
                a.pop("lat", None), a.pop("lon", None)
            else:
                a["lat"], a["lon"] = round(dados.lat, 6), round(dados.lon, 6)
        if "capacidade" in enviados:
            cap = a.setdefault("capacidade", {})
            if dados.capacidade is None:
                cap.pop(dados.tipo, None)
            else:
                cap[dados.tipo] = dados.capacidade
            if not cap:
                a.pop("capacidade")
        meta = {k for k in a if k not in ("alterado_por", "alterado_em")}
        if not meta:                                  # voltou tudo ao oficial
            d["unidades"].pop(chave, None)
            return None
        a.update(aj.carimbo(autor))
        return dict(a)

    m = municipio(cod)
    resultado = await run_in_threadpool(aj.alterar, m, mudar)
    _depois_de_gravar(cod)
    _registrar(request, acesso, "ajuste_equipamento",
               f"{cod} {chave} ({dados.tipo}): " + ", ".join(f"{k}={getattr(dados, k)!r}" for k in sorted(enviados)))
    return {"ok": True, "chave": chave, "ajuste": resultado}


@rotas.post("")
async def incluir(cod: str, dados: Nova, request: Request, acesso=Depends(gerir_municipio)):
    cfg = _tipo(cod, dados.tipo)
    await run_in_threadpool(_dentro, cod, dados.lat, dados.lon)
    ubs = cfg["fonte_dados"] == "cnes"
    if ubs and dados.equipes is None and dados.capacidade is None:
        raise HTTPException(400, "Informe o número de equipes ou a capacidade em pessoas.")
    if not ubs and dados.capacidade is None:
        raise HTTPException(400, "Informe a capacidade (vagas) da unidade.")
    if dados.equipes is not None and not ubs:
        raise HTTPException(400, "Equipes só valem para unidades de saúde.")
    autor = _autor(acesso)

    def criar(d: dict):
        novas = sum(1 for k in d["unidades"] if k.startswith("pref:"))
        if novas >= MAX_UNIDADES_NOVAS:
            raise HTTPException(400, "Limite de unidades incluídas atingido.")
        n = int(d.get("proximo", 1))
        d["proximo"] = n + 1
        chave = f"pref:{n}"
        a = {"nova": True, "fonte": "ubs" if ubs else "escola", "nome": dados.nome,
             "endereco": dados.endereco, "lat": round(dados.lat, 6), "lon": round(dados.lon, 6),
             "rede": "Municipal" if ubs else dados.rede, "criada_em_tipo": dados.tipo}
        if dados.capacidade is not None:
            a["capacidade"] = {dados.tipo: dados.capacidade}
        if dados.equipes is not None:
            a["equipes"] = dados.equipes
        a.update(aj.carimbo(autor))
        d["unidades"][chave] = a
        return chave

    m = municipio(cod)
    chave = await run_in_threadpool(aj.alterar, m, criar)
    _depois_de_gravar(cod)
    _registrar(request, acesso, "inclusao_equipamento", f"{cod} {chave} ({dados.tipo}): {dados.nome}")
    return {"ok": True, "chave": chave, "id": aj.id_da_chave(chave)}


@rotas.delete("/{chave}")
async def desfazer(cod: str, chave: str, request: Request, acesso=Depends(gerir_municipio)):
    """Unidade oficial: apaga os ajustes e volta ao dado do INEP/CNES. Incluída: apaga a unidade."""
    if not aj.CHAVE.match(chave):
        raise HTTPException(404, "Unidade não encontrada.")

    def tirar(d: dict):
        return d["unidades"].pop(chave, None)

    m = municipio(cod)
    antes = await run_in_threadpool(aj.alterar, m, tirar)
    if antes is None:
        raise HTTPException(404, "Esta unidade não tem ajustes.")
    _depois_de_gravar(cod)
    acao = "remocao_equipamento" if chave.startswith("pref:") else "ajuste_desfeito"
    _registrar(request, acesso, acao, f"{cod} {chave}: {antes.get('nome') or ''}".strip())
    return {"ok": True}
