"""Login, sessões, CSRF e acesso por município (sem carregar dados geográficos)."""
from __future__ import annotations

import os
import re

import pytest

os.environ.update({"MAPA_AMBIENTE": "teste", "MAPA_URL_BASE": "http://testserver",
                   "MAPA_AQUECER_AO_INICIAR": "false", "MAPA_COOKIE_SEGURO": "false"})

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from backend.app.acesso import credenciais as cr  # noqa: E402
from backend.app.acesso import configuracao  # noqa: E402
from backend.app.acesso import modelos as md  # noqa: E402

SENHA = "uma frase bem comprida 42"
CSRF = {"X-CSRF": "1", "Origin": "http://testserver"}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPA_DB_URL", f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    configuracao.cfg.cache_clear()
    md.iniciar_banco(configuracao.cfg().db_url)
    from backend.app.acesso import rotas
    from backend.app.acesso.web import LimiteTaxa
    monkeypatch.setattr(rotas, "_limite_ip", LimiteTaxa(1000, 60))
    from backend.app.api.main import app as aplicacao
    with TestClient(aplicacao, base_url="http://testserver") as c:
        yield c
    configuracao.cfg.cache_clear()


def criar(email: str, papel: str = "usuario", acessos=(), senha: str | None = SENHA) -> int:
    with md.nova_sessao_db() as s:
        u = md.Usuario(email=email, nome=email.split("@")[0].title(), papel=papel)
        u.acessos = [md.Acesso(cod_municipio=c, papel=p) for c, p in acessos]
        if senha:
            u.senha_hash = cr.gerar_hash(senha)
        s.add(u)
        s.commit()
        return u.id


def entrar(c: TestClient, email: str, senha: str = SENHA):
    return c.post("/auth/entrar", json={"email": email, "senha": senha}, headers=CSRF)


# ------------------------------------------------------------------ anônimo
def test_sem_login_tudo_fechado(app):
    assert app.get("/", follow_redirects=False).headers["location"] == "/entrar"
    assert app.get("/admin", follow_redirects=False).headers["location"] == "/entrar"
    assert app.get("/api/municipios").status_code == 401
    assert app.get("/api/2700300/config").status_code == 401
    assert app.get("/api/2700300/cobertura?tipo=creche&raio=500").status_code == 401
    assert app.get("/index.html").status_code == 404          # a página do mapa não vaza como estático
    assert app.get("/docs").status_code == 404
    assert app.get("/entrar").status_code == 200


def test_cabecalhos_de_seguranca(app):
    h = app.get("/entrar").headers
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert "script-src 'self'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert app.get("/api/municipios").headers["cache-control"] == "no-store"


# ------------------------------------------------------------------ CSRF
def test_csrf_exige_cabecalho_e_origem(app):
    criar("a@x.gov.br")
    dados = {"email": "a@x.gov.br", "senha": SENHA}
    assert app.post("/auth/entrar", json=dados).status_code == 403
    assert app.post("/auth/entrar", json=dados, headers={"X-CSRF": "1", "Origin": "https://malicioso.com"}).status_code == 403
    assert app.post("/auth/entrar", json=dados, headers={"X-CSRF": "1"}).status_code == 403   # sem origem
    assert app.post("/auth/entrar", json=dados, headers=CSRF).status_code == 200


# ------------------------------------------------------------------ login
def test_login_sessao_e_saida(app):
    criar("b@x.gov.br")
    r = entrar(app, "B@X.gov.br ")                       # e-mail sem diferença de caixa/espaço
    assert r.status_code == 200
    ck = r.headers["set-cookie"]
    assert "httponly" in ck.lower() and "samesite=lax" in ck.lower()
    token = app.cookies.get("sessao")
    with md.nova_sessao_db() as s:                       # o banco guarda só o hash
        assert s.scalar(select(md.Sessao.token_hash)) != token
    assert app.get("/auth/eu").json()["email"] == "b@x.gov.br"
    assert app.get("/", follow_redirects=False).status_code == 200
    assert app.post("/auth/sair", headers=CSRF).status_code == 200
    app.cookies.set("sessao", token)                     # o token antigo não vale mais
    assert app.get("/auth/eu").status_code == 401


def test_senha_errada_mesma_mensagem(app):
    criar("c@x.gov.br")
    r1 = entrar(app, "c@x.gov.br", "senha errada mesmo")
    r2 = entrar(app, "ninguem@x.gov.br", "senha errada mesmo")
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()                         # não revela se o e-mail existe


def test_bloqueio_apos_falhas(app):
    criar("d@x.gov.br")
    for _ in range(5):
        assert entrar(app, "d@x.gov.br", "errada errada errada").status_code == 401
    assert entrar(app, "d@x.gov.br").status_code == 429   # bloqueada mesmo com a senha certa


def test_limite_por_ip(app, monkeypatch):
    from backend.app.acesso import rotas
    from backend.app.acesso.web import LimiteTaxa
    monkeypatch.setattr(rotas, "_limite_ip", LimiteTaxa(3, 60))
    for _ in range(3):
        entrar(app, "x@x.gov.br", "qualquer coisa aqui")
    assert entrar(app, "x@x.gov.br", "qualquer coisa aqui").status_code == 429


