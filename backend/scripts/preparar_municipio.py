"""Etapa 2 – limpa e padroniza os dados do município em dados/processados/.

Uso:  python backend/scripts/preparar_municipio.py --municipio CÓDIGO

Saídas em dados/processados/{código}/ (GeoParquet, SIRGAS 2000 / UTM do município):
  meta.json             CRS métrico (zona UTM estimada pelo limite, se não fixada no YAML)
  setores.parquet       setores com população total e por faixa etária
  limite.parquet        limite municipal (união dos setores)
  enderecos.parquet     endereços residenciais do CNEFE (para distribuir população)
  escolas.parquet       escolas públicas com matrículas por etapa
  ubs.parquet           UBS/postos municipais com nº de equipes
e um relatório de conferência em dados/saidas/{código}/checagem_dados.md + mapa PNG.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402

from backend.app.config import CRS_GEO, Municipio, municipio_cli  # noqa: E402
from backend.app.ingestao import cnes, ibge, inep  # noqa: E402


def definir_crs(m: Municipio) -> str:
    """Zona UTM (SIRGAS 2000) que contém o município, gravada em meta.json.
    Se o YAML do município fixa crs_metrico, vale o do YAML."""
    set_geo = ibge.ler_setores(m, crs=CRS_GEO)
    crs = m._crs or set_geo.estimate_utm_crs(datum_name="SIRGAS 2000").to_string()
    m.processados.mkdir(parents=True, exist_ok=True)
    m.meta_arq.write_text(json.dumps({"crs_metrico": crs}, indent=1), encoding="utf-8")
    return crs


def main() -> int:
    m, _ = municipio_cli(descricao=__doc__)
    m.processados.mkdir(parents=True, exist_ok=True)
    m.saidas.mkdir(parents=True, exist_ok=True)
    rel: list[str] = [f"# Conferência dos dados – {m.nome}/{m.uf} ({m.cod})\n"]

    # ---------------- Setores e população ----------------
    print("Setores…")
    crs = definir_crs(m)
    rel.append(f"- Sistema de coordenadas métrico: {crs}\n")
    set_ = ibge.ler_setores(m)
    faixas = ibge.populacao_por_faixa(m, set_["CD_SETOR"])
    set_ = set_.merge(faixas, on="CD_SETOR", how="left")
    for c in ibge.FAIXAS_DEMANDA:
        set_[c] = set_[c].fillna(0).round(1)
    idades = ibge.idade_simples_municipio(m)
    limite = gpd.GeoDataFrame({"municipio": [m.nome]}, geometry=[set_.union_all()], crs=set_.crs)

    pop_setores = int(set_["pop_total"].sum())
    rel += ["## População (Censo 2022)\n",
            f"- Setores: **{len(set_)}** ({(set_.SITUACAO == 'Urbana').sum()} urbanos, "
            f"{(set_.SITUACAO != 'Urbana').sum()} rurais)",
            f"- Soma da população dos setores: **{pop_setores:,}**".replace(",", "."),
            f"- Área do município: {limite.area.iloc[0] / 1e6:,.1f} km²".replace(",", "X").replace(".", ",").replace("X", "."),
            f"- População urbana: {int(set_.loc[set_.SITUACAO == 'Urbana', 'pop_total'].sum()):,}".replace(",", "."),
            "", "Faixas de demanda (estimadas: faixas quinquenais dos setores × distribuição por idade simples do município, SIDRA 9514):", "",
            "| Faixa | Soma nos setores | Idade simples do município | Diferença |", "|---|---:|---:|---:|"]
    for faixa, (a, b) in ibge.FAIXAS_DEMANDA.items():
        s, ref = set_[faixa].sum(), idades.loc[a:b].sum()
        rel.append(f"| {a}–{b} anos | {s:,.0f} | {ref:,} | {100 * (s - ref) / ref:+.1f}% |".replace(",", "."))
    sem_pop = (set_["pop_total"] == 0).sum()
    rel.append(f"\n- Setores sem população (áreas não residenciais ou sigilo): {sem_pop}\n")

    # ---------------- CNEFE ----------------
    print("CNEFE…")
    cn = ibge.ler_cnefe(m)
    cn["especie"] = cn["COD_ESPECIE"].map(ibge.ESPECIE)
    res = cn[cn["COD_ESPECIE"].isin(["1", "2"])][["COD_UNICO_ENDERECO", "especie", "NV_GEO_COORD", "geometry"]]
    # O CNEFE traz códigos de setor preliminares (sufixo "P"), renumerados na
    # malha final; por isso o setor de cada endereço vem da posição do ponto.
    res = gpd.sjoin(res, set_[["CD_SETOR", "geometry"]], how="left", predicate="within").drop(columns="index_right")
    fora = res["CD_SETOR"].isna().sum()
    res = res.dropna(subset=["CD_SETOR"])
    por_setor = res.groupby("CD_SETOR").size()
    set_["enderecos_residenciais"] = set_["CD_SETOR"].map(por_setor).fillna(0).astype(int)
    sem_end = set_[(set_["pop_total"] > 0) & (set_["enderecos_residenciais"] == 0)]
    rel += ["## Endereços (CNEFE 2022)\n",
            f"- Endereços com coordenada: **{len(cn):,}**".replace(",", "."),
            f"- Residenciais (domicílios particulares e coletivos): **{len(res):,}**".replace(",", "."),
            f"- Residenciais descartados por cair fora de qualquer setor: {fora}",
            f"- Setores com população mas sem endereço residencial no CNEFE: {len(sem_end)} "
            f"({int(sem_end['pop_total'].sum())} pessoas) – nesses a população fica uniforme no setor.",
            "- Nível de precisão da coordenada (NV_GEO_COORD): " +
            ", ".join(f"{k}: {v:,}".replace(",", ".") for k, v in res["NV_GEO_COORD"].value_counts().sort_index().items()) + "\n"]

    # ---------------- Escolas ----------------
    print("Escolas…")
    esc = inep.montar_escolas(m, cn)
    esc["dentro_municipio"] = esc.geometry.within(limite.geometry.iloc[0].buffer(50))
    mun = esc[(esc["dependencia"] == "Municipal") & esc["em_funcionamento"]]
    mic = inep.ler_microdados(m)
    mic_mun = mic[(mic["dependencia"] == "Municipal") & mic["em_funcionamento"]]
    fora_catalogo = mic_mun[~mic_mun["codigo_inep"].isin(esc["codigo_inep"])]
    origem = ("Catálogo de Escolas (exportação manual)" if inep.tem_catalogo(m)
              else "microdados do Censo Escolar, geocodificadas pelo CNEFE")
    rel += ["## Escolas e creches (INEP)\n",
            f"- Fonte das escolas: {origem}",
            f"- Escolas públicas: {len(esc)} — municipais em funcionamento: **{len(mun)}**",
            f"- Matrículas da rede municipal (Censo Escolar {int(mic['ano_censo_escolar'].iloc[0])}): "
            + "; ".join(f"{rot} {int(mun[c].sum()):,}".replace(",", ".") for rot, c in [
                ("creche", "mat_creche"), ("pré-escola", "mat_pre_escola"),
                ("fundamental anos iniciais", "mat_fund_iniciais"), ("anos finais", "mat_fund_finais")]),
            f"- Escolas municipais que oferecem: creche {mun['oferta_creche'].sum()}, pré-escola {mun['oferta_pre_escola'].sum()}, "
            f"fund. iniciais {mun['oferta_fund_iniciais'].sum()}, fund. finais {mun['oferta_fund_finais'].sum()}",
            "- Origem das coordenadas (municipais em funcionamento): " +
            ", ".join(f"{k}: {v}" for k, v in mun["fonte_coord"].value_counts().items()),
            f"- Fora do limite municipal: {(~esc['dentro_municipio'] & esc['latitude'].notna()).sum()}",
            f"- Municipais em funcionamento no Censo Escolar mas ausentes do Catálogo: {len(fora_catalogo)}"]
    com_matricula = esc[list(inep.MAT.values())].sum(axis=1) > 0
    conferidas = esc[(esc["fonte_coord"] == "cnefe_nome_no_cep") & com_matricula]
    if len(conferidas):
        rel += ["", "Coordenadas obtidas do CNEFE com **nome conferido no mesmo CEP** (aceitas):", "",
                "| INEP | Escola (INEP) | Estabelecimento no CNEFE |", "|---|---|---|"]
        rel += [f"| {r.codigo_inep} | {r.escola} | {r.cnefe_nome_conferido} |" for r in conferidas.itertuples()]
    conferir = esc[esc["fonte_coord"].isin(["cnefe_nome_municipio", "cnefe_cep_numero", "cnefe_centroide_cep", "sem_coordenada"])
                   & esc["em_funcionamento"] & com_matricula]
    if len(conferir):
        rel += ["", "Escolas com localização aproximada ou ausente – **conferir com a Secretaria de Educação**:", "",
                "| INEP | Escola | Situação da coordenada | Referência usada |", "|---|---|---|---|"]
        rel += [f"| {r.codigo_inep} | {r.escola} | {r.fonte_coord} | {r.cnefe_nome_conferido or ''} |"
                for r in conferir.itertuples()]
    rel.append("")

    # ---------------- UBS ----------------
    print("UBS…")
    ubs = cnes.montar_ubs(m, cn)
    ubs["dentro_municipio"] = ubs.geometry.within(limite.geometry.iloc[0].buffer(50))
    at = ubs[ubs["ativa"]]
    rel += ["## Unidades básicas de saúde (CNES)\n",
            f"- UBS/postos municipais ativos: **{len(at)}** (desativados no cadastro: {(~ubs['ativa']).sum()})",
            f"- Equipes de atenção básica ativas (eSF/eAP, competência {at['competencia_equipes'].dropna().iloc[0] if at['competencia_equipes'].notna().any() else '?'}): **{at['equipes_ab'].sum()}**",
            f"- População por equipe: {pop_setores / max(at['equipes_ab'].sum(), 1):,.0f} hab.".replace(",", "."),
            f"- UBS ativas sem equipe vinculada: {(at['equipes_ab'] == 0).sum()}",
            "- UBS com equipes que não constam do cadastro aberto de estabelecimentos (localização aproximada): "
            + (", ".join(f"{r.nome} – CNES {r.cnes}, {r.equipes_ab} eq., {r.fonte_coord}"
                         for r in at[at['fonte_coord'] != 'cnes'].itertuples()) or "nenhuma"),
            f"- Sem coordenada: {(at['fonte_coord'] == 'sem_coordenada').sum()} — fora do limite: "
            + (", ".join(f"{r.nome} ({limite.geometry.iloc[0].distance(r.geometry):,.0f} m)"
                         for r in at[~at['dentro_municipio'] & at['lat'].notna()].itertuples()) or "nenhuma") + "\n"]

    # ---------------- Gravação ----------------
    set_.to_parquet(m.processados / "setores.parquet")
    limite.to_parquet(m.processados / "limite.parquet")
    res.to_parquet(m.processados / "enderecos.parquet")
    esc.to_parquet(m.processados / "escolas.parquet")
    ubs.to_parquet(m.processados / "ubs.parquet")

    mapa = m.saidas / "checagem_mapa.png"
    desenhar_mapa(set_, limite, esc, ubs, mapa)
    rel.append(f"![Mapa de conferência]({mapa.name})\n")
    (m.saidas / "checagem_dados.md").write_text("\n".join(rel), encoding="utf-8")

    print("\n".join(rel))
    return 0


def desenhar_mapa(set_, limite, esc, ubs, destino: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(1, 2, figsize=(16, 9))
    for ax, titulo in zip(axs, ["Município", "Sede urbana"]):
        dens = set_["pop_total"] / (set_.area / 1e6)
        set_.assign(dens=dens).plot(ax=ax, column="dens", cmap="Greys", scheme="quantiles", k=6,
                                    edgecolor="#bbb", linewidth=0.2, legend=(ax is axs[0]),
                                    legend_kwds={"title": "hab/km²", "loc": "lower left", "fontsize": 7})
        limite.boundary.plot(ax=ax, color="black", linewidth=0.8)
        e = esc[(esc["dependencia"] == "Municipal") & esc["em_funcionamento"] & ~esc.geometry.is_empty]
        e[e["oferta_creche"] | e["oferta_pre_escola"]].plot(ax=ax, color="#e8a33d", markersize=18, label="Ed. infantil (municipal)")
        e[e["oferta_fund_iniciais"] | e["oferta_fund_finais"]].plot(ax=ax, color="#2f6db5", markersize=10, marker="s", label="Fundamental (municipal)")
        aprox = e[e["fonte_coord"] != "inep_catalogo"]
        if len(aprox):
            aprox.plot(ax=ax, facecolor="none", edgecolor="red", markersize=60, linewidth=1, label="Coordenada estimada (CNEFE)")
        u = ubs[ubs["ativa"] & ~ubs.geometry.is_empty]
        u.plot(ax=ax, color="#2a9d5c", marker="P", markersize=40, label="UBS")
        ax.set_title(titulo)
        ax.set_axis_off()
    # Recorte da sede: setores urbanos entre os quantis 10–90% das coordenadas
    c = set_[set_["SITUACAO"] == "Urbana"].centroid
    x0, x1 = c.x.quantile([0.10, 0.90])
    y0, y1 = c.y.quantile([0.10, 0.90])
    pad = 1200
    axs[1].set_xlim(x0 - pad, x1 + pad)
    axs[1].set_ylim(y0 - pad, y1 + pad)
    axs[1].set_title("Sede urbana")
    axs[1].legend(loc="lower right", fontsize=8)
    fig.suptitle("Conferência – setores (densidade), escolas municipais e UBS", fontsize=13)
    fig.tight_layout()
    fig.savefig(destino, dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
