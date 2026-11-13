"""Baixa as fontes públicas brutas de um município para dados/brutos/.

Uso:  python backend/scripts/baixar_dados.py --municipio CÓDIGO

Arquivos já baixados não são baixados de novo. Nacionais (grandes, compartilhados
entre municípios) ficam em dados/brutos/{ibge,inep,cnes}/; por estado em
dados/brutos/uf/{UF}/; do município em dados/brutos/municipios/{código}/.
"""
from __future__ import annotations

import ftplib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests  # noqa: E402
import truststore  # noqa: E402

from backend.app.config import BRUTOS, RAIZ, Municipio, municipio_cli  # noqa: E402

# Usa o repositório de certificados do sistema: o servidor do INEP não envia a
# cadeia intermediária completa e o Python puro recusa a conexão.
truststore.inject_into_ssl()

IBGE_SET = "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios"
CNEFE = ("https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/"
         "Censo_Demografico_2022/Arquivos_CNEFE/CSV/Municipio")
GEOFTP = ("https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/"
          "malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022")
DATASUS_FTP, DATASUS_EP = "ftp.datasus.gov.br", "/dissemin/publicos/CNES/200508_/Dados/EP"

NACIONAIS = {
    # Agregados por setor (CSV nacional, lido direto do zip)
    "ibge/agregados_demografia_BR.zip": f"{IBGE_SET}/Agregados_por_Setor_csv/Agregados_por_setores_demografia_BR.zip",
    "ibge/agregados_basico_BR.zip": f"{IBGE_SET}/Agregados_por_Setor_csv/Agregados_por_setores_basico_BR_20260520.zip",
    "ibge/dicionario_agregados_setores.xlsx": f"{IBGE_SET}/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx",
    # Área efetivamente domiciliada por setor (refina densidade)
    "ibge/area_domiciliada_setores.xlsx": f"{GEOFTP}/Area_efetivamente_domiciliada_e_densidade_ajustada_dos_Setores_Censitarios.xlsx",
    "ibge/dicionario_cnefe.xls": f"{CNEFE.rsplit('/', 1)[0]}/Dicionario_CNEFE_Censo_2022.xls",
    # INEP – microdados do Censo Escolar (matrículas por etapa e endereço das escolas)
    "inep/microdados_censo_escolar_2024.zip": "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip",
    # CNES – cadastro nacional completo (a API por município devolve lista incompleta)
    "cnes/cnes_estabelecimentos_BR.zip": "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/CNES/cnes_estabelecimentos.zip",
}


def baixar(url: str, destino: Path) -> None:
    if destino.exists() and destino.stat().st_size > 0:
        print(f"  já existe: {destino.relative_to(RAIZ)}")
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".part")
    print(f"  baixando {url}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for bloco in r.iter_content(1 << 20):
                f.write(bloco)
    tmp.replace(destino)
    print(f"    ok ({destino.stat().st_size / 1e6:.1f} MB)")


def url_cnefe(m: Municipio) -> str:
    """O nome do arquivo leva o nome do município sem acento ("2706307_PALMEIRA_DOS_INDIOS.zip");
    em vez de adivinhar, procura na listagem da pasta do estado."""
    pasta = f"{CNEFE}/{m.cod[:2]}_{m.uf}/"
    r = requests.get(pasta, timeout=60)
    r.raise_for_status()
    nomes = set(re.findall(rf'href="({m.cod}_[^"/]+\.zip)"', r.text))
    if len(nomes) != 1:
        raise RuntimeError(f"CNEFE: esperava 1 arquivo {m.cod}_*.zip em {pasta}, achei {sorted(nomes)}")
    return pasta + nomes.pop()


def baixar_equipes_cnes(m: Municipio) -> None:
    """Arquivo de equipes (EP) mais recente do estado, no FTP do DATASUS."""
    if list(m.brutos_uf.glob(f"cnes_EP{m.uf}*.dbc")):
        print(f"  já existe: equipes CNES de {m.uf}")
        return
    with ftplib.FTP(DATASUS_FTP, timeout=120) as ftp:
        ftp.login()
        ftp.cwd(DATASUS_EP)
        nomes = sorted(n for n in ftp.nlst() if re.fullmatch(rf"EP{m.uf}\d{{4}}\.dbc", n, re.I))
        if not nomes:
            raise RuntimeError(f"Sem arquivo EP{m.uf}*.dbc no DATASUS")
        nome = nomes[-1]
        m.brutos_uf.mkdir(parents=True, exist_ok=True)
        destino = m.brutos_uf / f"cnes_{nome}"
        print(f"  baixando ftp://{DATASUS_FTP}{DATASUS_EP}/{nome}")
        with open(destino, "wb") as f:
            ftp.retrbinary(f"RETR {nome}", f.write)


def arquivos_do_municipio(m: Municipio) -> dict[Path, str]:
    return {
        # Malha de setores com atributos básicos (população, domicílios) – por estado
        m.brutos_uf / "setores.gpkg": f"{IBGE_SET}/malha_com_atributos/setores/gpkg/UF/{m.uf}/{m.uf}_setores_CD2022.gpkg",
        # CNEFE: endereços do município com coordenadas
        m.brutos / "cnefe.zip": url_cnefe(m),
        # SIDRA 9514 – população por idade simples do município (para quebrar as
        # faixas quinquenais dos setores em 0–3, 4–5, 6–10, 11–14)
        m.brutos / "sidra_9514.json": (
            f"https://apisidra.ibge.gov.br/values/t/9514/n6/{m.cod}/v/93/p/2022/c2/6794/c287/all/c286/113635"),
    }


def baixar_municipio(m: Municipio) -> None:
    print(f"Município: {m.nome}/{m.uf} ({m.cod})")
    for rel, url in NACIONAIS.items():
        baixar(url, BRUTOS / rel)
    for destino, url in arquivos_do_municipio(m).items():
        baixar(url, destino)
    baixar_equipes_cnes(m)


def main() -> int:
    m, _ = municipio_cli(descricao=__doc__)
    baixar_municipio(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
