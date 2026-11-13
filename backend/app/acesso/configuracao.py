"""Configuração do servidor (variáveis de ambiente com prefixo MAPA_, ou arquivo .env).

Em produção (MAPA_AMBIENTE=producao) o servidor se recusa a subir sem HTTPS na
URL base, sem cookie seguro ou com o banco de dados dentro da pasta do projeto
sincronizada (Google Drive corrompe SQLite).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PASTA_LOCAL = Path.home() / ".mapa-equipamentos"


class Configuracao(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAPA_", env_file=".env", extra="ignore")

    ambiente: str = Field("desenvolvimento", pattern="^(desenvolvimento|producao|teste)$")
    url_base: str = "http://localhost:8000"            # endereço público (https://seu-dominio)
    db_url: str = f"sqlite:///{(PASTA_LOCAL / 'app.db').as_posix()}"
    cookie_seguro: bool = False                        # True em produção (só HTTPS)
    nome_cookie: str = "sessao"

    sessao_ociosa_horas: float = 12                    # sem uso por este tempo → sai
    sessao_max_dias: float = 7                         # no máximo, mesmo em uso
    convite_validade_horas: float = 72

    login_falhas_bloqueio: int = 5                     # falhas seguidas na mesma conta…
    login_bloqueio_minutos: int = 15                   # …bloqueiam a conta por este tempo
    login_por_ip_minuto: int = 10                      # tentativas por IP por minuto

    pdf_simultaneos: int = 1                           # relatórios gerados ao mesmo tempo
    pdf_por_usuario_hora: int = 10
    upload_max_mb: int = 200

    # E-mail (opcional). Sem SMTP, o administrador copia o link de convite e envia.
    smtp_host: str | None = None
    smtp_porta: int = 587
    smtp_usuario: str | None = None
    smtp_senha: str | None = None
    smtp_remetente: str | None = None

    aquecer_ao_iniciar: bool = True                    # pré-carrega os municípios configurados

    # Mapa de fundo (mosaicos raster {z}/{x}/{y}). O tile.openstreetmap.org serve para
    # desenvolvimento; em produção use um provedor contratado (MapTiler, Stadia…), com a chave na URL.
    mosaicos_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    mosaicos_atribuicao: str = "© OpenStreetMap contributors"
    mosaicos_zoom_max: int = 19

    @field_validator("url_base")
    @classmethod
    def _sem_barra(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("mosaicos_url")
    @classmethod
    def _mosaicos(cls, v: str) -> str:
        if not v.startswith("https://") or not all(k in v for k in ("{z}", "{x}", "{y}")) or "{s}" in v:
            raise ValueError("MAPA_MOSAICOS_URL precisa ser https://, conter {z}, {x} e {y} e não usar {s}")
        return v

    @property
    def mosaicos_origem(self) -> str:
        """Origem (https://host) dos mosaicos, para a política de segurança (CSP)."""
        from urllib.parse import urlsplit
        return f"https://{urlsplit(self.mosaicos_url).netloc}"

    def mapa_base(self) -> dict:
        return {"url": self.mosaicos_url, "atribuicao": self.mosaicos_atribuicao, "zoom_max": self.mosaicos_zoom_max}

    @property
    def producao(self) -> bool:
        return self.ambiente == "producao"

    @property
    def nome_cookie_efetivo(self) -> str:
        # __Host- exige Secure, Path=/ e sem Domain: o cookie não vaza para subdomínios
        return f"__Host-{self.nome_cookie}" if self.cookie_seguro else self.nome_cookie

    @property
    def tem_email(self) -> bool:
        return bool(self.smtp_host and self.smtp_remetente)

    def validar_producao(self) -> None:
        if not self.producao:
            return
        erros = []
        if not self.url_base.startswith("https://"):
            erros.append("MAPA_URL_BASE precisa começar com https://")
        if not self.cookie_seguro:
            erros.append("MAPA_COOKIE_SEGURO precisa ser true")
        if self.db_url.startswith("sqlite") and "Meu Drive" in self.db_url:
            erros.append("o banco SQLite não pode ficar numa pasta sincronizada")
        if erros:
            raise RuntimeError("Configuração de produção inválida: " + "; ".join(erros))


@lru_cache
def cfg() -> Configuracao:
    return Configuracao()
