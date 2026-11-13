"""Exporta uma versão estática do mapa de UM município (sem servidor e SEM LOGIN).

    python backend/scripts/exportar_estatico.py --municipio CÓDIGO [--passo 100] [--saida site]

ATENÇÃO: o resultado é público para quem tiver os arquivos. Use só quando a
prefeitura autorizar a divulgação; a versão normal é o servidor com login.

Pré-calcula as respostas da API para cada raio (de 200 a 3000 m, no passo
indicado), nos dois modos de distância, e copia o frontend. O app.js detecta o
arquivo dados/estatico.json e passa a ler os JSON em vez de chamar a API.
Os relatórios PDF vão prontos, com os raios padrão.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import servicos  # noqa: E402
from backend.app.config import RAIZ, municipio_cli  # noqa: E402
from backend.app.relatorio.gerar import nome_arquivo  # noqa: E402

RAIO_MIN, RAIO_MAX = 200, 3000


def arred(o, casas=6):
    if isinstance(o, float):
        return round(o, casas)
    if isinstance(o, dict):
        return {k: arred(v, casas) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [arred(v, casas) for v in o]
    return o


def grava(caminho: Path, dados) -> int:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(arred(dados), ensure_ascii=False, separators=(",", ":"), default=str)
    caminho.write_text(txt, encoding="utf-8")
    return len(txt.encode())


def main() -> None:
    m, resto = municipio_cli()
    ap = argparse.ArgumentParser()
    ap.add_argument("--passo", type=int, default=100)
    ap.add_argument("--saida", type=Path, default=RAIZ / "site")
    a = ap.parse_args(resto)
    t0 = time.time()
    out: Path = a.saida
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(RAIZ / "frontend", out, ignore=shutil.ignore_patterns("entrar.html", "definir-senha.html",
                                                                          "admin.html", "entrar.js", "definir-senha.js", "admin.js"))
    (out / ".nojekyll").write_text("")
    cod = m.cod
    d = out / "dados" / cod
    P = m.P
    tipos = list(P["equipamentos"])
    raios = list(range(RAIO_MIN, RAIO_MAX + 1, a.passo))
    for c in P["equipamentos"].values():                       # o raio padrão precisa existir
        if int(c["raio_m"]) not in raios:
            raios.append(int(c["raio_m"]))
    raios.sort()
    tam = 0

    grava(out / "dados" / "municipios.json", [{"codigo": m.cod, "nome": m.nome, "uf": m.uf}])
    tam += grava(d / "config.json", {**servicos.config(cod), "papel": "consulta"})
    tam += grava(d / "limite.json", servicos.limite(cod))
    tam += grava(d / "equipamentos.json", servicos.equipamentos(cod))
    for modo in ("reta", "rede"):
        tam += grava(d / f"prioridade_{modo}.json", servicos.prioridade(cod, modo))
    print(f"base: {time.time() - t0:.0f} s")

    for t in tipos:
        for raio in raios:
            for modo in ("reta", "rede"):
                tam += grava(d / "cobertura" / modo / f"{t}_{raio}.json", servicos.cobertura(cod, t, raio, modo))
            tam += grava(d / "areas" / f"{t}_{raio}.json", servicos.areas(cod, t, raio))
        servicos.cobertura.cache_clear()
        servicos.areas.cache_clear()
        print(f"{t}: {time.time() - t0:.0f} s, {tam / 1e6:.0f} MB até agora", flush=True)

    # relatórios com os raios padrão
    from backend.app.relatorio.gerar import gerar_pdf
    pdfs = {}
    for modo in ("reta", "rede"):
        nome = f"relatorio_{nome_arquivo(m.nome)}_{modo}.pdf"
        gerar_pdf(cod, d / nome, modo=modo)

        pdfs[modo] = f"dados/{cod}/{nome}"

    grava(out / "dados" / "estatico.json", {
        "estatico": True, "passo": a.passo, "raio_min": RAIO_MIN, "raio_max": RAIO_MAX,
        "pdf": pdfs, "gerado_em": date.today().isoformat(),
    })
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"site em {out}: {total / 1e6:.0f} MB, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
