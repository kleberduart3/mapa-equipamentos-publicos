"""Tabelas de usuários, acessos por município, sessões, convites e auditoria."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

PAPEIS = ("admin", "usuario")              # admin: gerencia contas e vê todos os municípios
PAPEIS_MUNICIPIO = ("consulta", "gestor")  # gestor: também envia dados da prefeitura


def agora() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)   # sempre minúsculo
    nome: Mapped[str] = mapped_column(String(120))
    senha_hash: Mapped[str | None] = mapped_column(String(255))               # None até aceitar o convite
    papel: Mapped[str] = mapped_column(String(16), default="usuario")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    falhas_login: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acessos: Mapped[list["Acesso"]] = relationship(back_populates="usuario", cascade="all, delete-orphan")

    @property
    def admin(self) -> bool:
        return self.papel == "admin"

    def papel_em(self, cod: str) -> str | None:
        """Papel no município (None = sem acesso). Admin é gestor em todos."""
        if self.admin:
            return "gestor"
        return next((a.papel for a in self.acessos if a.cod_municipio == cod), None)


class Acesso(Base):
    __tablename__ = "acessos"
    __table_args__ = (UniqueConstraint("usuario_id", "cod_municipio"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    cod_municipio: Mapped[str] = mapped_column(String(7))
    papel: Mapped[str] = mapped_column(String(16), default="consulta")
    usuario: Mapped[Usuario] = relationship(back_populates="acessos")


class Sessao(Base):
    """Sessão de login. Guardamos só o hash do token: quem lê o banco não entra."""
    __tablename__ = "sessoes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    usada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(45))
    agente: Mapped[str | None] = mapped_column(String(200))
    usuario: Mapped[Usuario] = relationship()


class Convite(Base):
    """Link de uso único para definir a senha (primeiro acesso ou redefinição)."""
    __tablename__ = "convites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    motivo: Mapped[str] = mapped_column(String(16))           # convite | redefinicao
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    usado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usuario: Mapped[Usuario] = relationship()


class Visao(Base):
    """Configuração do mapa salva com um nome (raios, camadas, enquadramento…).
    Todas as contas com acesso ao município veem; só o autor ou o admin apaga."""
    __tablename__ = "visoes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cod_municipio: Mapped[str] = mapped_column(String(7), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True)
    autor: Mapped[str] = mapped_column(String(120))          # nome guardado: a visão sobrevive à conta
    nome: Mapped[str] = mapped_column(String(80))
    estado: Mapped[str] = mapped_column(Text)                 # JSON validado em api/visoes.py
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)


class Evento(Base):
    """Trilha de auditoria: logins, falhas, mudanças de conta, uploads, relatórios."""
    __tablename__ = "eventos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quando: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, index=True)
    usuario_id: Mapped[int | None] = mapped_column(Integer, index=True)
    acao: Mapped[str] = mapped_column(String(40))
    detalhe: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(45))


# --------------------------------------------------------------------------- #
_fabrica: sessionmaker | None = None


def iniciar_banco(url: str):
    """Cria o motor e as tabelas (create_all: o esquema ainda é pequeno; sem migrações)."""
    global _fabrica
    if url.startswith("sqlite:///"):
        from pathlib import Path
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    motor = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
                          pool_pre_ping=True)
    if url.startswith("sqlite"):
        @event.listens_for(motor, "connect")
        def _pragmas(con, _):                     # integridade referencial e escrita concorrente
            cur = con.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()
    Base.metadata.create_all(motor)
    _fabrica = sessionmaker(motor, expire_on_commit=False)
    return motor


def nova_sessao_db():
    if _fabrica is None:
        from .configuracao import cfg
        iniciar_banco(cfg().db_url)
    return _fabrica()
