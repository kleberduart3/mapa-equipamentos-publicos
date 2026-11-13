"""Senhas (Argon2id), sessões e convites. Sem dependência da web: testável e usado pela CLI."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .configuracao import cfg
from .modelos import Convite, Evento, Sessao, Usuario, agora

_hasher = PasswordHasher()          # Argon2id com os parâmetros recomendados pela biblioteca
# hash de uma senha qualquer: a verificação de e-mail inexistente custa o mesmo tempo
_HASH_FALSO = _hasher.hash(secrets.token_urlsafe(16))

SENHA_MIN = 12
_COMUNS = {"123456789012", "senha1234567", "password1234", "qwertyuiopas", "000000000000",
           "abcdefghijkl", "arapiraca123", "prefeitura12", "prefeitura123", "123456789abc"}


class SenhaFraca(ValueError):
    pass


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def validar_senha(senha: str, email: str = "") -> None:
    if len(senha) < SENHA_MIN:
        raise SenhaFraca(f"A senha precisa ter pelo menos {SENHA_MIN} caracteres.")
    if len(senha) > 256:
        raise SenhaFraca("Senha longa demais.")
    baixa = senha.lower()
    if baixa in _COMUNS or len(set(baixa)) < 5:
        raise SenhaFraca("Senha muito previsível. Use uma frase ou combine palavras.")
    local = normalizar_email(email).split("@")[0]
    if local and len(local) >= 4 and local in baixa:
        raise SenhaFraca("A senha não pode conter o seu e-mail.")


def gerar_hash(senha: str) -> str:
    return _hasher.hash(senha)


def conferir_senha(u: Usuario | None, senha: str) -> bool:
    """Confere a senha em tempo constante (mesmo se o usuário não existir)."""
    alvo = u.senha_hash if (u is not None and u.senha_hash) else _HASH_FALSO
    try:
        ok = _hasher.verify(alvo, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    if ok and u is not None and u.senha_hash and _hasher.check_needs_rehash(u.senha_hash):
        u.senha_hash = _hasher.hash(senha)           # parâmetros mais fortes numa versão nova
    return ok and u is not None and bool(u.senha_hash)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def registrar(db: Session, acao: str, usuario_id: int | None = None, detalhe: str | None = None,
              ip: str | None = None) -> None:
    db.add(Evento(acao=acao, usuario_id=usuario_id, detalhe=(detalhe or "")[:2000] or None, ip=ip))


# ------------------------------- sessões ----------------------------------- #
def criar_sessao(db: Session, u: Usuario, ip: str | None, agente: str | None) -> str:
    token = secrets.token_urlsafe(32)
    c = cfg()
    db.add(Sessao(token_hash=_hash_token(token), usuario_id=u.id, ip=ip, agente=(agente or "")[:200],
                  expira_em=agora() + timedelta(days=c.sessao_max_dias)))
    return token


def sessao_valida(db: Session, token: str | None) -> Sessao | None:
    if not token or len(token) > 100:
        return None
    s = db.scalar(select(Sessao).where(Sessao.token_hash == _hash_token(token)))
    if s is None:
        return None
    t = agora()
    ociosa = timedelta(hours=cfg().sessao_ociosa_horas)
    if _utc(s.expira_em) <= t or _utc(s.usada_em) + ociosa <= t or not s.usuario.ativo:
        db.delete(s)
        db.commit()
        return None
    if t - _utc(s.usada_em) > timedelta(minutes=5):    # não grava a cada requisição
        s.usada_em = t
        db.commit()
    return s


def encerrar_sessao(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(Sessao).where(Sessao.token_hash == _hash_token(token)))


def encerrar_todas(db: Session, usuario_id: int) -> None:
    db.execute(delete(Sessao).where(Sessao.usuario_id == usuario_id))


def limpar_expiradas(db: Session) -> None:
    db.execute(delete(Sessao).where(Sessao.expira_em <= agora()))
    db.execute(delete(Convite).where(Convite.expira_em <= agora() - timedelta(days=30)))


def _utc(d):
    """SQLite devolve datas sem fuso; tudo aqui é gravado em UTC."""
    from datetime import timezone
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ------------------------------- convites ---------------------------------- #
def criar_convite(db: Session, u: Usuario, motivo: str = "convite") -> str:
    """Link de uso único para definir a senha. Invalida convites anteriores do usuário."""
    db.execute(delete(Convite).where(Convite.usuario_id == u.id, Convite.usado_em.is_(None)))
    token = secrets.token_urlsafe(32)
    db.add(Convite(token_hash=_hash_token(token), usuario_id=u.id, motivo=motivo,
                   expira_em=agora() + timedelta(hours=cfg().convite_validade_horas)))
    return token


def link_convite(token: str) -> str:
    return f"{cfg().url_base}/definir-senha#{token}"      # no fragmento: não vai para logs nem Referer


def convite_valido(db: Session, token: str | None) -> Convite | None:
    if not token or len(token) > 100:
        return None
    c = db.scalar(select(Convite).where(Convite.token_hash == _hash_token(token)))
    if c is None or c.usado_em is not None or _utc(c.expira_em) <= agora() or not c.usuario.ativo:
        return None
    return c


def usar_convite(db: Session, c: Convite, senha: str) -> Usuario:
    u = c.usuario
    validar_senha(senha, u.email)
    u.senha_hash = gerar_hash(senha)
    u.falhas_login = 0
    u.bloqueado_ate = None
    c.usado_em = agora()
    encerrar_todas(db, u.id)                 # trocou a senha: derruba sessões antigas
    return u
