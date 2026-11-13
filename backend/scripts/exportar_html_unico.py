"""Gera UM arquivo HTML autocontido com o mapa (dados embutidos e comprimidos).

    python backend/scripts/exportar_html_unico.py [--passo 500] [--saida saidas/mapa_arapiraca.html]

Usa a pasta site/ gerada por exportar_estatico.py. O arquivo funciona aberto em
qualquer hospedagem (ou com duplo clique), sem servidor e sem outras pastas.
Para caber em poucos MB, leva os raios de --passo em --passo metros (e os padrão).
Os PDFs não vão dentro: o botão aponta para os PDFs publicados no GitHub Pages.
A biblioteca do mapa (MapLibre) vai embutida; precisa de internet só para o mapa
de fundo (OpenStreetMap) e a fonte. ATENÇÃO: o arquivo não tem login – é público
para quem o receber.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SITE_ONLINE = "https://kleberduart3.github.io/mapa-equipamentos-publicos/"

CARREGADOR = """<script>
/* Dados embutidos: substitui fetch("dados/...") pela leitura deste arquivo. */
(() => {
  const b64 = document.getElementById("dados-embutidos").textContent.trim();
  const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const pronto = new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"))).json();
  const fetchOrig = window.fetch.bind(window);
  window.fetch = async (url, opts) => {
    const u = String(url);
    if (u.startsWith("dados/")) {
      const d = await pronto;
      if (u in d) return new Response(d[u], { status: 200, headers: { "Content-Type": "application/json" } });
      return new Response("não incluído nesta versão", { status: 404 });
    }
    return fetchOrig(url, opts);
  };
})();
</script>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--passo", type=int, default=500)
    ap.add_argument("--site", type=Path, default=RAIZ / "site")
    ap.add_argument("--saida", type=Path, default=RAIZ / "dados" / "saidas" / "mapa_arapiraca.html")
    a = ap.parse_args()
    site: Path = a.site
    est = json.loads((site / "dados" / "estatico.json").read_text(encoding="utf-8"))
    raio_max = est["raio_max"]
    raios = set(range(a.passo, raio_max + 1, a.passo))

    dados: dict[str, str] = {}
    for f in (site / "dados").rglob("*.json"):
        rel = f.relative_to(site).as_posix()
        m = re.search(r"_(\d+)\.json$", rel)
        if ("/cobertura/" in rel or "/areas/" in rel) and m:
            r = int(m.group(1))
            if r not in raios:
                continue
        dados[rel] = f.read_text(encoding="utf-8")

    cfg = json.loads(next(v for k, v in dados.items() if k.endswith("/config.json")))
    faltando = [t for t, c in cfg["tipos"].items()
                if isinstance(c, dict) and int(c.get("raio_m", a.passo)) % a.passo]
    if faltando:
        sys.exit(f"raio padrão fora do passo {a.passo}: {faltando}")
    for t in cfg["tipos"]:
        for r in raios:
            for chave in (f"cobertura/reta/{t}_{r}", f"cobertura/rede/{t}_{r}", f"areas/{t}_{r}"):
                if not any(k.endswith(chave + ".json") for k in dados):
                    sys.exit(f"falta {chave}: use um passo que exista em site/ (lá é {est['passo']} m)")

    est.update(passo=a.passo, raio_min=a.passo,
               pdf={k: SITE_ONLINE + v for k, v in est["pdf"].items()})
    dados["dados/estatico.json"] = json.dumps(est, ensure_ascii=False)

    bruto = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode()
    b64 = base64.b64encode(gzip.compress(bruto, 9)).decode()

    html = (site / "index.html").read_text(encoding="utf-8")
    css = (site / "css" / "app.css").read_text(encoding="utf-8")
    js = (site / "js" / "app.js").read_text(encoding="utf-8")
    vend = site / "vendor" / "maplibre-gl-4.7.1"
    ml_css = (vend / "maplibre-gl.css").read_text(encoding="utf-8")
    ml_js = (vend / "maplibre-gl.js").read_text(encoding="utf-8").replace("</script", "<\/script")
    js = js.replace("</script", "<\/script")
    html = re.sub(r'<link href="vendor/maplibre-gl-4.7.1/maplibre-gl.css" rel="stylesheet">',
                  lambda _: f"<style>\n{ml_css}\n</style>", html)
    html = re.sub(r'<script src="vendor/maplibre-gl-4.7.1/maplibre-gl.js"></script>',
                  lambda _: f"<script>\n{ml_js}\n</script>", html)
    html = re.sub(r'<link href="css/app.css" rel="stylesheet">', lambda _: f"<style>\n{css}\n</style>", html)

    html = re.sub(r'<script src="js/app.js"></script>',
                  lambda _: f'<script type="text/plain" id="dados-embutidos">{b64}</script>\n'
                            f"{CARREGADOR}\n<script>\n{js}\n</script>", html)
    if "dados-embutidos" not in html or "<style>" not in html:
        sys.exit("não achei as tags de css/js no index.html")
    a.saida.parent.mkdir(parents=True, exist_ok=True)
    a.saida.write_text(html, encoding="utf-8")
    print(f"{len(dados)} arquivos, {len(bruto) / 1e6:.0f} MB de JSON -> {a.saida} ({a.saida.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
