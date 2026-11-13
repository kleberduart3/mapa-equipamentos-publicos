"""Resumo compacto das respostas da API, usado no teste de regressão."""
from __future__ import annotations


def resumo_cobertura(r: dict) -> dict:
    hexes = r["hex"]["features"]
    return {
        "indicadores": r["indicadores"],
        "n_hex": len(hexes),
        "soma_deficit": round(sum(f["properties"]["deficit"] for f in hexes), 0),
        "radar": [[round(c, 4) for c in f["geometry"]["coordinates"]] for f in r["radar"]["features"]],
    }


def resumo_prioridade(fc: dict) -> dict:
    v = [f["properties"]["prioridade_geral"] for f in fc["features"]]
    return {"n": len(v), "soma": round(sum(v), 0)}


def resumo_areas(fc: dict) -> dict:
    return {"n": len(fc["features"]), "raios": sorted({f["properties"]["raio_m"] for f in fc["features"]})}
