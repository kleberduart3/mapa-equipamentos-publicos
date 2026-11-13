"""Relatório PDF de uma VISÃO SALVA: o que a pessoa guardou no mapa, e não o relatório geral.

Reproduz o enquadramento, o serviço mostrado, a divisão do mapa (hexágonos ou setores), as
camadas ligadas e a simulação de nova unidade, e traz os números do serviço no município e
na área visível do mapa, os bairros dessa área com mais gente morando longe e as fontes.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from pyproj import Transformer

from .. import servicos
from ..analise.contexto import base
from ..estilo import ESTILO, UNIDADE
from ..fontes import REFERENCIAS
from .gerar import AQUI, CMAP_DEFICIT, CMAP_PRIORIDADE, LOGO, MESES, WEB, _fundo, _png, _radar, fmt, imprimir_pdf

WGS84 = "EPSG:4326"
RES0 = 78271.51696402048            # metros por pixel no zoom 0 do MapLibre (blocos de 512 px)
TELA = (1100, 720)                  # área de mapa típica no computador, em pixels


def _fc(fc: dict) -> gpd.GeoDataFrame:
    if not fc.get("features"):
        return gpd.GeoDataFrame(geometry=[], crs=WGS84)
    return gpd.GeoDataFrame.from_features(fc["features"], crs=WGS84)


def _enquadramento(b, estado: dict) -> tuple[float, float, float, float]:
    """Extensão em Web Mercator (x0, y0, x1, y1) igual à que a pessoa via na tela ao salvar."""
    mp = estado.get("mapa")
    if mp:
        cx, cy = Transformer.from_crs(WGS84, WEB, always_xy=True).transform(mp["lng"], mp["lat"])
        res = RES0 / 2 ** float(mp["zoom"])
        w, h = TELA[0] * res / 2, TELA[1] * res / 2
        return cx - w, cy - h, cx + w, cy + h
    urb = b.pts[~b.pts["rural"]].to_crs(WEB)                     # sem enquadramento: a sede urbana
    x0, x1 = urb.geometry.x.quantile([0.03, 0.97])
    y0, y1 = urb.geometry.y.quantile([0.03, 0.97])
    return x0 - 900, y0 - 900, x1 + 900, y1 + 900


def _mapa(b, cod: str, estado: dict, raios: dict, ext, sim: dict | None) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    modo, t = estado.get("modo", "reta"), estado.get("mostrar")
    visiveis = [k for k, v in (estado.get("visiveis") or {}).items() if v and k in raios] or \
               ([t] if t in raios else list(raios))
    camadas = estado.get("camadas") or {}
    x0, y0, x1, y1 = ext
    fig, ax = plt.subplots(figsize=(8, 8 * (y1 - y0) / (x1 - x0)))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)

    # déficit (ou prioridade geral)
    if t == "prioridade":
        h = _fc(servicos.prioridade(cod, modo)).to_crs(WEB)
        if len(h):
            h.plot(ax=ax, column="prioridade_geral", cmap=CMAP_PRIORIDADE, alpha=0.6, linewidth=0, zorder=2)
    else:
        fc = servicos.setores(cod, t, raios[t], modo) if estado.get("unid") == "setor" \
            else servicos.cobertura(cod, t, raios[t], modo)["hex"]
        h = _fc(fc)
        if len(h):
            h = h[h["deficit"] > 0.5].to_crs(WEB)
            vis = h.cx[x0:x1, y0:y1]
            vmax = max((vis if len(vis) else h)["deficit"].quantile(0.95), 1)
            h.plot(ax=ax, column="deficit", cmap=CMAP_DEFICIT, alpha=0.55, zorder=2, vmin=0, vmax=vmax,
                   edgecolor="#C93A27" if estado.get("unid") == "setor" else "none",
                   linewidth=0.3 if estado.get("unid") == "setor" else 0)

    # alcance de cada unidade (se a camada estava ligada)
    eq = _fc(servicos.equipamentos(cod))
    if camadas.get("raios"):
        for k in visiveis:
            cor = ESTILO[k]["cor"]
            if modo == "rede":
                a = _fc(servicos.areas(cod, k, raios[k])).to_crs(WEB)
            else:
                f = eq[eq["tipo"] == k].to_crs(b.pts.crs)
                r = np.where(f["rural"].astype(bool), raios[k] * b.fr, raios[k])
                a = gpd.GeoSeries(f.geometry.buffer(r), crs=f.crs).to_crs(WEB)
            if len(a):
                a.plot(ax=ax, facecolor=cor, edgecolor=cor, alpha=0.12, linewidth=0.6, zorder=3)

    # unidades dos tipos visíveis
    for k in visiveis:
        f = eq[eq["tipo"] == k].to_crs(WEB)
        if len(f):
            aprox = ~f["fonte_coord"].isin(["inep_catalogo", "cnes", "cnefe_nome_no_cep"])
            f.plot(ax=ax, color=ESTILO[k]["cor"], markersize=46, edgecolor=np.where(aprox, "#C93A27", "white"),
                   linewidth=1.2, zorder=5)

    # áreas prioritárias sugeridas
    if camadas.get("radar") and t in raios:
        for s in _fc(servicos.cobertura(cod, t, raios[t], modo)["radar"]).to_crs(WEB).itertuples():
            _radar(ax, s.geometry.x, s.geometry.y, ESTILO[t]["cor"], str(s.ordem))

    # nova unidade simulada
    if sim:
        area = gpd.GeoDataFrame.from_features([sim["area"]], crs=WGS84).to_crs(WEB)
        area.plot(ax=ax, facecolor="#2F4BFF", alpha=0.14, edgecolor="#2F4BFF", linewidth=1.6, linestyle="--", zorder=6)
        px, py = Transformer.from_crs(WGS84, WEB, always_xy=True).transform(sim["lng"], sim["lat"])
        ax.scatter([px], [py], s=260, color="#2F4BFF", edgecolor="white", linewidth=2.5, zorder=8)
        ax.scatter([px], [py], s=55, color="#FF6B57", zorder=9)

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    _fundo(ax)
    ax.set_axis_off()
    return _png(fig)


def _na_area(b, ext) -> np.ndarray:
    """Máscara das moradias dentro do enquadramento."""
    x0, y0, x1, y1 = ext
    t = Transformer.from_crs(WEB, WGS84, always_xy=True)
    (lo0, la0), (lo1, la1) = t.transform(x0, y0), t.transform(x1, y1)
    return (b.lon >= lo0) & (b.lon <= lo1) & (b.lat >= la0) & (b.lat <= la1)


def _numeros(b, cod: str, t: str, raio: int, modo: str, area: np.ndarray) -> dict:
    r, fac = servicos._resultado(cod, t, raio, modo)
    vel = servicos.velocidade(cod)
    dist = servicos._dist_proxima(cod, t, modo)
    pf = r.pop_faixa

    def bloco(msk):
        tot = float(pf[msk].sum())
        longe = float(pf[msk & ~r.coberto].sum())
        return {"total": tot, "longe": longe, "pct_perto": 100 * (tot - longe) / tot if tot else None,
                "tempo": servicos._tempo_medio(dist[msk], pf[msk], vel) if tot else None}

    tudo = np.ones(len(pf), bool)
    df = pd.DataFrame({"bairro": b.pts["bairro"].to_numpy(), "pop": pf, "longe": np.where(r.coberto, 0, pf),
                       "min": np.minimum(dist / vel, 60) * pf})[area]
    g = df.groupby("bairro").sum()
    g = g[g["pop"] >= 0.5]
    g["pct"] = 100 * g["longe"] / g["pop"]
    g["tempo"] = g["min"] / g["pop"]
    bairros = [{"bairro": n, "total": v["pop"], "longe": v["longe"], "pct": v["pct"], "tempo": v["tempo"]}
               for n, v in g.sort_values("longe", ascending=False).head(10).iterrows() if v["longe"] >= 1]
    return {"municipio": bloco(tudo), "area": bloco(area), "bairros": bairros,
            "unidades_total": int(len(fac))}


def montar_html(cod: str, estado: dict, titulo: str) -> str:
    b = base(cod)
    m = b.m
    tipos = b.P["equipamentos"]
    modo = estado.get("modo", "reta")
    raios = {k: int((estado.get("raios") or {}).get(k, c["raio_m"])) for k, c in tipos.items()}
    t = estado.get("mostrar")
    t = t if t in tipos or t == "prioridade" else next(iter(tipos))
    estado = {**estado, "mostrar": t}
    vel = servicos.velocidade(cod)
    ext = _enquadramento(b, estado)
    area = _na_area(b, ext)

    sim = None
    if estado.get("sim") and estado["sim"].get("tipo") in tipos:
        s = estado["sim"]
        try:
            sim = {**servicos.simular(cod, s["tipo"], raios[s["tipo"]], modo, s["lng"], s["lat"]),
                   "lng": s["lng"], "lat": s["lat"], "rotulo": tipos[s["tipo"]]["rotulo"],
                   "unidade": UNIDADE.get(s["tipo"], "pessoas")}
        except servicos.ForaDoMunicipio:
            sim = None

    # serviços descritos: o mostrado (ou, na prioridade geral, todos os visíveis)
    vis = [k for k, v in (estado.get("visiveis") or {}).items() if v and k in tipos]
    descritos = [t] if t in tipos else (vis or list(tipos))
    servicos_txt = []
    for k in descritos:
        servicos_txt.append({"t": k, "rotulo": tipos[k]["rotulo"], "cor": ESTILO[k]["cor"],
                             "unidade": UNIDADE.get(k, "pessoas"), "raio": raios[k],
                             "minutos": max(1, round(raios[k] / vel)), "n": _numeros(b, cod, k, raios[k], modo, area)})

    unidades_area = []
    eq = _fc(servicos.equipamentos(cod))
    if len(eq):
        e = eq.to_crs(WEB)
        x0, y0, x1, y1 = ext
        dentro = e[(e.geometry.x >= x0) & (e.geometry.x <= x1) & (e.geometry.y >= y0) & (e.geometry.y <= y1)
                   & e["tipo"].isin(vis or descritos)]
        unidades_area = [{"nome": r.nome, "tipo": tipos[r.tipo]["rotulo"].split(" (")[0], "cor": ESTILO[r.tipo]["cor"],
                          "bairro": r.bairro if isinstance(r.bairro, str) else "–"} for r in dentro.itertuples()][:30]

    hoje = date.today()
    env = Environment(loader=FileSystemLoader(AQUI), autoescape=select_autoescape(["html"]))
    env.filters["n"] = fmt
    env.filters["min"] = lambda mm: max(1, round(float(mm) / vel))
    return env.get_template("modelo_visao.html").render(
        logo=Markup(LOGO.read_text(encoding="utf-8")) if LOGO.exists() else "Equicidade",
        titulo=titulo, m=m.info(), data=f"{hoje.day} de {MESES[hoje.month - 1]} de {hoje.year}",
        modo=modo, unid=estado.get("unid", "hex"), prioridade=(t == "prioridade"),
        servicos=servicos_txt, sim=sim, fr=b.fr, vel=vel, camadas=estado.get("camadas") or {},
        mapa=_mapa(b, cod, estado, raios, ext, sim), unidades_area=unidades_area,
        legenda_tipos=[{"rotulo": tipos[k]["rotulo"].split(" (")[0], "cor": ESTILO[k]["cor"]} for k in (vis or descritos)],
        referencias=REFERENCIAS, enquadrado=bool(estado.get("mapa")),
    )


def gerar_pdf_visao(cod: str, estado: dict, titulo: str, destino: Path, tempo_limite_s: float = 180) -> Path:
    m = base(cod).m.info()
    html = montar_html(cod, estado, titulo)
    return imprimir_pdf(html, destino, f"Equicidade · {m['nome']}/{m['uf']} · visão “{titulo}”", tempo_limite_s)
