"""Pasta de conferência: o recorte copia as linhas do arquivo nacional sem alterar nada."""
from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fontes_conferencia", RAIZ / "backend/scripts/fontes_conferencia.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


def test_recorte_copia_linhas_byte_a_byte(tmp_path):
    linhas = [
        'CD_setor;NM_MUN;V01006\r\n'.encode("latin1"),
        '270030005000001;"Arapiraca; AL";12,5\r\n'.encode("latin1"),      # separador dentro de aspas
        '270630705000002;Palmeira dos Índios;7\r\n'.encode("latin1"),     # acento em latin1
        '270030005000003;Arapiraca;X\r\n'.encode("latin1"),                # "X" = sigilo, mantido como veio
    ]
    zp = tmp_path / "nacional.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("dados/Agregados.csv", b"".join(linhas))
    saida = tmp_path / "recorte.csv"
    n = fc.recortar_linhas(zp, "Agregados.csv", "CD_setor", "2700300", saida, comeca=True)
    assert n == 2
    assert saida.read_bytes() == linhas[0] + linhas[1] + linhas[3]

    n = fc.recortar_linhas(zp, "Agregados.csv", "CD_setor", "270630705000002", saida)
    assert n == 1 and saida.read_bytes() == linhas[0] + linhas[2]


def test_referencias_do_relatorio_tem_links_https():
    from backend.app.fontes import REFERENCIAS
    links = [url for r in REFERENCIAS for _, url in r["links"]]
    assert links and all(u.startswith("https://") for u in links)     # navegadores não abrem ftp://
