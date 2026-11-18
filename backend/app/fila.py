"""Fila de espera da creche enviada pela prefeitura.

A planilha tem dados pessoais de crianças (LGPD, art. 14). Por isso:
- o arquivo é lido numa pasta temporária e apagado logo depois (quem chama faz isso);
- aqui só se guarda a CONTAGEM de crianças por hexágono e por bairro, sem nome, CPF, NIS,
  endereço ou data de nascimento;
- nenhuma rota devolve linha individual.

Localização, em ordem: colunas de latitude/longitude; CEP + número no CNEFE; centroide do CEP.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

from .analise.contexto import base
from .config import municipio

WGS84 = "EPSG:4326"
ARQUIVO = "fila_creche.json"


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _coluna(df: pd.DataFrame, nomes: tuple[str, ...]) -> str | None:
    norm = {_norm(c): c for c in df.columns}
    for n in nomes:
        if n in norm:
            return norm[n]
    for n in nomes:                                    # "cep_responsavel", "latitude_gps"…
        for k, c in norm.items():
            if k.startswith(n + "_") or k.endswith("_" + n):
                return c
    return None


def ler_planilha(caminho: Path) -> pd.DataFrame:
    if caminho.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(caminho, dtype=str)
    for enc in ("utf-8-sig", "latin1"):
        try:
            return pd.read_csv(caminho, sep=None, engine="python", dtype=str, encoding=enc, nrows=200_000)
        except UnicodeDecodeError:
            continue
    raise ValueError("codificação não reconhecida")


@lru_cache(maxsize=4)
def _cnefe_ceps(cod: str) -> tuple[dict, dict]:
    """(CEP → (lon, lat) mediano) e ((CEP, número) → (lon, lat)), a partir do CNEFE do município."""
    from .ingestao.ibge import ler_cnefe
    cn = ler_cnefe(municipio(cod)).to_crs(WGS84)
    df = pd.DataFrame({"cep": cn["CEP"].astype(str).str.replace(r"\D", "", regex=True),
                       "num": cn["NUM_ENDERECO"].astype(str).str.strip(),
                       "lon": cn.geometry.x, "lat": cn.geometry.y})
    por_cep = df.groupby("cep")[["lon", "lat"]].median()
    por_num = df.groupby(["cep", "num"])[["lon", "lat"]].mean()
    return ({k: (v.lon, v.lat) for k, v in por_cep.iterrows()},
            {k: (v.lon, v.lat) for k, v in por_num.iterrows()})


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def localizar(cod: str, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, dict]:
    """Coordenadas (lon, lat) de cada linha, NaN quando não deu para localizar, e o método usado."""
    n = len(df)
    lon, lat = np.full(n, np.nan), np.full(n, np.nan)
    metodo = {"coordenadas": 0, "cep_numero": 0, "cep": 0}
    c_lat = _coluna(df, ("latitude", "lat", "y"))
    c_lon = _coluna(df, ("longitude", "lon", "lng", "x"))
    c_cep = _coluna(df, ("cep",))
    c_num = _coluna(df, ("numero", "num", "n", "numero_residencia", "nro"))
    if c_lat and c_lon:
        la, lo = df[c_lat].map(_num).to_numpy(float), df[c_lon].map(_num).to_numpy(float)
        ok = np.isfinite(la) & np.isfinite(lo) & (np.abs(la) <= 90) & (np.abs(lo) <= 180) & (la != 0)
        lat[ok], lon[ok] = la[ok], lo[ok]
        metodo["coordenadas"] = int(ok.sum())
    if c_cep:
        por_cep, por_num = _cnefe_ceps(cod)
        ceps = df[c_cep].astype(str).str.replace(r"\D", "", regex=True).str.zfill(8)
        nums = df[c_num].astype(str).str.extract(r"(\d+)")[0] if c_num else pd.Series([None] * n)
        for i in np.flatnonzero(~np.isfinite(lat)):
            ponto = por_num.get((ceps.iat[i], nums.iat[i])) if nums.iat[i] else None
            if ponto:
                metodo["cep_numero"] += 1
            else:
                ponto = por_cep.get(ceps.iat[i])
                if ponto:
                    metodo["cep"] += 1
            if ponto:
                lon[i], lat[i] = ponto
    return lon, lat, metodo


def agregar(cod: str, df: pd.DataFrame) -> dict:
    """Conta a fila por hexágono e por bairro. Devolve só agregados (sem nenhum dado pessoal)."""
    b = base(cod)
    if not len(df):
        raise ValueError("planilha vazia")
    lon, lat, metodo = localizar(cod, df)
    achou = np.isfinite(lon)
    pts = gpd.GeoSeries(gpd.points_from_xy(lon[achou], lat[achou]), crs=WGS84).to_crs(b.pts.crs)
    dentro = pts.within(b.limite.geometry.iloc[0].buffer(500)).to_numpy()
    pts = pts[dentro].reset_index(drop=True)
    res = int(b.P["prioridade"]["resolucao_h3"])
    ll = pts.to_crs(WGS84)
    hexes = pd.Series([h3.latlng_to_cell(p.y, p.x, res) for p in ll]).value_counts()
    bairro = b.situacao(pts)["NM_BAIRRO"].fillna("Sem bairro definido") if len(pts) else pd.Series(dtype=str)
    por_bairro = bairro.value_counts()
    return {
        "enviado_em": datetime.now().astimezone().strftime("%d/%m/%Y %H:%M"),
        "total": int(len(df)), "localizados": int(len(pts)),
        "sem_local": int((~achou).sum()), "fora_do_municipio": int((~dentro).sum()),
        "metodo": metodo,
        "por_hex": {h: int(v) for h, v in hexes.items()},
        "por_bairro": {str(k): int(v) for k, v in por_bairro.items()},
    }


def salvar(cod: str, resumo: dict) -> Path:
    destino = municipio(cod).prefeitura / ARQUIVO
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(resumo, ensure_ascii=False), encoding="utf-8")
    return destino


def carregar(cod: str) -> dict | None:
    arq = municipio(cod).prefeitura / ARQUIVO
    if not arq.exists():
        return None
    d = json.loads(arq.read_text(encoding="utf-8"))
    feats = [{"type": "Feature", "properties": {"h3": h, "fila": n},
              "geometry": {"type": "Polygon", "coordinates": [[[lng, lat] for lat, lng in h3.cell_to_boundary(h)]
                                                              + [list(reversed(h3.cell_to_boundary(h)[0]))]]}}
             for h, n in d["por_hex"].items()]
    bairros = sorted(({"bairro": k, "criancas": v} for k, v in d["por_bairro"].items()), key=lambda x: -x["criancas"])
    return {"existe": True} | {k: d[k] for k in ("enviado_em", "total", "localizados", "sem_local", "fora_do_municipio", "metodo")} | {
        "bairros": bairros, "hex": {"type": "FeatureCollection", "features": feats}}
