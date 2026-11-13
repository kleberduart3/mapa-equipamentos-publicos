"""Escolas e creches – INEP (microdados do Censo Escolar + coordenadas).

Coordenadas, em ordem de preferência:
  1. Catálogo de Escolas do INEP exportado à mão (opcional, por município):
     dados/brutos/municipios/{código}/inep_catalogo.tsv (+ inep_enderecos.tsv);
  2. geocodificação do endereço dos microdados pelo CNEFE (ver geocodificar_por_cnefe).
"""
from __future__ import annotations

import re
import zipfile

import geopandas as gpd
import pandas as pd

from ..config import BRUTOS, CRS_GEO, Municipio

MAT = {
    "QT_MAT_INF_CRE": "mat_creche",
    "QT_MAT_INF_PRE": "mat_pre_escola",
    "QT_MAT_FUND_AI": "mat_fund_iniciais",
    "QT_MAT_FUND_AF": "mat_fund_finais",
    "QT_MAT_MED": "mat_medio",
}
DEPENDENCIA = {1: "Federal", 2: "Estadual", 3: "Municipal", 4: "Privada"}
LOCALIZACAO = {1: "Urbana", 2: "Rural"}
SITUACAO = {1: "FUNCIONANDO", 2: "PARALISADA", 3: "EXTINTA", 4: "EXTINTA NO ANO ANTERIOR"}
ENDERECO = ["DS_ENDERECO", "NU_ENDERECO", "NO_BAIRRO", "CO_CEP"]


def ler_microdados(m: Municipio, ano: int = 2024) -> pd.DataFrame:
    """Matrículas por etapa e endereço de cada escola do município."""
    cod = int(m.cod)
    with zipfile.ZipFile(BRUTOS / "inep" / f"microdados_censo_escolar_{ano}.zip") as zf:
        nome = next(n for n in zf.namelist() if n.endswith(f"microdados_ed_basica_{ano}.csv"))
        cols = ["CO_MUNICIPIO", "CO_ENTIDADE", "NO_ENTIDADE", "TP_DEPENDENCIA",
                "TP_LOCALIZACAO", "TP_SITUACAO_FUNCIONAMENTO", *ENDERECO, *MAT]
        partes = [b[b["CO_MUNICIPIO"] == cod] for b in
                  pd.read_csv(zf.open(nome), sep=";", encoding="latin1", usecols=cols, chunksize=50_000)]
    df = pd.concat(partes).rename(columns=MAT)
    df["codigo_inep"] = df["CO_ENTIDADE"].astype(str)
    df["dependencia"] = df["TP_DEPENDENCIA"].map(DEPENDENCIA)
    df["em_funcionamento"] = df["TP_SITUACAO_FUNCIONAMENTO"] == 1
    df["localizacao"] = df["TP_LOCALIZACAO"].map(LOCALIZACAO)
    df["situacao"] = df["TP_SITUACAO_FUNCIONAMENTO"].map(SITUACAO)
    df["endereco"] = [_endereco(*v) for v in df[ENDERECO].itertuples(index=False)]
    for c in MAT.values():
        df[c] = df[c].fillna(0).astype(int)
    df["ano_censo_escolar"] = ano
    return df[["codigo_inep", "NO_ENTIDADE", "dependencia", "localizacao", "situacao", "endereco",
               "em_funcionamento", *MAT.values(), "ano_censo_escolar"]]


def _endereco(logradouro, numero, bairro, cep) -> str | None:
    """Endereço no mesmo formato do Catálogo ("Rua X, 12 - Bairro - CEP 57300-000"),
    que é o que _cep_numero sabe ler."""
    if not isinstance(logradouro, str):
        return None
    cep = re.sub(r"\D", "", str(int(cep)) if isinstance(cep, float) and cep == cep else str(cep or ""))
    num = str(numero).strip() if isinstance(numero, str) and numero.strip() else "S/N"
    partes = [f"{logradouro.strip()}, {num}"]
    if isinstance(bairro, str) and bairro.strip():
        partes.append(bairro.strip())
    if len(cep) == 8:
        partes.append(f"CEP {cep[:5]}-{cep[5:]}")
    return " - ".join(partes)


def tem_catalogo(m: Municipio) -> bool:
    return (m.brutos / "inep_catalogo.tsv").exists()


def ler_catalogo(m: Municipio) -> pd.DataFrame:
    """Exportação manual do Catálogo de Escolas (escolas públicas) com coordenadas."""
    cat = pd.read_csv(m.brutos / "inep_catalogo.tsv", sep="\t", dtype=str)
    extra = m.brutos / "inep_enderecos.tsv"
    if extra.exists():
        cat = cat.merge(pd.read_csv(extra, sep="\t", dtype=str), on="codigo_inep", how="left")
    else:
        cat["endereco"] = None
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
              "FUND", "ESC", "ENS", "CEI", "EDUC", "COMUNITARIA", "SENHORA", "NOSSA", "SILVA", "SANTOS",
              "ESTADUAL", "INDIGENA", "COLEGIO", "GRAU", "BASICA", "EDUCACIONAL", "CRECHE", "UNIDADE",
              "INSTITUTO", "PROFESSORES", "MUNICIPIO"}


def _tokens(nome) -> set[str]:
    if not isinstance(nome, str):
        return set()
    return {t for t in re.findall(r"[A-ZÀ-Ú]+", nome.upper()) if len(t) >= 4 and t not in _GENERICAS}


# Para aceitar um estabelecimento de outro CEP, o nome precisa bater de verdade:
# ≥2 palavras em comum que somem esta fração do "peso" do nome da escola
# (palavras raras pesam mais que nomes comuns como JOSE ou MARIA).
SEMELHANCA_MIN_MUNICIPIO = 0.6
SEMELHANCA_MIN_CEP = 0.5



