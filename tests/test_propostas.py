"""Propostas: link + código, preços, bloqueio por tentativas, só admin gerencia."""
from __future__ import annotations

from test_acesso import CSRF, app, criar, entrar  # noqa: F401 – app é fixture

NOVA = {"cliente": "Prefeitura de Teste", "municipio": "Teste", "uf": "al", "populacao": 71574,
        "contato": "Maria Silva", "desconto_pct": 20, "incluir_estudo": False, "validade_dias": 30}


def _criar(app):
    criar("adm@x.gov.br", papel="admin")
    entrar(app, "adm@x.gov.br")
    r = app.post("/api/admin/propostas", headers=CSRF, json=NOVA)
    assert r.status_code == 201, r.text
    return r.json()


def test_orcamento_por_faixa():
    from backend.app.api.propostas import orcamento
    o = orcamento(71574, 20)
    assert o["implantacao"] == 8000 and o["anual"] == 30000 and o["anual_1"] == 24000 and o["total_1"] == 32000
    assert o["cabe_dispensa"] is True
    assert orcamento(20000)["anual"] == 9600 and orcamento(20001)["anual"] == 18000
    assert orcamento(400000) == {"faixa": None, "sob_proposta": True}


def test_criar_e_abrir_com_codigo(app):
    p = _criar(app)
    assert p["uf"] == "AL" and "/p/" in p["link"] and len(p["codigo"]) == 9
    slug = p["link"].rsplit("/", 1)[1]
    app.post("/auth/sair", headers=CSRF)
    # página pública sem login, sem indexação
    pg = app.get(f"/p/{slug}")
    assert pg.status_code == 200 and "noindex" in pg.headers["x-robots-tag"]
    # código errado, depois certo (minúsculo e sem hífen também vale)
    assert app.post(f"/api/proposta/{slug}/abrir", headers=CSRF, json={"codigo": "ZZZZ-ZZZZ"}).status_code == 403
    r = app.post(f"/api/proposta/{slug}/abrir", headers=CSRF, json={"codigo": p["codigo"].replace("-", "").lower()})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["cliente"] == "Prefeitura de Teste" and d["orcamento"]["total_1"] == 32000
    assert "codigo" not in d and "slug" not in d


def test_inexistente_desativada_e_codigo_novo(app):
    p = _criar(app)
    slug = p["link"].rsplit("/", 1)[1]
    assert app.post("/api/proposta/naoexiste/abrir", headers=CSRF, json={"codigo": "AAAA-AAAA"}).status_code == 404
    novo = app.post(f"/api/admin/propostas/{p['id']}/codigo", headers=CSRF).json()["codigo"]
    assert app.post(f"/api/proposta/{slug}/abrir", headers=CSRF, json={"codigo": p["codigo"]}).status_code == 403
    assert app.post(f"/api/proposta/{slug}/abrir", headers=CSRF, json={"codigo": novo}).status_code == 200
    app.patch(f"/api/admin/propostas/{p['id']}", headers=CSRF, json={"ativa": False})
    assert app.post(f"/api/proposta/{slug}/abrir", headers=CSRF, json={"codigo": novo}).status_code == 404
    lista = app.get("/api/admin/propostas").json()
    assert lista[0]["aberturas"] == 1 and lista[0]["ativa"] is False


def test_bloqueio_por_tentativas(app, monkeypatch):
    from backend.app.api import propostas
    from backend.app.acesso.web import LimiteTaxa
    monkeypatch.setattr(propostas, "_limite", LimiteTaxa(1000, 60))
    p = _criar(app)
    slug = p["link"].rsplit("/", 1)[1]
    for _ in range(propostas.MAX_FALHAS):
        app.post(f"/api/proposta/{slug}/abrir", headers=CSRF, json={"codigo": "ZZZZ-ZZZZ"})
    assert app.post(f"/api/proposta/{slug}/abrir", headers=CSRF, json={"codigo": p["codigo"]}).status_code == 423


def test_so_admin_gerencia(app):
    criar("u@x.gov.br")
    entrar(app, "u@x.gov.br")
    assert app.get("/api/admin/propostas").status_code == 403
    assert app.post("/api/admin/propostas", headers=CSRF, json=NOVA).status_code == 403


def test_validacao(app):
    criar("adm@x.gov.br", papel="admin")
    entrar(app, "adm@x.gov.br")
    for ruim in ({**NOVA, "desconto_pct": 90}, {**NOVA, "uf": "ALA"}, {**NOVA, "populacao": 10}, {**NOVA, "extra": 1}):
        assert app.post("/api/admin/propostas", headers=CSRF, json=ruim).status_code == 422
