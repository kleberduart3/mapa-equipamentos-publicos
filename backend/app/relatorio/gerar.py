"""Relatório PDF de cobertura de equipamentos públicos.

Uso por script:  python backend/scripts/gerar_relatorio.py --municipio CÓDIGO [--creche 600 ...]
Uso pela API:    GET /api/{cod}/relatorio.pdf?creche=500&ubs=1000...

Fluxo: recalcula a cobertura com os raios informados → desenha os mapas
(matplotlib + mosaicos do OpenStreetMap) → preenche o modelo HTML → Chromium
(Playwright) imprime em PDF A4.
"""
from __future__ import annotations

import base64
import io
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..analise import cobertura as cob
from ..analise.contexto import Base, base
from ..estilo import ESTILO, UNIDADE
from ..ingestao import inep

AQUI = Path(__file__).parent
WEB = "EPSG:3857"
PRECISAS = {"inep_catalogo", "cnes", "cnefe_nome_no_cep"}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


def fmt(n, casas=0) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "–"
    return f"{n:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------- #
# Análise com os raios escolhidos
# --------------------------------------------------------------------------- #
def analisar(b: Base, raios: dict[str, int] | None = None, modo: str = "reta") -> dict:
    P = b.P
    raios = raios or {}
    md = b.medidor(modo)
    tipos = {}
    cols = {}
    for t, cfg0 in P["equipamentos"].items():
        cfg = {**cfg0, "raio_m": int(raios.get(t, cfg0["raio_m"]))}
        fac, sem = cob.ofertas(t, cfg, b.escolas, b.ubs)
        r = cob.calcular(t, cfg, b.pts, fac, sem, b.fr, tree=b.tree, medidor=md)
        sit = b.situacao(fac.geometry) if len(fac) else pd.DataFrame()
        fac = fac.assign(rural=(sit["SITUACAO"] != "Urbana").to_numpy() if len(fac) else [])
        rp = cob.raios(b.pts, cfg["raio_m"], b.fr)
        sug = cob.sugerir_locais(t, r, b.pts, b.cand_xy, b.hex_ids, rp, int(P["prioridade"]["sugestoes_por_tipo"]),
                                 float(P["prioridade"]["ganho_minimo"][t]), b.tree, medidor=md)
        if len(sug):
            g = gpd.GeoSeries(gpd.points_from_xy(sug["x"], sug["y"]), crs=b.pts.crs)
            s2 = b.situacao(g)
            sug["bairro"] = [bb if isinstance(bb, str) and bb.strip() else f"Zona rural – {d}" for bb, d in
                             zip(s2["NM_BAIRRO"], s2["NM_DIST"])]
            sug = gpd.GeoDataFrame(sug, geometry=g.values, crs=b.pts.crs)
        rural = b.pts["rural"].to_numpy()
        sens = {}
        for e in (0.5, 1.5):
            sens[e] = cob.pct_coberto(cob.calcular(t, cfg, b.pts, fac.drop(columns="rural"), sem, b.fr, e, b.tree, md))
        tipos[t] = {
            "t": t, "cfg": cfg, "rotulo": cfg["rotulo"], "cor": ESTILO[t]["cor"], "unidade": UNIDADE[t],
            "res": r, "fac": fac, "sem_coord": sem, "sug": sug,
            "pop_faixa": r.pop_faixa.sum(), "pct": cob.pct_coberto(r),
            "pct_urb": 100 * r.pop_faixa[r.coberto & ~rural].sum() / max(r.pop_faixa[~rural].sum(), 1),
            "pct_rur": 100 * r.pop_faixa[r.coberto & rural].sum() / max(r.pop_faixa[rural].sum(), 1),
            "pop_desc": r.pop_faixa[~r.coberto].sum(), "dem": r.demanda.sum(),
            "sem_cob": r.sem_cobertura.sum(), "def_cap": r.deficit_cap.sum(),
            "sens": {"0.5": sens[0.5], "1": cob.pct_coberto(r), "1.5": sens[1.5]},
        }
        cols.update(cob.colunas_ponto(r))
    tab = pd.concat([b.pts[["h3"]].reset_index(drop=True), pd.DataFrame(cols)], axis=1)
    hexa = cob.agregar(tab, "h3", list(tipos))
    hexa = cob.indice_prioridade(hexa, list(tipos), P["prioridade"]["pesos"])
    hexa = b.hex_gdf(hexa["h3"]).merge(hexa, on="h3")
    return {"tipos": tipos, "hex": hexa, "modo": modo}


