"""Setores censitários, população por faixa etária e endereços (CNEFE) – IBGE."""
from __future__ import annotations

import json
import re
import zipfile

import geopandas as gpd
import pandas as pd

from ..config import BRUTOS, CRS_GEO, Municipio

# Faixas de demanda usadas na análise (idades inclusivas)
FAIXAS_DEMANDA = {
    "pop_0_3": (0, 3),
    "pop_4_5": (4, 5),
    "pop_6_10": (6, 10),
    "pop_11_14": (11, 14),
    "pop_15_17": (15, 17),
}
# Faixas quinquenais publicadas por setor (Agregados – Demografia)
QUINQUENAIS = {"V01031": (0, 4), "V01032": (5, 9), "V01033": (10, 14), "V01034": (15, 19)}


def _so_digitos(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\D", "", regex=True)


def ler_setores(m: Municipio, crs: str | None = None) -> gpd.GeoDataFrame:
    """Malha de setores do município com população total (v0001) e domicílios.
    Sai no CRS métrico do município (ou em `crs`, se informado)."""
    g = gpd.read_file(m.brutos_uf / "setores.gpkg", where=f"CD_MUN='{m.cod}'")
    if not len(g):
        raise ValueError(f"{m}: nenhum setor com CD_MUN={m.cod} em {m.brutos_uf / 'setores.gpkg'}")
    g = g.set_crs(CRS_GEO, allow_override=True)
    g = g.rename(columns={"v0001": "pop_total", "v0002": "domicilios", "v0003": "domicilios_ocupados"})
    g["CD_SETOR"] = _so_digitos(g["CD_SETOR"])
    cols = ["CD_SETOR", "SITUACAO", "CD_SIT", "NM_DIST", "CD_BAIRRO", "NM_BAIRRO", "AREA_KM2",
            "pop_total", "domicilios", "domicilios_ocupados", "geometry"]
    g = g[cols].to_crs(crs or m.crs)
    g["pop_total"] = pd.to_numeric(g["pop_total"], errors="coerce").fillna(0).astype(int)
    return g


def idade_simples_municipio(m: Municipio) -> pd.Series:
    """População por idade simples (0–19) do município – SIDRA tabela 9514."""
    dados = json.loads((m.brutos / "sidra_9514.json").read_text(encoding="utf-8"))
    pop = {}
    for linha in dados[1:]:
        rotulo = linha["D5N"]
        if rotulo == "Menos de 1 ano":
            pop[0] = int(linha["V"])
            continue
        mm = re.fullmatch(r"(\d+) anos?", rotulo)
        if mm and int(mm.group(1)) <= 19:
            pop[int(mm.group(1))] = int(linha["V"])
    s = pd.Series(pop).sort_index()
    faltando = set(range(20)) - set(s.index)
    if faltando:
        raise ValueError(f"SIDRA sem idades {sorted(faltando)}")
    return s


def _pesos_faixas(idades: pd.Series) -> dict[str, dict[str, float]]:
    """Para cada faixa de demanda, a fração de cada faixa quinquenal que cai nela,
    segundo a distribuição por idade simples do município."""
    pesos: dict[str, dict[str, float]] = {}
    for faixa, (a, b) in FAIXAS_DEMANDA.items():
        pesos[faixa] = {}
        for var, (qa, qb) in QUINQUENAIS.items():
            ini, fim = max(a, qa), min(b, qb)
            if ini > fim:
                continue
            pesos[faixa][var] = idades.loc[ini:fim].sum() / idades.loc[qa:qb].sum()
    return pesos


def populacao_por_faixa(m: Municipio, setores: pd.Series) -> pd.DataFrame:
    """Lê as faixas quinquenais por setor e redistribui nas faixas de demanda."""
    alvo = set(setores)
    with zipfile.ZipFile(BRUTOS / "ibge" / "agregados_demografia_BR.zip") as zf:
        nome = zf.namelist()[0]
        partes = []
        for bloco in pd.read_csv(zf.open(nome), sep=";", dtype=str, chunksize=100_000,
                                 usecols=["CD_setor", "V01006", *QUINQUENAIS]):
            bloco["CD_setor"] = _so_digitos(bloco["CD_setor"])
            partes.append(bloco[bloco["CD_setor"].isin(alvo)])
    df = pd.concat(partes).rename(columns={"CD_setor": "CD_SETOR"})
    for c in ["V01006", *QUINQUENAIS]:
        # "X" = dado suprimido por sigilo (setores muito pequenos) → tratado como 0
        df[c] = pd.to_numeric(df[c].str.replace(",", "."), errors="coerce").fillna(0)
    pesos = _pesos_faixas(idade_simples_municipio(m))
    for faixa, ws in pesos.items():
        df[faixa] = sum(df[v] * w for v, w in ws.items())
    return df[["CD_SETOR", *FAIXAS_DEMANDA]]


def ler_cnefe(m: Municipio) -> gpd.GeoDataFrame:
    """Endereços do CNEFE 2022 com coordenadas, já com a espécie classificada."""
    with zipfile.ZipFile(m.brutos / "cnefe.zip") as zf:
        nome = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        df = pd.read_csv(zf.open(nome), sep=";", dtype=str)
    df = df[df["COD_MUNICIPIO"] == m.cod]
    df["COD_SETOR"] = _so_digitos(df["COD_SETOR"])
    df["lat"] = pd.to_numeric(df["LATITUDE"], errors="coerce")
    df["lon"] = pd.to_numeric(df["LONGITUDE"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"])
    g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=CRS_GEO)
    return g.to_crs(m.crs)



# Espécies do CNEFE (dicionário 2022)
ESPECIE = {"1": "domicilio_particular", "2": "domicilio_coletivo", "3": "agropecuario",
           "4": "ensino", "5": "saude", "6": "outras_finalidades", "7": "em_construcao",
           "8": "religioso"}
