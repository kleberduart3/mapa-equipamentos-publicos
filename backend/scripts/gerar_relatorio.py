"""Etapa 5 – gera o relatório PDF.

Uso:  python backend/scripts/gerar_relatorio.py [--creche 600] [--ubs 1200] [--modo rede] [--saida caminho.pdf]
Sem argumentos, usa os raios de config/parametros.yaml. Saída padrão: dados/saidas/relatorio_<municipio>_<data>.pdf
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.config import parametros  # noqa: E402
from backend.app.relatorio.gerar import gerar_pdf  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    for t in parametros()["equipamentos"]:
        ap.add_argument(f"--{t}", type=int, help=f"raio (m) para {t}")
    ap.add_argument("--modo", choices=["reta", "rede"], default=parametros().get("distancia_padrao", "reta"),
                    help="distância em linha reta ou a pé pelas ruas")
    ap.add_argument("--saida", type=Path)
    a = ap.parse_args()
    raios = {t: getattr(a, t) for t in parametros()["equipamentos"] if getattr(a, t)}
    print("Gerando relatório…")
    print(gerar_pdf(a.saida, raios, a.modo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
