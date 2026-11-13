"""Escolas e creches – INEP (Catálogo de Escolas + microdados do Censo Escolar)."""
from __future__ import annotations

import re
import zipfile

import geopandas as gpd
import pandas as pd

from ..config import BRUTOS, CRS_GEO, crs_metrico, municipio

MAT = {
    "QT_MAT_INF_CRE": "mat_creche",
    "QT_MAT_INF_PRE": "mat_pre_escola",
    "QT_MAT_FUND_AI": "mat_fund_iniciais",
    "QT_MAT_FUND_AF": "mat_fund_finais",
    "QT_MAT_MED": "mat_medio",
}
DEPENDENCIA = {1: "Federal", 2: "Estadual", 3: "Municipal", 4: "Privada"}


def ler_microdados(ano: int = 2024) -> pd.DataFrame:
    """Matrículas por etapa de cada escola do município."""
    cod = int(municipio()["codigo_ibge"])
    with zipfile.ZipFile(BRUTOS / "inep" / f"microdados_censo_escolar_{ano}.zip") as zf:
        nome = next(n for n in zf.namelist() if n.endswith(f"microdados_ed_basica_{ano}.csv"))
        cols = ["CO_MUNICIPIO", "CO_ENTIDADE", "NO_ENTIDADE", "TP_DEPENDENCIA",
                "TP_LOCALIZACAO", "TP_SITUACAO_FUNCIONAMENTO", *MAT]
        partes = [b[b["CO_MUNICIPIO"] == cod] for b in
                  pd.read_csv(zf.open(nome), sep=";", encoding="latin1", usecols=cols, chunksize=50_000)]
    df = pd.concat(partes).rename(columns=MAT)
    df["codigo_inep"] = df["CO_ENTIDADE"].astype(str)
    df["dependencia"] = df["TP_DEPENDENCIA"].map(DEPENDENCIA)
    df["em_funcionamento"] = df["TP_SITUACAO_FUNCIONAMENTO"] == 1
    for c in MAT.values():
        df[c] = df[c].fillna(0).astype(int)
    df["ano_censo_escolar"] = ano
    return df[["codigo_inep", "NO_ENTIDADE", "dependencia", "em_funcionamento",
               *MAT.values(), "ano_censo_escolar"]]


def ler_catalogo() -> pd.DataFrame:
    """Exportação do Catálogo de Escolas (escolas públicas) com coordenadas."""
    cat = pd.read_csv(BRUTOS / "inep" / "catalogo_escolas_arapiraca_publicas.tsv", sep="\t", dtype=str)
    end = pd.read_csv(BRUTOS / "inep" / "escolas_sem_coordenadas_enderecos.tsv", sep="\t", dtype=str)
    cat = cat.merge(end, on="codigo_inep", how="left")
    cat["latitude"] = pd.to_numeric(cat["latitude"], errors="coerce")
    cat["longitude"] = pd.to_numeric(cat["longitude"], errors="coerce")
    return cat


def _cep_numero(endereco: str) -> tuple[str | None, str | None]:
    if not isinstance(endereco, str):
        return None, None
    cep = re.search(r"(\d{5})-(\d{3})", endereco)
    num = re.search(r",\s*(\d+)\b", endereco)
    return (cep.group(1) + cep.group(2) if cep else None, num.group(1) if num else None)


_GENERICAS = {"ESCOLA", "ENSINO", "FUNDAMENTAL", "CENTRO", "EDUCACAO", "INFANTIL", "PROFESSORA",
              "PROFESSOR", "PROF", "PROFª", "TEMPO", "INTEGRAL", "MUNICIPAL", "CRECHE", "DOS", "DAS",
              "FUND", "ESC", "ENS", "CEI", "EDUC", "COMUNITARIA", "SENHORA", "NOSSA", "SILVA", "SANTOS"}


def _tokens(nome) -> set[str]:
    if not isinstance(nome, str):
        return set()
    return {t for t in re.findall(r"[A-ZÀ-Ú]+", nome.upper()) if len(t) >= 4 and t not in _GENERICAS}


