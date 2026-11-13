"""Dados do município carregados uma vez por processo (mapa e relatório)."""
from __future__ import annotations

from functools import lru_cache

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from ..config import CRS_GEO, PROCESSADOS, parametros
from . import cobertura as cob


class Base:
    def __init__(self) -> None:
        P = parametros()
        self.P = P
        self.fr = float(P["fator_raio_rural"])
        self.setores = gpd.read_parquet(PROCESSADOS / "setores.parquet")
        self.escolas = gpd.read_parquet(PROCESSADOS / "escolas.parquet")
        self.ubs = gpd.read_parquet(PROCESSADOS / "ubs.parquet")
        self.limite = gpd.read_parquet(PROCESSADOS / "limite.parquet")
        end = gpd.read_parquet(PROCESSADOS / "enderecos.parquet")
        self.pts = cob.pontos_demanda(self.setores, end)
        self.xy = np.column_stack([self.pts.geometry.x, self.pts.geometry.y])
        self.tree = cKDTree(self.xy)
        res = int(P["prioridade"]["resolucao_h3"])
        ll = self.pts.to_crs(CRS_GEO)
        self.pts["h3"] = [h3.latlng_to_cell(y, x, res) for x, y in zip(ll.geometry.x, ll.geometry.y)]
        self.hex_ids = np.array(sorted(self.pts["h3"].unique()))
        cent = [h3.cell_to_latlng(c) for c in self.hex_ids]
        cand = gpd.GeoSeries(gpd.points_from_xy([c[1] for c in cent], [c[0] for c in cent]), crs=CRS_GEO)
        cand = cand.to_crs(self.pts.crs)
        self.cand_xy = np.column_stack([cand.x, cand.y])
        self.hex_poly = {c: [[lng, lat] for lat, lng in h3.cell_to_boundary(c)] for c in self.hex_ids}
        self.bairros = self.setores[["NM_BAIRRO", "NM_DIST", "SITUACAO", "geometry"]]

        self._medidores: dict = {}

    @property
    def tem_rede(self) -> bool:
        return (PROCESSADOS / "rede_arestas.parquet").exists()

    def medidor(self, modo: str = "reta"):
        """'reta' (linha reta) ou 'rede' (a pé pela malha do OpenStreetMap)."""
        if modo not in ("reta", "rede"):
            raise ValueError(f"modo de distância desconhecido: {modo}")
        if modo not in self._medidores:
            if modo == "reta":
                self._medidores[modo] = cob.LinhaReta(self.xy, self.tree)
            else:
                from .rede import Rede
                rede = Rede.carregar()
                if rede is None:
                    raise FileNotFoundError("Malha viária não preparada: rode backend/scripts/preparar_rede.py")
                self.rede = rede
                self._medidores[modo] = cob.APe(rede, self.xy, self.tree)
        return self._medidores[modo]

    def situacao(self, g: gpd.GeoSeries) -> pd.DataFrame:
        """Bairro, distrito e situação (urbana/rural) do setor que contém cada ponto."""
        j = gpd.sjoin(gpd.GeoDataFrame(geometry=g, crs=self.pts.crs), self.bairros, how="left", predicate="within")
        return j.groupby(level=0).first()

    def hex_gdf(self, ids) -> gpd.GeoDataFrame:
        from shapely.geometry import Polygon
        return gpd.GeoDataFrame({"h3": list(ids)}, geometry=[Polygon(self.hex_poly[h]) for h in ids],
                                crs=CRS_GEO).to_crs(self.pts.crs)


@lru_cache
def base() -> Base:
    return Base()
