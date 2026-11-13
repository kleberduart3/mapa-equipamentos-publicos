"""Visões salvas: quem vê, quem apaga, o que é aceito como estado."""
from __future__ import annotations

import pytest

from test_acesso import CSRF, app, criar, entrar  # noqa: F401 – app é fixture

COD = "2700300"
ESTADO = {"mostrar": "creche", "modo": "reta", "unid": "setor", "raios": {"creche": 800, "ubs": 1500},
          "visiveis": {"creche": True, "ubs": False}, "camadas": {"raios": True, "radar": False, "estaduais": False},
          "mapa": {"lng": -36.66, "lat": -9.75, "zoom": 13.2}, "sim": {"tipo": "creche", "lng": -36.65, "lat": -9.74}}


@pytest.fixture(autouse=True)
def _processado():
    from backend.app.config import municipio
    if not municipio(COD).processado:
        pytest.skip("Arapiraca não processada nesta máquina")


def test_salvar_listar_e_restaurar(app):
    criar("a@x.gov.br", acessos=[(COD, "consulta")])
    entrar(app, "a@x.gov.br")
    r = app.post(f"/api/{COD}/visoes", headers=CSRF, json={"nome": "  Creches   norte  ", "estado": ESTADO})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["nome"] == "Creches norte" and v["autor"] == "A" and v["pode_apagar"]
    lista = app.get(f"/api/{COD}/visoes").json()
    assert [x["id"] for x in lista] == [v["id"]]
    assert lista[0]["estado"] == ESTADO


def test_equipe_ve_mas_so_autor_ou_admin_apaga(app):
    criar("a@x.gov.br", acessos=[(COD, "gestor")])
    criar("b@x.gov.br", acessos=[(COD, "consulta")])
    criar("adm@x.gov.br", papel="admin")
    entrar(app, "a@x.gov.br")
    vid = app.post(f"/api/{COD}/visoes", headers=CSRF, json={"nome": "Da A", "estado": ESTADO}).json()["id"]
    app.post("/auth/sair", headers=CSRF)

    entrar(app, "b@x.gov.br")
    lista = app.get(f"/api/{COD}/visoes").json()
    assert lista[0]["id"] == vid and lista[0]["pode_apagar"] is False
    assert app.delete(f"/api/{COD}/visoes/{vid}", headers=CSRF).status_code == 403
    app.post("/auth/sair", headers=CSRF)

    entrar(app, "adm@x.gov.br")
    assert app.delete(f"/api/{COD}/visoes/{vid}", headers=CSRF).status_code == 204
    assert app.get(f"/api/{COD}/visoes").json() == []


def test_sem_acesso_ao_municipio_nao_ve_nem_salva(app):
    criar("c@x.gov.br", acessos=[("2706307", "gestor")])
    entrar(app, "c@x.gov.br")
    assert app.get(f"/api/{COD}/visoes").status_code == 404
    assert app.post(f"/api/{COD}/visoes", headers=CSRF, json={"nome": "X", "estado": ESTADO}).status_code == 404


def test_apagar_de_outro_municipio_da_404(app):
    criar("adm@x.gov.br", papel="admin")
    entrar(app, "adm@x.gov.br")
    vid = app.post(f"/api/{COD}/visoes", headers=CSRF, json={"nome": "X", "estado": ESTADO}).json()["id"]
    from backend.app.config import municipio
    if municipio("2706307").processado:
        assert app.delete(f"/api/2706307/visoes/{vid}", headers=CSRF).status_code == 404


@pytest.mark.parametrize("estado", [
    {**ESTADO, "modo": "carro"},
    {**ESTADO, "raios": {"creche": 10}},
    {**ESTADO, "raios": {"../x": 800}},
    {**ESTADO, "extra": 1},
    {**ESTADO, "mapa": {"lng": 0, "lat": 0, "zoom": 99}},
    {**ESTADO, "camadas": {"raios": True, "script": "<x>"}},
])
def test_estado_invalido_recusado(app, estado):
    criar("d@x.gov.br", acessos=[(COD, "consulta")])
    entrar(app, "d@x.gov.br")
    assert app.post(f"/api/{COD}/visoes", headers=CSRF, json={"nome": "X", "estado": estado}).status_code == 422


