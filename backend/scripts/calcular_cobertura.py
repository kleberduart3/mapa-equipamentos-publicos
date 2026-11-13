"""Etapa 3 – cobertura, demanda × capacidade e áreas prioritárias.

Uso:  python backend/scripts/calcular_cobertura.py
Lê dados/processados/*.parquet e config/parametros.yaml. Saídas em dados/saidas/:
  cobertura_setores.parquet      indicadores por setor censitário (polígonos)
  cobertura_hex.parquet          indicadores e índice de prioridade por hexágono H3
  equipamentos_capacidade.parquet  cada equipamento com demanda no raio e razão capacidade/demanda
  sugestoes_novos.parquet        hexágonos sugeridos para novos equipamentos
  indicadores.json               resumo municipal (para o painel e o relatório)
  resumo_cobertura.md + cobertura_mapa.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import geopandas as gpd  # noqa: E402
import h3  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402

from backend.app.analise import cobertura as cob  # noqa: E402
from backend.app.config import CRS_GEO, PROCESSADOS, SAIDAS, crs_metrico, municipio, parametros  # noqa: E402
from backend.app.ingestao import inep  # noqa: E402

CORES = {"creche": "#e8873d", "pre_escola": "#e9c46a", "fundamental_iniciais": "#2f6db5",
         "fundamental_finais": "#7b4fb3", "ubs": "#2a9d5c"}


def fmt(n, casas=0):
    return f"{n:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main() -> int:
    P, m = parametros(), municipio()
    eqs = P["equipamentos"]
    fr = float(P["fator_raio_rural"])
    res_h3 = int(P["prioridade"]["resolucao_h3"])

    setores = gpd.read_parquet(PROCESSADOS / "setores.parquet")
    enderecos = gpd.read_parquet(PROCESSADOS / "enderecos.parquet")
    escolas = gpd.read_parquet(PROCESSADOS / "escolas.parquet")
    ubs = gpd.read_parquet(PROCESSADOS / "ubs.parquet")
    limite = gpd.read_parquet(PROCESSADOS / "limite.parquet")

    # ---------------- 1. Demanda ----------------
    print("Distribuindo população nos endereços…")
    pts = cob.pontos_demanda(setores, enderecos)
    chk_pop = {c: (round(float(pts[c].sum()), 1), round(float(setores[c].sum()), 1)) for c in cob.FAIXAS}
    for c, (a, b) in chk_pop.items():
        assert abs(a - b) < 1, f"população {c} não fecha: pontos {a} × setores {b}"
    xy = np.column_stack([pts.geometry.x, pts.geometry.y])
    tree = cKDTree(xy)
    ll = pts.to_crs(CRS_GEO)
    pts["h3"] = [h3.latlng_to_cell(y, x, res_h3) for x, y in zip(ll.geometry.x, ll.geometry.y)]

    # ---------------- 2–3. Cobertura e 2SFCA ----------------
    resultados: dict[str, cob.Resultado] = {}
    sensib, facs = {}, []
    tipos_calc = [(t, t, None) for t in eqs] + \
                 [(f"{t}_rede_publica", t, cob.REDE_PUBLICA) for t in P.get("variante_rede_publica", [])]
    for chave, t, redes in tipos_calc:
        cfg = eqs[t]
        fac, sem = cob.ofertas(t, cfg, escolas, ubs, redes)
        r = cob.calcular(chave, cfg, pts, fac, sem, fr, tree=tree)
        resultados[chave] = r
        sensib[chave] = {f"{e:g}x": round(cob.pct_coberto(cob.calcular(chave, cfg, pts, fac, sem, fr, e, tree)), 1)
                         for e in (0.5, 1.0, 1.5)}
        sensib[chave]["raio_gigante"] = round(cob.pct_coberto(cob.calcular(chave, cfg, pts, fac, sem, fr, 100, tree)), 1)
        if redes is None and len(fac):
            g = fac.copy()
            g = g.merge(r.fac[["id", "demanda_no_raio", "capacidade_por_demanda", "sem_demanda_no_raio"]], on="id")
            g["tipo"], g["raio_m"] = t, cfg["raio_m"]
            facs.append(g)
        print(f"  {chave}: {cob.pct_coberto(r):.1f}% coberto, 2SFCA ok={r.checagem['2sfca_consistente']}")

    tipos = list(eqs)
    tipos_todos = list(resultados)
    cols = {}
    for chave, r in resultados.items():
        cols.update(cob.colunas_ponto(r))
    base = pd.concat([pts[["CD_SETOR", "h3", "rural"]].reset_index(drop=True), pd.DataFrame(cols)], axis=1)

    # checagem: atendida + não atendida = população da faixa
    for t in tipos_todos:
        assert np.allclose(base[f"{t}_pop_coberta"] + base[f"{t}_pop_descoberta"], base[f"{t}_pop"])

    # ---------------- 4. Agregações ----------------
    por_setor = cob.agregar(base, "CD_SETOR", tipos_todos)
    set_out = setores[["CD_SETOR", "SITUACAO", "NM_BAIRRO", "pop_total", "geometry"]].merge(por_setor, on="CD_SETOR", how="left")
    por_hex = cob.agregar(base, "h3", tipos_todos)
    por_hex["pop_total"] = base.assign(p=pts["pop_total"].to_numpy()).groupby("h3")["p"].sum().reindex(por_hex["h3"]).to_numpy()
    por_hex = cob.indice_prioridade(por_hex, tipos, P["prioridade"]["pesos"])
    geoms = [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in por_hex["h3"]]
    hex_out = gpd.GeoDataFrame(por_hex, geometry=geoms, crs=CRS_GEO).to_crs(crs_metrico())

    # ---------------- 5. Sugestões ----------------
    print("Sugerindo locais…")
    cent = [h3.cell_to_latlng(c) for c in por_hex["h3"]]
    cand = gpd.GeoSeries(gpd.points_from_xy([c[1] for c in cent], [c[0] for c in cent]), crs=CRS_GEO).to_crs(crs_metrico())
    cand_xy = np.column_stack([cand.x, cand.y])
    sug = []
    for t in tipos:
        rp = cob.raios(pts, eqs[t]["raio_m"], fr)
        s = cob.sugerir_locais(t, resultados[t], pts, cand_xy, por_hex["h3"].to_numpy(), rp,
                               int(P["prioridade"]["sugestoes_por_tipo"]),
                               float(P["prioridade"]["ganho_minimo"][t]), tree)
        if len(s):
            s["raio_m"] = eqs[t]["raio_m"]
            sug.append(s)
    sug = pd.concat(sug, ignore_index=True) if sug else pd.DataFrame()
    if len(sug):
        sug = gpd.GeoDataFrame(sug, geometry=gpd.points_from_xy(sug["x"], sug["y"]), crs=crs_metrico())
        bairros = gpd.sjoin(sug[["geometry"]], setores[["NM_BAIRRO", "SITUACAO", "geometry"]], how="left", predicate="within")
        sug["bairro"] = bairros["NM_BAIRRO"].groupby(level=0).first()
        sug["situacao"] = bairros["SITUACAO"].groupby(level=0).first()

    # ---------------- 6. Indicadores municipais ----------------
    mic = inep.ler_microdados()
    mic = mic[mic["em_funcionamento"]]
    ind = {"municipio": m["nome"], "uf": m["uf"], "codigo_ibge": m["codigo_ibge"],
           "populacao": int(setores["pop_total"].sum()), "fator_raio_rural": fr,
           "pesos_prioridade_aplicados": "populacao_nao_atendida 2/3, deficit_capacidade 1/3 (sem IPTU)",
           "tipos": {}}
    for chave, r in resultados.items():
        t = chave.replace("_rede_publica", "")
        cfg = eqs[t]
        d = {
            "rotulo": cfg["rotulo"] + (" – toda a rede pública" if chave != t else ""),
            "raio_m": cfg["raio_m"], "meta": cfg.get("taxa_atendimento_meta", 1.0),
            "pop_faixa": round(float(r.pop_faixa.sum())),
            "pop_coberta": round(float(r.pop_faixa[r.coberto].sum())),
            "pct_coberta": round(cob.pct_coberto(r), 1),
            "pct_coberta_urbana": round(float(100 * r.pop_faixa[r.coberto & ~pts['rural'].to_numpy()].sum()
                                               / max(r.pop_faixa[~pts['rural'].to_numpy()].sum(), 1)), 1),
            "pct_coberta_rural": round(float(100 * r.pop_faixa[r.coberto & pts['rural'].to_numpy()].sum()
                                              / max(r.pop_faixa[pts['rural'].to_numpy()].sum(), 1)), 1),
            "demanda_meta": round(float(r.demanda.sum())),
            "demanda_sem_cobertura": round(float(r.sem_cobertura.sum())),
            "deficit_capacidade_cobertos": round(float(r.deficit_cap.sum())),
            "equipamentos": int(len(r.fac)), "equipamentos_sem_coordenada": int(len(r.sem_coord)),
            "sensibilidade_pct_coberta": sensib[chave],
            "checagem": r.checagem,
        }
        if cfg["fonte_dados"] == "inep":
            col = cfg["capacidade"]
            d["matriculas_por_rede_municipio"] = {k: int(v) for k, v in mic.groupby("dependencia")[col].sum().items()}
            d["matriculas_total_municipio"] = int(mic[col].sum())
            d["matriculas_total_sobre_demanda_meta"] = round(mic[col].sum() / max(r.demanda.sum(), 1), 2)
        else:
            d["equipes"] = int(ubs.loc[ubs["ativa"], "equipes_ab"].sum())
            d["capacidade_pessoas"] = d["equipes"] * cfg["pessoas_por_equipe"]
        ind["tipos"][chave] = d
    ind["checagem_populacao"] = {c: {"pontos": a, "setores": b} for c, (a, b) in chk_pop.items()}

    # ---------------- Gravação ----------------
    SAIDAS.mkdir(parents=True, exist_ok=True)
    set_out.to_parquet(SAIDAS / "cobertura_setores.parquet")
    hex_out.to_parquet(SAIDAS / "cobertura_hex.parquet")
    if facs:
        gpd.GeoDataFrame(pd.concat(facs, ignore_index=True), crs=crs_metrico()).to_parquet(SAIDAS / "equipamentos_capacidade.parquet")
    if len(sug):
        sug.to_parquet(SAIDAS / "sugestoes_novos.parquet")
    (SAIDAS / "indicadores.json").write_text(json.dumps(ind, ensure_ascii=False, indent=2, default=float), encoding="utf-8")

    desenhar(hex_out, limite, facs, sug, eqs, SAIDAS / "cobertura_mapa.png")
    resumo(ind, sug, facs, SAIDAS / "resumo_cobertura.md")
    print((SAIDAS / "resumo_cobertura.md").read_text(encoding="utf-8"))
    return 0


def resumo(ind, sug, facs, destino: Path) -> None:
    L = [f"# Cobertura de equipamentos – {ind['municipio']}/{ind['uf']}\n",
         f"População: {fmt(ind['populacao'])} · fator de raio rural: {ind['fator_raio_rural']:g}× · "
         "cobertura por raio em linha reta (distância caminhável fica para a fase 2).\n",
         "## Cobertura e capacidade\n",
         "| Equipamento | Raio | População da faixa | Coberta | Urbana | Rural | Demanda-meta | Sem cobertura | Déficit de capacidade (cobertos) |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for d in ind["tipos"].values():
        L.append(f"| {d['rotulo']} | {d['raio_m']} m | {fmt(d['pop_faixa'])} | {fmt(d['pct_coberta'], 1)}% | "
                 f"{fmt(d['pct_coberta_urbana'], 1)}% | {fmt(d['pct_coberta_rural'], 1)}% | {fmt(d['demanda_meta'])} | "
                 f"{fmt(d['demanda_sem_cobertura'])} | {fmt(d['deficit_capacidade_cobertos'])} |")
    L += ["", "*Demanda-meta* = população da faixa × meta de atendimento (creche 50%). *Sem cobertura* = demanda fora "
          "de qualquer raio. *Déficit de capacidade* = demanda dentro de algum raio que a capacidade instalada "
          "(matrículas/equipes) não alcança, pelo método 2SFCA. As duas parcelas não se sobrepõem.\n",
          "## Matrículas no município × demanda (todas as redes, sem considerar localização)\n",
          "| Etapa | Demanda-meta | Municipal | Estadual | Federal | Privada | Total / demanda |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k, d in ind["tipos"].items():
        if "matriculas_por_rede_municipio" in d and not k.endswith("_rede_publica"):
            r = d["matriculas_por_rede_municipio"]
            L.append(f"| {d['rotulo']} | {fmt(d['demanda_meta'])} | {fmt(r.get('Municipal', 0))} | {fmt(r.get('Estadual', 0))} | "
                     f"{fmt(r.get('Federal', 0))} | {fmt(r.get('Privada', 0))} | {fmt(d['matriculas_total_sobre_demanda_meta'], 2)} |")
    L += ["", "Escolas privadas (sem coordenadas no Catálogo) atendem parte da demanda e **não entram** no mapa de cobertura.\n",
          "## Sensibilidade ao raio (% da população da faixa coberta)\n",
          "| Equipamento | 0,5× raio | raio atual | 1,5× raio |", "|---|---:|---:|---:|"]
    for d in ind["tipos"].values():
        s = d["sensibilidade_pct_coberta"]
        L.append(f"| {d['rotulo']} | {fmt(s['0.5x'], 1)}% | {fmt(s['1x'], 1)}% | {fmt(s['1.5x'], 1)}% |")
    L += ["", "## Sugestões de áreas para novos equipamentos\n",
          "Hexágonos H3 (~0,1 km²), escolhidos em sequência: cada um é o que alcança, com o raio do tipo, a maior "
          "demanda ainda não resolvida. São **áreas para estudo**, não endereços.\n",
          "| Tipo | Ordem | Bairro | Situação | Demanda absorvida | dos quais sem cobertura hoje |", "|---|---:|---|---|---:|---:|"]
    if len(sug):
        for r in sug.itertuples():
            bairro = r.bairro if isinstance(r.bairro, str) and r.bairro.strip() else "(setor sem bairro no IBGE)"
            L.append(f"| {ind['tipos'][r.tipo]['rotulo']} | {r.ordem} | {bairro} | {r.situacao} | "
                     f"{fmt(r.demanda_absorvida)} | {fmt(r.demanda_sem_cobertura_absorvida)} |")
    L += ["", "## Conferências\n"]
    for k, d in ind["tipos"].items():
        c = d["checagem"]
        if not c:
            continue
        L.append(f"- **{d['rotulo']}**: 2SFCA consistente = {c['2sfca_consistente']}; capacidade fora da análise: "
                 f"sem coordenada {fmt(c['capacidade_sem_coordenada'])}, sem demanda no raio {fmt(c['capacidade_sem_demanda_no_raio'])}"
                 + (f" ({', '.join(c['equipamentos_sem_demanda_no_raio'])})" if c["equipamentos_sem_demanda_no_raio"] else "")
                 + f"; raio gigante cobre {fmt(d['sensibilidade_pct_coberta']['raio_gigante'], 1)}%.")
    L.append("- População distribuída nos pontos = população dos setores em todas as faixas (verificado).")
    L.append("\n![Mapa de cobertura](cobertura_mapa.png)\n")
    destino.write_text("\n".join(L), encoding="utf-8")


def desenhar(hex_out, limite, facs, sug, eqs, destino: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    tipos = list(eqs)
    fig, axs = plt.subplots(2, 3, figsize=(21, 14))
    fac = pd.concat(facs, ignore_index=True) if facs else pd.DataFrame()
    for ax, t in zip(axs.flat, tipos):
        cor = CORES.get(t, "#444")
        cmap = LinearSegmentedColormap.from_list(t, ["#ffffff", "#f4a6a6", "#c0392b"])
        h = hex_out.copy()
        h["deficit"] = h[f"{t}_demanda_sem_cobertura"] + h[f"{t}_deficit_capacidade"]
        limite.plot(ax=ax, color="#f4f4f2", edgecolor="#333", linewidth=0.6)
        h[h["deficit"] > 0.5].plot(ax=ax, column="deficit", cmap=cmap, linewidth=0, legend=True,
                                   legend_kwds={"shrink": 0.5, "label": "demanda não resolvida"})
        f = fac[fac["tipo"] == t] if len(fac) else fac
        if len(f):
            gpd.GeoSeries(f.geometry, crs=hex_out.crs).buffer(eqs[t]["raio_m"]).plot(
                ax=ax, facecolor=cor, alpha=0.12, edgecolor=cor, linewidth=0.6)
            gpd.GeoSeries(f.geometry, crs=hex_out.crs).plot(ax=ax, color=cor, markersize=14, edgecolor="white", linewidth=0.4)
        s = sug[sug["tipo"] == t] if len(sug) else sug
        if len(s):
            s.plot(ax=ax, marker="*", color="black", markersize=180)
            for r in s.itertuples():
                ax.annotate(str(r.ordem), (r.x, r.y), xytext=(6, 6), textcoords="offset points", fontsize=10, weight="bold")
        ax.set_title(f"{eqs[t]['rotulo']} – raio {eqs[t]['raio_m']} m", fontsize=12)
        ax.set_axis_off()
    ax = axs.flat[len(tipos)]
    limite.plot(ax=ax, color="#f4f4f2", edgecolor="#333", linewidth=0.6)
    hex_out[hex_out["prioridade_geral"] > 1].plot(ax=ax, column="prioridade_geral", cmap="magma_r", linewidth=0,
                                                  legend=True, legend_kwds={"shrink": 0.5, "label": "índice 0–100"})
    ax.set_title("Prioridade geral (média dos tipos)", fontsize=12)
    ax.set_axis_off()
    fig.suptitle("Cobertura por raio: círculos = raio de cada equipamento · vermelho = demanda não resolvida · ★ = área sugerida",
                 fontsize=14)
    fig.tight_layout()
    fig.savefig(destino, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
