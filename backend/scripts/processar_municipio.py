"""Coloca um município novo no ar (ou reprocessa um existente), do começo ao fim.

    python backend/scripts/processar_municipio.py CÓDIGO_IBGE [--sem-rede] [--etapas baixar,preparar,...]

Etapas, em ordem:
  config    cria config/municipios/{código}.yaml (nome e UF pela API de localidades do IBGE)
  baixar    fontes públicas (IBGE, INEP, CNES)                  – baixar_dados.py
  preparar  limpeza, CRS, escolas geocodificadas, conferência   – preparar_municipio.py
  cobertura indicadores e áreas prioritárias (linha reta)       – calcular_cobertura.py
  rede      malha a pé do OpenStreetMap                         – preparar_rede.py
  fontes    pasta de conferência: originais, recortes, documentação oficial e hashes – fontes_conferencia.py

Depois, leia dados/saidas/{código}/checagem_dados.md: escolas sem coordenada
precisa e UBS fora do limite precisam de conferência com a prefeitura.
Num servidor em execução, os dados novos aparecem depois de reiniciar a API
(ou na primeira vez que o município for aberto, se ainda não estava em memória).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests  # noqa: E402

from backend.app.config import CONFIG_MUNICIPIOS, RAIZ, cod_valido  # noqa: E402

ETAPAS = ["config", "baixar", "preparar", "cobertura", "rede", "fontes"]
SCRIPTS = {"baixar": "baixar_dados.py", "preparar": "preparar_municipio.py",
           "cobertura": "calcular_cobertura.py", "rede": "preparar_rede.py",
           "fontes": "fontes_conferencia.py"}


def criar_config(cod: str) -> None:
    arq = CONFIG_MUNICIPIOS / f"{cod}.yaml"
    if arq.exists():
        print(f"  já existe: {arq.relative_to(RAIZ)}")
        return
    r = requests.get(f"https://servicodados.ibge.gov.br/api/v1/localidades/municipios/{cod}", timeout=30)
    r.raise_for_status()
    d = r.json()
    if not d:
        raise SystemExit(f"Código IBGE inexistente: {cod}")
    nome = d["nome"]
    uf = d["microrregiao"]["mesorregiao"]["UF"]["sigla"] if d.get("microrregiao") else d["regiao-imediata"]["regiao-intermediaria"]["UF"]["sigla"]
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(
        f"# {nome}/{uf}. Qualquer chave de config/parametros.yaml pode ser substituída\n"
        f"# aqui, dentro de \"parametros:\". O CRS métrico é estimado no preparo.\n"
        f"nome: {nome}\nuf: {uf}\nparametros: {{}}\n", encoding="utf-8")
    print(f"  criado {arq.relative_to(RAIZ)} ({nome}/{uf})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("codigo", help="código IBGE de 7 dígitos")
    ap.add_argument("--etapas", default=",".join(ETAPAS), help="lista separada por vírgulas")
    ap.add_argument("--sem-rede", action="store_true", help="pula a malha a pé (só linha reta)")
    a = ap.parse_args()
    if not cod_valido(a.codigo):
        raise SystemExit("Código IBGE deve ter 7 dígitos")
    etapas = [e.strip() for e in a.etapas.split(",") if e.strip()]
    if a.sem_rede and "rede" in etapas:
        etapas.remove("rede")
    if desconhecidas := set(etapas) - set(ETAPAS):
        raise SystemExit(f"Etapas desconhecidas: {desconhecidas}")
    for e in ETAPAS:
        if e not in etapas:
            continue
        t0 = time.time()
        print(f"\n=== {e} ===", flush=True)
        if e == "config":
            criar_config(a.codigo)
        else:
            script = Path(__file__).parent / SCRIPTS[e]
            subprocess.run([sys.executable, str(script), "--municipio", a.codigo], check=True)
        print(f"=== {e}: {time.time() - t0:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
