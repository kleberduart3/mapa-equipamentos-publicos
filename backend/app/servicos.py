"""Respostas do mapa (GeoJSON/dicts), por município.

Funções puras sobre os dados de base(cod), usadas pela API e pelos exportadores.
Nada aqui verifica permissão: quem chama (a API) já conferiu o acesso ao município.
Os caches levam o código do município na chave.
"""
from __future__ import annotations

import json
from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import mapping

from .analise import cobertura as cob
from .analise.contexto import base
from .config import municipio
from .estilo import ESTILO, UNIDADE

WGS84 = "EPSG:4326"
MODOS = ("reta", "rede")


class TipoDesconhecido(LookupError):
    pass


def _num(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def tipos(cod: str) -> dict:
    return municipio(cod).P["equipamentos"]


def checa_tipo(cod: str, tipo: str) -> None:
    if tipo not in tipos(cod):
        raise TipoDesconhecido(tipo)


def config(cod: str) -> dict:
    b = base(cod)
    P = b.P
    lim = b.limite.to_crs(WGS84).total_bounds
    ts = {}
    for t, c in P["equipamentos"].items():
        ts[t] = {"rotulo": c["rotulo"], "raio_m": c["raio_m"], **ESTILO.get(t, {"cor": "#555", "icone": "ponto"}),
                 "unidade": UNIDADE.get(t, "pessoas"), "redes": c.get("redes", ["Municipal"])}
    return {"municipio": b.m.info(), "fator_raio_rural": b.fr, "tipos": ts,
            "bbox": [float(v) for v in lim], "tem_rede": b.tem_rede,
            "distancia_padrao": P.get("distancia_padrao", "reta") if b.tem_rede else "reta"}


def limite(cod: str) -> dict:
    g = base(cod).limite.to_crs(WGS84)
    return _fc([{"type": "Feature", "properties": {}, "geometry": mapping(g.geometry.iloc[0])}])


@lru_cache(maxsize=16)
def equipamentos(cod: str) -> dict:
    """Um registro por equipamento e tipo atendido (uma escola pode ter vários)."""
    b = base(cod)
    feats = []
    for t, cfg in b.P["equipamentos"].items():
        fac, _ = cob.ofertas(t, cfg, b.escolas, b.ubs)
        if not len(fac):
            continue
        sit = b.situacao(fac.geometry)
        ll = fac.to_crs(WGS84)
        src = b.ubs.set_index("cnes") if cfg["fonte_dados"] == "cnes" else b.escolas.set_index("codigo_inep")
        for i, r in enumerate(fac.itertuples()):
            s = src.loc[r.id]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[0]
            rural = sit["SITUACAO"].iloc[i] != "Urbana"
            props = {
                "id": r.id, "tipo": t, "nome": r.nome, "rede": r.rede, "capacidade": _num(r.capacidade),
                "fonte_coord": r.fonte_coord, "bairro": _num(sit["NM_BAIRRO"].iloc[i]), "rural": bool(rural),
                "raio_m": cfg["raio_m"] * (b.fr if rural else 1),
            }
            if cfg["fonte_dados"] == "cnes":
                props.update({"equipes": _num(s["equipes_ab"]), "endereco": f"{s['logradouro']}, {s['numero']} – {s['bairro']}"})
            else:
                props.update({k: _num(s[k]) for k in ["mat_creche", "mat_pre_escola", "mat_fund_iniciais", "mat_fund_finais"]})
            feats.append({"type": "Feature", "properties": props,
                          "geometry": {"type": "Point", "coordinates": [ll.geometry.iloc[i].x, ll.geometry.iloc[i].y]}})
    # Contexto: ensino médio das redes estadual/federal (fora dos indicadores municipais)
    e = b.escolas
    ctx = e[e["em_funcionamento"].astype(bool) & e["oferta_medio"].astype(bool)
            & e["dependencia"].isin(["Estadual", "Federal"]) & e["latitude"].notna()].to_crs(WGS84)
    for r in ctx.itertuples():
        feats.append({"type": "Feature", "properties": {
            "id": r.codigo_inep, "tipo": "contexto_medio", "nome": r.escola, "rede": r.dependencia,
            "fonte_coord": r.fonte_coord, "bairro": None, "rural": False, "mat_medio": _num(r.mat_medio)},
            "geometry": {"type": "Point", "coordinates": [r.geometry.x, r.geometry.y]}})
    return _fc(feats)


@lru_cache(maxsize=256)
def cobertura(cod: str, t: str, raio: int, modo: str = "reta") -> dict:
    checa_tipo(cod, t)
    b = base(cod)
    P = b.P
    md = b.medidor(modo)
    cfg = {**P["equipamentos"][t], "raio_m": raio}
    fac, sem = cob.ofertas(t, cfg, b.escolas, b.ubs)
    r = cob.calcular(t, cfg, b.pts, fac, sem, b.fr, tree=b.tree, medidor=md)

    # déficit por hexágono
    df = pd.DataFrame({"h3": b.pts["h3"], "sem_cob": r.sem_cobertura, "def_cap": r.deficit_cap,
                       "pop_desc": np.where(r.coberto, 0, r.pop_faixa)})
    g = df.groupby("h3").sum()
    g["deficit"] = g["sem_cob"] + g["def_cap"]
    g = g[g["deficit"] > 0.5]
    hexes = [{"type": "Feature",
              "properties": {"h3": h, "deficit": round(float(v["deficit"]), 1),
                             "sem_cobertura": round(float(v["sem_cob"]), 1),
                             "deficit_capacidade": round(float(v["def_cap"]), 1),
                             "pop_descoberta": round(float(v["pop_desc"]), 1)},
              "geometry": {"type": "Polygon", "coordinates": [b.hex_poly[h] + [b.hex_poly[h][0]]]}}
             for h, v in g.iterrows()]

    # sugestões (radar pulsante)
    rp = cob.raios(b.pts, raio, b.fr)
    sug = cob.sugerir_locais(t, r, b.pts, b.cand_xy, b.hex_ids, rp, int(P["prioridade"]["sugestoes_por_tipo"]),
                             float(P["prioridade"]["ganho_minimo"][t]), b.tree, medidor=md)
    radar = []
    if len(sug):
        pts = gpd.GeoSeries(gpd.points_from_xy(sug["x"], sug["y"]), crs=b.pts.crs)
        sit = b.situacao(pts)
        ll = pts.to_crs(WGS84)
        for i, s in sug.iterrows():
            radar.append({"type": "Feature", "properties": {
                "tipo": t, "ordem": int(s["ordem"]), "bairro": _num(sit["NM_BAIRRO"].iloc[i]),
                "demanda_absorvida": round(float(s["demanda_absorvida"])),
                "sem_cobertura": round(float(s["demanda_sem_cobertura_absorvida"]))},
                "geometry": {"type": "Point", "coordinates": [ll.iloc[i].x, ll.iloc[i].y]}})

    rural = b.pts["rural"].to_numpy()
    ind = {
        "tipo": t, "raio_m": raio, "modo": modo, "pop_faixa": round(float(r.pop_faixa.sum())),
        "pct_coberta": round(cob.pct_coberto(r), 1),
        "pct_coberta_rural": round(float(100 * r.pop_faixa[r.coberto & rural].sum() / max(r.pop_faixa[rural].sum(), 1)), 1),
        "pop_descoberta": round(float(r.pop_faixa[~r.coberto].sum())),
        "demanda_meta": round(float(r.demanda.sum())),
        "demanda_sem_cobertura": round(float(r.sem_cobertura.sum())),
        "deficit_capacidade": round(float(r.deficit_cap.sum())),
        "equipamentos": int(len(fac)),
    }
    return {"indicadores": ind, "hex": _fc(hexes), "radar": _fc(radar)}


@lru_cache(maxsize=96)
def areas(cod: str, t: str, raio: int) -> dict:
    """Área alcançável a pé de cada equipamento (vias dentro do raio + faixa de 40 m)."""
    checa_tipo(cod, t)
    b = base(cod)
    rede = b.medidor("rede").rede
    cfg = {**b.P["equipamentos"][t], "raio_m": raio}
    fac, _ = cob.ofertas(t, cfg, b.escolas, b.ubs)
    if not len(fac):
        return _fc([])
    rural = (b.situacao(fac.geometry)["SITUACAO"] != "Urbana").to_numpy()
    r = np.where(rural, raio * b.fr, raio).astype(float)
    xy = np.column_stack([fac.geometry.x, fac.geometry.y])
    g = gpd.GeoSeries(rede.areas_servico(xy, r), crs=b.pts.crs).to_crs(WGS84).simplify(0.00005)
    return _fc([{"type": "Feature", "properties": {"id": fac["id"].iloc[i], "tipo": t, "raio_m": float(r[i])},
                 "geometry": mapping(g.iloc[i])} for i in range(len(fac))])


def indicadores(cod: str) -> dict:
    return json.loads((municipio(cod).saidas / "indicadores.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _prioridade_rede(cod: str) -> gpd.GeoDataFrame:
    from .relatorio.gerar import analisar
    return analisar(base(cod), None, "rede")["hex"]


@lru_cache(maxsize=16)
def prioridade(cod: str, modo: str = "reta") -> dict:
    """Índice de prioridade com os raios padrão do município."""
    if modo == "rede":
        base(cod).medidor("rede")
        h = _prioridade_rede(cod)
    else:
        h = gpd.read_parquet(municipio(cod).saidas / "cobertura_hex.parquet")
    h = h.to_crs(WGS84)
    h = h[h["prioridade_geral"] > 1][["h3", "prioridade_geral", "geometry"]]
    h["prioridade_geral"] = h["prioridade_geral"].round(1)
    return json.loads(h.to_json())


def esquecer(cod: str | None = None) -> None:
    """Limpa os caches (depois de reprocessar dados ou mudar parâmetros)."""
    from .analise import contexto
    for f in (equipamentos, cobertura, areas, _prioridade_rede, prioridade):
        f.cache_clear()          # lru_cache não remove por chave; limpar tudo é barato
    contexto.esquecer(cod)


def aquecer(cod: str) -> None:
    """Pré-calcula o que o mapa abre por padrão (para a primeira troca de modo ser rápida)."""
    b = base(cod)
    if b.tem_rede:
        for t, c in b.P["equipamentos"].items():
            cobertura(cod, t, int(c["raio_m"]), "rede")
        prioridade(cod, "rede")
