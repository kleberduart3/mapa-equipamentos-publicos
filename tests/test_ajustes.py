"""Ajustes de equipamentos pela prefeitura: quem pode, o que muda no cálculo, desfazer."""
from __future__ import annotations

import pytest

from test_acesso import CSRF, app, criar, entrar  # noqa: F401 – app é fixture

COD = "2700300"
# um ponto no centro de Arapiraca e outro bem fora do município
DENTRO, FORA = {"lat": -9.7517, "lon": -36.6611}, {"lat": -9.40, "lon": -36.20}


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    from backend.app import ajustes, servicos
    from backend.app.config import municipio
    if not municipio(COD).processado:
        pytest.skip("Arapiraca não processada nesta máquina")
    monkeypatch.setattr(ajustes, "_arquivo", lambda m: tmp_path / f"ajustes_{m.cod}.json")
    monkeypatch.setattr(servicos, "recalcular", lambda cod, esperar=False: servicos.esquecer(cod))
    servicos.esquecer(COD)
    yield
    servicos.esquecer(COD)


def _creches(app):
    return [f for f in app.get(f"/api/{COD}/equipamentos").json()["features"] if f["properties"]["tipo"] == "creche"]


def test_consulta_ve_mas_nao_altera(app):
    criar("c@x.gov.br", acessos=[(COD, "consulta")])
    entrar(app, "c@x.gov.br")
    r = app.get(f"/api/{COD}/ajustes")
    assert r.status_code == 200 and r.json()["ajustes"] == []
    cid = _creches(app)[0]["properties"]["id"]
    assert app.put(f"/api/{COD}/ajustes/escola/{cid}", headers=CSRF, json={"ativo": False}).status_code == 403
    assert app.post(f"/api/{COD}/ajustes", headers=CSRF,
                    json={"fonte": "escola", "nome": "Creche Nova", **DENTRO, "capacidade": {"creche": 100}}).status_code == 403


def test_gestor_move_desativa_inclui_e_desfaz(app):
    criar("g@x.gov.br", acessos=[(COD, "gestor")])
    entrar(app, "g@x.gov.br")
    antes = _creches(app)
    alvo = antes[0]["properties"]["id"]
    pct0 = app.get(f"/api/{COD}/cobertura?tipo=creche&raio=500").json()["indicadores"]["pct_coberta"]

    # corrigir o local: a unidade passa a "prefeitura" (localização confiável) no ponto informado
    r = app.put(f"/api/{COD}/ajustes/escola/{alvo}", headers=CSRF, json={**DENTRO, "obs": "conferido no local"})
    assert r.status_code == 200, r.text
    f = next(x for x in _creches(app) if x["properties"]["id"] == alvo)
    assert f["properties"]["fonte_coord"] == "prefeitura" and f["properties"]["ajustado"]
    assert f["geometry"]["coordinates"] == pytest.approx([DENTRO["lon"], DENTRO["lat"]], abs=1e-6)

    # fora do município é recusado
    assert app.put(f"/api/{COD}/ajustes/escola/{alvo}", headers=CSRF, json=FORA).status_code == 400
    # capacidade de UBS numa escola é recusada
    assert app.put(f"/api/{COD}/ajustes/escola/{alvo}", headers=CSRF, json={"capacidade": {"ubs": 2}}).status_code == 400

    # desativar tira a unidade do mapa e do cálculo
    assert app.put(f"/api/{COD}/ajustes/escola/{alvo}", headers=CSRF, json={"ativo": False}).status_code == 200
    assert alvo not in {x["properties"]["id"] for x in _creches(app)}

    # incluir uma creche nova aumenta a cobertura
    r = app.post(f"/api/{COD}/ajustes", headers=CSRF, json={"fonte": "escola", "nome": "  Creche   Nova Esperança ",
                                                              "lat": -9.7905, "lon": -36.6280, "capacidade": {"creche": 150}})
    assert r.status_code == 201, r.text
    nova = r.json()["chave"].split(":", 1)[1]
    nf = next(x for x in _creches(app) if x["properties"]["id"] == nova)
    assert nf["properties"]["nome"] == "Creche Nova Esperança" and nf["properties"]["mat_creche"] == 150
    lista = app.get(f"/api/{COD}/ajustes").json()["ajustes"]
    assert {a["chave"] for a in lista} == {f"escola:{alvo}", f"escola:{nova}"}
    assert next(a for a in lista if a["id"] == alvo)["resumo"] == "local corrigido, desativada"

    # desfazer volta ao dado oficial
    assert app.delete(f"/api/{COD}/ajustes/escola/{alvo}", headers=CSRF).status_code == 200
    assert app.delete(f"/api/{COD}/ajustes/escola/{nova}", headers=CSRF).status_code == 200
    depois = _creches(app)
    assert [x["geometry"]["coordinates"] for x in depois] == [x["geometry"]["coordinates"] for x in antes]
    pct1 = app.get(f"/api/{COD}/cobertura?tipo=creche&raio=500").json()["indicadores"]["pct_coberta"]
    assert pct1 == pct0
    assert app.delete(f"/api/{COD}/ajustes/escola/{alvo}", headers=CSRF).status_code == 404


def test_unidade_sem_localizacao_entra_no_calculo_quando_marcada(app):
    from backend.app import servicos
    criar("adm@x.gov.br", papel="admin")
    entrar(app, "adm@x.gov.br")
    sem = app.get(f"/api/{COD}/ajustes").json()["sem_localizacao"]
    if not sem:
        pytest.skip("nenhuma unidade sem localização em Arapiraca")
    u = sem[0]
    r = app.put(f"/api/{COD}/ajustes/{u['fonte']}/{u['id']}", headers=CSRF, json=DENTRO)
    assert r.status_code == 200, r.text
    assert u["chave"] not in {s["chave"] for s in servicos.sem_localizacao(COD)}
    ids = {f["properties"]["id"] for f in app.get(f"/api/{COD}/equipamentos").json()["features"]}
    assert u["id"] in ids
