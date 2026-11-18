"""Ajustes de equipamentos pela prefeitura (gestor do município ou administrador).

    GET    /api/{cod}/ajustes                    ajustes feitos e unidades sem localização (todos com acesso veem)
    PUT    /api/{cod}/ajustes/{fonte}/{id}       corrige local, nome, capacidade ou situação de uma unidade
    POST   /api/{cod}/ajustes                    inclui uma unidade que não está no INEP/CNES
    DELETE /api/{cod}/ajustes/{fonte}/{id}       desfaz o ajuste (volta ao dado oficial; apaga a unidade incluída)

Os dados oficiais não mudam: ver backend/app/ajustes.py. Cada alteração fica no registro de eventos.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator
from shapely.geometry import Point

from .. import ajustes, servicos
from ..acesso import credenciais as cr
from ..acesso.modelos import nova_sessao_db
from ..acesso.web import gerir_municipio, ip_cliente, ver_municipio
from ..analise.contexto import base
from ..config import municipio

rotas = APIRouter(prefix="/api/{cod}/ajustes", tags=["ajustes"])
Fonte = Literal["escola", "ubs"]
REF = r"^[A-Za-z0-9-]{1,20}$"


class _Rigido(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Edicao(_Rigido):
    lat: float | None = Field(None, ge=-34, le=6)          # território brasileiro
    lon: float | None = Field(None, ge=-75, le=-28)
    nome: str | None = Field(None, min_length=3, max_length=120)
    ativo: bool | None = None
    capacidade: dict[str, int] | None = None
    endereco: str | None = Field(None, max_length=200)
    obs: str | None = Field(None, max_length=300)

    @field_validator("capacidade")
    @classmethod
    def _cap(cls, v):
        if v is not None and any(not 0 <= n <= 100_000 for n in v.values()):
            raise ValueError("capacidade fora do intervalo")
        return v


class Nova(Edicao):
    fonte: Fonte
    nome: str = Field(min_length=3, max_length=120)
    lat: float = Field(ge=-34, le=6)
    lon: float = Field(ge=-75, le=-28)


def _validar(cod: str, fonte: str, e: Edicao) -> dict:
    tipos = servicos.tipos(cod)
    validos = [t for t, c in tipos.items() if (c["fonte_dados"] == "cnes") == (fonte == "ubs")]
    for t in e.capacidade or {}:
        if t not in validos:
            raise HTTPException(400, f"Capacidade de “{t}” não se aplica a {'UBS' if fonte == 'ubs' else 'escola'}.")
    if (e.lat is None) != (e.lon is None):
        raise HTTPException(400, "Informe latitude e longitude juntas.")
    if e.lat is not None:
        b = base(cod)
        import geopandas as gpd
        p = gpd.GeoSeries([Point(e.lon, e.lat)], crs="EPSG:4326").to_crs(b.limite.crs).iloc[0]
        if not b.limite.geometry.iloc[0].buffer(1000).contains(p):
            raise HTTPException(400, "Esse ponto fica fora do município.")
    d = e.model_dump(exclude={"fonte"})
    for k in ("nome", "endereco", "obs"):
        if d.get(k):
            d[k] = " ".join(d[k].split())
    return d


def _registrar(request: Request, u, evento: str, detalhe: str) -> None:
    with nova_sessao_db() as s:
        cr.registrar(s, evento, u.id, ip=ip_cliente(request), detalhe=detalhe)
        s.commit()


def _existe(cod: str, fonte: str, ref: str) -> bool:
    b = base(cod)
    return bool((b.escolas["codigo_inep"] == ref).any() if fonte == "escola" else (b.ubs["cnes"] == ref).any())


@rotas.get("")
def listar(cod: str, _=Depends(ver_municipio)):
    return {"ajustes": servicos.lista_ajustes(cod), "sem_localizacao": servicos.sem_localizacao(cod)}


@rotas.put("/{fonte}/{ref}")
async def editar(cod: str, fonte: Fonte, ref: str, dados: Edicao, request: Request, acesso=Depends(gerir_municipio)):
    import re
    if not re.match(REF, ref) or not _existe(cod, fonte, ref):
        raise HTTPException(404, "Unidade não encontrada.")
    d = _validar(cod, fonte, dados)
    if not any(v is not None for v in d.values()):
        raise HTTPException(400, "Nada para alterar.")
    u = acesso[0]
    k = ajustes.salvar(municipio(cod), ajustes.chave(fonte, ref), {**d, "fonte": fonte}, u.email)
    _registrar(request, u, "equipamento_ajustado", f"{cod} {k} {ajustes.resumo(d)}")
    await run_in_threadpool(servicos.recalcular, cod)
    return {"ok": True, "chave": k}


@rotas.post("", status_code=201)
async def incluir(cod: str, dados: Nova, request: Request, acesso=Depends(gerir_municipio)):
    d = _validar(cod, dados.fonte, dados)
    if not any((dados.capacidade or {}).values()):
        raise HTTPException(400, "Informe o que a unidade atende: matrículas por etapa (escola) ou equipes (UBS).")
    u = acesso[0]
    k = ajustes.salvar(municipio(cod), None, {**d, "fonte": dados.fonte, "ativo": True}, u.email)
    _registrar(request, u, "equipamento_incluido", f"{cod} {k} {d['nome']}")
    await run_in_threadpool(servicos.recalcular, cod)
    return {"ok": True, "chave": k}


@rotas.delete("/{fonte}/{ref}")
async def desfazer(cod: str, fonte: Fonte, ref: str, request: Request, acesso=Depends(gerir_municipio)):
    item = ajustes.remover(municipio(cod), ajustes.chave(fonte, ref))
    if item is None:
        raise HTTPException(404, "Ajuste não encontrado.")
    _registrar(request, acesso[0], "equipamento_ajuste_desfeito", f"{cod} {fonte}:{ref} {ajustes.resumo(item)}")
    await run_in_threadpool(servicos.recalcular, cod)
    return {"ok": True}
