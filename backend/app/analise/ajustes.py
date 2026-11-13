"""Ajustes da prefeitura no cadastro de equipamentos.

As escolas (INEP) e as UBS (CNES) vêm de bases nacionais. A prefeitura conhece
melhor as próprias unidades: a capacidade real (vagas, e não só matrículas), o
endereço certo, as que fecharam e as que abriram depois do último censo.

Os ajustes ficam num arquivo por município, fora das bases oficiais:

    dados/brutos/municipios/{código}/prefeitura/equipamentos_ajustes.json

    {"versao": 1, "proximo": 3, "unidades": {
        "inep:27012345": {"capacidade": {"creche": 120}, "alterado_por": "...", "alterado_em": "..."},
        "cnes:2001234":  {"equipes": 3, "excluida": true, ...},
        "pref:1":        {"nova": true, "fonte": "escola", "nome": "...", "lat": -9.7, "lon": -36.6,
                          "rede": "Municipal", "capacidade": {"creche": 80}, ...}}}

Chaves: inep:{código INEP}, cnes:{código CNES} ou pref:{n} (unidade incluída pela prefeitura).
Cada campo ausente vale o que está na base oficial; apagar o ajuste devolve o dado oficial.

aplicar() devolve cópias de escolas e UBS com os ajustes; o cálculo de cobertura
(cobertura.ofertas) usa a coluna cap_{tipo} quando ela tem valor.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from ..config import CRS_GEO, Municipio

NOME_ARQUIVO = "equipamentos_ajustes.json"
CHAVE = re.compile(r"^(inep|cnes|pref):[A-Za-z0-9]{1,20}$")
FONTE_COORD = "prefeitura"
_trava = threading.Lock()


def arquivo(m: Municipio) -> Path:
    return m.prefeitura / NOME_ARQUIVO


def vazio() -> dict:
    return {"versao": 1, "proximo": 1, "unidades": {}}


def ler(m: Municipio) -> dict:
    a = arquivo(m)
    if not a.exists():
        return vazio()
    d = json.loads(a.read_text(encoding="utf-8"))
    d.setdefault("unidades", {})
    d.setdefault("proximo", 1)
    return d


def salvar(m: Municipio, dados: dict) -> None:
    """Grava de forma atômica (arquivo temporário + rename): nunca deixa o JSON pela metade."""
    a = arquivo(m)
    a.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ajustes_", suffix=".json", dir=a.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=1)
        os.replace(tmp, a)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def alterar(m: Municipio, funcao) -> dict:
    """Lê, aplica funcao(dados) e grava, com trava (duas edições ao mesmo tempo não se perdem)."""
    with _trava:
        dados = ler(m)
        resultado = funcao(dados)
        salvar(m, dados)
        return resultado


def carimbo(autor: str) -> dict:
    return {"alterado_por": autor, "alterado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def id_da_chave(chave: str) -> str:
    """Identificador da unidade nas tabelas (código INEP/CNES ou PREF-n)."""
    prefixo, valor = chave.split(":", 1)
    return f"PREF-{valor}" if prefixo == "pref" else valor


def chave_da_unidade(fonte: str, ident: str) -> str:
    if str(ident).startswith("PREF-"):
        return f"pref:{str(ident)[5:]}"
    return f"{'cnes' if fonte == 'ubs' else 'inep'}:{ident}"


def _ponto(lat: float, lon: float, crs) -> object:
    return gpd.GeoSeries(gpd.points_from_xy([lon], [lat]), crs=CRS_GEO).to_crs(crs).iloc[0]


def _tem(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def aplicar(escolas: gpd.GeoDataFrame, ubs: gpd.GeoDataFrame, ajustes: dict,
            tipos: dict) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Cópias de escolas e UBS com os ajustes da prefeitura.

    tipos: P["equipamentos"] (para saber a coluna de oferta de cada etapa)."""
    esc = escolas.copy()
    ub = ubs.copy()
    tipos_escola = {t: c for t, c in tipos.items() if c.get("fonte_dados") != "cnes"}
    tipos_ubs = [t for t, c in tipos.items() if c.get("fonte_dados") == "cnes"]
    for t in tipos_escola:
        esc[f"cap_{t}"] = np.nan
    for t in tipos_ubs:
        ub[f"cap_{t}"] = np.nan
    esc["ajuste_prefeitura"] = False
    ub["ajuste_prefeitura"] = False

    unidades = ajustes.get("unidades", {})
    novas_esc, novas_ubs = [], []
    pos_esc = {c: i for i, c in enumerate(esc["codigo_inep"].astype(str))}
    pos_ubs = {c: i for i, c in enumerate(ub["cnes"].astype(str))}

    for chave, a in unidades.items():
        if not CHAVE.match(chave):
            continue
        prefixo, ident = chave.split(":", 1)
        if prefixo == "pref":
            (novas_ubs if a.get("fonte") == "ubs" else novas_esc).append((id_da_chave(chave), a))
            continue
        if prefixo == "inep" and ident in pos_esc:
            _ajustar(esc, pos_esc[ident], a, "escola", tipos_escola, esc.crs)
        elif prefixo == "cnes" and ident in pos_ubs:
            _ajustar(ub, pos_ubs[ident], a, "ubs", {t: tipos[t] for t in tipos_ubs}, ub.crs)

    if novas_esc:
        esc = _incluir(esc, [_nova_escola(i, a, tipos_escola) for i, a in novas_esc])
    if novas_ubs:
        ub = _incluir(ub, [_nova_ubs(i, a, tipos_ubs) for i, a in novas_ubs])
    return esc, ub


