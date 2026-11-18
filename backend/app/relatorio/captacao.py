"""Estudo para captação de recursos: o PDF que acompanha a proposta de uma unidade nova.

Parte da simulação (tipo de equipamento + local escolhido no mapa) e reúne, na ordem dos
elementos do estudo técnico preliminar (Lei 14.133/2021, art. 18, § 1º):
  necessidade (déficit, metas do PNE, fila da creche), solução e resultados (quem passa a morar
  perto, cobertura antes e depois), alternativas (o local proposto comparado às áreas que a
  ferramenta sugere), estimativa de custo, programas de financiamento a consultar, mapa, método e fontes.
Itens que dependem da prefeitura (terreno, projeto, previsão no plano de contratações) ficam
listados como pendências, sem inventar nada.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from pyproj import Transformer

from .. import ajustes, servicos
from ..analise.contexto import base
from ..estilo import ESTILO, UNIDADE
from ..fontes import REFERENCIAS
from .gerar import AQUI, LOGO, MESES, WEB, fmt, imprimir_pdf
from .visao import WGS84, _mapa

N_ALTERNATIVAS = 3


def reais(v) -> str:
    if v is None:
        return "–"
    return f"R$ {fmt(v / 1e6, 1)} mi" if v >= 1e6 else f"R$ {fmt(v)}"


def _extensao(pontos: list[tuple[float, float]], raio_m: float) -> tuple[float, float, float, float]:
    """Retângulo (Web Mercator) que mostra o local proposto e as alternativas, com folga."""
    t = Transformer.from_crs(WGS84, WEB, always_xy=True)
    xy = [t.transform(lo, la) for lo, la in pontos]
    xs, ys = [p[0] for p in xy], [p[1] for p in xy]
    folga = max(1.6 * raio_m, 700)
    x0, x1, y0, y1 = min(xs) - folga, max(xs) + folga, min(ys) - folga, max(ys) + folga
    # proporção do mapa ~ 4:3 e largura mínima de 3,5 km
    w, h = max(x1 - x0, 3500), max(y1 - y0, 2600)
    if w / h > 4 / 3:
        h = w * 3 / 4
    else:
        w = h * 4 / 3
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def montar_html(cod: str, tipo: str, lng: float, lat: float, raio: int, modo: str) -> tuple[str, dict]:
    b = base(cod)
    m = b.m.info()
    tipos = b.P["equipamentos"]
    c = tipos[tipo]
    vel = servicos.velocidade(cod)
    sim = servicos.simular(cod, tipo, raio, modo, lng, lat)            # ForaDoMunicipio sobe para a API
    sim = {**sim, "lng": lng, "lat": lat}
    cob = servicos.cobertura(cod, tipo, raio, modo)
    ind, acesso = cob["indicadores"], cob["acesso"]

    # alternativas: as áreas que a ferramenta sugere, simuladas com a mesma regra
    alternativas = [{"rotulo": "Local proposto", "proposto": True, "bairro": sim.get("bairro"), "lng": lng, "lat": lat,
                     "novos": sim["novos_atendidos"], "absorve": sim["demanda_total_absorvivel"],
                     "depois": sim["pct_coberta_depois"], "custo": sim.get("custo")}]
    for f in cob["radar"]["features"][:N_ALTERNATIVAS]:
        lo, la = f["geometry"]["coordinates"]
        try:
            s = servicos.simular(cod, tipo, raio, modo, lo, la)
        except servicos.ForaDoMunicipio:
            continue
        alternativas.append({"rotulo": f"Área sugerida {f['properties']['ordem']}", "proposto": False,
                             "bairro": f["properties"].get("bairro"), "lng": lo, "lat": la, "novos": s["novos_atendidos"],
                             "absorve": s["demanda_total_absorvivel"], "depois": s["pct_coberta_depois"], "custo": s.get("custo")})
    melhor = max(alternativas, key=lambda a: a["novos"])
    posicao = sorted(alternativas, key=lambda a: -a["novos"]).index(alternativas[0]) + 1

    ranking = servicos.ranking(cod, tipo, raio, modo)["bairros"][:8]
    metas = next((x for x in servicos.metas(cod, modo)["metas"] if x["tipo"] == tipo), None)
    fila = None
    if tipo == "creche":
        from .. import fila as fila_mod
        fila = fila_mod.carregar(cod)
        if fila:
            fila["no_bairro"] = next((x["criancas"] for x in fila["bairros"] if x["bairro"] == sim.get("bairro")), 0)

    fonte_eq = "ubs" if c["fonte_dados"] == "cnes" else "escola"
    n_ajustes = sum(1 for k in ajustes.carregar(b.m) if k.startswith(fonte_eq + ":"))
    prog = (b.P.get("captacao") or {}).get("programas") or {}
    programas = prog.get(tipo) or prog.get(fonte_eq) or []

    raios = {k: int(v["raio_m"]) for k, v in tipos.items()} | {tipo: int(raio)}
    estado = {"mostrar": tipo, "modo": modo, "unid": "hex", "raios": raios, "visiveis": {tipo: True},
              "camadas": {"raios": True, "radar": True}}
    ext = _extensao([(a["lng"], a["lat"]) for a in alternativas], sim["raio_efetivo_m"])
    mapa = _mapa(b, cod, estado, raios, ext, {**sim, "area": sim["area"]})

    hoje = date.today()
    env = Environment(loader=FileSystemLoader(AQUI), autoescape=select_autoescape(["html"]))
    env.filters["n"] = fmt
    env.filters["reais"] = reais
    env.filters["min"] = lambda mm: max(1, round(float(mm) / vel))
    contexto = dict(
        logo=Markup(LOGO.read_text(encoding="utf-8")) if LOGO.exists() else "Equicidade",
        m=m, data=f"{hoje.day} de {MESES[hoje.month - 1]} de {hoje.year}", modo=modo, vel=vel, fr=b.fr,
        t=tipo, rotulo=c["rotulo"], rotulo_curto=c["rotulo"].split(" (")[0], cor=ESTILO[tipo]["cor"],
        unidade=UNIDADE.get(tipo, "pessoas"), raio=raio, minutos=max(1, round(raio / vel)),
        meta_pct=round(100 * float(c.get("taxa_atendimento_meta", 1))),
        sim=sim, ind=ind, acesso=acesso, alternativas=alternativas, melhor=melhor, posicao=posicao,
        ranking=ranking, metas=metas, fila=fila, custo=sim.get("custo"), programas=programas,
        aviso_programas=(b.P.get("captacao") or {}).get("aviso"), mapa=mapa, n_ajustes=n_ajustes,
        referencias=REFERENCIAS, coord=f"{lat:.5f}, {lng:.5f}",
        link_mapa=f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lng:.5f}#map=17/{lat:.5f}/{lng:.5f}",
    )
    return env.get_template("modelo_captacao.html").render(**contexto), contexto


def gerar_pdf_captacao(cod: str, tipo: str, lng: float, lat: float, raio: int, modo: str, destino: Path,
                       tempo_limite_s: float = 180) -> Path:
    html, ctx = montar_html(cod, tipo, lng, lat, raio, modo)
    m = ctx["m"]
    return imprimir_pdf(html, destino, f"Equicidade · {m['nome']}/{m['uf']} · estudo para captação – {ctx['rotulo_curto']}",
                        tempo_limite_s)