def test_nome_obrigatorio_e_csrf(app):
    criar("e@x.gov.br", acessos=[(COD, "consulta")])
    entrar(app, "e@x.gov.br")
    assert app.post(f"/api/{COD}/visoes", headers=CSRF, json={"nome": "   ", "estado": ESTADO}).status_code == 422
    assert app.post(f"/api/{COD}/visoes", json={"nome": "X", "estado": ESTADO}).status_code == 403


def test_atualizar_visao_so_autor_ou_admin(app):
    criar("a@x.gov.br", acessos=[(COD, "gestor")])
    criar("b@x.gov.br", acessos=[(COD, "consulta")])
    entrar(app, "a@x.gov.br")
    vid = app.post(f"/api/{COD}/visoes", headers=CSRF, json={"nome": "Antes", "estado": ESTADO}).json()["id"]
    novo = {**ESTADO, "modo": "rede", "raios": {"creche": 600}}
    r = app.put(f"/api/{COD}/visoes/{vid}", headers=CSRF, json={"estado": novo, "nome": " Depois "})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["nome"] == "Depois" and v["estado"]["modo"] == "rede" and v["estado"]["raios"] == {"creche": 600}
    assert v["atualizada_em"] and v["atualizada_por"] == "A" and v["pode_editar"]
    assert app.put(f"/api/{COD}/visoes/{vid}", headers=CSRF, json={}).status_code == 400
    assert app.put(f"/api/{COD}/visoes/{vid}", headers=CSRF, json={"estado": {**ESTADO, "modo": "voo"}}).status_code == 422
    assert app.put(f"/api/{COD}/visoes/999999", headers=CSRF, json={"nome": "X"}).status_code == 404
    app.post("/auth/sair", headers=CSRF)

    entrar(app, "b@x.gov.br")
    assert app.get(f"/api/{COD}/visoes").json()[0]["pode_editar"] is False
    assert app.put(f"/api/{COD}/visoes/{vid}", headers=CSRF, json={"nome": "Da B"}).status_code == 403


def test_camadas_desligadas_por_padrao(app):
    criar("a@x.gov.br", acessos=[(COD, "consulta")])
    entrar(app, "a@x.gov.br")
    sem_camadas = {k: v for k, v in ESTADO.items() if k != "camadas"}
    v = app.post(f"/api/{COD}/visoes", headers=CSRF, json={"nome": "Só equipamentos", "estado": sem_camadas}).json()
    assert v["estado"]["camadas"] == {"raios": False, "radar": False, "estaduais": False}


def test_relatorio_da_visao(app, monkeypatch):
    """O relatório da visão usa os raios e o modo guardados nela e leva o nome dela na capa."""
    from backend.app.api import main
    from backend.app.relatorio import gerar
    chamadas = []

    def falso(cod, destino, raios, modo, tempo, titulo):
        chamadas.append((cod, raios, modo, titulo))
        destino.write_bytes(b"%PDF-1.4 teste")
        return destino

    monkeypatch.setattr(gerar, "gerar_pdf", falso)
    monkeypatch.setattr(main, "_medidor", lambda cod, modo: None)
    criar("a@x.gov.br", acessos=[(COD, "consulta")])
    entrar(app, "a@x.gov.br")
    vid = app.post(f"/api/{COD}/visoes", headers=CSRF, json={"nome": "Creches norte", "estado": ESTADO}).json()["id"]
    r = app.get(f"/api/{COD}/relatorio.pdf?visao={vid}")
    assert r.status_code == 200, r.text
    assert "creches_norte" in r.headers["content-disposition"]
    assert chamadas == [(COD, {"creche": 800, "ubs": 1500}, "reta", "Creches norte")]
    assert app.get(f"/api/{COD}/relatorio.pdf?visao=999999").status_code == 404
    assert app.get(f"/api/{COD}/relatorio.pdf?visao=abc").status_code == 400
