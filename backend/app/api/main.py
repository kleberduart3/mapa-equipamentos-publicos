"""API do Mapa de Equipamentos Públicos.

Rodar (com o ambiente ativado), na raiz do projeto:
    uvicorn backend.app.api.main:app --port 8000
e abrir http://localhost:8000
"""
from __future__ import annotations

import json
import shutil
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from shapely.geometry import mapping

from ..analise import cobertura as cob
from ..config import BRUTOS, RAIZ, SAIDAS, municipio, parametros

FRONT = RAIZ / "frontend"
WGS84 = "EPSG:4326"

from ..estilo import ESTILO, UNIDADE  # noqa: E402

app = FastAPI(title="Mapa de Equipamentos Públicos")


# Carga dos dados (uma vez por processo): backend/app/analise/contexto.py
from ..analise.contexto import base  # noqa: E402


@app.on_event("startup")
def _aquecer() -> None:
    """Carrega dados e rede em segundo plano para a primeira troca de modo ser rápida."""
    import threading

    def tarefa():
        b = base()
        if b.tem_rede:
            for t, c in parametros()["equipamentos"].items():
                _cobertura(t, int(c["raio_m"]), "rede")
            _prioridade_rede()

    threading.Thread(target=tarefa, daemon=True).start()


def _checa_municipio(cod: str) -> None:
    if cod != municipio()["codigo_ibge"]:
        raise HTTPException(404, "Município ainda não processado")


