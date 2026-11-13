"""Caminhos do projeto e leitura de config/parametros.yaml."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
DADOS = RAIZ / "dados"
BRUTOS = DADOS / "brutos"
PROCESSADOS = DADOS / "processados"
SAIDAS = DADOS / "saidas"
CONFIG = RAIZ / "config" / "parametros.yaml"

CRS_GEO = "EPSG:4674"  # SIRGAS 2000 geográfico (malhas do IBGE)


@lru_cache
def parametros() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def municipio() -> dict:
    m = parametros()["municipio"]
    return {**m, "codigo_ibge6": m["codigo_ibge"][:6]}


def crs_metrico() -> str:
    return parametros()["municipio"]["crs_metrico"]
