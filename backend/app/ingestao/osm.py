"""Malha viária de pedestres do OpenStreetMap (fase 2: distância a pé).

Baixa pela Overpass API (OSMnx) as vias caminháveis do município com uma folga
de 2 km além do limite, para que quem mora na divisa alcance equipamentos pelo
caminho real. Guarda o grafo bruto (GraphML) e uma versão simplificada em
GeoParquet: nós (x, y) e arestas (u, v, comprimento em metros), no CRS métrico.
"""
from __future__ import annotations

import time

import geopandas as gpd
import pandas as pd

from ..config import BRUTOS, CRS_GEO, Municipio

FOLGA_M = 2000


def caminho_bruto(m: Municipio):
    return m.brutos / "osm_malha_pe.graphml"


def baixar_malha(m: Municipio, limite: gpd.GeoDataFrame, forcar: bool = False):
    import osmnx as ox

    destino = caminho_bruto(m)
    if destino.exists() and not forcar:
        return ox.load_graphml(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(BRUTOS / "osm" / "cache_overpass")
    ox.settings.requests_timeout = 300
    area = limite.to_crs(m.crs).buffer(FOLGA_M).to_crs(CRS_GEO).union_all()
    erro = None
    # o servidor público principal vive lotado: tenta espelhos, com espera crescente
    for tentativa, url in enumerate(SERVIDORES * 2):
        ox.settings.overpass_url = url
        try:
            G = ox.graph_from_polygon(area, network_type="walk", simplify=True, retain_all=False)
            break
        except Exception as e:  # noqa: BLE001
            erro = e
            print(f"  {url} falhou ({str(e).splitlines()[0][:90]}); tentando outro")
            time.sleep(10 * (tentativa + 1))
    else:
        raise RuntimeError("Nenhum servidor Overpass respondeu") from erro
    ox.save_graphml(G, destino)
    return G


SERVIDORES = ["https://overpass-api.de/api", "https://overpass.private.coffee/api",
              "https://maps.mail.ru/osm/tools/overpass/api"]


def preparar_rede(m: Municipio, G) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Nós e arestas não direcionadas (a pé não há mão de direção).

    Comprimento = comprimento da geometria no CRS métrico (o mesmo usado para
    medir a posição de cada endereço ao longo da via). A geometria de cada
    aresta é orientada de u para v."""
    import numpy as np
    import shapely
    import osmnx as ox

    crs = m.crs
    nos, arestas = ox.graph_to_gdfs(G, nodes=True, edges=True)
    nos = nos.to_crs(crs)[["geometry"]].reset_index().rename(columns={"osmid": "osm_id"})
    idx = pd.Series(range(len(nos)), index=nos["osm_id"])
    a = arestas.reset_index()[["u", "v", "highway", "geometry"]].to_crs(crs)
    u = idx.loc[a["u"]].to_numpy()
    v = idx.loc[a["v"]].to_numpy()
    geo = a.geometry.to_numpy()
    via = a["highway"].astype(str).to_numpy()
    # u < v; inverte a geometria quando a aresta trocou de sentido
    troca = u > v
    u, v = np.where(troca, v, u), np.where(troca, u, v)
    geo = np.where(troca, shapely.reverse(geo), geo)
    # garante que a linha começa no nó u (OSMnx às vezes guarda o sentido oposto)
    xy = np.column_stack([nos.geometry.x, nos.geometry.y])
    ini = shapely.get_coordinates(shapely.get_point(geo, 0))
    fim = shapely.get_coordinates(shapely.get_point(geo, -1))
    errada = np.hypot(*(ini - xy[u]).T) > np.hypot(*(fim - xy[u]).T)
    geo = np.where(errada, shapely.reverse(geo), geo)
    a = gpd.GeoDataFrame({"u": u, "v": v, "via": via}, geometry=geo, crs=crs)
    a["comprimento_m"] = a.geometry.length
    # ida e volta, ou vias paralelas entre os mesmos nós: fica a mais curta
    a = a[a["u"] != a["v"]].sort_values("comprimento_m").drop_duplicates(["u", "v"]).reset_index(drop=True)
    nos["no"] = range(len(nos))
    return nos, a


def salvar_rede(m: Municipio, nos: gpd.GeoDataFrame, arestas: gpd.GeoDataFrame) -> None:
    m.processados.mkdir(parents=True, exist_ok=True)
    nos.to_parquet(m.processados / "rede_nos.parquet")
    arestas.to_parquet(m.processados / "rede_arestas.parquet")

