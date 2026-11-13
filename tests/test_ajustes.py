"""Ajustes da prefeitura no cadastro de equipamentos (capacidade, local, exclusão e inclusão).

Roda com um município sintético pequeno (dois setores, quatro escolas, duas UBS),
sem depender dos dados reais de Arapiraca.
"""
from __future__ import annotations

import os

import pytest

os.environ.update({"MAPA_AMBIENTE": "teste", "MAPA_URL_BASE": "http://testserver",
                   "MAPA_AQUECER_AO_INICIAR": "false", "MAPA_COOKIE_SEGURO": "false"})

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

from backend.app import config  # noqa: E402
from backend.app.acesso import configuracao  # noqa: E402
from backend.app.acesso import credenciais as cr  # noqa: E402
from backend.app.acesso import modelos as md  # noqa: E402

COD = "2799990"
CRS = "EPSG:31984"
SENHA = "uma frase bem comprida 42"
CSRF = {"X-CSRF": "1", "Origin": "http://testserver"}
# canto sudoeste do município sintético, em UTM 24S (perto de Arapiraca)
X0, Y0 = 760_000.0, 8_920_000.0


def _ll(x, y):
    p = gpd.GeoSeries([Point(x, y)], crs=CRS).to_crs("EPSG:4326").iloc[0]
    return p.y, p.x