def geocodificar_por_cnefe(faltantes: pd.DataFrame, cnefe: gpd.GeoDataFrame) -> pd.DataFrame:
    """Completa coordenadas usando o CNEFE, em ordem de confiança:
    1) estabelecimento de ensino (espécie 4) do mesmo CEP cujo nome confere;
    2) estabelecimento de ensino em qualquer CEP do município com ≥2 palavras do nome;
    3) mesmo CEP + mesmo número de porta (posição do endereço, nome não verificado);
    4) centroide dos endereços do CEP (aproximado).
    CEPs genéricos (…-899, …-970) sem nome conferido ficam sem coordenada.
    Os casos 3, 4 e sem coordenada vão para a lista de conferência."""
    cn = cnefe.to_crs(CRS_GEO)
    cn = cn.assign(lon=cn.geometry.x, lat=cn.geometry.y)
    ensino = cn[cn["COD_ESPECIE"] == "4"].copy()
    ensino["tok"] = ensino["DSC_ESTABELECIMENTO"].map(_tokens)
    saida = []
    for _, r in faltantes.iterrows():
        cep, num = _cep_numero(r.get("endereco"))
        alvo = _tokens(r.get("escola"))
        lat = lon = None
        metodo, ref = "sem_coordenada", None
        comum = ensino["tok"].map(lambda t: len(t & alvo))
        cand = ensino[(ensino["CEP"] == cep) & (comum >= 1)] if cep else ensino.iloc[0:0]
        if not len(cand):
            cand = ensino[comum >= 2]
            if len(cand):
                metodo = "cnefe_nome_municipio"
        else:
            metodo = "cnefe_nome_no_cep"
        if len(cand):
            melhor = cand.loc[comum[cand.index].idxmax()]
            lat, lon, ref = melhor["lat"], melhor["lon"], melhor["DSC_ESTABELECIMENTO"]
        elif cep and not cep.endswith(("899", "970", "000")):
            no_cep = cn[cn["CEP"] == cep]
            exato = no_cep[no_cep["NUM_ENDERECO"] == num] if num is not None else no_cep.iloc[0:0]
            if len(exato):
                lat, lon, metodo = exato["lat"].mean(), exato["lon"].mean(), "cnefe_cep_numero"
            elif len(no_cep):
                lat, lon, metodo = no_cep["lat"].median(), no_cep["lon"].median(), "cnefe_centroide_cep"
        saida.append({"codigo_inep": r["codigo_inep"], "latitude": lat, "longitude": lon,
                      "fonte_coord": metodo, "cnefe_nome_conferido": ref})
    return pd.DataFrame(saida)


def montar_escolas(cnefe: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    cat = ler_catalogo()
    cat["fonte_coord"] = cat["latitude"].notna().map({True: "inep_catalogo", False: None})
    cat["cnefe_nome_conferido"] = None
    sem = cat[cat["latitude"].isna()]
    if len(sem):
        geo = geocodificar_por_cnefe(sem, cnefe).set_index("codigo_inep")
        cat = cat.set_index("codigo_inep")
        cat.update(geo)
        cat = cat.reset_index()
    mic = ler_microdados()
    esc = cat.merge(mic.drop(columns=["dependencia"]), on="codigo_inep", how="left")
    esc["em_funcionamento"] = esc["em_funcionamento"].fillna(esc["situacao"] == "FUNCIONANDO")
    for c in MAT.values():
        esc[c] = esc[c].fillna(0).astype(int)
    esc["oferta_creche"] = esc["mat_creche"] > 0
    esc["oferta_pre_escola"] = esc["mat_pre_escola"] > 0
    esc["oferta_fund_iniciais"] = esc["mat_fund_iniciais"] > 0
    esc["oferta_fund_finais"] = esc["mat_fund_finais"] > 0
    esc["oferta_medio"] = esc["mat_medio"] > 0
    g = gpd.GeoDataFrame(esc, geometry=gpd.points_from_xy(esc["longitude"], esc["latitude"]), crs=CRS_GEO)
    return g.to_crs(crs_metrico())
