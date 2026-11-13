"""Regressão: os números de Arapiraca não podem mudar com refatorações.

O gabarito (fixtures/arapiraca_2700300.json) foi tirado da versão publicada em
12/11/2026, antes da versão multi-município. Lento (carrega a malha a pé):
    pytest -m lento
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _resumo import resumo_areas, resumo_cobertura, resumo_prioridade

COD = "2700300"
GABARITO = json.loads((Path(__file__).parent / "fixtures" / f"arapiraca_{COD}.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.lento


@pytest.fixture(scope="module")
def srv():
    from backend.app import config, servicos
    if not config.municipio(COD).processado:
        pytest.skip("dados de Arapiraca não processados nesta máquina")
    return servicos


@pytest.mark.parametrize("chave", sorted(GABARITO["cobertura"]))
def test_cobertura(srv, chave):
    t, raio, modo = chave.rsplit("_", 2)
    obtido = resumo_cobertura(srv.cobertura(COD, t, int(raio), modo))
    esperado = GABARITO["cobertura"][chave]
    assert obtido["indicadores"] == esperado["indicadores"]
    assert obtido["n_hex"] == esperado["n_hex"]
    assert obtido["soma_deficit"] == pytest.approx(esperado["soma_deficit"], abs=2)
    assert obtido["radar"] == esperado["radar"]


@pytest.mark.parametrize("modo", ["reta", "rede"])
def test_prioridade(srv, modo):
    assert resumo_prioridade(srv.prioridade(COD, modo)) == GABARITO["prioridade"][modo]


@pytest.mark.parametrize("t", sorted(GABARITO["areas"]))
def test_areas(srv, t):
    raio = int(srv.tipos(COD)[t]["raio_m"])
    assert resumo_areas(srv.areas(COD, t, raio)) == GABARITO["areas"][t]


def test_equipamentos(srv):
    assert len(srv.equipamentos(COD)["features"]) == GABARITO["n_equipamentos"]
