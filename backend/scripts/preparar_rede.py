"""Fase 2 – baixa e prepara a malha viária de pedestres (OpenStreetMap).

    python backend/scripts/preparar_rede.py [--forcar]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import geopandas as gpd  # noqa: E402

from backend.app.config import municipio_cli  # noqa: E402
from backend.app.ingestao import osm  # noqa: E402


def main() -> None:
    m, resto = municipio_cli()
    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true", help="baixa de novo mesmo se já existir")
    a = ap.parse_args(resto)
    t0 = time.time()
    limite = gpd.read_parquet(m.processados / "limite.parquet")
    G = osm.baixar_malha(m, limite, forcar=a.forcar)
    print(f"grafo OSM: {G.number_of_nodes():,} nós, {G.number_of_edges():,} arestas ({time.time() - t0:.0f} s)")
    nos, arestas = osm.preparar_rede(m, G)
    osm.salvar_rede(m, nos, arestas)

    print(f"rede salva: {len(nos):,} nós, {len(arestas):,} arestas, {arestas['comprimento_m'].sum() / 1000:,.0f} km de vias")
    print(arestas["via"].value_counts().head(12).to_string())


if __name__ == "__main__":
    main()
