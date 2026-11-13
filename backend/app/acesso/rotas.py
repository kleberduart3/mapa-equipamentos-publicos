"""Rotas de login (/auth) e de administração de contas (/api/admin)."""
from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import MunicipioDesconhecido, cod_valido, municipio, municipios
from . import credenciais as cr
from . import email as mail
from .configuracao import cfg
from .modelos import PAPEIS, PAPEIS_MUNICIPIO, Acesso, Evento, Usuario, agora
from .web import LimiteTaxa, admin_atual, db, ip_cliente, token_da_requisicao, usuario_atual

auth = APIRouter(prefix="/auth", tags=["login"])
admin = APIRouter(prefix="/api/admin", tags=["administração"])

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_limite_ip = LimiteTaxa(cfg().login_por_ip_minuto, 60)
_limite_esqueci = LimiteTaxa(3, 3600)
MSG_LOGIN = "E-mail ou senha incorretos."
MSG_MUITAS = "Muitas tentativas. Aguarde alguns minutos e tente de novo."


def _email(v: str) -> str:
    v = cr.normalizar_email(v)
    if len(v) > 254 or not _EMAIL.match(v):
        raise ValueError("e-mail inválido")
    return v


def _usuario_json(u: Usuario) -> dict:
    if u.admin:
        acessos = [{"cod": m.cod, "nome": m.nome, "uf": m.uf, "papel": "gestor"} for m in municipios()]
    else:
        acessos = []
        for a in u.acessos:
            try:
                m = municipio(a.cod_municipio)
                acessos.append({"cod": m.cod, "nome": m.nome, "uf": m.uf, "papel": a.papel})
            except MunicipioDesconhecido:
                continue
    return {"id": u.id, "email": u.email, "nome": u.nome, "papel": u.papel, "municipios": acessos}


# =============================== /auth ===================================== #
class Entrada(BaseModel):
    email: str = Field(max_length=254)
    senha: str = Field(max_length=256)


@auth.post("/entrar")
def entrar(dados: Entrada, request: Request, response: Response, s: Session = Depends(db)):
    ip = ip_cliente(request)
    if not _limite_ip.permitir(ip):
        cr.registrar(s, "login_limite_ip", detalhe=dados.email[:254], ip=ip)
        s.commit()
        raise HTTPException(429, MSG_MUITAS)
    email = cr.normalizar_email(dados.email)
    u = s.scalar(select(Usuario).where(Usuario.email == email))
    if u is not None and u.bloqueado_ate and cr._utc(u.bloqueado_ate) > agora():
        cr.conferir_senha(None, dados.senha)            # mesmo custo de tempo
        raise HTTPException(429, MSG_MUITAS)
    if not cr.conferir_senha(u, dados.senha) or not u.ativo:
        if u is not None:
            u.falhas_login += 1
            if u.falhas_login >= cfg().login_falhas_bloqueio:
                u.bloqueado_ate = agora() + timedelta(minutes=cfg().login_bloqueio_minutos)
                u.falhas_login = 0
                cr.registrar(s, "conta_bloqueada", u.id, ip=ip)
        cr.registrar(s, "login_falhou", u.id if u else None, detalhe=None if u else email, ip=ip)
        s.commit()
        raise HTTPException(401, MSG_LOGIN)
    u.falhas_login, u.bloqueado_ate, u.ultimo_login = 0, None, agora()
    cr.encerrar_sessao(s, token_da_requisicao(request))   # nunca reaproveita sessão anterior
    token = cr.criar_sessao(s, u, ip, request.headers.get("user-agent"))
    cr.registrar(s, "login", u.id, ip=ip)
    s.commit()
    c = cfg()
    response.set_cookie(c.nome_cookie_efetivo, token, max_age=int(c.sessao_max_dias * 86400), path="/",
                        httponly=True, secure=c.cookie_seguro, samesite="lax")
    return _usuario_json(u)


@auth.post("/sair")
def sair(request: Request, response: Response, s: Session = Depends(db)):
    cr.encerrar_sessao(s, token_da_requisicao(request))
    s.commit()
    response.delete_cookie(cfg().nome_cookie_efetivo, path="/", secure=cfg().cookie_seguro, httponly=True,
                           samesite="lax")
    return {"ok": True}


@auth.get("/eu")
def eu(u: Usuario = Depends(usuario_atual)):
    return _usuario_json(u)


class TrocaSenha(BaseModel):
    senha_atual: str = Field(max_length=256)
    nova: str = Field(max_length=256)


@auth.post("/trocar-senha")
def trocar_senha(dados: TrocaSenha, request: Request, response: Response, u: Usuario = Depends(usuario_atual),
                 s: Session = Depends(db)):
    u = s.merge(u)
    if not cr.conferir_senha(u, dados.senha_atual):
        raise HTTPException(400, "Senha atual incorreta.")
    try:
        cr.validar_senha(dados.nova, u.email)
    except cr.SenhaFraca as e:
        raise HTTPException(400, str(e)) from None
    u.senha_hash = cr.gerar_hash(dados.nova)
    cr.encerrar_todas(s, u.id)
    token = cr.criar_sessao(s, u, ip_cliente(request), request.headers.get("user-agent"))
    cr.registrar(s, "senha_trocada", u.id, ip=ip_cliente(request))
    s.commit()
    c = cfg()
    response.set_cookie(c.nome_cookie_efetivo, token, max_age=int(c.sessao_max_dias * 86400), path="/",
                        httponly=True, secure=c.cookie_seguro, samesite="lax")
    return {"ok": True}


