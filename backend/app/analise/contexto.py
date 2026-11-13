"""Dados de cada município carregados em memória (mapa e relatório).

base(cod) guarda poucos municípios ao mesmo tempo (cada um leva a malha de ruas
em memória); o menos usado sai quando chega um novo.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from ..config import CRS_GEO, Municipio, municipio
from . import cobertura as cob

MAX_MUNICIPIOS_EM_MEMORIA = 3


class MunicipioNaoProcessado(FileNotFoundError):
    pass


class Base:
    def __init__(self, m: Municipio) -> None:
        if not m.processado:
            raise MunicipioNaoProcessado(f"{m}: dados ainda não processados")
        self.m = m
        P = m.P
        self.P = P
        self.fr = float(P["fator_raio_rural"])
        d = m.processados
        self.setores = gpd.read_parquet(d / "setores.parquet")
        self.escolas = gpd.read_parquet(d / "escolas.parquet")
        self.ubs = gpd.read_parquet(d / "ubs.parquet")
        self.limite = gpd.read_parquet(d / "limite.parquet")
        end = gpd.read_parquet(d / "enderecos.parquet")
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
        self._trava = threading.Lock()

    @property
    def tem_rede(self) -> bool:
        return self.m.tem_rede

    def medidor(self, modo: str = "reta"):
        """'reta' (linha reta) ou 'rede' (a pé pela malha do OpenStreetMap)."""
        if modo not in ("reta", "rede"):
            raise ValueError(f"modo de distância desconhecido: {modo}")
        with self._trava:
            if modo not in self._medidores:
                if modo == "reta":
                    self._medidores[modo] = cob.LinhaReta(self.xy, self.tree)
                else:
                    from .rede import Rede
                    rede = Rede.carregar(self.m)
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


_bases: OrderedDict[str, Base] = OrderedDict()
_travas: dict[str, threading.Lock] = {}
_trava_geral = threading.Lock()


def base(cod: str) -> Base:
    """Dados do município `cod` (carrega na primeira vez; no máximo
    MAX_MUNICIPIOS_EM_MEMORIA ao mesmo tempo)."""
    with _trava_geral:
        if cod in _bases:
            _bases.move_to_end(cod)
            return _bases[cod]
        trava = _travas.setdefault(cod, threading.Lock())
    with trava:                                   # duas requisições não carregam o mesmo município 2×
        with _trava_geral:
            if cod in _bases:
                return _bases[cod]
        b = Base(municipio(cod))
        with _trava_geral:
            _bases[cod] = b
            while len(_bases) > MAX_MUNICIPIOS_EM_MEMORIA:
                _bases.popitem(last=False)
        return b


def esquecer(cod: str | None = None) -> None:
    """Descarta os dados em memória (depois de reprocessar um município)."""
    with _trava_geral:
        if cod is None:
            _bases.clear()
        else:
            _bases.pop(cod, None)

