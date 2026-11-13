"""Peças web do controle de acesso: dependências do FastAPI, limites de taxa,
proteção contra CSRF e cabeçalhos de segurança."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..config import MunicipioDesconhecido, cod_valido, municipio
from .configuracao import cfg
from .credenciais import sessao_valida
from .modelos import Usuario, nova_sessao_db


# ------------------------------- banco ------------------------------------- #
def db() -> Iterator[Session]:
    s = nova_sessao_db()
    try:
        yield s
    finally:
        s.close()


def ip_cliente(request: Request) -> str:
    # Atrás do Caddy, o uvicorn roda com --proxy-headers e --forwarded-allow-ips
    # restrito ao proxy: request.client já é o IP real e não dá para forjá-lo.
    return request.client.host if request.client else "?"


# ------------------------------- sessão ------------------------------------ #
def token_da_requisicao(request: Request) -> str | None:
    return request.cookies.get(cfg().nome_cookie_efetivo)


def usuario_opcional(request: Request, s: Session = Depends(db)) -> Usuario | None:
    sess = sessao_valida(s, token_da_requisicao(request))
    return sess.usuario if sess else None


def usuario_atual(u: Usuario | None = Depends(usuario_opcional)) -> Usuario:
    if u is None:
        raise HTTPException(401, "Faça login para continuar.")
    return u


def admin_atual(u: Usuario = Depends(usuario_atual)) -> Usuario:
    if not u.admin:
        raise HTTPException(403, "Acesso restrito ao administrador.")
    return u


class AcessoMunicipio:
    """Dependência: o usuário logado pode ver o município {cod}?
    Sem acesso ou município inexistente dá a MESMA resposta (404): não revela
    quais municípios existem no sistema."""

    def __init__(self, papel_minimo: str = "consulta") -> None:
        self.papel_minimo = papel_minimo

    def __call__(self, cod: str, u: Usuario = Depends(usuario_atual)) -> tuple[Usuario, str]:
        papel = u.papel_em(cod) if cod_valido(cod) else None
        if papel is None:
            raise HTTPException(404, "Município não encontrado.")
        try:
            m = municipio(cod)
        except MunicipioDesconhecido:
            raise HTTPException(404, "Município não encontrado.") from None
        if not m.processado:
            raise HTTPException(404, "Município ainda não processado.")
        if self.papel_minimo == "gestor" and papel != "gestor":
            raise HTTPException(403, "Seu acesso a este município é só de consulta.")
        return u, papel


ver_municipio = AcessoMunicipio("consulta")
gerir_municipio = AcessoMunicipio("gestor")


# ------------------------------- limites ----------------------------------- #
class LimiteTaxa:
    """Janela deslizante em memória (o servidor roda num processo só)."""

    def __init__(self, maximo: int, janela_s: float) -> None:
        self.maximo, self.janela = maximo, janela_s
        self._hist: dict[str, deque] = defaultdict(deque)
        self._trava = threading.Lock()

    def permitir(self, chave: str) -> bool:
        t = time.monotonic()
        with self._trava:
            h = self._hist[chave]
            while h and h[0] <= t - self.janela:
                h.popleft()
            if len(h) >= self.maximo:
                return False
            h.append(t)
            if len(self._hist) > 50_000:            # não deixa a memória crescer sem fim
                for k in [k for k, v in self._hist.items() if not v][:25_000]:
                    del self._hist[k]
            return True


# ------------------------------- CSRF -------------------------------------- #
METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


class ProtecaoCSRF(BaseHTTPMiddleware):
    """Requisições que alteram algo precisam vir do próprio site:
    - cabeçalho X-CSRF: 1 (formulários de outros sites não conseguem enviá-lo, e
      fetch de outra origem com cabeçalho próprio exige CORS, que não liberamos);
    - Origin (ou Referer) igual à URL base.
    O cookie de sessão também é SameSite=Lax."""

    async def dispatch(self, request, call_next):
        if request.method not in METODOS_SEGUROS and request.url.path.startswith(("/api/", "/auth/")):
            if request.headers.get("x-csrf") != "1":
                return JSONResponse({"detail": "Requisição recusada (CSRF)."}, status_code=403)
            origem = request.headers.get("origin") or request.headers.get("referer")
            if not origem or _origem(origem) != _origem(cfg().url_base):
                return JSONResponse({"detail": "Requisição recusada (origem)."}, status_code=403)
        return await call_next(request)


def _origem(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower()


# ------------------------------- cabeçalhos -------------------------------- #
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",   # estilos inline do MapLibre e dos popups
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob: https://tile.openstreetmap.org",
    "connect-src 'self' https://tile.openstreetmap.org",
    "worker-src 'self' blob:",
    "child-src blob:",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "object-src 'none'",
])


class CabecalhosSeguranca(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        r = await call_next(request)
        h = r.headers
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")   # o OSM pede Referer; vai só o domínio
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.path.startswith(("/api/", "/auth/")):
            h.setdefault("Cache-Control", "no-store")             # dados por usuário: nada em cache compartilhado
        if cfg().cookie_seguro:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return r
