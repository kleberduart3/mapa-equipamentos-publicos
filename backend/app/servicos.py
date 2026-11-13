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
            "velocidade_caminhada_m_min": velocidade(cod),
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


def velocidade(cod: str) -> float:
    """Velocidade de caminhada (m/min) usada para converter distância em tempo."""
    return float(municipio(cod).P.get("velocidade_caminhada_m_min", 80))


@lru_cache(maxsize=128)
def _resultado(cod: str, t: str, raio: int, modo: str):
    """Cobertura de um tipo com um raio e um modo (base de cobertura, ranking, setores e simulador)."""
    checa_tipo(cod, t)
    b = base(cod)
    cfg = {**b.P["equipamentos"][t], "raio_m": raio}
    fac, sem = cob.ofertas(t, cfg, b.escolas, b.ubs)
    return cob.calcular(t, cfg, b.pts, fac, sem, b.fr, tree=b.tree, medidor=b.medidor(modo)), fac


@lru_cache(maxsize=32)
def _dist_proxima(cod: str, t: str, modo: str) -> np.ndarray:
    """Distância (m) de cada moradia até o equipamento do tipo mais próximo, em linha
    reta ou a pé. Não depende do raio. Sem equipamento ou sem caminho: inf."""
    from scipy.spatial import cKDTree

    b = base(cod)
    fac, _ = cob.ofertas(t, b.P["equipamentos"][t], b.escolas, b.ubs)
    if not len(fac):
        return np.full(len(b.pts), np.inf)
    xy_f = np.column_stack([fac.geometry.x, fac.geometry.y])
    if modo == "rede":
        md = b.medidor("rede")
        return md.rede.distancia_mais_proxima(md.lig, xy_f)
    return cKDTree(xy_f).query(b.xy)[0]


def _tempo_medio(dist: np.ndarray, peso: np.ndarray, vel: float) -> float | None:
    """Tempo médio a pé (min), ponderado pela população da faixa; sem caminho conta como 60 min."""
    if peso.sum() <= 0:
        return None
    minutos = np.minimum(dist / vel, 60)
    return round(float((minutos * peso).sum() / peso.sum()), 1)