# --------------------------------------------------------------------------- #
# Mapas
# --------------------------------------------------------------------------- #
def _png(fig) -> str:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# A política de uso dos mosaicos do OSM exige identificar a aplicação; mosaicos
# ficam em cache local para não serem baixados de novo a cada relatório.
CABECALHO_OSM = {"User-Agent": "MapaEquipamentosPublicos/0.1 (relatorio PDF de planejamento urbano)"}
_CACHE_OK = False


def _fundo(ax):
    import tempfile

    import contextily as ctx
    global _CACHE_OK
    if not _CACHE_OK:
        pasta = Path(tempfile.gettempdir()) / "mapa_equipamentos_mosaicos"
        pasta.mkdir(exist_ok=True)
        ctx.set_cache_dir(str(pasta))
        _CACHE_OK = True
    try:
        ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, crs=WEB, attribution_size=6,
                        attribution="© OpenStreetMap contributors", headers=CABECALHO_OSM)
    except Exception:  # noqa: BLE001 – sem internet o mapa sai sem fundo
        ax.set_facecolor("#f2f2ee")


def _radar(ax, x, y, cor, rotulo):
    for s, a in [(900, 0.15), (520, 0.3), (220, 0.55)]:
        ax.scatter([x], [y], s=s, facecolor="none", edgecolor=cor, linewidth=1.4, alpha=a, zorder=6)
    ax.scatter([x], [y], s=90, color=cor, edgecolor="white", linewidth=1.5, zorder=7)
    ax.annotate(rotulo, (x, y), xytext=(9, 7), textcoords="offset points", fontsize=8, weight="bold", color="white",
                bbox={"boxstyle": "round,pad=0.25", "fc": cor, "ec": "none"}, zorder=8)


def _extensao(ax, b, extra: gpd.GeoSeries | None = None, pad=900, proporcao=4 / 3):
    urb = b.pts[~b.pts["rural"]].to_crs(WEB)
    x0, x1 = urb.geometry.x.quantile([0.03, 0.97])
    y0, y1 = urb.geometry.y.quantile([0.03, 0.97])
    if extra is not None and len(extra):
        e = extra.to_crs(WEB)
        x0, x1 = min(x0, e.x.min()), max(x1, e.x.max())
        y0, y1 = min(y0, e.y.min()), max(y1, e.y.max())
    cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    if w / h < proporcao:
        w = h * proporcao
    else:
        h = w / proporcao
    ax.set_xlim(cx - w / 2, cx + w / 2)
    ax.set_ylim(cy - h / 2, cy + h / 2)


