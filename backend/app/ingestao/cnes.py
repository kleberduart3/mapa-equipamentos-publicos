"""Unidades básicas de saúde e equipes – CNES/DATASUS."""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from ..config import BRUTOS, CRS_GEO, Municipio

# Tipos de unidade do CNES considerados atenção básica
TIPOS_UBS = {"1": "Posto de Saúde", "2": "Centro de Saúde/UBS"}
# Nomes que, mesmo com tipo 1/2, não são porta de entrada da atenção básica
EXCLUIR_NOME = r"ACOLHIMENTO|PRESIDIO|AMBULATORIO|SAUDE MENTAL"
# Tipos de equipe que contam como capacidade de atenção básica
EQUIPES_AB = {"70": "eSF", "76": "eAP"}


def ler_estabelecimentos(m: Municipio) -> pd.DataFrame:
    with zipfile.ZipFile(BRUTOS / "cnes" / "cnes_estabelecimentos_BR.zip") as zf:
        partes = [b[b["CO_IBGE"] == m.cod6] for b in
                  pd.read_csv(zf.open("cnes_estabelecimentos.csv"), sep=";", encoding="latin1",
                              dtype=str, chunksize=100_000)]
    return pd.concat(partes)


def ler_equipes(m: Municipio) -> pd.DataFrame:
    """Equipes ativas por estabelecimento, do arquivo EP mais recente (.dbc)."""
    import datasus_dbc
    from dbfread import DBF

    arqs = sorted(m.brutos_uf.glob(f"cnes_EP{m.uf}*.dbc"))
    if not arqs:
        raise FileNotFoundError(f"Sem arquivo de equipes do CNES em {m.brutos_uf} â€“ rode baixar_dados.py")
    arq = arqs[-1]
    with tempfile.TemporaryDirectory() as tmp:
        dbf = Path(tmp) / "ep.dbf"
        datasus_dbc.decompress(str(arq), str(dbf))
        df = pd.DataFrame(iter(DBF(dbf, encoding="latin1")))
    df = df[(df["CODUFMUN"] == m.cod6) & df["TIPO_EQP"].isin(EQUIPES_AB)]
    # DT_DESAT = "900001" (ou vazio) significa equipe NÃO desativada
    desat = df["DT_DESAT"].astype(str).str.strip()
    ativas = df[desat.isin(["", "None", "nan", "900001"])]
    cont = ativas.groupby("CNES").agg(
        equipes_ab=("CNES", "size"), TP_UNID=("TP_UNID", "first"), TPGESTAO=("TPGESTAO", "first"),
        COD_CEP=("COD_CEP", "first"), NOME_EQP=("NOME_EQP", "first")).reset_index()
    cont["competencia_equipes"] = arq.stem[-4:]
    return cont.rename(columns={"CNES": "CO_CNES"})


def _ubs_so_no_arquivo_de_equipes(eq: pd.DataFrame, ubs: pd.DataFrame, cnefe: gpd.GeoDataFrame | None) -> pd.DataFrame:
    """UBS que têm equipes ativas no arquivo EP mas não estão no cadastro aberto
    de estabelecimentos. Entram com localização aproximada pelo CEP (CNEFE)."""
    falt = eq[~eq["CO_CNES"].isin(ubs["CO_CNES"]) & eq["TP_UNID"].isin(["01", "02"]) & (eq["TPGESTAO"] == "M")]
    linhas = []
    cn = cnefe.to_crs(CRS_GEO) if cnefe is not None else None
    for r in falt.itertuples():
        lat = lon = None
        cep = str(r.COD_CEP)
        if cn is not None and not cep.endswith(("899", "970", "000")):
            no_cep = cn[cn["CEP"] == cep]
            if len(no_cep):
                lat, lon = no_cep.geometry.y.median(), no_cep.geometry.x.median()
        nome = "UBS " + str(r.NOME_EQP).replace("ESF", "").strip(" I") if r.NOME_EQP else f"UBS CNES {r.CO_CNES}"
        linhas.append({"CO_CNES": r.CO_CNES, "NO_FANTASIA": nome + " (só no arquivo de equipes)",
                       "TP_UNIDADE": str(int(r.TP_UNID)), "CO_CEP": cep, "ativa": True,
                       "NU_LATITUDE": None if lat is None else str(lat), "NU_LONGITUDE": None if lon is None else str(lon),
                       "_fonte": "cnefe_centroide_cep" if lat is not None else "sem_coordenada"})
    return pd.DataFrame(linhas)


def montar_ubs(m: Municipio, cnefe: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    est = ler_estabelecimentos(m)
    ubs = est[est["TP_UNIDADE"].isin(TIPOS_UBS) & (est["TP_GESTAO"] == "M")]
    ubs = ubs[~ubs["NO_FANTASIA"].str.contains(EXCLUIR_NOME, na=False)]
    ubs = ubs.assign(ativa=ubs["CO_MOTIVO_DESAB"].isna())
    ubs["CO_CNES"] = ubs["CO_CNES"].str.zfill(7)
    eq = ler_equipes(m)

    eq["CO_CNES"] = eq["CO_CNES"].astype(str).str.zfill(7)
    extra = _ubs_so_no_arquivo_de_equipes(eq, ubs, cnefe)
    ubs = pd.concat([ubs, extra], ignore_index=True)
    ubs = ubs.merge(eq[["CO_CNES", "equipes_ab", "competencia_equipes"]], on="CO_CNES", how="left")
    ubs["equipes_ab"] = ubs["equipes_ab"].fillna(0).astype(int)
    ubs["lat"] = pd.to_numeric(ubs["NU_LATITUDE"].astype(str).str.replace(",", "."), errors="coerce")
    ubs["lon"] = pd.to_numeric(ubs["NU_LONGITUDE"].astype(str).str.replace(",", "."), errors="coerce")
    ubs["fonte_coord"] = ubs["lat"].notna().map({True: "cnes", False: "sem_coordenada"})
    if "_fonte" in ubs:
        ubs["fonte_coord"] = ubs["_fonte"].fillna(ubs["fonte_coord"])
    ubs["tipo"] = ubs["TP_UNIDADE"].map(TIPOS_UBS)
    out = ubs.rename(columns={"CO_CNES": "cnes", "NO_FANTASIA": "nome", "NO_LOGRADOURO": "logradouro",
                              "NU_ENDERECO": "numero", "NO_BAIRRO": "bairro", "CO_CEP": "cep"})
    out = out[["cnes", "nome", "tipo", "ativa", "equipes_ab", "competencia_equipes", "logradouro",
               "numero", "bairro", "cep", "lat", "lon", "fonte_coord"]]
    g = gpd.GeoDataFrame(out, geometry=gpd.points_from_xy(out["lon"], out["lat"]), crs=CRS_GEO)
    return g.to_crs(m.crs)