@lru_cache(maxsize=256)
def cobertura(cod: str, t: str, raio: int, modo: str = "reta") -> dict:
    b = base(cod)
    P = b.P
    md = b.medidor(modo)
    r, fac = _resultado(cod, t, raio, modo)
    sem = r.sem_coord
    vel = velocidade(cod)
    dist = _dist_proxima(cod, t, modo)
    minutos = np.minimum(dist / vel, 60)

    # déficit por hexágono
    df = pd.DataFrame({"h3": b.pts["h3"], "sem_cob": r.sem_cobertura, "def_cap": r.deficit_cap,
                       "pop_desc": np.where(r.coberto, 0, r.pop_faixa),
                       "pop": r.pop_faixa, "min_x_pop": minutos * r.pop_faixa})
    g = df.groupby("h3").sum()
    g["deficit"] = g["sem_cob"] + g["def_cap"]
    g = g[g["deficit"] > 0.5]
    hexes = [{"type": "Feature",
              "properties": {"h3": h, "deficit": round(float(v["deficit"]), 1),
                             "sem_cobertura": round(float(v["sem_cob"]), 1),
                             "deficit_capacidade": round(float(v["def_cap"]), 1),
                             "pop_descoberta": round(float(v["pop_desc"]), 1),
                             "tempo_medio_min": round(float(v["min_x_pop"] / v["pop"]), 1) if v["pop"] > 0 else None},
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
    pf = r.pop_faixa
    acesso = {
        "velocidade_m_min": vel,
        "tempo_medio_min": _tempo_medio(dist, pf, vel),
        "pct_ate_15min": round(float(100 * pf[minutos <= 15].sum() / max(pf.sum(), 1)), 1),
        "raio_em_minutos": round(raio / vel, 1),
    }
    return {"indicadores": ind, "acesso": acesso, "hex": _fc(hexes), "radar": _fc(radar)}


def _agrupar(cod: str, t: str, raio: int, modo: str, chave: np.ndarray) -> pd.DataFrame:
    """Indicadores somados por grupo de moradias (bairro ou setor)."""
    b = base(cod)
    r, _ = _resultado(cod, t, raio, modo)
    vel = velocidade(cod)
    minutos = np.minimum(_dist_proxima(cod, t, modo) / vel, 60)
    df = pd.DataFrame({"g": chave, "pop": r.pop_faixa, "fora": np.where(r.coberto, 0, r.pop_faixa),
                       "sem_cob": r.sem_cobertura, "def_cap": r.deficit_cap, "min_x_pop": minutos * r.pop_faixa,
                       "rural": b.pts["rural"].to_numpy(), "lon": b.lon, "lat": b.lat})
    g = df.groupby("g").agg(pop=("pop", "sum"), fora=("fora", "sum"), sem_cob=("sem_cob", "sum"),
                            def_cap=("def_cap", "sum"), min_x_pop=("min_x_pop", "sum"), rural=("rural", "mean"),
                            lon0=("lon", "min"), lat0=("lat", "min"), lon1=("lon", "max"), lat1=("lat", "max"))
    g["pct_fora"] = np.where(g["pop"] > 0, 100 * g["fora"] / g["pop"], 0)
    g["tempo_medio_min"] = np.where(g["pop"] > 0, g["min_x_pop"] / g["pop"].where(g["pop"] > 0, 1), np.nan)
    g["deficit"] = g["sem_cob"] + g["def_cap"]
    return g


@lru_cache(maxsize=64)
def ranking(cod: str, t: str, raio: int, modo: str = "reta") -> dict:
    """Bairros ordenados pela população da faixa fora do raio de qualquer equipamento."""
    b = base(cod)
    g = _agrupar(cod, t, raio, modo, b.pts["bairro"].to_numpy())
    g = g[g["pop"] >= 0.5].sort_values(["fora", "deficit"], ascending=False)
    linhas = [{"bairro": nome, "pop_faixa": round(float(v["pop"])), "pop_fora": round(float(v["fora"])),
               "pct_fora": round(float(v["pct_fora"]), 1), "deficit_capacidade": round(float(v["def_cap"])),
               "demanda_nao_resolvida": round(float(v["deficit"])),
               "tempo_medio_min": None if np.isnan(v["tempo_medio_min"]) else round(float(v["tempo_medio_min"]), 1),
               "rural": bool(v["rural"] > 0.5),
               "bbox": [round(float(v[k]), 5) for k in ("lon0", "lat0", "lon1", "lat1")]}
              for nome, v in g.iterrows()]
    return {"tipo": t, "raio_m": raio, "modo": modo, "unidade": UNIDADE.get(t, "pessoas"),
            "total_fora": round(float(g["fora"].sum())), "bairros": linhas}


@lru_cache(maxsize=4)
def _setores_geo(cod: str) -> dict:
    """Polígono de cada setor em WGS84 (simplificado para o mapa)."""
    s = base(cod).setores[["CD_SETOR", "geometry"]].to_crs(WGS84)
    s["geometry"] = s.geometry.simplify(0.00003)
    return {cd: mapping(geo) for cd, geo in zip(s["CD_SETOR"], s.geometry)}


@lru_cache(maxsize=64)
def setores(cod: str, t: str, raio: int, modo: str = "reta") -> dict:
    """Déficit por setor censitário (a mesma conta dos hexágonos, na malha do IBGE)."""
    b = base(cod)
    g = _agrupar(cod, t, raio, modo, b.pts["CD_SETOR"].to_numpy())
    geo = _setores_geo(cod)
    feats = []
    for cd, v in g.iterrows():
        if cd not in geo or v["pop"] < 0.5:
            continue
        feats.append({"type": "Feature", "properties": {
            "setor": cd, "bairro": b.setor_bairro.get(cd, "Sem bairro"),
            "deficit": round(float(v["deficit"]), 1), "pop_faixa": round(float(v["pop"]), 1),
            "pop_descoberta": round(float(v["fora"]), 1), "pct_fora": round(float(v["pct_fora"]), 1),
            "deficit_capacidade": round(float(v["def_cap"]), 1),
            "tempo_medio_min": None if np.isnan(v["tempo_medio_min"]) else round(float(v["tempo_medio_min"]), 1)},
            "geometry": geo[cd]})
    return _fc(feats)


class ForaDoMunicipio(ValueError):
    pass


def simular(cod: str, t: str, raio: int, modo: str, lon: float, lat: float) -> dict:
    """Quanto um equipamento novo do tipo `t` em (lon, lat) passaria a atender.

    Conta as pessoas da faixa que ficam dentro do raio do ponto (com a mesma regra
    de raio rural e a mesma medida de distância do mapa) e, entre elas, as que hoje
    não têm nenhum equipamento no raio."""
    from shapely.geometry import Point

    b = base(cod)
    r, _ = _resultado(cod, t, raio, modo)
    p = gpd.GeoSeries([Point(lon, lat)], crs=WGS84).to_crs(b.pts.crs)
    if not b.limite.geometry.iloc[0].buffer(1000).contains(p.iloc[0]):
        raise ForaDoMunicipio("Ponto fora do município.")
    xy = np.array([[p.iloc[0].x, p.iloc[0].y]])
    rp = cob.raios(b.pts, raio, b.fr)
    ii, _ = b.medidor(modo).pares(rp, xy)
    sit = b.situacao(p)
    rural = bool(sit["SITUACAO"].iloc[0] != "Urbana") if pd.notna(sit["SITUACAO"].iloc[0]) else False
    bairro = _num(sit["NM_BAIRRO"].iloc[0])
    raio_ef = raio * (b.fr if rural else 1)
    novos = ii[~r.coberto[ii]]
    pf = r.pop_faixa
    tot = max(float(pf.sum()), 1)
    antes = float(pf[r.coberto].sum())
    if modo == "rede":
        area = gpd.GeoSeries(b.medidor("rede").rede.areas_servico(xy, np.array([raio_ef])), crs=b.pts.crs)
    else:
        area = gpd.GeoSeries([p.iloc[0].buffer(raio_ef, quad_segs=24)], crs=b.pts.crs)
    area = area.to_crs(WGS84).simplify(0.00005)
    return {
        "tipo": t, "raio_m": raio, "raio_efetivo_m": raio_ef, "modo": modo, "rural": rural, "bairro": bairro,
        "pop_no_raio": round(float(pf[ii].sum())),
        "novos_atendidos": round(float(pf[novos].sum())),
        "demanda_sem_cobertura_absorvida": round(float(r.sem_cobertura[ii].sum())),
        "demanda_total_absorvivel": round(float((r.sem_cobertura + r.deficit_cap)[ii].sum())),
        "pct_coberta_antes": round(100 * antes / tot, 1),
        "pct_coberta_depois": round(100 * (antes + float(pf[novos].sum())) / tot, 1),
        "tempo_raio_min": round(raio_ef / velocidade(cod), 1),
        "area": {"type": "Feature", "properties": {}, "geometry": mapping(area.iloc[0])},
    }


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
    for f in (equipamentos, cobertura, areas, _prioridade_rede, prioridade, _resultado, _dist_proxima,
              ranking, setores, _setores_geo):
        f.cache_clear()          # lru_cache não remove por chave; limpar tudo é barato
    contexto.esquecer(cod)


def aquecer(cod: str) -> None:
    """Pré-calcula o que o mapa abre por padrão (para a primeira troca de modo ser rápida)."""
    b = base(cod)
    if b.tem_rede:
        for t, c in b.P["equipamentos"].items():
            cobertura(cod, t, int(c["raio_m"]), "rede")
        prioridade(cod, "rede")