def mapa_tipo(b: Base, d: dict, hexa: gpd.GeoDataFrame, modo: str = "reta") -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t, cor = d["t"], d["cor"]
    fig, ax = plt.subplots(figsize=(8, 6))
    h = hexa.assign(deficit=hexa[f"{t}_demanda_sem_cobertura"] + hexa[f"{t}_deficit_capacidade"])
    h = h[h["deficit"] > 0.5].to_crs(WEB)
    _extensao(ax, b, d["sug"].geometry if len(d["sug"]) else None)
    if len(h):
        h.plot(ax=ax, column="deficit", cmap="Reds", alpha=0.55, linewidth=0, zorder=2,
               vmin=0, vmax=max(h["deficit"].quantile(0.97), 1))
    fac = d["fac"]
    if len(fac):
        r = np.where(fac["rural"], d["cfg"]["raio_m"] * b.fr, d["cfg"]["raio_m"])
        if modo == "rede":
            xy = np.column_stack([fac.geometry.x, fac.geometry.y])
            areas = gpd.GeoSeries(b.medidor("rede").rede.areas_servico(xy, r.astype(float)), crs=fac.crs).to_crs(WEB)
            areas.plot(ax=ax, facecolor=cor, edgecolor="none", alpha=0.14, zorder=3)
            areas.boundary.plot(ax=ax, color=cor, linewidth=0.7, alpha=0.8, zorder=3)
        else:
            circ = gpd.GeoSeries(fac.geometry.buffer(r), crs=fac.crs).to_crs(WEB)
            circ.plot(ax=ax, facecolor=cor, edgecolor="none", alpha=0.08, zorder=3)
            for k, (lw, al) in zip((1, 0.66, 0.33), ((1.1, 0.85), (0.7, 0.45), (0.6, 0.3))):
                gpd.GeoSeries(fac.geometry.buffer(r * k), crs=fac.crs).to_crs(WEB).boundary.plot(
                    ax=ax, color=cor, linewidth=lw, alpha=al, zorder=3)
        f = fac.to_crs(WEB)
        prec = f["fonte_coord"].isin(PRECISAS)
        f[prec].plot(ax=ax, color=cor, markersize=34, edgecolor="white", linewidth=1, zorder=5)
        if (~prec).any():
            f[~prec].plot(ax=ax, color=cor, markersize=34, edgecolor="#d62828", linewidth=1.2, zorder=5)
    for s in (d["sug"].to_crs(WEB).itertuples() if len(d["sug"]) else []):
        _radar(ax, s.geometry.x, s.geometry.y, cor, str(s.ordem))
    _fundo(ax)
    ax.set_axis_off()
    return _png(fig)


def mapa_prioridade(b: Base, an: dict) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.6))
    h = an["hex"][an["hex"]["prioridade_geral"] > 1].to_crs(WEB)
    _extensao(ax, b, proporcao=16 / 9)
    h.plot(ax=ax, column="prioridade_geral", cmap="magma_r", alpha=0.6, linewidth=0, zorder=2, legend=True,
           legend_kwds={"shrink": 0.55, "label": "Índice de prioridade (0–100)"})
    for d in an["tipos"].values():
        if len(d["sug"]):
            for s in d["sug"].to_crs(WEB).itertuples():
                if s.ordem <= 3:
                    _radar(ax, s.geometry.x, s.geometry.y, d["cor"], str(s.ordem))
    _fundo(ax)
    ax.set_axis_off()
    return _png(fig)


# --------------------------------------------------------------------------- #
# Conteúdo
# --------------------------------------------------------------------------- #
def achados(an: dict, mat: dict) -> list[str]:
    tp = an["tipos"]
    ape = " a pé pelas ruas" if an.get("modo") == "rede" else ""
    L = []
    pior = min(tp.values(), key=lambda d: d["pct"])
    L.append(f"<b>{pior['rotulo']}</b> é o equipamento com menor cobertura: só {fmt(pior['pct'])}% das "
             f"{pior['unidade']} da faixa moram a até {fmt(pior['cfg']['raio_m'])} m{ape} de um equipamento.")
    if "creche" in tp and mat.get("creche"):
        r = mat["creche"]["total"] / max(tp["creche"]["dem"], 1)
        if r < 1:
            L.append(f"Somando todas as redes, há matrículas de creche para {fmt(100 * r)}% da meta de atendimento "
                     f"({fmt(100 * tp['creche']['cfg']['taxa_atendimento_meta'])}% das crianças de 0 a 3 anos): "
                     f"faltam cerca de {fmt(tp['creche']['dem'] - mat['creche']['total'])} vagas no município.")
    for d in tp.values():
        if d["pct_rur"] + 10 < d["pct_urb"]:
            L.append(f"Na zona rural a cobertura de <b>{d['rotulo'].split(' (')[0]}</b> cai para {fmt(d['pct_rur'])}% "
                     f"(urbana: {fmt(d['pct_urb'])}%), mesmo com raio ampliado.")
    bairros = pd.concat([d["sug"][["bairro"]].assign(t=d["rotulo"]) for d in tp.values() if len(d["sug"])])
    if len(bairros):
        top = bairros.groupby("bairro")["t"].nunique().sort_values(ascending=False)
        top = top[top >= 2].head(3)
        if len(top):
            L.append("Áreas que aparecem como prioritárias para mais de um tipo de equipamento: "
                     + ", ".join(f"<b>{b}</b> ({n} tipos)" for b, n in top.items()) + ".")
    return L


