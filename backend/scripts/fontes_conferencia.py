"""Monta a pasta de conferência das fontes de um município: originais sem alteração,
recortes do município tirados linha a linha dos arquivos nacionais, documentação oficial
(PDF/XLS) e um índice com link, data e SHA-256 de cada arquivo.

    python backend/scripts/fontes_conferencia.py --municipio CÓDIGO

Resultado em dados/fontes/{código}_{nome}/:
    LEIA-ME.md       índice legível (o que é cada arquivo, de onde veio, para que serve)
    fontes.json      o mesmo índice, para conferência automática
    originais/       arquivos do município exatamente como foram baixados (cópia byte a byte)
    recortes/        linhas do município copiadas sem alteração de valores dos arquivos
                     nacionais (os nacionais inteiros ficam em dados/brutos/, com o hash no índice)
    documentacao/    dicionários de dados, leia-me e notas técnicas oficiais

Para conferir um arquivo: calcule o SHA-256 (Windows: certutil -hashfile ARQUIVO SHA256) e
compare com o do índice; ou baixe de novo pelo link oficial e compare.
"""
from __future__ import annotations

import csv
import ftplib
import hashlib
import io
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests  # noqa: E402
import truststore  # noqa: E402

from backend.app import fontes as F  # noqa: E402
from backend.app.config import BRUTOS, DADOS, RAIZ, Municipio, municipio_cli  # noqa: E402

truststore.inject_into_ssl()
DOCS = BRUTOS / "docs"                      # documentação oficial, baixada uma vez
REGISTRO = BRUTOS / "registro_downloads.json"
CACHE_HASH = BRUTOS / ".hashes.json"


# ------------------------------------------------------------------ utilidades
def sha256(p: Path) -> str:
    """SHA-256 do arquivo, com cache por (tamanho, data) para não reler os grandes."""
    cache = json.loads(CACHE_HASH.read_text("utf-8")) if CACHE_HASH.exists() else {}
    st = p.stat()
    chave = str(p.resolve())
    if chave in cache and cache[chave]["tam"] == st.st_size and cache[chave]["mtime"] == st.st_mtime:
        return cache[chave]["sha256"]
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while bloco := f.read(1 << 20):
            h.update(bloco)
    cache[chave] = {"tam": st.st_size, "mtime": st.st_mtime, "sha256": h.hexdigest()}
    CACHE_HASH.write_text(json.dumps(cache, indent=1), "utf-8")
    return h.hexdigest()