class Token(BaseModel):
    token: str = Field(max_length=100)


@auth.post("/convite")
def ver_convite(dados: Token, request: Request, s: Session = Depends(db)):
    if not _limite_ip.permitir("convite:" + ip_cliente(request)):
        raise HTTPException(429, MSG_MUITAS)
    c = cr.convite_valido(s, dados.token)
    if c is None:
        raise HTTPException(404, "Link inválido ou expirado. Peça um novo ao administrador.")
    return {"email": c.usuario.email, "nome": c.usuario.nome, "motivo": c.motivo}


class DefinirSenha(BaseModel):
    token: str = Field(max_length=100)
    senha: str = Field(max_length=256)


@auth.post("/definir-senha")
def definir_senha(dados: DefinirSenha, request: Request, s: Session = Depends(db)):
    if not _limite_ip.permitir("convite:" + ip_cliente(request)):
        raise HTTPException(429, MSG_MUITAS)
    c = cr.convite_valido(s, dados.token)
    if c is None:
        raise HTTPException(404, "Link inválido ou expirado. Peça um novo ao administrador.")
    try:
        u = cr.usar_convite(s, c, dados.senha)
    except cr.SenhaFraca as e:
        raise HTTPException(400, str(e)) from None
    cr.registrar(s, "senha_definida", u.id, detalhe=c.motivo, ip=ip_cliente(request))
    s.commit()
    return {"ok": True, "email": u.email}


class Esqueci(BaseModel):
    email: str = Field(max_length=254)


@auth.post("/esqueci")
def esqueci(dados: Esqueci, request: Request, s: Session = Depends(db)):
    """Sempre responde igual (não revela se o e-mail tem conta)."""
    ip = ip_cliente(request)
    if not cfg().tem_email:
        return {"ok": True, "mensagem": "Peça ao administrador um link para criar uma nova senha."}
    email = cr.normalizar_email(dados.email)
    if _limite_ip.permitir("esqueci:" + ip) and _limite_esqueci.permitir(email):
        u = s.scalar(select(Usuario).where(Usuario.email == email))
        if u is not None and u.ativo:
            token = cr.criar_convite(s, u, "redefinicao")
            cr.registrar(s, "redefinicao_pedida", u.id, ip=ip)
            s.commit()
            assunto, texto = mail.texto_convite(u.nome, cr.link_convite(token), "redefinicao")
            mail.enviar(u.email, assunto, texto)
    return {"ok": True, "mensagem": "Se o e-mail tiver uma conta, enviamos um link para criar uma nova senha."}


# =============================== /api/admin ================================ #
class AcessoIn(BaseModel):
    cod: str
    papel: str = "consulta"

    @field_validator("cod")
    @classmethod
    def _cod(cls, v: str) -> str:
        if not cod_valido(v):
            raise ValueError("código IBGE inválido")
        try:
            municipio(v)
        except MunicipioDesconhecido:
            raise ValueError(f"município {v} não configurado") from None
        return v

    @field_validator("papel")
    @classmethod
    def _papel(cls, v: str) -> str:
        if v not in PAPEIS_MUNICIPIO:
            raise ValueError(f"papel deve ser um de {PAPEIS_MUNICIPIO}")
        return v


class UsuarioNovo(BaseModel):
    email: str = Field(max_length=254)
    nome: str = Field(min_length=2, max_length=120)
    papel: str = "usuario"
    acessos: list[AcessoIn] = []

    _e = field_validator("email")(lambda cls, v: _email(v))

    @field_validator("papel")
    @classmethod
    def _papel(cls, v: str) -> str:
        if v not in PAPEIS:
            raise ValueError(f"papel deve ser um de {PAPEIS}")
        return v


class UsuarioEdicao(BaseModel):
    nome: str | None = Field(None, min_length=2, max_length=120)
    papel: str | None = None
    ativo: bool | None = None
    acessos: list[AcessoIn] | None = None

    @field_validator("papel")
    @classmethod
    def _papel(cls, v):
        if v is not None and v not in PAPEIS:
            raise ValueError(f"papel deve ser um de {PAPEIS}")
        return v


def _admin_json(u: Usuario) -> dict:
    return {"id": u.id, "email": u.email, "nome": u.nome, "papel": u.papel, "ativo": u.ativo,
            "senha_definida": bool(u.senha_hash), "ultimo_login": u.ultimo_login,
            "bloqueado": bool(u.bloqueado_ate and cr._utc(u.bloqueado_ate) > agora()),
            "acessos": [{"cod": a.cod_municipio, "papel": a.papel} for a in u.acessos]}


