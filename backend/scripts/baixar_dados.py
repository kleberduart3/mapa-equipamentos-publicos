"""Baixa as fontes públicas brutas para dados/brutos/.

Uso:  python backend/scripts/baixar_dados.py

Arquivos já baixados não são baixados de novo. O Catálogo de Escolas do INEP
(coordenadas das escolas) é exportado manualmente pelo portal inepdata — ver
docs/fontes.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import truststore
import requests
import yaml

# Usa o repositório de certificados do Windows: o servidor do INEP não envia a
# cadeia intermediária completa e o Python puro recusa a conexão.
truststore.inject_into_ssl()

RAIZ = Path(__file__).resolve().parents[2]
BRUTOS = RAIZ / "dados" / "brutos"
CFG = yaml.safe_load((RAIZ / "config" / "parametros.yaml").read_text(encoding="utf-8"))
COD_IBGE = CFG["municipio"]["codigo_ibge"]          # 7 dígitos, ex.: 2700300
COD_IBGE6 = COD_IBGE[:6]                            # DATASUS usa 6 dígitos
UF = CFG["municipio"]["uf"]
NOME = CFG["municipio"]["nome"].upper()
COD_UF = COD_IBGE[:2]

IBGE_SET = "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios"
CNEFE = "https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/Censo_Demografico_2022"
GEOFTP = ("https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/"
          "malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022")

ARQUIVOS = {
    # Malha de setores com atributos básicos (população, domicílios)
    "ibge/setores_uf.gpkg": f"{IBGE_SET}/malha_com_atributos/setores/gpkg/UF/{UF}/{UF}_setores_CD2022.gpkg",
    # Agregados por setor (CSV nacional, lido direto do zip)
    "ibge/agregados_demografia_BR.zip": f"{IBGE_SET}/Agregados_por_Setor_csv/Agregados_por_setores_demografia_BR.zip",
    "ibge/agregados_basico_BR.zip": f"{IBGE_SET}/Agregados_por_Setor_csv/Agregados_por_setores_basico_BR_20260520.zip",
    "ibge/dicionario_agregados_setores.xlsx": f"{IBGE_SET}/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx",
    # Área efetivamente domiciliada por setor (refina densidade)
    "ibge/area_domiciliada_setores.xlsx": f"{GEOFTP}/Area_efetivamente_domiciliada_e_densidade_ajustada_dos_Setores_Censitarios.xlsx",
    # CNEFE: endereços do município com coordenadas
    "ibge/cnefe_municipio.zip": f"{CNEFE}/Arquivos_CNEFE/CSV/Municipio/{COD_UF}_{UF}/{COD_IBGE}_{NOME}.zip",
    "ibge/dicionario_cnefe.xls": f"{CNEFE}/Arquivos_CNEFE/CSV/Dicionario_CNEFE_Censo_2022.xls",
    # INEP – microdados do Censo Escolar (matrículas por etapa)
    "inep/microdados_censo_escolar_2024.zip": "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip",
    # CNES – cadastro nacional completo (a API por município devolve lista incompleta)
    "cnes/cnes_estabelecimentos_BR.zip": "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/CNES/cnes_estabelecimentos.zip",
    # SIDRA 9514 – população por idade simples do município (para quebrar as
    # faixas quinquenais dos setores em 0–3, 4–5, 6–10, 11–14)
    "ibge/sidra_9514_idade_simples.json": (
        f"https://apisidra.ibge.gov.br/values/t/9514/n6/{COD_IBGE}/v/93/p/2022/c2/6794/c287/all/c286/113635"
    ),
}


def baixar(url: str, destino: Path) -> None:
    if destino.exists() and destino.stat().st_size > 0:
        print(f"  já existe: {destino.relative_to(RAIZ)}")
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".part")
    print(f"  baixando {url}")
    with requests.get(url, stream=True, timeout=120, verify=True) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for bloco in r.iter_content(1 << 20):
                f.write(bloco)
    tmp.replace(destino)
    print(f"    ok ({destino.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    print(f"Município: {CFG['municipio']['nome']} ({COD_IBGE})")
    for rel, url in ARQUIVOS.items():
        baixar(url, BRUTOS / rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