def test_conta_desativada_nao_entra(app):
    uid = criar("e@x.gov.br")
    assert entrar(app, "e@x.gov.br").status_code == 200
    with md.nova_sessao_db() as s:
        s.get(md.Usuario, uid).ativo = False
        s.commit()
    assert app.get("/auth/eu").status_code == 401         # sessão existente cai
    assert entrar(app, "e@x.gov.br").status_code == 401


# ------------------------------------------------------------------ convites
def test_convite_uso_unico_e_senha_fraca(app):
    uid = criar("f@x.gov.br", senha=None)
    with md.nova_sessao_db() as s:
        token = cr.criar_convite(s, s.get(md.Usuario, uid))
        s.commit()
    assert app.post("/auth/convite", json={"token": token}, headers=CSRF).json()["email"] == "f@x.gov.br"
    assert app.post("/auth/definir-senha", json={"token": token, "senha": "curta"}, headers=CSRF).status_code == 400
    assert app.post("/auth/definir-senha", json={"token": token, "senha": "123456789012"}, headers=CSRF).status_code == 400
    assert app.post("/auth/definir-senha", json={"token": token, "senha": SENHA}, headers=CSRF).status_code == 200
    assert app.post("/auth/definir-senha", json={"token": token, "senha": SENHA + "x"}, headers=CSRF).status_code == 404
    assert entrar(app, "f@x.gov.br").status_code == 200


def test_link_de_convite_usa_fragmento():
    assert re.fullmatch(r"http://testserver/definir-senha#[\w-]{40,}", cr.link_convite("a" * 43))


# ------------------------------------------------------------------ acesso
def test_usuario_ve_so_os_seus_municipios(app):
    criar("g@x.gov.br", acessos=[("2700300", "consulta")])
    entrar(app, "g@x.gov.br")
    from backend.app.config import municipio
    lista = app.get("/api/municipios").json()
    if municipio("2700300").processado:
        assert [m["codigo"] for m in lista] == ["2700300"]
    # sem acesso, inexistente ou malformado: a mesma resposta
    for cod in ("2706307", "9999999", "..%2Fetc", "abc"):
        assert app.get(f"/api/{cod}/limite").status_code == 404, cod
    assert app.get("/api/admin/usuarios").status_code == 403
    assert app.get("/admin", follow_redirects=False).headers["location"] == "/"


def test_consulta_nao_envia_iptu(app):
    criar("h@x.gov.br", acessos=[("2700300", "consulta")])
    entrar(app, "h@x.gov.br")
    from backend.app.config import municipio
    if not municipio("2700300").processado:
        pytest.skip("Arapiraca não processada nesta máquina")
    r = app.post("/api/2700300/upload-iptu", headers=CSRF, files={"arquivos": ("a.csv", b"lat,lon\n1,2\n")})
    assert r.status_code == 403


# ------------------------------------------------------------------ admin
def test_admin_cria_conta_e_libera_municipio(app):
    criar("adm@x.gov.br", papel="admin")
    entrar(app, "adm@x.gov.br")
    r = app.post("/api/admin/usuarios", headers=CSRF, json={
        "email": "Nova@X.gov.br", "nome": "Nova Pessoa", "acessos": [{"cod": "2700300", "papel": "gestor"}]})
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["usuario"]["email"] == "nova@x.gov.br"
    assert corpo["usuario"]["acessos"] == [{"cod": "2700300", "papel": "gestor"}]
    assert "#" in corpo["convite"]["link"] and corpo["convite"]["email_enviado"] is False
    # duplicado, papel inválido, município inexistente
    assert app.post("/api/admin/usuarios", headers=CSRF, json={"email": "nova@x.gov.br", "nome": "X Y"}).status_code == 409
    assert app.post("/api/admin/usuarios", headers=CSRF, json={"email": "o@x.gov.br", "nome": "X Y", "papel": "root"}).status_code == 422
    assert app.post("/api/admin/usuarios", headers=CSRF, json={
        "email": "p@x.gov.br", "nome": "X Y", "acessos": [{"cod": "1234567", "papel": "consulta"}]}).status_code == 422


def test_admin_nao_se_rebaixa(app):
    uid = criar("adm2@x.gov.br", papel="admin")
    entrar(app, "adm2@x.gov.br")
    assert app.patch(f"/api/admin/usuarios/{uid}", headers=CSRF, json={"ativo": False}).status_code == 400
    assert app.patch(f"/api/admin/usuarios/{uid}", headers=CSRF, json={"papel": "usuario"}).status_code == 400


def test_eventos_de_auditoria(app):
    criar("adm3@x.gov.br", papel="admin")
    entrar(app, "adm3@x.gov.br", "errada errada errada")
    entrar(app, "adm3@x.gov.br")
    acoes = [e["acao"] for e in app.get("/api/admin/eventos").json()]
    assert acoes[:2] == ["login", "login_falhou"]


def test_producao_exige_https(monkeypatch):
    monkeypatch.setenv("MAPA_AMBIENTE", "producao")
    monkeypatch.setenv("MAPA_URL_BASE", "http://exemplo.gov.br")
    with pytest.raises(RuntimeError):
        configuracao.Configuracao().validar_producao()
    monkeypatch.setenv("MAPA_URL_BASE", "https://exemplo.gov.br")
    monkeypatch.setenv("MAPA_COOKIE_SEGURO", "true")
    configuracao.Configuracao().validar_producao()