def _pesos_idf(conjuntos) -> dict[str, float]:
    import math
    n = max(len(conjuntos), 1)
    df: dict[str, int] = {}
    for c in conjuntos:
        for t in c:
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n + 1) / (k + 0.5)) for t, k in df.items()} | {"__novo__": math.log((n + 1) / 0.5)}


def _semelhanca(alvo: set[str], cand: set[str], idf: dict[str, float]) -> float:
    if not alvo:
        return 0.0
    novo = idf["__novo__"]
    total = sum(idf.get(t, novo) for t in alvo)
    return sum(idf.get(t, novo) for t in alvo & cand) / total


def geocodificar_por_cnefe(faltantes: pd.DataFrame, cnefe: gpd.GeoDataFrame) -> pd.DataFrame:
    """Completa coordenadas usando o CNEFE, em ordem de confiança:
    1) estabelecimento de ensino (espécie 4) do mesmo CEP cujo nome confere;
    2) estabelecimento de ensino em qualquer CEP do município com nome muito parecido
       (≥2 palavras em comum e semelhança ≥ SEMELHANCA_MIN_MUNICIPIO);
    3) mesmo CEP + mesmo número de porta (posição do endereço, nome não verificado);
    4) centroide dos endereços do CEP (aproximado).
    CEPs genéricos (…-899, …-970) sem nome conferido ficam sem coordenada.
    Os casos 3, 4 e sem coordenada vão para a lista de conferência."""
    cn = cnefe.to_crs(CRS_GEO)
    cn = cn.assign(lon=cn.geometry.x, lat=cn.geometry.y)
    ensino = cn[cn["COD_ESPECIE"] == "4"].copy()
    ensino["tok"] = ensino["DSC_ESTABELECIMENTO"].map(_tokens)
    idf = _pesos_idf(ensino["tok"])
    saida = []
    for _, r in faltantes.iterrows():
        cep, num = _cep_numero(r.get("endereco"))
        alvo = _tokens(r.get("escola"))
        lat = lon = None
        metodo, ref = "sem_coordenada", None
        comum = ensino["tok"].map(lambda t: len(t & alvo))
        cand = ensino[(ensino["CEP"] == cep) & (comum >= 1)] if cep else ensino.iloc[0:0]
        if len(cand):
            # no mesmo CEP basta menos, mas não uma palavra solta (ex.: só SAMPAIO):
            # o nome do CNEFE inteiro contido no da escola, ou metade do "peso" do nome
            sem = cand["tok"].map(lambda t: _semelhanca(alvo, t, idf))
            aceitos = sem[(sem >= SEMELHANCA_MIN_CEP) | cand["tok"].map(lambda t: bool(t) and t <= alvo)]
            cand = cand.loc[aceitos.index]
        if len(cand):
            metodo = "cnefe_nome_no_cep"
            melhor = cand.loc[sem[cand.index].idxmax()]
        else:
            sem = ensino.loc[comum >= 2, "tok"].map(lambda t: _semelhanca(alvo, t, idf))
            sem = sem[sem >= SEMELHANCA_MIN_MUNICIPIO]
            if len(sem):
                metodo = "cnefe_nome_municipio"
                cand = ensino.loc[sem.index]
                melhor = cand.loc[sem.idxmax()]
        if len(cand):

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


def _sem_catalogo(mic: pd.DataFrame) -> pd.DataFrame:
    """Escolas públicas dos microdados no formato do Catálogo, ainda sem coordenadas."""
    pub = mic[mic["dependencia"] != "Privada"]
    cat = pub.rename(columns={"NO_ENTIDADE": "escola"})[
        ["codigo_inep", "escola", "dependencia", "localizacao", "situacao", "endereco"]].copy()
    cat["latitude"] = float("nan")
    cat["longitude"] = float("nan")
    return cat


def montar_escolas(m: Municipio, cnefe: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    mic = ler_microdados(m)
    if tem_catalogo(m):
        cat = ler_catalogo(m)
        # endereço dos microdados para quem o Catálogo não trouxe
        end = mic.set_index("codigo_inep")["endereco"]
        cat["endereco"] = cat["endereco"].fillna(cat["codigo_inep"].map(end))
    else:
        cat = _sem_catalogo(mic)
    cat["fonte_coord"] = cat["latitude"].notna().map({True: "inep_catalogo", False: None})
    cat["cnefe_nome_conferido"] = None
    sem = cat[cat["latitude"].isna()]
    if len(sem):
        geo = geocodificar_por_cnefe(sem, cnefe).set_index("codigo_inep")
        cat = cat.set_index("codigo_inep")
        cat.update(geo)
        cat = cat.reset_index()
    esc = cat.merge(mic.drop(columns=["dependencia", "localizacao", "situacao", "endereco"]),
                    on="codigo_inep", how="left")
    esc["em_funcionamento"] = esc["em_funcionamento"].fillna(esc["situacao"] == "FUNCIONANDO")
    for c in MAT.values():
        esc[c] = esc[c].fillna(0).astype(int)
    esc["oferta_creche"] = esc["mat_creche"] > 0
    esc["oferta_pre_escola"] = esc["mat_pre_escola"] > 0
    esc["oferta_fund_iniciais"] = esc["mat_fund_iniciais"] > 0
    esc["oferta_fund_finais"] = esc["mat_fund_finais"] > 0
    esc["oferta_medio"] = esc["mat_medio"] > 0
    g = gpd.GeoDataFrame(esc, geometry=gpd.points_from_xy(esc["longitude"], esc["latitude"]), crs=CRS_GEO)
    return g.to_crs(m.crs)

