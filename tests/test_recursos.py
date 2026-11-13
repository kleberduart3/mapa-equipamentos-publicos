"""Ranking de bairros, déficit por setor, simulador e tempo a pé – coerência com a cobertura.

Usa os dados reais de Arapiraca (lento): pytest -m lento
"""
from __future__ import annotations

import numpy as np
import pytest

COD = "2700300"
pytestmark = pytest.mark.lento


@pytest.fixture(scope="module")
def srv():
    from backend.app import config, servicos
    if not config.municipio(COD).processado:
        pytest.skip("dados de Arapiraca não processados nesta máquina")
    return servicos


@pytest.mark.parametrize("modo", ["reta", "rede"])
def test_ranking_e_setores_somam_o_mesmo_que_a_cobertura(srv, modo):
    ind = srv.cobertura(COD, "creche", 500, modo)["indicadores"]
    rk = srv.ranking(COD, "creche", 500, modo)
    assert rk["total_fora"] == pytest.approx(ind["pop_descoberta"], abs=1)
    fora = [b["pop_fora"] for b in rk["bairros"]]
    assert fora == sorted(fora, reverse=True)                     # ordenado
    st = srv.setores(COD, "creche", 500, modo)
    assert sum(f["properties"]["pop_descoberta"] for f in st["features"]) == pytest.approx(ind["pop_descoberta"], abs=5)


@pytest.mark.parametrize("modo", ["reta", "rede"])
def test_simulador_confere_com_a_area_sugerida(srv, modo):
    """No centro da 1ª área sugerida, o simulador tem de achar a mesma demanda que a sugestão."""
    radar = srv.cobertura(COD, "creche", 500, modo)["radar"]["features"][0]
    lon, lat = radar["geometry"]["coordinates"]
    sim = srv.simular(COD, "creche", 500, modo, lon, lat)
    assert sim["demanda_sem_cobertura_absorvida"] == radar["properties"]["sem_cobertura"]
    assert sim["demanda_total_absorvivel"] == radar["properties"]["demanda_absorvida"]
    assert sim["pct_coberta_depois"] > sim["pct_coberta_antes"]
    assert sim["area"]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_simulador_recusa_ponto_fora_do_municipio(srv):
    with pytest.raises(srv.ForaDoMunicipio):
        srv.simular(COD, "ubs", 1000, "reta", -46.63, -23.55)     # São Paulo


def test_tempo_a_pe_nunca_menor_que_linha_reta(srv):
    reta = srv._dist_proxima(COD, "ubs", "reta")
    pe = srv._dist_proxima(COD, "ubs", "rede")
    assert np.isfinite(pe).all()
    assert (pe >= reta - 1e-3).all()
    # quem está dentro do raio a pé tem, de fato, um equipamento a até essa distância
    r, _ = srv._resultado(COD, "ubs", 1000, "rede")
    from backend.app.analise.contexto import base
    raios = np.where(base(COD).pts["rural"].to_numpy(), 1000 * base(COD).fr, 1000)
    assert (pe[r.coberto] <= raios[r.coberto] + 1e-3).all()
    assert (pe[~r.coberto] > raios[~r.coberto] - 1e-3).all()