def _definir_acessos(u: Usuario, acessos: list[AcessoIn]) -> None:
    vistos = {}
    for a in acessos:
        vistos[a.cod] = a.papel
    u.acessos = [Acesso(cod_municipio=c, papel=p) for c, p in vistos.items()]


def _enviar_link(u: Usuario, token: str, motivo: str) -> dict:
    link = cr.link_convite(token)
    assunto, texto = mail.texto_convite(u.nome, link, motivo)
    enviado = mail.enviar(u.email, assunto, texto)
    return {"link": link, "email_enviado": enviado, "validade_horas": cfg().convite_validade_horas}


@admin.get("/municipios")
def admin_municipios(_: Usuario = Depends(admin_atual)):
    return [{"cod": m.cod, "nome": m.nome, "uf": m.uf, "processado": m.processado, "tem_rede": m.tem_rede}
            for m in municipios()]


@admin.get("/usuarios")
def listar(_: Usuario = Depends(admin_atual), s: Session = Depends(db)):
    return [_admin_json(u) for u in s.scalars(select(Usuario).order_by(Usuario.nome))]


@admin.post("/usuarios", status_code=201)
def criar(dados: UsuarioNovo, request: Request, eu_: Usuario = Depends(admin_atual), s: Session = Depends(db)):
    if s.scalar(select(Usuario).where(Usuario.email == dados.email)):
        raise HTTPException(409, "Já existe uma conta com este e-mail.")
    u = Usuario(email=dados.email, nome=dados.nome.strip(), papel=dados.papel)
    _definir_acessos(u, dados.acessos)
    s.add(u)
    s.flush()
    token = cr.criar_convite(s, u, "convite")
    cr.registrar(s, "usuario_criado", eu_.id, detalhe=f"{u.email} papel={u.papel} "
                 f"acessos={[(a.cod_municipio, a.papel) for a in u.acessos]}", ip=ip_cliente(request))
    s.commit()
    return {"usuario": _admin_json(u), "convite": _enviar_link(u, token, "convite")}


def _alvo(s: Session, uid: int) -> Usuario:
    u = s.get(Usuario, uid)
    if u is None:
        raise HTTPException(404, "Usuário não encontrado.")
    return u


@admin.patch("/usuarios/{uid}")
def editar(uid: int, dados: UsuarioEdicao, request: Request, eu_: Usuario = Depends(admin_atual),
           s: Session = Depends(db)):
    u = _alvo(s, uid)
    if u.id == eu_.id and (dados.ativo is False or (dados.papel and dados.papel != "admin")):
        raise HTTPException(400, "Você não pode desativar nem rebaixar a própria conta.")
    mud = []
    if dados.nome is not None:
        u.nome = dados.nome.strip()
        mud.append("nome")
    if dados.papel is not None and dados.papel != u.papel:
        u.papel = dados.papel
        mud.append(f"papel={dados.papel}")
    if dados.ativo is not None and dados.ativo != u.ativo:
        u.ativo = dados.ativo
        mud.append(f"ativo={dados.ativo}")
        if not dados.ativo:
            cr.encerrar_todas(s, u.id)
    if dados.acessos is not None:
        _definir_acessos(u, dados.acessos)
        mud.append(f"acessos={[(a.cod, a.papel) for a in dados.acessos]}")
    cr.registrar(s, "usuario_editado", eu_.id, detalhe=f"{u.email}: {', '.join(mud)}", ip=ip_cliente(request))
    s.commit()
    return _admin_json(u)


@admin.post("/usuarios/{uid}/link")
def novo_link(uid: int, request: Request, eu_: Usuario = Depends(admin_atual), s: Session = Depends(db)):
    """Novo link para definir senha (primeiro acesso ou senha esquecida). Desbloqueia a conta."""
    u = _alvo(s, uid)
    motivo = "redefinicao" if u.senha_hash else "convite"
    token = cr.criar_convite(s, u, motivo)
    u.bloqueado_ate, u.falhas_login = None, 0
    cr.registrar(s, "link_gerado", eu_.id, detalhe=f"{u.email} ({motivo})", ip=ip_cliente(request))
    s.commit()
    return _enviar_link(u, token, motivo)


@admin.post("/usuarios/{uid}/encerrar-sessoes")
def derrubar(uid: int, request: Request, eu_: Usuario = Depends(admin_atual), s: Session = Depends(db)):
    u = _alvo(s, uid)
    cr.encerrar_todas(s, u.id)
    cr.registrar(s, "sessoes_encerradas", eu_.id, detalhe=u.email, ip=ip_cliente(request))
    s.commit()
    return {"ok": True}


@admin.get("/eventos")
def eventos(limite: int = 200, _: Usuario = Depends(admin_atual), s: Session = Depends(db)):
    limite = max(1, min(limite, 1000))
    nomes = {u.id: u.email for u in s.scalars(select(Usuario))}
    return [{"quando": e.quando, "acao": e.acao, "usuario": nomes.get(e.usuario_id), "detalhe": e.detalhe,
             "ip": e.ip} for e in s.scalars(select(Evento).order_by(Evento.id.desc()).limit(limite))]
