"""Propostas comerciais: página de venda no domínio, aberta com link + código de acesso.

Admin (logado):
    GET    /api/admin/propostas               lista
    POST   /api/admin/propostas               cria; devolve o link e o código (o código só aparece aqui)
    PATCH  /api/admin/propostas/{id}          ativa/desativa, muda validade, desconto, estudo, observação
    POST   /api/admin/propostas/{id}/codigo   gera um código novo (o antigo deixa de valer)
    GET    /api/admin/precos                  tabela de preços (para a prévia no painel)
Público (sem login):
    GET    /p/{slug}                          página (estática; sem dados até o código ser aceito)
    POST   /api/proposta/{slug}/abrir         {codigo} -> dados da proposta e orçamento calculado

O código tem 8 caracteres de um alfabeto sem letras parecidas (40 bits). Tentativas erradas
são limitadas por IP e por proposta; depois de 20 erros a proposta trava até o admin gerar outro código.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..acesso import credenciais as cr
from ..acesso.configuracao import cfg
from ..acesso.modelos import Proposta, Usuario, agora
from ..acesso.web import LimiteTaxa, admin_atual, db, ip_cliente

# ------------------------------------------------------------------ preços
# (até população, rótulo, implantação, assinatura anual). Acima da última faixa: sob proposta.
FAIXAS = [
    (20_000, "até 20 mil hab.", 4_000, 9_600),
    (50_000, "20 a 50 mil hab.", 6_000, 18_000),
    (100_000, "50 a 100 mil hab.", 8_000, 30_000),
    (300_000, "100 a 300 mil hab.", 10_000, 48_000),
]
ESTUDO = 12_000                 # estudo de localização (valor médio da faixa R$ 8–15 mil)
TETO_DISPENSA = 62_000          # referência aproximada (Lei 14.133, art. 75, II); conferir o valor vigente
MAX_FALHAS = 20

ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sem 0/O, 1/I


def tabela_precos() -> dict:
    return {"faixas": [{"ate": a, "rotulo": r, "implantacao": i, "anual": n} for a, r, i, n in FAIXAS],
            "estudo": ESTUDO, "teto_dispensa": TETO_DISPENSA}


def orcamento(populacao: int, desconto_pct: int = 0, incluir_estudo: bool = False) -> dict:
    for i, (ate, rotulo, impl, anual) in enumerate(FAIXAS):
        if populacao <= ate:
            anual_1 = round(anual * (100 - desconto_pct) / 100)
            estudo = ESTUDO if incluir_estudo else 0
            total = impl + anual_1 + estudo
            return {"faixa": i, "rotulo": rotulo, "implantacao": impl, "anual": anual, "anual_1": anual_1,
                    "desconto_pct": desconto_pct, "estudo": estudo, "total_1": total,
                    "cabe_dispensa": total <= TETO_DISPENSA}
    return {"faixa": None, "sob_proposta": True}


# ------------------------------------------------------------------ código
def novo_codigo() -> str:
    c = "".join(secrets.choice(ALFABETO) for _ in range(8))
    return f"{c[:4]}-{c[4:]}"


def _norm(codigo: str) -> str:
    return "".join(ch for ch in codigo.upper() if ch in ALFABETO)


def _hash(slug: str, codigo: str) -> str:
    return hashlib.sha256(f"{slug}:{_norm(codigo)}".encode()).hexdigest()


def link(slug: str) -> str:
    return f"{cfg().url_base.rstrip('/')}/p/{slug}"


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ admin
admin = APIRouter(prefix="/api/admin", tags=["propostas"])


class _Rigido(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PropostaNova(_Rigido):
    cliente: str = Field(min_length=3, max_length=120)
    contato: str | None = Field(None, max_length=120)
    municipio: str = Field(min_length=2, max_length=80)
    uf: str = Field(pattern=r"^[A-Za-z]{2}$")
    populacao: int = Field(ge=500, le=15_000_000)
    desconto_pct: int = Field(0, ge=0, le=60)
    incluir_estudo: bool = False
    observacao: str | None = Field(None, max_length=1000)
    validade_dias: int = Field(30, ge=1, le=365)

    @field_validator("cliente", "contato", "municipio", "observacao")
    @classmethod
    def _limpa(cls, v):
        return " ".join(v.split()) if isinstance(v, str) and v.strip() else (None if v is not None else v)


class PropostaEdicao(_Rigido):
    ativa: bool | None = None
    desconto_pct: int | None = Field(None, ge=0, le=60)
    incluir_estudo: bool | None = None
    observacao: str | None = Field(None, max_length=1000)
    validade_dias: int | None = Field(None, ge=1, le=365)


def _admin_json(p: Proposta) -> dict:
    expirada = _utc(p.validade) < agora()
    return {"id": p.id, "link": link(p.slug), "cliente": p.cliente, "contato": p.contato,
            "municipio": p.municipio, "uf": p.uf, "populacao": p.populacao, "desconto_pct": p.desconto_pct,
            "incluir_estudo": p.incluir_estudo, "observacao": p.observacao, "validade": p.validade,
            "ativa": p.ativa, "expirada": expirada, "travada": p.falhas >= MAX_FALHAS,
            "criada_em": p.criada_em, "aberturas": p.aberturas, "ultima_abertura": p.ultima_abertura,
            "orcamento": orcamento(p.populacao, p.desconto_pct, p.incluir_estudo)}


def _alvo(s: Session, pid: int) -> Proposta:
    p = s.get(Proposta, pid)
    if p is None:
        raise HTTPException(404, "Proposta não encontrada.")
    return p


@admin.get("/precos")
def precos(_: Usuario = Depends(admin_atual)):
    return tabela_precos()


@admin.get("/propostas")
def listar(_: Usuario = Depends(admin_atual), s: Session = Depends(db)):
    return [_admin_json(p) for p in s.scalars(select(Proposta).order_by(Proposta.id.desc()))]


@admin.post("/propostas", status_code=201)
def criar(dados: PropostaNova, request: Request, eu_: Usuario = Depends(admin_atual), s: Session = Depends(db)):
    slug, codigo = secrets.token_urlsafe(12), novo_codigo()
    p = Proposta(slug=slug, codigo_hash=_hash(slug, codigo), cliente=dados.cliente, contato=dados.contato,
                 municipio=dados.municipio, uf=dados.uf.upper(), populacao=dados.populacao,
                 desconto_pct=dados.desconto_pct, incluir_estudo=dados.incluir_estudo,
                 observacao=dados.observacao, validade=agora() + timedelta(days=dados.validade_dias),
                 criada_por=eu_.id)
    s.add(p)
    s.flush()
    cr.registrar(s, "proposta_criada", eu_.id, detalhe=f"#{p.id} {p.cliente}", ip=ip_cliente(request))
    s.commit()
    return {**_admin_json(p), "codigo": codigo}


@admin.patch("/propostas/{pid}")
def editar(pid: int, dados: PropostaEdicao, request: Request, eu_: Usuario = Depends(admin_atual),
           s: Session = Depends(db)):
    p = _alvo(s, pid)
    mud = dados.model_dump(exclude_none=True)
    if "validade_dias" in mud:
        p.validade = agora() + timedelta(days=mud.pop("validade_dias"))
        mud["validade"] = p.validade.date().isoformat()
    for k, v in mud.items():
        if hasattr(p, k) and k != "validade":
            setattr(p, k, (" ".join(v.split()) or None) if isinstance(v, str) else v)
    cr.registrar(s, "proposta_editada", eu_.id, detalhe=f"#{p.id} {mud}", ip=ip_cliente(request))
    s.commit()
    return _admin_json(p)


@admin.post("/propostas/{pid}/codigo")
def trocar_codigo(pid: int, request: Request, eu_: Usuario = Depends(admin_atual), s: Session = Depends(db)):
    p = _alvo(s, pid)
    codigo = novo_codigo()
    p.codigo_hash, p.falhas = _hash(p.slug, codigo), 0
    cr.registrar(s, "proposta_codigo", eu_.id, detalhe=f"#{p.id}", ip=ip_cliente(request))
    s.commit()
    return {**_admin_json(p), "codigo": codigo}


# ------------------------------------------------------------------ público
publico = APIRouter(prefix="/api/proposta", tags=["proposta pública"])
_limite = LimiteTaxa(10, 600)          # 10 tentativas por IP a cada 10 min


class Abrir(_Rigido):
    codigo: str = Field(min_length=4, max_length=20)


NAO_ENCONTRADA = "Proposta não encontrada ou expirada. Peça um novo link a quem enviou."


@publico.post("/{slug}/abrir")
def abrir(slug: str, dados: Abrir, request: Request, s: Session = Depends(db)):
    ip = ip_cliente(request)
    if not _limite.permitir(ip):
        raise HTTPException(429, "Muitas tentativas. Espere alguns minutos e tente de novo.")
    p = s.scalar(select(Proposta).where(Proposta.slug == slug[:32]))
    if p is None or not p.ativa or _utc(p.validade) < agora():
        raise HTTPException(404, NAO_ENCONTRADA)
    if p.falhas >= MAX_FALHAS:
        raise HTTPException(423, "Esta proposta foi bloqueada por excesso de tentativas. Peça um novo código.")
    if not hmac.compare_digest(p.codigo_hash, _hash(slug, dados.codigo)):
        p.falhas += 1
        cr.registrar(s, "proposta_codigo_errado", None, detalhe=f"#{p.id}", ip=ip)
        s.commit()
        raise HTTPException(403, "Código incorreto. Confira as letras e os números enviados junto com o link.")
    primeira = p.aberturas == 0
    p.aberturas += 1
    p.ultima_abertura = agora()
    if primeira:
        cr.registrar(s, "proposta_aberta", None, detalhe=f"#{p.id} {p.cliente}", ip=ip)
    s.commit()
    return {"cliente": p.cliente, "contato": p.contato, "municipio": p.municipio, "uf": p.uf,
            "populacao": p.populacao, "observacao": p.observacao, "validade": p.validade,
            "orcamento": orcamento(p.populacao, p.desconto_pct, p.incluir_estudo), "precos": tabela_precos()}
