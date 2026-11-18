"""Metas do PNE, custo da simulação e fila da creche (só agregados, planilha descartada)."""
from __future__ import annotations

import io
import json

import pytest

from test_acesso import CSRF, app, criar, entrar  # noqa: F401 – app é fixture

COD = "2700300"


@pytest.fixture(autouse=True)
def _processado():
    from backend.app.config import municipio
    if not municipio(COD).processado:
        pytest.skip("Arapiraca não processada nesta máquina")


@pytest.fixture
def prefeitura_tmp(tmp_path, monkeypatch):
    """A fila é gravada numa pasta temporária, não em dados/ de verdade."""
    from backend.app.config import municipio
    monkeypatch.setattr(municipio(COD), "prefeitura", tmp_path / "prefeitura")
    return tmp_path / "prefeitura"


def test_metas_pne_usa_matriculas_de_todas_as_redes(app):
    criar("a@x.gov.br", acessos=[(COD, "consulta")])
    entrar(app, "a@x.gov.br")
    r = app.get(f"/api/{COD}/metas?modo=reta")
    assert r.status_code == 200, r.text
    m = {x["tipo"]: x for x in r.json()["metas"]}
    c = m["creche"]
    assert c["matriculas"] == sum(c["matriculas_por_rede"].values())        # inclui a privada
    assert c["taxa_pct"] == pytest.approx(100 * c["matriculas"] / c["pop_faixa"], abs=0.1)
    assert c["vagas_para_meta"] == max(0, round(c["meta_pct"] / 100 * c["pop_faixa"] - c["matriculas"]))
    assert "pre_escola" in m and r.json()["referencia"]


def test_custo_da_simulacao_respeita_capacidade():
    from backend.app import servicos
    cap = servicos.tipos(COD)["creche"]["custo"]["capacidade"]
    k = servicos.custo_unidade(COD, "creche", 10 * cap)
    assert k["atendidos"] == cap and k["unidades_para_demanda"] == 10
    assert k["obra_por_atendido_rs"] == round(k["obra_rs"] / cap)
    k = servicos.custo_unidade(COD, "creche", 40)
    assert k["atendidos"] == 40 and k["unidades_para_demanda"] == 1


def _planilha() -> bytes:
    from backend.app import fila
    por_cep, _ = fila._cnefe_ceps(COD)
    cep = next(iter(por_cep))
    linhas = ["nome;cpf;cep;numero;latitude;longitude",
              "Criança A;111;;;-9.7525;-36.6600",
              "Criança B;222;;;-9.7525;-36.6600",
              f"Criança C;333;{cep[:5]}-{cep[5:]};;;",
              "Criança D;444;00000-000;;;",                 # CEP inexistente: sem local
              "Criança E;555;;;-23.55;-46.63"]              # São Paulo: fora do município
    return "\n".join(linhas).encode("utf-8")


def test_fila_guarda_so_contagem_e_descarta_a_planilha(app, prefeitura_tmp, tmp_path, monkeypatch):
    import tempfile
    pastas = []
    original = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda *a, **k: pastas.append(original(*a, **k)) or pastas[-1])

    criar("g@x.gov.br", acessos=[(COD, "gestor")])
    entrar(app, "g@x.gov.br")
    r = app.post(f"/api/{COD}/upload-fila", headers=CSRF,
                 files={"arquivos": ("fila.csv", io.BytesIO(_planilha()), "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["total"] == 5 and d["localizados"] == 3
    assert d["sem_local"] == 1 and d["fora_do_municipio"] == 1

    # a planilha não sobrevive em disco; o que fica não tem dado pessoal
    from pathlib import Path
    assert pastas and not any(Path(p).exists() for p in pastas)
    salvos = list(prefeitura_tmp.rglob("*"))
    assert [p.name for p in salvos] == ["fila_creche.json"]
    texto = salvos[0].read_text(encoding="utf-8")
    for proibido in ("Criança", "111", "222", "333", "nome", "cpf"):
        assert proibido not in texto
    assert sum(json.loads(texto)["por_hex"].values()) == 3

    g = app.get(f"/api/{COD}/fila").json()
    assert g["existe"] and g["localizados"] == 3
    assert sum(f["properties"]["fila"] for f in g["hex"]["features"]) == 3


def test_fila_so_gestor_envia(app, prefeitura_tmp):
    criar("c@x.gov.br", acessos=[(COD, "consulta")])
    entrar(app, "c@x.gov.br")
    r = app.post(f"/api/{COD}/upload-fila", headers=CSRF,
                 files={"arquivos": ("fila.csv", io.BytesIO(b"cep\n57300000"), "text/csv")})
    assert r.status_code == 403
    assert app.get(f"/api/{COD}/fila").json() == {"existe": False}