def _num(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/municipios")
def municipios():
    m = municipio()
    return [{"codigo": m["codigo_ibge"], "nome": m["nome"], "uf": m["uf"]}]


@app.get("/api/{cod}/config")
def config(cod: str):
    _checa_municipio(cod)
    P = parametros()
    b = base()
    lim = b.limite.to_crs(WGS84).total_bounds
    tipos = {}
    for t, c in P["equipamentos"].items():
        tipos[t] = {"rotulo": c["rotulo"], "raio_m": c["raio_m"], **ESTILO.get(t, {"cor": "#555", "icone": "ponto"}),
                    "unidade": UNIDADE.get(t, "pessoas"), "redes": c.get("redes", ["Municipal"])}
    return {"municipio": municipio(), "fator_raio_rural": b.fr, "tipos": tipos,
            "bbox": [float(v) for v in lim], "tem_rede": b.tem_rede,
            "distancia_padrao": P.get("distancia_padrao", "reta") if b.tem_rede else "reta"}


@app.get("/api/{cod}/limite")
def limite(cod: str):
    _checa_municipio(cod)
    g = base().limite.to_crs(WGS84)
    return _fc([{"type": "Feature", "properties": {}, "geometry": mapping(g.geometry.iloc[0])}])


@app.get("/api/{cod}/equipamentos")
def equipamentos(cod: str):
    """Um registro por equipamento e tipo atendido (uma escola pode ter vários)."""
    _checa_municipio(cod)
    b = base()
    P = parametros()
    feats = []
    for t, cfg in P["equipamentos"].items():
        fac, _ = cob.ofertas(t, cfg, b.escolas, b.ubs)
        if not len(fac):
            continue
        sit = b.situacao(fac.geometry)
        ll = fac.to_crs(WGS84)
        src = b.ubs.set_index("cnes") if cfg["fonte_dados"] == "cnes" else b.escolas.set_index("codigo_inep")
        for i, r in enumerate(fac.itertuples()):
            s = src.loc[r.id]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[0]
            rural = sit["SITUACAO"].iloc[i] != "Urbana"
            props = {
                "id": r.id, "tipo": t, "nome": r.nome, "rede": r.rede, "capacidade": _num(r.capacidade),
                "fonte_coord": r.fonte_coord, "bairro": _num(sit["NM_BAIRRO"].iloc[i]), "rural": bool(rural),
                "raio_m": cfg["raio_m"] * (b.fr if rural else 1),
            }
            if cfg["fonte_dados"] == "cnes":
                props.update({"equipes": _num(s["equipes_ab"]), "endereco": f"{s['logradouro']}, {s['numero']} – {s['bairro']}"})
            else:
                props.update({k: _num(s[k]) for k in ["mat_creche", "mat_pre_escola", "mat_fund_iniciais", "mat_fund_finais"]})
            feats.append({"type": "Feature", "properties": props,
                          "geometry": {"type": "Point", "coordinates": [ll.geometry.iloc[i].x, ll.geometry.iloc[i].y]}})
    # Contexto: ensino médio das redes estadual/federal (fora dos indicadores municipais)
    e = b.escolas
    ctx = e[e["em_funcionamento"].astype(bool) & e["oferta_medio"].astype(bool)
            & e["dependencia"].isin(["Estadual", "Federal"]) & e["latitude"].notna()].to_crs(WGS84)
    for r in ctx.itertuples():
        feats.append({"type": "Feature", "properties": {
            "id": r.codigo_inep, "tipo": "contexto_medio", "nome": r.escola, "rede": r.dependencia,
            "fonte_coord": r.fonte_coord, "bairro": None, "rural": False, "mat_medio": _num(r.mat_medio)},
            "geometry": {"type": "Point", "coordinates": [r.geometry.x, r.geometry.y]}})
    return _fc(feats)


def _medidor(modo: str):
    try:
        return base().medidor(modo)
    except FileNotFoundError as e:
        raise HTTPException(409, str(e)) from e


@lru_cache(maxsize=96)
def _cobertura(t: str, raio: int, modo: str = "reta") -> dict:
    b = base()
    P = parametros()
    md = _medidor(modo)
    cfg = {**P["equipamentos"][t], "raio_m": raio}
    fac, sem = cob.ofertas(t, cfg, b.escolas, b.ubs)
    r = cob.calcular(t, cfg, b.pts, fac, sem, b.fr, tree=b.tree, medidor=md)

    # déficit por hexágono
    df = pd.DataFrame({"h3": b.pts["h3"], "sem_cob": r.sem_cobertura, "def_cap": r.deficit_cap,
                       "pop_desc": np.where(r.coberto, 0, r.pop_faixa)})
    g = df.groupby("h3").sum()
    g["deficit"] = g["sem_cob"] + g["def_cap"]
    g = g[g["deficit"] > 0.5]
    hexes = [{"type": "Feature",
              "properties": {"h3": h, "deficit": round(float(v["deficit"]), 1),
                             "sem_cobertura": round(float(v["sem_cob"]), 1),
                             "deficit_capacidade": round(float(v["def_cap"]), 1),
                             "pop_descoberta": round(float(v["pop_desc"]), 1)},
              "geometry": {"type": "Polygon", "coordinates": [b.hex_poly[h] + [b.hex_poly[h][0]]]}}
             for h, v in g.iterrows()]

    # sugestões (radar pulsante)
    rp = cob.raios(b.pts, raio, b.fr)
    sug = cob.sugerir_locais(t, r, b.pts, b.cand_xy, b.hex_ids, rp, int(P["prioridade"]["sugestoes_por_tipo"]),
                             float(P["prioridade"]["ganho_minimo"][t]), b.tree, medidor=md)
    radar = []
    if len(sug):
        pts = gpd.GeoSeries(gpd.points_from_xy(sug["x"], sug["y"]), crs=b.pts.crs)
        sit = b.situacao(pts)
        ll = pts.to_crs(WGS84)
        for i, s in sug.iterrows():
            radar.append({"type": "Feature", "properties": {
                "tipo": t, "ordem": int(s["ordem"]), "bairro": _num(sit["NM_BAIRRO"].iloc[i]),
                "demanda_absorvida": round(float(s["demanda_absorvida"])),
                "sem_cobertura": round(float(s["demanda_sem_cobertura_absorvida"]))},
                "geometry": {"type": "Point", "coordinates": [ll.iloc[i].x, ll.iloc[i].y]}})

    rural = b.pts["rural"].to_numpy()
    ind = {
        "tipo": t, "raio_m": raio, "modo": modo, "pop_faixa": round(float(r.pop_faixa.sum())),
        "pct_coberta": round(cob.pct_coberto(r), 1),
        "pct_coberta_rural": round(float(100 * r.pop_faixa[r.coberto & rural].sum() / max(r.pop_faixa[rural].sum(), 1)), 1),
        "pop_descoberta": round(float(r.pop_faixa[~r.coberto].sum())),
        "demanda_meta": round(float(r.demanda.sum())),
        "demanda_sem_cobertura": round(float(r.sem_cobertura.sum())),
        "deficit_capacidade": round(float(r.deficit_cap.sum())),
        "equipamentos": int(len(fac)),
    }
    return {"indicadores": ind, "hex": _fc(hexes), "radar": _fc(radar)}


MODO = Query("reta", pattern="^(reta|rede)$")


@app.get("/api/{cod}/cobertura")
def cobertura(cod: str, tipo: str, raio: int = Query(..., ge=50, le=20000), modo: str = MODO):
    _checa_municipio(cod)
    if tipo not in parametros()["equipamentos"]:
        raise HTTPException(404, "tipo desconhecido")
    return JSONResponse(_cobertura(tipo, int(raio), modo))


@lru_cache(maxsize=48)
def _areas(t: str, raio: int) -> dict:
    """Área alcançável a pé de cada equipamento (vias dentro do raio + faixa de 40 m)."""
    b = base()
    rede = _medidor("rede").rede
    cfg = {**parametros()["equipamentos"][t], "raio_m": raio}
    fac, _ = cob.ofertas(t, cfg, b.escolas, b.ubs)
    if not len(fac):
        return _fc([])
    rural = (b.situacao(fac.geometry)["SITUACAO"] != "Urbana").to_numpy()
    r = np.where(rural, raio * b.fr, raio).astype(float)
    xy = np.column_stack([fac.geometry.x, fac.geometry.y])
    g = gpd.GeoSeries(rede.areas_servico(xy, r), crs=b.pts.crs).to_crs(WGS84).simplify(0.00005)
    return _fc([{"type": "Feature", "properties": {"id": fac["id"].iloc[i], "tipo": t, "raio_m": float(r[i])},
                 "geometry": mapping(g.iloc[i])} for i in range(len(fac))])


@app.get("/api/{cod}/areas")
def areas(cod: str, tipo: str, raio: int = Query(..., ge=50, le=20000)):
    """Polígonos de alcance a pé (modo 'rede'), no lugar dos círculos."""
    _checa_municipio(cod)
    if tipo not in parametros()["equipamentos"]:
        raise HTTPException(404, "tipo desconhecido")
    return JSONResponse(_areas(tipo, int(raio)))


@app.get("/api/{cod}/indicadores")
def indicadores(cod: str):
    _checa_municipio(cod)
    return json.loads((SAIDAS / "indicadores.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=2)
def _prioridade_rede() -> gpd.GeoDataFrame:
    from ..relatorio.gerar import analisar
    _medidor("rede")
    return analisar(None, "rede")["hex"]


@app.get("/api/{cod}/prioridade")
def prioridade(cod: str, modo: str = MODO):
    """Índice de prioridade com os raios padrão do parametros.yaml."""
    _checa_municipio(cod)
    h = (_prioridade_rede() if modo == "rede" else gpd.read_parquet(SAIDAS / "cobertura_hex.parquet")).to_crs(WGS84)
    h = h[h["prioridade_geral"] > 1][["h3", "prioridade_geral", "geometry"]]
    h["prioridade_geral"] = h["prioridade_geral"].round(1)
    return JSONResponse(json.loads(h.to_json()))


@app.get("/api/{cod}/relatorio.pdf")
def relatorio(cod: str, request: Request):
    """Relatório PDF com os raios atuais do mapa (?creche=500&ubs=1000…)."""
    _checa_municipio(cod)
    from ..relatorio.gerar import gerar_pdf

    tipos = parametros()["equipamentos"]
    modo = request.query_params.get("modo", "reta")
    if modo not in ("reta", "rede"):
        raise HTTPException(400, "modo inválido")
    _medidor(modo)
    raios = {}
    for t in tipos:
        v = request.query_params.get(t)
        if v is not None:
            if not v.isdigit() or not 50 <= int(v) <= 20000:
                raise HTTPException(400, f"raio inválido para {t}")
            raios[t] = int(v)
    destino = gerar_pdf(raios=raios, modo=modo)
    return FileResponse(destino, media_type="application/pdf", filename=destino.name)


EXT_OK = {".csv", ".zip", ".gpkg", ".geojson", ".json", ".shp", ".dbf", ".shx", ".prj", ".cpg"}


@app.post("/api/{cod}/upload-iptu")
async def upload_iptu(cod: str, arquivos: list[UploadFile] = File(...)):
    """Recebe o cadastro do IPTU (CSV com coordenadas, GeoPackage, GeoJSON ou
    shapefile — .zip ou os arquivos .shp/.dbf/.shx/.prj juntos) e confere o conteúdo."""
    _checa_municipio(cod)
    destino = BRUTOS / "prefeitura" / "iptu"
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    nomes = []
    for a in arquivos:
        nome = Path(a.filename or "").name
        if Path(nome).suffix.lower() not in EXT_OK:
            raise HTTPException(400, f"Formato não aceito: {nome}")
        (destino / nome).write_bytes(await a.read())
        nomes.append(nome)
    principal = next((destino / n for n in nomes if n.lower().endswith((".shp", ".gpkg", ".geojson", ".json", ".zip"))), None)
    try:
        if principal is not None:
            g = gpd.read_file(principal)
        else:
            csv = destino / next(n for n in nomes if n.lower().endswith(".csv"))
            df = pd.read_csv(csv, sep=None, engine="python")
            lat = next((c for c in df.columns if c.lower() in ("lat", "latitude", "y")), None)
            lon = next((c for c in df.columns if c.lower() in ("lon", "lng", "longitude", "x")), None)
            if not (lat and lon):
                return {"ok": False, "mensagem": "CSV sem colunas de coordenadas (latitude/longitude). Colunas: " + ", ".join(df.columns[:20])}
            g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[lon], df[lat]), crs=WGS84)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "mensagem": f"Não consegui ler o arquivo: {e}"}
    if g.crs is None:
        return {"ok": False, "mensagem": "Arquivo sem sistema de coordenadas (.prj ausente)."}
    g = g.to_crs(base().pts.crs)
    dentro = g.geometry.representative_point().within(base().limite.geometry.iloc[0].buffer(100)).mean()
    return {"ok": True, "registros": int(len(g)), "pct_dentro_municipio": round(float(100 * dentro), 1),
            "colunas": list(map(str, g.columns[:30])),
            "mensagem": "Cadastro recebido. O refinamento da densidade com o IPTU entra numa próxima etapa."}


# --------------------------------------------------------------------------- #
# Frontend
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return FileResponse(FRONT / "index.html")


app.mount("/", StaticFiles(directory=FRONT), name="front")