def data_arquivo(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")


def registro() -> dict:
    return json.loads(REGISTRO.read_text("utf-8")) if REGISTRO.exists() else {}


def baixar_doc(doc: dict) -> Path:
    destino = DOCS / doc["arquivo"]
    if destino.exists() and destino.stat().st_size:
        return destino
    DOCS.mkdir(parents=True, exist_ok=True)
    print(f"  documentação: {doc['arquivo']}")
    if doc["tipo"] == "url":
        r = requests.get(doc["url"], timeout=120)
        r.raise_for_status()
        destino.write_bytes(r.content)
    elif doc["tipo"] == "ftp":
        u = urlparse(doc["url"])
        with ftplib.FTP(u.hostname, timeout=120) as ftp:
            ftp.login()
            with open(destino, "wb") as f:
                ftp.retrbinary(f"RETR {u.path}", f.write)
    elif doc["tipo"] == "zip":
        with zipfile.ZipFile(BRUTOS / doc["zip"]) as z:
            membro = next(n for n in z.namelist() if _sem_acento(n).endswith(_sem_acento(doc["membro"])))
            destino.write_bytes(z.read(membro))          # bytes do arquivo dentro do zip, sem alteração
    return destino


def _sem_acento(s: str) -> str:
    """Nomes dentro do zip do INEP vêm em cp437/latin1; compara só o que é ASCII."""
    return re.sub(r"[^A-Za-z0-9._ /-]", "", s)


def recortar_linhas(zip_path: Path, membro_fim: str, coluna: str, valor: str, destino: Path,
                    comeca: bool = False) -> int:
    """Copia, byte a byte, o cabeçalho e as linhas do CSV dentro do zip em que `coluna`
    é igual a `valor` (ou começa com ele). Nenhum valor é reescrito."""
    with zipfile.ZipFile(zip_path) as z:
        membro = next(n for n in z.namelist() if n.endswith(membro_fim))
        with z.open(membro) as f, open(destino, "wb") as out:
            cab = f.readline()
            out.write(cab)
            texto_cab = cab.decode("latin1").strip()
            sep = ";" if texto_cab.count(";") >= texto_cab.count(",") else ","
            nomes = next(csv.reader([texto_cab], delimiter=sep))
            idx = [i for i, n in enumerate(nomes) if n.strip('"').upper() == coluna.upper()]
            if not idx:
                raise ValueError(f"coluna {coluna} não existe em {membro}")
            i = idx[0]
            n = 0
            for linha in f:
                campos = next(csv.reader([linha.decode("latin1")], delimiter=sep))
                if len(campos) <= i:
                    continue
                v = campos[i].strip().strip('"')
                if (v.startswith(valor) if comeca else v == valor):
                    out.write(linha)
                    n += 1
    return n


# ------------------------------------------------------------------ principal
def montar(m: Municipio) -> Path:
    from backend.app.config import municipio  # noqa: F401  (garante a configuração carregada)

    nome_pasta = re.sub(r"[^a-z0-9]+", "_", _ascii(m.nome).lower()).strip("_")
    raiz = DADOS / "fontes" / f"{m.cod}_{nome_pasta}"
    if raiz.exists():
        shutil.rmtree(raiz)
    for sub in ("originais", "recortes", "documentacao"):
        (raiz / sub).mkdir(parents=True)
    reg = registro()
    itens = []

    def item(grupo, caminho: Path, titulo, orgao, origem_url, pagina, uso, como, obtido=None):
        itens.append({
            "grupo": grupo, "arquivo": caminho.relative_to(raiz).as_posix() if caminho.is_relative_to(raiz)
            else caminho.relative_to(RAIZ).as_posix(),
            "titulo": titulo, "orgao": orgao, "url_arquivo": origem_url, "pagina_oficial": pagina,
            "usado_para": uso, "como_foi_obtido": como, "bytes": caminho.stat().st_size, "sha256": sha256(caminho),
            "obtido_em": obtido or data_arquivo(caminho)})

    def url_registrada(rel: str, padrao: str | None) -> str | None:
        return reg.get(rel, {}).get("url", padrao)

    # --- originais do município e do estado (cópia byte a byte) ------------------
    print("Originais…")
    originais = [
        (m.brutos / "cnefe.zip", "CNEFE 2022 – endereços do município (CSV dentro do zip)", "IBGE",
         url_registrada(f"municipios/{m.cod}/cnefe.zip", _url_cnefe(m)), F.PAGINAS["cnefe"],
         "distribuir a população dentro de cada setor e localizar escolas"),
        (m.brutos / "sidra_9514.json", "SIDRA tabela 9514 – população por idade simples (resposta original da API, JSON)", "IBGE",
         url_registrada(f"municipios/{m.cod}/sidra_9514.json",
                        f"https://apisidra.ibge.gov.br/values/t/9514/n6/{m.cod}/v/93/p/2022/c2/6794/c287/all/c286/113635"),
         F.PAGINAS["sidra9514"], "dividir as faixas de 5 anos em 0–3, 4–5, 6–10 e 11–14 anos"),
        (m.brutos / "osm_malha_pe.graphml", "Malha de ruas e caminhos de pedestres (OpenStreetMap, via Overpass)", "OpenStreetMap",
         "https://overpass-api.de/api/interpreter (consulta OSMnx, network_type=walk, limite do município + 2 km)",
         F.PAGINAS["osm"], "distância e tempo a pé pelas ruas"),
        (m.brutos / "inep_catalogo.tsv", "Catálogo de Escolas do INEP (exportação manual do portal)", "INEP",
         "exportado à mão do Catálogo de Escolas (sem API)", F.PAGINAS["catalogo_escolas"], "coordenadas das escolas"),
        (m.brutos / "inep_enderecos.tsv", "Endereços das escolas sem coordenada no Catálogo", "INEP",
         "exportado à mão do Catálogo de Escolas", F.PAGINAS["catalogo_escolas"], "localizar escolas sem coordenada"),
    ]
    for ep in sorted(m.brutos_uf.glob(f"cnes_EP{m.uf}*.dbc")):
        aamm = ep.stem[-4:]
        originais.append((ep, f"CNES – arquivo de equipes (EP) de {m.uf}, competência {aamm[2:]}/20{aamm[:2]}",
                          "Ministério da Saúde / DATASUS",
                          f"{F.DATASUS_FTP}/Dados/EP/{ep.name.removeprefix('cnes_')}", F.PAGINAS["cnes_ftp"],
                          "equipes de Saúde da Família por UBS (capacidade)"))
    for origem, titulo, orgao, url, pagina, uso in originais:
        if not origem.exists():
            continue
        destino = raiz / "originais" / origem.name
        shutil.copy2(origem, destino)
        item("original", destino, titulo, orgao, url, pagina, uso, "cópia byte a byte do arquivo baixado",
             reg.get(origem.relative_to(BRUTOS).as_posix(), {}).get("baixado_em"))

    # --- recortes dos arquivos nacionais (linhas sem alteração) -------------------
    print("Recortes…")
    rec = raiz / "recortes"
    nac = [
        ("ibge/agregados_demografia_BR.zip", "Agregados_por_setores_demografia_BR.csv", "CD_setor", m.cod, True,
         "agregados_demografia_setores.csv", "IBGE", "Censo 2022 – agregados por setor, demografia (idade por faixa)",
         f"{F.IBGE_SET}/Agregados_por_Setor_csv/Agregados_por_setores_demografia_BR.zip", "população por faixa de idade em cada setor"),
        ("ibge/agregados_basico_BR.zip", ".csv", "CD_SETOR", m.cod, True,
         "agregados_basico_setores.csv", "IBGE", "Censo 2022 – agregados por setor, básico (moradores, domicílios)",
         f"{F.IBGE_SET}/Agregados_por_Setor_csv/Agregados_por_setores_basico_BR_20260520.zip", "população total por setor"),
        ("inep/microdados_censo_escolar_2024.zip", "microdados_ed_basica_2024.csv", "CO_MUNICIPIO", m.cod, False,
         "microdados_censo_escolar_2024_escolas.csv", "INEP", "Microdados do Censo Escolar 2024 – escolas do município",
         "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip", "escolas, rede, endereço e matrículas por etapa"),
        ("cnes/cnes_estabelecimentos_BR.zip", "cnes_estabelecimentos.csv", "CO_IBGE", m.cod6, False,
         "cnes_estabelecimentos.csv", "Ministério da Saúde", "CNES – estabelecimentos de saúde do município",
         "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/CNES/cnes_estabelecimentos.zip", "UBS e postos de saúde e suas coordenadas"),
    ]
    for zrel, membro, coluna, valor, comeca, saida, orgao, titulo, url, uso in nac:
        zp = BRUTOS / zrel
        if not zp.exists():
            continue
        destino = rec / saida
        try:
            n = recortar_linhas(zp, membro, coluna, valor, destino, comeca)
        except (ValueError, StopIteration) as e:
            print(f"  aviso: {zrel}: {e}")
            destino.unlink(missing_ok=True)
            continue
        item("recorte", destino, f"{titulo} ({n} linhas)", orgao, url,
             F.PAGINAS["cnes"] if "CNES" in titulo else F.PAGINAS["censo_escolar"] if "Escolar" in titulo else F.PAGINAS["censo2022"],
             uso, f"cabeçalho + linhas com {coluna} {'começando com' if comeca else '='} {valor}, copiadas byte a byte "
                  f"do arquivo nacional (SHA-256 do nacional no índice)")
        item("nacional", zp, f"Arquivo nacional completo: {zp.name}", orgao, url,
             None, "origem do recorte acima", "arquivo baixado sem alteração, guardado em dados/brutos/",
             reg.get(zrel, {}).get("baixado_em"))

    setores_uf = m.brutos_uf / "setores.gpkg"
    if setores_uf.exists():
        import pyogrio
        g = pyogrio.read_dataframe(setores_uf, where=f"CD_MUN='{m.cod}'")
        destino = rec / "malha_setores_com_atributos.gpkg"
        pyogrio.write_dataframe(g, destino, driver="GPKG")
        url = f"{F.IBGE_SET}/malha_com_atributos/setores/gpkg/UF/{m.uf}/{m.uf}_setores_CD2022.gpkg"
        item("recorte", destino, f"Malha de setores com atributos – setores do município ({len(g)} setores)", "IBGE", url,
             F.PAGINAS["censo2022"], "limites dos setores, moradores (v0001), urbano/rural, bairro",
             f"setores com CD_MUN = {m.cod} do arquivo do estado; geometria e atributos sem alteração")
        item("nacional", setores_uf, f"Malha de setores com atributos – {m.uf} (arquivo do estado)", "IBGE", url, None,
             "origem do recorte acima", "arquivo baixado sem alteração, guardado em dados/brutos/")

    # --- documentação oficial ----------------------------------------------------
    print("Documentação…")
    for doc in F.DOCUMENTOS:
        try:
            origem = baixar_doc(doc)
        except Exception as e:                     # noqa: BLE001 – segue sem o documento, mas avisa
            print(f"  aviso: não consegui obter {doc['arquivo']}: {e}")
            continue
        destino = raiz / "documentacao" / doc["arquivo"]
        shutil.copy2(origem, destino)
        orgao = doc["arquivo"].split("_")[0]
        item("documentação", destino, doc["descricao"], orgao, doc["url"], None, "conferir variáveis e método",
             "baixado do site oficial" if doc["tipo"] != "zip" else f"extraído sem alteração de {doc['zip']} ({doc['membro']})")

    # --- conferências automáticas -------------------------------------------------
    conferencias = []
    md5_inep = raiz / "documentacao" / "INEP_md5_microdados_2024.txt"
    zip_inep = BRUTOS / "inep/microdados_censo_escolar_2024.zip"
    if md5_inep.exists() and zip_inep.exists():
        publicado = md5_inep.read_text("latin1").split()[0].lower()
        with zipfile.ZipFile(zip_inep) as z:
            h = hashlib.md5()
            with z.open(next(n for n in z.namelist() if n.endswith("microdados_ed_basica_2024.csv"))) as f:
                while bloco := f.read(1 << 20):
                    h.update(bloco)
        ok = h.hexdigest() == publicado
        conferencias.append(f"Microdados do Censo Escolar 2024: MD5 calculado `{h.hexdigest()}` "
                            f"{'**igual**' if ok else '**DIFERENTE**'} ao publicado pelo INEP `{publicado}`.")
        print("  conferência INEP:", "ok" if ok else "DIFERENTE")

    # --- índice ------------------------------------------------------------------
    gerado = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    (raiz / "fontes.json").write_text(json.dumps({"municipio": m.nome, "uf": m.uf, "codigo_ibge": m.cod,
                                                  "gerado_em": gerado, "conferencias": conferencias, "arquivos": itens}, ensure_ascii=False, indent=1), "utf-8")
    (raiz / "LEIA-ME.md").write_text(_leia_me(m, itens, gerado, conferencias), "utf-8")
    print(f"Pasta de conferência: {raiz.relative_to(RAIZ)} ({len(itens)} arquivos no índice)")
    return raiz


def _ascii(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _url_cnefe(m: Municipio) -> str | None:
    pasta = f"{F.CNEFE_FTP}/Municipio/{m.cod[:2]}_{m.uf}/"
    try:
        r = requests.get(pasta, timeout=60)
        nomes = re.findall(rf'href="({m.cod}_[^"/]+\.zip)"', r.text)
        return pasta + nomes[0] if nomes else pasta
    except requests.RequestException:
        return pasta


def _leia_me(m: Municipio, itens: list[dict], gerado: str, conferencias: list[str]) -> str:
    L = [f"# Fontes de dados – {m.nome}/{m.uf} ({m.cod})", "",
         f"Pasta gerada em {gerado} por `backend/scripts/fontes_conferencia.py`.", "",
         "Tudo o que a Equicidade usa para este município, para conferência:", "",
         "- **originais/**: arquivos exatamente como foram baixados (cópia byte a byte).",
         "- **recortes/**: as linhas deste município copiadas, sem alterar nenhum valor, dos arquivos nacionais"
         " (que ficam inteiros em `dados/brutos/`; o hash deles está na tabela).",
         "- **documentacao/**: dicionários de dados, leia-me e notas técnicas oficiais.", "",
         "Para conferir um arquivo, calcule o SHA-256 e compare com a tabela "
         "(Windows: `certutil -hashfile ARQUIVO SHA256`; Linux/Mac: `sha256sum ARQUIVO`), "
         "ou baixe de novo pelo link oficial.", "",
         "As páginas do ibge.gov.br às vezes recusam acesso automático, mas abrem normalmente no navegador.", ""]
    if conferencias:
        L += ["## Conferências automáticas", "", *[f"- {c}" for c in conferencias], ""]
    nomes = {"original": "Originais do município", "recorte": "Recortes dos arquivos nacionais",
             "nacional": "Arquivos nacionais completos (em dados/brutos/)", "documentação": "Documentação oficial"}
    for grupo, titulo in nomes.items():
        sel = [i for i in itens if i["grupo"] == grupo]
        if not sel:
            continue
        L += [f"## {titulo}", ""]
        for i in sel:
            L += [f"### `{i['arquivo']}`", "",
                  f"- **O que é:** {i['titulo']} ({i['orgao']})",
                  f"- **Usado para:** {i['usado_para']}",
                  f"- **Origem:** <{i['url_arquivo']}>" if str(i["url_arquivo"]).startswith(("http", "ftp")) else f"- **Origem:** {i['url_arquivo']}",
                  *( [f"- **Página oficial:** <{i['pagina_oficial']}>"] if i["pagina_oficial"] else []),
                  f"- **Como foi obtido:** {i['como_foi_obtido']}",
                  f"- **Obtido em:** {i['obtido_em']}",
                  f"- **Tamanho:** {i['bytes']:,} bytes".replace(",", "."),
                  f"- **SHA-256:** `{i['sha256']}`", ""]
    return "\n".join(L)


def main() -> int:
    m, _ = municipio_cli(descricao=__doc__)
    montar(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