def achado_rede(comp: list[dict], modo: str) -> list[str]:
    if not comp:
        return []
    pior = max(comp, key=lambda c: c["reta"] - c["rede"])
    return [f"Medindo a distância a pé pelas ruas, e não em linha reta, a cobertura cai em todos os tipos; a maior queda é em "
            f"<b>{pior['rotulo']}</b>: de {fmt(pior['reta'])}% para {fmt(pior['rede'])}%."]


def pendencias(b: Base) -> list[str]:
    e = b.escolas
    mats = e[list(inep.MAT.values())].sum(axis=1) > 0
    conf = e[e["em_funcionamento"].astype(bool) & mats & ~e["fonte_coord"].isin(PRECISAS)
             & (e["dependencia"] == "Municipal")]
    L = [f"{r.escola} (INEP {r.codigo_inep}) – localização "
         f"{'ausente' if r.fonte_coord == 'sem_coordenada' else 'aproximada'}" for r in conf.itertuples()]
    u = b.ubs[b.ubs["ativa"]]
    lim = b.limite.geometry.iloc[0]
    for r in u.itertuples():
        if r.fonte_coord != "cnes":
            L.append(f"{r.nome} (CNES {r.cnes}) – localização {'ausente' if r.fonte_coord == 'sem_coordenada' else 'aproximada'}")
        elif not r.geometry.is_empty and r.geometry.distance(lim) > 100:
            L.append(f"{r.nome} (CNES {r.cnes}) – coordenada do CNES fora do município ({fmt(r.geometry.distance(lim))} m)")
    return L


def matriculas(b: Base) -> dict:
    mic = inep.ler_microdados(b.m)
    mic = mic[mic["em_funcionamento"]]
    out = {}
    for t, cfg in b.P["equipamentos"].items():
        if cfg["fonte_dados"] != "inep":
            continue
        g = mic.groupby("dependencia")[cfg["capacidade"]].sum()
        out[t] = {"Municipal": int(g.get("Municipal", 0)), "Estadual": int(g.get("Estadual", 0)),
                  "Federal": int(g.get("Federal", 0)), "Privada": int(g.get("Privada", 0)), "total": int(g.sum())}
    return out


# --------------------------------------------------------------------------- #
# HTML → PDF
# --------------------------------------------------------------------------- #
def comparacao(b: Base, raios: dict[str, int] | None = None) -> list[dict]:
    """% coberta por tipo nos dois modos de distância (sem sugestões: rápido)."""
    P = b.P
    if not b.tem_rede:
        return []
    rural = b.pts["rural"].to_numpy()
    out = []
    for t, cfg0 in P["equipamentos"].items():
        cfg = {**cfg0, "raio_m": int((raios or {}).get(t, cfg0["raio_m"]))}
        fac, sem = cob.ofertas(t, cfg, b.escolas, b.ubs)
        linha = {"rotulo": cfg["rotulo"].split(" (")[0].replace("Unidade Básica de Saúde", "UBS"),
                 "cor": ESTILO[t]["cor"], "raio": cfg["raio_m"]}
        for m in ("reta", "rede"):
            r = cob.calcular(t, cfg, b.pts, fac, sem, b.fr, tree=b.tree, medidor=b.medidor(m))
            pf = r.pop_faixa
            linha[m] = cob.pct_coberto(r)
            linha[m + "_rur"] = 100 * pf[r.coberto & rural].sum() / max(pf[rural].sum(), 1)
            linha[m + "_desc"] = pf[~r.coberto].sum()
        out.append(linha)
    return out