@pytest.fixture()
def municipio_sintetico(tmp_path, monkeypatch):
    """Dois setores de 1 km² lado a lado; escolas e UBS concentradas no setor oeste."""
    cfgdir, proc, brutos, saidas = (tmp_path / n for n in ("config", "processados", "brutos", "saidas"))
    cfgdir.mkdir()
    (cfgdir / f"{COD}.yaml").write_text(f'nome: Cidade Teste\nuf: AL\ncrs_metrico: "{CRS}"\nparametros: {{}}\n',
                                        encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_MUNICIPIOS", cfgdir)
    monkeypatch.setattr(config, "PROCESSADOS", proc)
    monkeypatch.setattr(config, "BRUTOS", brutos)
    monkeypatch.setattr(config, "SAIDAS", saidas)
    config.municipio.cache_clear()
    d = proc / COD
    d.mkdir(parents=True)

    oeste, leste = box(X0, Y0, X0 + 1000, Y0 + 1000), box(X0 + 1000, Y0, X0 + 2000, Y0 + 1000)
    setores = gpd.GeoDataFrame({
        "CD_SETOR": ["1", "2"], "NM_BAIRRO": ["Centro", "Leste"], "NM_DIST": ["Sede", "Sede"],
        "SITUACAO": ["Urbana", "Urbana"], "pop_total": [4000.0, 4000.0], "pop_0_3": [200.0, 200.0],
        "pop_4_5": [100.0, 100.0], "pop_6_10": [250.0, 250.0], "pop_11_14": [200.0, 200.0],
        "pop_15_17": [150.0, 150.0]}, geometry=[oeste, leste], crs=CRS)
    setores.to_parquet(d / "setores.parquet")
    gpd.GeoDataFrame(geometry=[oeste.union(leste)], crs=CRS).to_parquet(d / "limite.parquet")
    pts, cds = [], []
    for i in range(10):
        for j in range(10):
            for k, x0 in enumerate((X0, X0 + 1000)):
                pts.append(Point(x0 + 50 + 100 * i, Y0 + 50 + 100 * j))
                cds.append(str(k + 1))
    gpd.GeoDataFrame({"CD_SETOR": cds}, geometry=pts, crs=CRS).to_parquet(d / "enderecos.parquet")

    def escola(cod, nome, x, y, creche=0, pre=0, ai=0, af=0, dep="Municipal"):
        lat, lon = _ll(x, y)
        return {"codigo_inep": cod, "escola": nome, "dependencia": dep, "localizacao": "Urbana",
                "situacao": "FUNCIONANDO", "endereco": f"Rua {nome}, 10 - Centro", "em_funcionamento": True,
                "mat_creche": creche, "mat_pre_escola": pre, "mat_fund_iniciais": ai, "mat_fund_finais": af,
                "mat_medio": 0, "oferta_creche": creche > 0, "oferta_pre_escola": pre > 0,
                "oferta_fund_iniciais": ai > 0, "oferta_fund_finais": af > 0, "oferta_medio": False,
                "fonte_coord": "inep_catalogo", "latitude": lat, "longitude": lon, "geometry": Point(x, y)}

    escolas = gpd.GeoDataFrame([
        escola("27000001", "Creche Sol", X0 + 300, Y0 + 500, creche=40),
        escola("27000002", "Creche Lua", X0 + 700, Y0 + 500, creche=60),
        escola("27000003", "Escola Rio", X0 + 500, Y0 + 300, pre=80, ai=300),
        escola("27000004", "Escola Estadual", X0 + 500, Y0 + 700, af=200, dep="Estadual"),
    ], crs=CRS)
    escolas.to_parquet(d / "escolas.parquet")

    def ubs(cnes, nome, x, y, eq):
        lat, lon = _ll(x, y)
        return {"cnes": cnes, "nome": nome, "tipo": "UBS", "ativa": True, "equipes_ab": eq,
                "competencia_equipes": "2410", "logradouro": f"Rua {nome}", "numero": "1", "bairro": "Centro",
                "cep": "57300000", "lat": lat, "lon": lon, "fonte_coord": "cnes", "geometry": Point(x, y)}

    gpd.GeoDataFrame([ubs("2000001", "UBS Norte", X0 + 400, Y0 + 400, 1),
                      ubs("2000002", "UBS Sul", X0 + 600, Y0 + 600, 2)], crs=CRS).to_parquet(d / "ubs.parquet")

    from backend.app import servicos
    servicos.esquecer()
    yield config.municipio(COD)
    servicos.esquecer()
    config.municipio.cache_clear()


@pytest.fixture()
def app(tmp_path, monkeypatch, municipio_sintetico):
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


def _conta(email: str, papel_mun: str) -> None:
    with md.nova_sessao_db() as s:
        u = md.Usuario(email=email, nome="Teste", papel="usuario")
        u.acessos = [md.Acesso(cod_municipio=COD, papel=papel_mun)]
        u.senha_hash = cr.gerar_hash(SENHA)
        s.add(u)
        s.commit()


def _entrar(c: TestClient, email: str) -> None:
    assert c.post("/auth/entrar", json={"email": email, "senha": SENHA}, headers=CSRF).status_code == 200


def _linhas(c, tipo):
    r = c.get(f"/api/{COD}/ajustes/equipamentos?tipo={tipo}")
    assert r.status_code == 200, r.text
    return r.json()


def _linha(c, tipo, ident):
    return next(l for l in _linhas(c, tipo)["linhas"] if l["id"] == ident)


# --------------------------------------------------------------------------- aplicar (sem API)
def test_capacidade_informada_entra_no_calculo(municipio_sintetico):
    from backend.app.analise import ajustes, cobertura as cob

    m = municipio_sintetico
    esc = gpd.read_parquet(m.processados / "escolas.parquet")
    ub = gpd.read_parquet(m.processados / "ubs.parquet")
    a = {"unidades": {"inep:27000001": {"capacidade": {"creche": 150}},
                      "cnes:2000002": {"excluida": True},
                      "pref:1": {"nova": True, "fonte": "escola", "nome": "Creche Nova", "lat": -9.7, "lon": -36.6,
                                 "rede": "Municipal", "capacidade": {"creche": 90}}}}
    e2, u2 = ajustes.aplicar(esc, ub, a, m.P["equipamentos"])
    fac, _ = cob.ofertas("creche", m.P["equipamentos"]["creche"], e2, u2)
    cap = dict(zip(fac["id"], fac["capacidade"]))
    assert cap["27000001"] == 150                      # vaga informada no lugar da matrícula (40)
    assert cap["27000002"] == 60                       # sem ajuste: matrícula
    assert cap["PREF-1"] == 90                         # unidade incluída
    fu, _ = cob.ofertas("ubs", m.P["equipamentos"]["ubs"], e2, u2)
    assert list(fu["id"]) == ["2000001"]               # a excluída sai do cálculo
    assert len(esc) == 4 and "cap_creche" not in esc  # a base oficial não é alterada


def test_capacidade_zero_tira_a_etapa(municipio_sintetico):
    from backend.app.analise import ajustes, cobertura as cob

    m = municipio_sintetico
    esc = gpd.read_parquet(m.processados / "escolas.parquet")
    ub = gpd.read_parquet(m.processados / "ubs.parquet")
    e2, u2 = ajustes.aplicar(esc, ub, {"unidades": {"inep:27000003": {"capacidade": {"pre_escola": 0, "creche": 30}}}},
                             m.P["equipamentos"])
    pre, _ = cob.ofertas("pre_escola", m.P["equipamentos"]["pre_escola"], e2, u2)
    cre, _ = cob.ofertas("creche", m.P["equipamentos"]["creche"], e2, u2)
    assert "27000003" not in set(pre["id"])
    assert "27000003" in set(cre["id"])                # passou a oferecer creche


# --------------------------------------------------------------------------- API
def test_consulta_ve_a_lista_mas_nao_edita(app):
    _conta("consulta@x.br", "consulta")
    _entrar(app, "consulta@x.br")
    j = _linhas(app, "creche")
    assert j["pode_editar"] is False
    assert {l["nome"] for l in j["linhas"]} == {"Creche Sol", "Creche Lua"}
    assert app.put(f"/api/{COD}/ajustes/equipamentos/inep:27000001", json={"tipo": "creche", "capacidade": 99},
                   headers=CSRF).status_code == 403
    assert app.post(f"/api/{COD}/ajustes/equipamentos", headers=CSRF,
                    json={"tipo": "creche", "nome": "X", "lat": -9.7, "lon": -36.6, "capacidade": 1}).status_code == 403


def test_sem_login_e_sem_acesso(app):
    assert app.get(f"/api/{COD}/ajustes/equipamentos?tipo=creche").status_code == 401
    _conta("outro@x.br", "gestor")
    with md.nova_sessao_db() as s:                       # tira o acesso ao município
        u = s.query(md.Usuario).filter_by(email="outro@x.br").one()
        u.acessos = []
        s.commit()
    _entrar(app, "outro@x.br")
    assert app.get(f"/api/{COD}/ajustes/equipamentos?tipo=creche").status_code == 404


def test_gestor_ajusta_capacidade_e_o_mapa_muda(app):
    _conta("gestor@x.br", "gestor")
    _entrar(app, "gestor@x.br")
    antes = app.get(f"/api/{COD}/cobertura?tipo=creche&raio=500").json()["indicadores"]
    assert antes["deficit_capacidade"] > 0
    r = app.put(f"/api/{COD}/ajustes/equipamentos/inep:27000001", headers=CSRF,
                json={"tipo": "creche", "capacidade": 400})
    assert r.status_code == 200, r.text
    l = _linha(app, "creche", "27000001")
    assert (l["capacidade"], l["capacidade_oficial"], l["capacidade_informada"], l["ajustada"]) == (400, 40, True, True)
    depois = app.get(f"/api/{COD}/cobertura?tipo=creche&raio=500").json()["indicadores"]
    assert depois["deficit_capacidade"] < antes["deficit_capacidade"]
    # desfazer volta ao número oficial
    assert app.delete(f"/api/{COD}/ajustes/equipamentos/inep:27000001", headers=CSRF).status_code == 200
    assert _linha(app, "creche", "27000001")["capacidade"] == 40
    assert app.get(f"/api/{COD}/cobertura?tipo=creche&raio=500").json()["indicadores"] == antes
    with md.nova_sessao_db() as s:
        acoes = [e.acao for e in s.query(md.Evento).all()]
    assert "ajuste_equipamento" in acoes and "ajuste_desfeito" in acoes


def test_ubs_por_equipes_local_e_exclusao(app):
    _conta("gestor@x.br", "gestor")
    _entrar(app, "gestor@x.br")
    l = _linha(app, "ubs", "2000001")
    assert (l["equipes"], l["capacidade"]) == (1, 3500)
    assert app.put(f"/api/{COD}/ajustes/equipamentos/cnes:2000001", headers=CSRF,
                   json={"tipo": "ubs", "equipes": 3}).json()["ok"]
    assert _linha(app, "ubs", "2000001")["capacidade"] == 3 * 3500
    lat, lon = _ll(X0 + 1500, Y0 + 500)                   # muda para o setor leste
    assert app.put(f"/api/{COD}/ajustes/equipamentos/cnes:2000001", headers=CSRF,
                   json={"tipo": "ubs", "lat": lat, "lon": lon, "endereco": "Av. Nova, 200"}).status_code == 200
    l = _linha(app, "ubs", "2000001")
    assert l["bairro"] == "Leste" and l["endereco"] == "Av. Nova, 200" and l["fonte_coord"] == "prefeitura"
    assert app.put(f"/api/{COD}/ajustes/equipamentos/cnes:2000002", headers=CSRF,
                   json={"tipo": "ubs", "excluida": True}).status_code == 200
    eq = app.get(f"/api/{COD}/equipamentos").json()["features"]
    assert {f["properties"]["id"] for f in eq if f["properties"]["tipo"] == "ubs"} == {"2000001"}
    assert _linha(app, "ubs", "2000002")["excluida"] is True       # continua na lista, para desfazer
    assert app.put(f"/api/{COD}/ajustes/equipamentos/cnes:2000002", headers=CSRF,
                   json={"tipo": "ubs", "excluida": False}).status_code == 200
    eq = app.get(f"/api/{COD}/equipamentos").json()["features"]
    assert {f["properties"]["id"] for f in eq if f["properties"]["tipo"] == "ubs"} == {"2000001", "2000002"}


def test_incluir_e_remover_unidade_nova(app):
    _conta("gestor@x.br", "gestor")
    _entrar(app, "gestor@x.br")
    lat, lon = _ll(X0 + 1500, Y0 + 500)
    r = app.post(f"/api/{COD}/ajustes/equipamentos", headers=CSRF,
                 json={"tipo": "creche", "nome": "CMEI Leste", "endereco": "Rua A, 1", "lat": lat, "lon": lon,
                       "capacidade": 120})
    assert r.status_code == 200, r.text
    chave = r.json()["chave"]
    l = _linha(app, "creche", r.json()["id"])
    assert l["nova"] and l["capacidade"] == 120 and l["bairro"] == "Leste"
    eq = app.get(f"/api/{COD}/equipamentos").json()["features"]
    assert any(f["properties"]["nome"] == "CMEI Leste" for f in eq)
    ind = app.get(f"/api/{COD}/cobertura?tipo=creche&raio=500").json()["indicadores"]
    assert ind["equipamentos"] == 3
    assert app.delete(f"/api/{COD}/ajustes/equipamentos/{chave}", headers=CSRF).status_code == 200
    assert all(l["nome"] != "CMEI Leste" for l in _linhas(app, "creche")["linhas"])


def test_validacoes(app):
    _conta("gestor@x.br", "gestor")
    _entrar(app, "gestor@x.br")
    url = f"/api/{COD}/ajustes/equipamentos"
    # fora do município
    assert app.post(url, headers=CSRF, json={"tipo": "creche", "nome": "Longe", "lat": -23.5, "lon": -46.6,
                                             "capacidade": 10}).status_code == 400
    # sem capacidade
    lat, lon = _ll(X0 + 500, Y0 + 500)
    assert app.post(url, headers=CSRF, json={"tipo": "creche", "nome": "Sem vaga", "lat": lat, "lon": lon}).status_code == 400
    # campo desconhecido, chave inventada, unidade que não está na lista, tipo inexistente
    assert app.put(f"{url}/inep:27000001", headers=CSRF, json={"tipo": "creche", "senha": "x"}).status_code == 422
    assert app.put(f"{url}/inep:../../etc", headers=CSRF, json={"tipo": "creche", "capacidade": 1}).status_code == 404
    assert app.put(f"{url}/inep:99999999", headers=CSRF, json={"tipo": "creche", "capacidade": 1}).status_code == 404
    assert app.put(f"{url}/inep:27000004", headers=CSRF, json={"tipo": "creche", "capacidade": 1}).status_code == 404
    assert app.put(f"{url}/inep:27000001", headers=CSRF, json={"tipo": "piscina", "capacidade": 1}).status_code == 404
    assert app.put(f"{url}/inep:27000001", headers=CSRF, json={"tipo": "creche", "equipes": 2}).status_code == 400
    assert app.put(f"{url}/inep:27000001", headers=CSRF, json={"tipo": "creche", "capacidade": -5}).status_code == 422
    assert app.delete(f"{url}/inep:27000002", headers=CSRF).status_code == 404     # sem ajuste para desfazer
    # sem o cabeçalho anti-CSRF
    assert app.put(f"{url}/inep:27000001", json={"tipo": "creche", "capacidade": 1}).status_code == 403


def test_arquivo_de_ajustes_sobrevive_a_recarga(app, municipio_sintetico):
    from backend.app import servicos
    from backend.app.analise import ajustes

    _conta("gestor@x.br", "gestor")
    _entrar(app, "gestor@x.br")
    app.put(f"/api/{COD}/ajustes/equipamentos/inep:27000002", headers=CSRF, json={"tipo": "creche", "capacidade": 75})
    dados = ajustes.ler(municipio_sintetico)
    assert dados["unidades"]["inep:27000002"]["capacidade"] == {"creche": 75}
    assert dados["unidades"]["inep:27000002"]["alterado_por"] == "gestor@x.br"
    servicos.esquecer()                                   # simula reinício do servidor
    assert _linha(app, "creche", "27000002")["capacidade"] == 75
    assert np.isfinite(_linha(app, "creche", "27000002")["lat"])
