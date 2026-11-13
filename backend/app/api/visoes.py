"""Visões salvas: a configuração do mapa guardada com um nome.

    GET    /api/{cod}/visoes          lista as visões do município (todas as contas com acesso veem)
    POST   /api/{cod}/visoes          salva {nome, estado}
    DELETE /api/{cod}/visoes/{id}     apaga (só o autor ou o administrador)

O estado é validado campo a campo: nada além do que o mapa sabe restaurar.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..acesso import credenciais as cr
from ..acesso.modelos import Usuario, Visao
from ..acesso.web import db, ip_cliente, ver_municipio

MAX_POR_MUNICIPIO = 200
CHAVE = r"^[a-z0-9_]{1,40}$"

rotas = APIRouter(prefix="/api/{cod}/visoes", tags=["visões"])


class _Rigido(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Camadas(_Rigido):
    raios: bool = True
    radar: bool = True
    estaduais: bool = False


class Enquadramento(_Rigido):
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    zoom: float = Field(ge=0, le=22)


class Simulacao(_Rigido):
    tipo: str = Field(pattern=CHAVE)
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class Estado(_Rigido):
    mostrar: str = Field(pattern=CHAVE)                 # tipo de equipamento ou "prioridade"
    modo: Literal["reta", "rede"] = "reta"
    unid: Literal["hex", "setor"] = "hex"
    raios: dict[str, int] = Field(default_factory=dict, max_length=20)
    visiveis: dict[str, bool] = Field(default_factory=dict, max_length=20)
    camadas: Camadas = Field(default_factory=Camadas)
    mapa: Enquadramento | None = None
    sim: Simulacao | None = None

    @field_validator("raios")
    @classmethod
    def _raios(cls, v: dict[str, int]) -> dict[str, int]:
        for k, r in v.items():
            if not re.match(CHAVE, k) or not 50 <= r <= 20000:
                raise ValueError(f"raio inválido: {k}={r}")
        return v

    @field_validator("visiveis")
    @classmethod
    def _visiveis(cls, v: dict[str, bool]) -> dict[str, bool]:
        if any(not re.match(CHAVE, k) for k in v):
            raise ValueError("tipo inválido")
        return v


class VisaoNova(_Rigido):
    nome: str = Field(min_length=1, max_length=80)
    estado: Estado

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("dê um nome à visão")
        return v


def _saida(v: Visao, u: Usuario) -> dict:
    return {"id": v.id, "nome": v.nome, "autor": v.autor, "criada_em": v.criada_em.isoformat(),
            "estado": json.loads(v.estado), "pode_apagar": u.admin or v.usuario_id == u.id}


@rotas.get("")
def listar(cod: str, acesso=Depends(ver_municipio), s: Session = Depends(db)):
    u = acesso[0]
    vs = s.scalars(select(Visao).where(Visao.cod_municipio == cod).order_by(Visao.criada_em.desc(), Visao.id.desc()))
    return [_saida(v, u) for v in vs]


@rotas.post("", status_code=201)
def salvar(cod: str, dados: VisaoNova, request: Request, acesso=Depends(ver_municipio), s: Session = Depends(db)):
    u = acesso[0]
    n = s.scalar(select(func.count()).select_from(Visao).where(Visao.cod_municipio == cod))
    if n >= MAX_POR_MUNICIPIO:
        raise HTTPException(409, f"Este município já tem {MAX_POR_MUNICIPIO} visões salvas. Apague alguma antes.")
    v = Visao(cod_municipio=cod, usuario_id=u.id, autor=u.nome, nome=dados.nome,
              estado=dados.estado.model_dump_json(exclude_none=True))
    s.add(v)
    s.flush()
    cr.registrar(s, "visao_salva", u.id, detalhe=f"{cod} #{v.id} {dados.nome}", ip=ip_cliente(request))
    s.commit()
    return _saida(v, u)


@rotas.delete("/{vid}", status_code=204)
def apagar(cod: str, vid: int, request: Request, acesso=Depends(ver_municipio), s: Session = Depends(db)):
    u = acesso[0]
    v = s.get(Visao, vid)
    if v is None or v.cod_municipio != cod:
        raise HTTPException(404, "Visão não encontrada.")
    if not (u.admin or v.usuario_id == u.id):
        raise HTTPException(403, "Só quem salvou a visão (ou o administrador) pode apagá-la.")
    s.delete(v)
    cr.registrar(s, "visao_apagada", u.id, detalhe=f"{cod} #{vid} {v.nome}", ip=ip_cliente(request))
    s.commit()
    return Response(status_code=204)