def montar_html(b: Base, raios: dict[str, int] | None = None, modo: str = "reta") -> str:
    an = analisar(b, raios, modo)
    m, P = b.m.info(), b.P
    mat = matriculas(b)
    comp = comparacao(b, raios)
    hoje = date.today()
    tipos = []
    for t, d in an["tipos"].items():
        tipos.append({**{k: v for k, v in d.items() if k not in ("res", "fac", "sem_coord", "sug")},
                      "mapa": mapa_tipo(b, d, an["hex"], modo), "n_fac": len(d["fac"]), "n_sem_coord": len(d["sem_coord"]),
                      "sug": [] if not len(d["sug"]) else d["sug"].drop(columns="geometry").to_dict("records"),
                      "mat": mat.get(t), "redes": ", ".join(d["cfg"].get("redes", ["Municipal"])),
                      "capacidade_txt": ("equipes de Saúde da Família × " + fmt(d["cfg"]["pessoas_por_equipe"]) + " pessoas"
                                         if t == "ubs" else "matrículas (Censo Escolar 2024)")})
    env = Environment(loader=FileSystemLoader(AQUI), autoescape=select_autoescape(["html"]))
    env.filters["n"] = fmt
    return env.get_template("modelo.html").render(
        m=m, data=f"{hoje.day} de {MESES[hoje.month - 1]} de {hoje.year}", P=P, fr=b.fr,
        pop=int(b.setores["pop_total"].sum()), n_setores=len(b.setores), tipos=tipos,
        mapa_prioridade=mapa_prioridade(b, an), achados=achados(an, mat) + achado_rede(comp, modo), pendencias=pendencias(b),
        pesos="2/3 população fora do raio e 1/3 falta de capacidade (sem cadastro do IPTU)",
        modo=modo, comp=comp, rede_km=(b.medidor("rede").rede.km if b.tem_rede else None),
    )


def nome_arquivo(nome: str) -> str:
    """'Palmeira dos Índios' → 'palmeira_dos_indios' (seguro para nome de arquivo)."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def gerar_pdf(cod: str, destino: Path | None = None, raios: dict[str, int] | None = None,
              modo: str = "reta", tempo_limite_s: float = 180) -> Path:
    from playwright.sync_api import sync_playwright

    b = base(cod)
    html = montar_html(b, raios, modo)
    m = b.m.info()
    sufixo = "_a_pe" if modo == "rede" else ""
    destino = destino or b.m.saidas / f"relatorio_{nome_arquivo(m['nome'])}_{date.today():%Y%m%d}{sufixo}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    rodape = (f'<div style="font:8px Inter,Arial,sans-serif;color:#6b7785;width:100%;padding:0 14mm;'
              f'display:flex;justify-content:space-between"><span>Mapa de Equipamentos Públicos – {m["nome"]}/{m["uf"]}</span>'
              '<span>Página <span class="pageNumber"></span> de <span class="totalPages"></span></span></div>')
    with sync_playwright() as p:
        nav = p.chromium.launch()
        try:
            pg = nav.new_page()
            pg.set_default_timeout(tempo_limite_s * 1000)
            pg.set_content(html, wait_until="networkidle")
            pg.pdf(path=str(destino), format="A4", print_background=True, display_header_footer=True,
                   header_template="<span></span>", footer_template=rodape,
                   margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        finally:
            nav.close()
    return destino

