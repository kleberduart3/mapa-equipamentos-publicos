"""Fase 2 – compara a cobertura em linha reta × a pé pelas ruas.

    python backend/scripts/comparar_distancias.py
Gera dados/saidas/comparacao_distancias.md e .json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

from backend.app.analise import cobertura as cob  # noqa: E402
from backend.app.analise.contexto import base  # noqa: E402
from backend.app.analise.rede import diagnostico_ligacao  # noqa: E402
from backend.app.config import SAIDAS, parametros  # noqa: E402


def main() -> None:
    t0 = time.time()
    b, P = base(), parametros()
    rural = b.pts["rural"].to_numpy()
    med = {m: b.medidor(m) for m in ("reta", "rede")}
    print(f"carga + ligação à rede: {time.time() - t0:.1f} s")
    pop = b.pts["pop_total"].to_numpy(float)
    lig = diagnostico_ligacao(med["rede"].lig, pop, rural)

    linhas, out = [], {"ligacao_a_rede": lig, "malha_km": round(b.rede.km), "tipos": {}}
    for t, cfg in P["equipamentos"].items():
        fac, sem = cob.ofertas(t, cfg, b.escolas, b.ubs)
        rp = cob.raios(b.pts, cfg["raio_m"], b.fr)
        o = {}
        for m, md in med.items():
            t1 = time.time()
            r = cob.calcular(t, cfg, b.pts, fac, sem, b.fr, tree=b.tree, medidor=md)
            t_cal = time.time() - t1
            t1 = time.time()
            sug = cob.sugerir_locais(t, r, b.pts, b.cand_xy, b.hex_ids, rp, int(P["prioridade"]["sugestoes_por_tipo"]),
                                     float(P["prioridade"]["ganho_minimo"][t]), b.tree, medidor=md)
            t_sug = time.time() - t1
            pf = r.pop_faixa
            o[m] = {
                "pct": cob.pct_coberto(r),
                "pct_urb": 100 * pf[r.coberto & ~rural].sum() / max(pf[~rural].sum(), 1),
                "pct_rur": 100 * pf[r.coberto & rural].sum() / max(pf[rural].sum(), 1),
                "pop_desc": float(pf[~r.coberto].sum()), "def_cap": float(r.deficit_cap.sum()),
                "seg_calculo": round(t_cal, 2), "seg_sugestoes": round(t_sug, 2),
                "violacoes": r.checagem.get("pares_a_pe_menores_que_linha_reta", 0) + (md.violacoes if m == "rede" else 0),
                "2sfca_ok": r.checagem["2sfca_consistente"], "sugestoes": len(sug),
            }
        out["tipos"][t] = o
        a, p = o["reta"], o["rede"]
        linhas.append(f"| {cfg['rotulo'].split(' (')[0]} | {cfg['raio_m']} m | {a['pct']:.0f}% | {p['pct']:.0f}% | "
                      f"{a['pct_urb']:.0f}% → {p['pct_urb']:.0f}% | {a['pct_rur']:.0f}% → {p['pct_rur']:.0f}% | "
                      f"{a['pop_desc']:,.0f} → {p['pop_desc']:,.0f} | {p['seg_calculo']:.1f} + {p['seg_sugestoes']:.1f} s |"
                      .replace(",", "."))
        print(t, json.dumps(o, default=float))

    viol = sum(o["rede"]["violacoes"] for o in out["tipos"].values())
    ok2 = all(o[m]["2sfca_ok"] for o in out["tipos"].values() for m in o)
    md = ["# Cobertura: linha reta × a pé pelas ruas", "",
          f"Malha de pedestres do OpenStreetMap: {b.rede.km:,.0f} km de vias, {b.rede.n:,} nós.".replace(",", "."), "",
          "| Equipamento | Raio | Linha reta | A pé | Urbana | Rural | Fora do raio (pessoas da faixa) | Tempo (a pé) |",
          "|---|---|---|---|---|---|---|---|", *linhas, "",
          "## Ligação dos endereços à rede", "",
          "Trecho em linha reta que cada morador anda até a via mapeada mais próxima (ponderado pela população):", "",
          "| Zona | Mediana | 90% até | População a mais de 200 m | a mais de 500 m |", "|---|---|---|---|---|"]
    for z, d in lig.items():
        md.append(f"| {z} | {d['mediana_m']:.0f} m | {d['p90_m']:.0f} m | {d['pct_pop_acima_200m']:.1f}% | {d['pct_pop_acima_500m']:.1f}% |")
    md += ["", "## Conferências", "",
           f"- Pares com distância a pé menor que a linha reta: **{viol}** (deve ser 0).",
           f"- 2SFCA consistente em todos os cálculos: **{'sim' if ok2 else 'NÃO'}**."]
    (SAIDAS / "comparacao_distancias.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (SAIDAS / "comparacao_distancias.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print("\n".join(md))
    print(f"total {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
