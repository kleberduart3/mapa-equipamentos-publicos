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
from . import ajustes
from . import cobertura as cob

MAX_MUNICIPIOS_EM_MEMORIA = 3


class MunicipioNaoProcessado(FileNotFoundError):
    pass


def rotulo_bairro(setores: gpd.GeoDataFrame) -> pd.Series:
    """Nome usado no ranking para cada setor (índice: CD_SETOR).
    Com bairro no IBGE: o bairro. Urbano sem bairro: o bairro do setor nomeado mais
    próximo. Rural: "Zona rural" (com o distrito, se o município tiver mais de um)."""
    nome = setores["NM_BAIRRO"].where(setores["NM_BAIRRO"].astype(str).str.strip().ne("")
                                      & setores["NM_BAIRRO"].notna())
    rural = setores["SITUACAO"] != "Urbana"
    varios_distritos = setores["NM_DIST"].nunique() > 1
    zona = np.where(varios_distritos, "Zona rural – " + setores["NM_DIST"].astype(str), "Zona rural")
    out = pd.Series(np.where(rural & nome.isna(), zona, nome), index=setores.index, dtype=object)
    falta = out.isna()
    com_nome = setores[nome.notna()]
    if falta.any() and len(com_nome):
        perto = gpd.sjoin_nearest(setores.loc[falta, ["geometry"]], com_nome[["NM_BAIRRO", "geometry"]], how="left")
        perto = perto[~perto.index.duplicated()]
        out.loc[falta] = perto["NM_BAIRRO"].reindex(out.index[falta]).to_numpy()
    out = out.fillna("Sem bairro")
    out.index = setores["CD_SETOR"].to_numpy()
    return out


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
        # bases oficiais (INEP/CNES) e, por cima, os ajustes da prefeitura (analise/ajustes.py)
        self.escolas_oficial = gpd.read_parquet(d / "escolas.parquet")
        self.ubs_oficial = gpd.read_parquet(d / "ubs.parquet")
        self.ajustes = ajustes.ler(m)
        self.escolas, self.ubs = ajustes.aplicar(self.escolas_oficial, self.ubs_oficial, self.ajustes,
                                                 P["equipamentos"])
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
        # bairro de cada ponto, para o ranking (setor sem nome de bairro: ver rotulo_bairro)
        self.setor_bairro = rotulo_bairro(self.setores)
        self.pts["bairro"] = self.pts["CD_SETOR"].map(self.setor_bairro).fillna("Sem bairro").to_numpy()
        self.lon, self.lat = ll.geometry.x.to_numpy(), ll.geometry.y.to_numpy()

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