def _ajustar(df: gpd.GeoDataFrame, pos: int, a: dict, fonte: str, tipos: dict, crs) -> None:
    idx = df.index[pos]
    df.loc[idx, "ajuste_prefeitura"] = True
    if a.get("nome"):
        df.loc[idx, "escola" if fonte == "escola" else "nome"] = a["nome"]
    if a.get("endereco"):
        if fonte == "escola":
            df.loc[idx, "endereco"] = a["endereco"]
        else:
            df.loc[idx, ["logradouro", "numero", "bairro"]] = [a["endereco"], "", ""]
    if _tem(a.get("lat")) and _tem(a.get("lon")):
        df.loc[idx, "geometry"] = _ponto(a["lat"], a["lon"], crs)
        df.loc[idx, "fonte_coord"] = FONTE_COORD
    if fonte == "ubs" and _tem(a.get("equipes")):
        df.loc[idx, "equipes_ab"] = int(a["equipes"])
    for t, v in (a.get("capacidade") or {}).items():
        if t not in tipos or not _tem(v):
            continue
        df.loc[idx, f"cap_{t}"] = float(v)
        if fonte == "escola":
            df.loc[idx, tipos[t]["oferta"]] = float(v) > 0       # capacidade 0 = não oferece a etapa
    if a.get("excluida"):
        df.loc[idx, "em_funcionamento" if fonte == "escola" else "ativa"] = False


def _nova_escola(ident: str, a: dict, tipos: dict) -> dict:
    cap = a.get("capacidade") or {}
    r = {"codigo_inep": ident, "escola": a.get("nome") or ident, "dependencia": a.get("rede") or "Municipal",
         "localizacao": None, "situacao": "FUNCIONANDO", "endereco": a.get("endereco"),
         "em_funcionamento": not a.get("excluida"), "fonte_coord": FONTE_COORD if _tem(a.get("lat")) else "sem_coordenada",
         "latitude": a.get("lat"), "longitude": a.get("lon"), "oferta_medio": False, "mat_medio": 0,
         "ajuste_prefeitura": True}
    for t, c in tipos.items():
        v = cap.get(t)
        r[c["oferta"]] = _tem(v) and float(v) > 0
        r[f"cap_{t}"] = float(v) if _tem(v) else np.nan
        r[c["capacidade"]] = 0
    return r


def _nova_ubs(ident: str, a: dict, tipos: list[str]) -> dict:
    cap = a.get("capacidade") or {}
    r = {"cnes": ident, "nome": a.get("nome") or ident, "tipo": "UBS", "ativa": not a.get("excluida"),
         "equipes_ab": int(a.get("equipes") or 0), "competencia_equipes": None,
         "logradouro": a.get("endereco") or "", "numero": "", "bairro": "", "cep": None,
         "lat": a.get("lat"), "lon": a.get("lon"),
         "fonte_coord": FONTE_COORD if _tem(a.get("lat")) else "sem_coordenada", "ajuste_prefeitura": True}
    for t in tipos:
        v = cap.get(t)
        r[f"cap_{t}"] = float(v) if _tem(v) else np.nan
    return r


def _incluir(df: gpd.GeoDataFrame, linhas: list[dict]) -> gpd.GeoDataFrame:
    lat = "latitude" if "latitude" in linhas[0] else "lat"
    lon = "longitude" if lat == "latitude" else "lon"
    novas = pd.DataFrame(linhas)
    geo = gpd.GeoSeries(gpd.points_from_xy(novas[lon].astype(float), novas[lat].astype(float)), crs=CRS_GEO)
    novas = gpd.GeoDataFrame(novas, geometry=geo.to_crs(df.crs).values, crs=df.crs)
    novas = novas.reindex(columns=df.columns.union(novas.columns, sort=False))
    return gpd.GeoDataFrame(pd.concat([df, novas], ignore_index=True), geometry="geometry", crs=df.crs)
