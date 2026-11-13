"""API e páginas do Mapa de Equipamentos Públicos.

Rodar em desenvolvimento (com o ambiente ativado), na raiz do projeto:
    uvicorn backend.app.api.main:app --port 8000
Primeiro acesso: crie o administrador com
    python -m backend.app.acesso.cli criar-admin seu@email "Seu Nome"
e abra o link que o comando mostrar.

Tudo exige login. Cada usuário só enxerga os municípios liberados para ele
(o administrador vê todos). Ver backend/app/acesso/.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import geopandas as gpd
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from starlette.datastructures import UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .. import servicos
from ..acesso import credenciais as cr
from ..acesso.configuracao import cfg
from ..acesso.modelos import Usuario, iniciar_banco, nova_sessao_db
from ..acesso.rotas import admin as rotas_admin
from ..acesso.rotas import auth as rotas_auth
from ..acesso.web import (CabecalhosSeguranca, LimiteTaxa, ProtecaoCSRF, gerir_municipio, ip_cliente,
                          usuario_opcional, ver_municipio)
from ..analise.contexto import MunicipioNaoProcessado
from ..config import RAIZ, municipio, municipios

FRONT = RAIZ / "frontend"
log = logging.getLogger("mapa")


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    c = cfg()
    c.validar_producao()
    iniciar_banco(c.db_url)
    with nova_sessao_db() as s:
        cr.limpar_expiradas(s)
        s.commit()
    if c.aquecer_ao_iniciar:
        def tarefa():
            for m in municipios():
                if m.processado:
                    try:
                        servicos.aquecer(m.cod)
                    except Exception:            # noqa: BLE001 – aquecimento é opcional
                        log.exception("falha ao pré-carregar %s", m)
        threading.Thread(target=tarefa, daemon=True, name="aquecer").start()
    yield


app = FastAPI(title="Mapa de Equipamentos Públicos", lifespan=ciclo_de_vida,
              docs_url=None, redoc_url=None, openapi_url=None)   # sem documentação pública da API
app.add_middleware(ProtecaoCSRF)
app.add_middleware(CabecalhosSeguranca)
app.include_router(rotas_auth)
app.include_router(rotas_admin)


@app.exception_handler(MunicipioNaoProcessado)
async def _nao_processado(_, __):
    return JSONResponse({"detail": "Município ainda não processado."}, status_code=404)


@app.exception_handler(servicos.TipoDesconhecido)
async def _tipo(_, __):
    return JSONResponse({"detail": "Tipo de equipamento desconhecido."}, status_code=404)


@app.exception_handler(Exception)
async def _erro_interno(request: Request, exc: Exception):
    # o detalhe vai para o log do servidor, nunca para o navegador
    log.exception("erro em %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Erro interno. Tente de novo; se persistir, avise o administrador."},
                        status_code=500)


MODO = Query("reta", pattern="^(reta|rede)$")
RAIO = Query(..., ge=50, le=20000)


def _medidor(cod: str, modo: str) -> None:
    from ..analise.contexto import base
    try:
        base(cod).medidor(modo)
    except FileNotFoundError:
        raise HTTPException(409, "Distância a pé indisponível: malha viária ainda não preparada.") from None


# --------------------------------------------------------------------------- #
# Dados do mapa (todas exigem acesso ao município)
# --------------------------------------------------------------------------- #
@app.get("/api/municipios")
def listar_municipios(u: Usuario | None = Depends(usuario_opcional)):
    if u is None:
        raise HTTPException(401, "Faça login para continuar.")
    return [{"codigo": m.cod, "nome": m.nome, "uf": m.uf, "papel": u.papel_em(m.cod)}
            for m in municipios() if m.processado and u.papel_em(m.cod)]


@app.get("/api/{cod}/config")
def config(cod: str, acesso=Depends(ver_municipio)):
    return {**servicos.config(cod), "papel": acesso[1], "mapa_base": cfg().mapa_base()}


@app.get("/api/{cod}/limite")
def limite(cod: str, _=Depends(ver_municipio)):
    return servicos.limite(cod)


@app.get("/api/{cod}/equipamentos")
def equipamentos(cod: str, _=Depends(ver_municipio)):
    return servicos.equipamentos(cod)


@app.get("/api/{cod}/cobertura")
def cobertura(cod: str, tipo: str = Query(..., max_length=40), raio: int = RAIO, modo: str = MODO,
              _=Depends(ver_municipio)):
    servicos.checa_tipo(cod, tipo)
    _medidor(cod, modo)
    return JSONResponse(servicos.cobertura(cod, tipo, int(raio), modo))


@app.get("/api/{cod}/areas")
def areas(cod: str, tipo: str = Query(..., max_length=40), raio: int = RAIO, _=Depends(ver_municipio)):
    """Polígonos de alcance a pé (modo 'rede'), no lugar dos círculos."""
    servicos.checa_tipo(cod, tipo)
    _medidor(cod, "rede")
    return JSONResponse(servicos.areas(cod, tipo, int(raio)))


@app.get("/api/{cod}/ranking")
def ranking(cod: str, tipo: str = Query(..., max_length=40), raio: int = RAIO, modo: str = MODO,
            _=Depends(ver_municipio)):
    """Bairros ordenados pela população da faixa fora do raio de qualquer equipamento."""
    servicos.checa_tipo(cod, tipo)
    _medidor(cod, modo)
    return JSONResponse(servicos.ranking(cod, tipo, int(raio), modo))


@app.get("/api/{cod}/setores")
def setores(cod: str, tipo: str = Query(..., max_length=40), raio: int = RAIO, modo: str = MODO,
            _=Depends(ver_municipio)):
    """Déficit por setor censitário do IBGE (alternativa aos hexágonos)."""
    servicos.checa_tipo(cod, tipo)
    _medidor(cod, modo)
    return JSONResponse(servicos.setores(cod, tipo, int(raio), modo))


_limite_simulacao = LimiteTaxa(120, 60)


@app.get("/api/{cod}/simular")
def simular(cod: str, request: Request, tipo: str = Query(..., max_length=40), raio: int = RAIO,
            modo: str = MODO, lon: float = Query(..., ge=-75, le=-28), lat: float = Query(..., ge=-35, le=6),
            acesso=Depends(ver_municipio)):
    """Quantas pessoas um equipamento novo naquele ponto passaria a atender."""
    if not _limite_simulacao.permitir(f"u{acesso[0].id}"):
        raise HTTPException(429, "Muitas simulações seguidas. Aguarde um minuto.")
    servicos.checa_tipo(cod, tipo)
    _medidor(cod, modo)
    try:
        return JSONResponse(servicos.simular(cod, tipo, int(raio), modo, lon, lat))
    except servicos.ForaDoMunicipio:
        raise HTTPException(400, "Escolha um ponto dentro do município.") from None


@app.get("/api/{cod}/indicadores")
def indicadores(cod: str, _=Depends(ver_municipio)):
    return servicos.indicadores(cod)


@app.get("/api/{cod}/prioridade")
def prioridade(cod: str, modo: str = MODO, _=Depends(ver_municipio)):
    """Índice de prioridade com os raios padrão do município."""
    _medidor(cod, modo)
    return JSONResponse(servicos.prioridade(cod, modo))


# --------------------------------------------------------------------------- #
# Relatório PDF (pesado: ~40 s de Chromium) – fila e limite por usuário
# --------------------------------------------------------------------------- #
_fila_pdf = asyncio.Semaphore(cfg().pdf_simultaneos)
_limite_pdf = LimiteTaxa(cfg().pdf_por_usuario_hora, 3600)


@app.get("/api/{cod}/relatorio.pdf")
async def relatorio(cod: str, request: Request, acesso=Depends(ver_municipio)):
    """Relatório PDF com os raios atuais do mapa (?creche=500&ubs=1000&modo=rede)."""
    from ..relatorio.gerar import gerar_pdf, nome_arquivo

    u = acesso[0]
    tipos = servicos.tipos(cod)
    modo = request.query_params.get("modo", "reta")
    if modo not in ("reta", "rede"):
        raise HTTPException(400, "modo inválido")
    raios = {}
    for t in tipos:
        v = request.query_params.get(t)
        if v is not None:
            if not v.isdigit() or not 50 <= int(v) <= 20000:
                raise HTTPException(400, f"raio inválido para {t}")
            raios[t] = int(v)
    await run_in_threadpool(_medidor, cod, modo)
    if not _limite_pdf.permitir(f"u{u.id}"):
        raise HTTPException(429, "Limite de relatórios por hora atingido. Tente mais tarde.")
    if _fila_pdf.locked():
        raise HTTPException(503, "Outro relatório está sendo gerado. Tente de novo em um minuto.")
    async with _fila_pdf:
        pasta = Path(tempfile.mkdtemp(prefix="relatorio_"))
        m = municipio(cod)
        destino = pasta / f"relatorio_{nome_arquivo(m.nome)}{'_a_pe' if modo == 'rede' else ''}.pdf"
        try:
            await run_in_threadpool(gerar_pdf, cod, destino, raios, modo)
        except Exception:
            shutil.rmtree(pasta, ignore_errors=True)
            raise
    with nova_sessao_db() as s:
        cr.registrar(s, "relatorio_pdf", u.id, detalhe=f"{cod} modo={modo} raios={raios}", ip=ip_cliente(request))
        s.commit()
    return FileResponse(destino, media_type="application/pdf", filename=destino.name,
                        background=BackgroundTask(shutil.rmtree, pasta, ignore_errors=True))


# --------------------------------------------------------------------------- #
# Upload do cadastro do IPTU (só gestor do município)
# --------------------------------------------------------------------------- #
EXT_OK = {".csv", ".zip", ".gpkg", ".geojson", ".json", ".shp", ".dbf", ".shx", ".prj", ".cpg"}
_NOME_OK = re.compile(r"^[\w.\- ]{1,120}$")


@app.post("/api/{cod}/upload-iptu")
async def upload_iptu(cod: str, request: Request, acesso=Depends(gerir_municipio)):
    """Recebe o cadastro do IPTU (CSV com coordenadas, GeoPackage, GeoJSON ou
    shapefile — .zip ou os arquivos .shp/.dbf/.shx/.prj juntos) e confere o conteúdo.

    O corpo é lido aqui dentro, DEPOIS de conferir login e papel (com um parâmetro
    File(...) o FastAPI leria o arquivo inteiro antes de checar o acesso)."""
    u = acesso[0]
    limite_bytes = cfg().upload_max_mb * 1024 * 1024
    tamanho = request.headers.get("content-length")
    if tamanho and tamanho.isdigit() and int(tamanho) > limite_bytes + 1024 * 1024:
        raise HTTPException(413, f"Arquivos acima de {cfg().upload_max_mb} MB.")
    try:
        form = await request.form(max_files=10, max_fields=10)
    except Exception:                                   # noqa: BLE001 – multipart malformado ou acima dos limites
        raise HTTPException(400, "Envio inválido: no máximo 10 arquivos.") from None
    m = municipio(cod)
    tmp = Path(tempfile.mkdtemp(prefix="iptu_"))
    try:
        arquivos = [a for a in form.getlist("arquivos") if isinstance(a, UploadFile)]
        if not arquivos:
            raise HTTPException(400, "Escolha ao menos um arquivo.")
        total, nomes = 0, []
        for a in arquivos:
            nome = Path(a.filename or "").name
            if not _NOME_OK.match(nome) or Path(nome).suffix.lower() not in EXT_OK:
                raise HTTPException(400, f"Formato ou nome de arquivo não aceito: {nome[:80]}")
            with open(tmp / nome, "wb") as f:
                while bloco := await a.read(1 << 20):
                    total += len(bloco)
                    if total > limite_bytes:
                        raise HTTPException(413, f"Arquivos acima de {cfg().upload_max_mb} MB.")
                    f.write(bloco)
            nomes.append(nome)
        resultado = await run_in_threadpool(_conferir_iptu, cod, tmp, nomes)
        if resultado["ok"]:
            destino = m.prefeitura / "iptu"
            if destino.exists():
                shutil.rmtree(destino)
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp), str(destino))
        with nova_sessao_db() as s:
            cr.registrar(s, "upload_iptu", u.id, detalhe=f"{cod} {nomes} ok={resultado['ok']}", ip=ip_cliente(request))
            s.commit()
        return resultado
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        await form.close()


def _conferir_iptu(cod: str, pasta: Path, nomes: list[str]) -> dict:
    from ..analise.contexto import base
    principal = next((pasta / n for n in nomes if n.lower().endswith((".shp", ".gpkg", ".geojson", ".json", ".zip"))), None)
    try:
        if principal is not None:
            g = gpd.read_file(principal)
        else:
            csv = next((pasta / n for n in nomes if n.lower().endswith(".csv")), None)
            if csv is None:
                return {"ok": False, "mensagem": "Envie um CSV, GeoPackage, GeoJSON ou shapefile."}
            df = pd.read_csv(csv, sep=None, engine="python", nrows=2_000_000)
            lat = next((c for c in df.columns if str(c).lower() in ("lat", "latitude", "y")), None)
            lon = next((c for c in df.columns if str(c).lower() in ("lon", "lng", "longitude", "x")), None)
            if not (lat and lon):
                return {"ok": False, "mensagem": "CSV sem colunas de coordenadas (latitude/longitude). Colunas: "
                        + ", ".join(map(str, df.columns[:20]))}
            g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[lon], df[lat]), crs="EPSG:4326")
    except Exception:                                   # noqa: BLE001
        log.exception("IPTU ilegível (%s)", cod)
        return {"ok": False, "mensagem": "Não consegui ler o arquivo. Confira o formato e tente de novo."}
    if g.crs is None:
        return {"ok": False, "mensagem": "Arquivo sem sistema de coordenadas (.prj ausente)."}
    b = base(cod)
    g = g.to_crs(b.pts.crs)
    dentro = g.geometry.representative_point().within(b.limite.geometry.iloc[0].buffer(100)).mean()
    return {"ok": True, "registros": int(len(g)), "pct_dentro_municipio": round(float(100 * dentro), 1),
            "colunas": list(map(str, g.columns[:30])),
            "mensagem": "Cadastro recebido. O refinamento da densidade com o IPTU entra numa próxima etapa."}


# --------------------------------------------------------------------------- #
# Páginas
# --------------------------------------------------------------------------- #
def _pagina(nome: str) -> FileResponse:
    return FileResponse(FRONT / nome, headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def inicio(u: Usuario | None = Depends(usuario_opcional)):
    return _pagina("index.html") if u else RedirectResponse("/entrar", status_code=303)


@app.get("/entrar", include_in_schema=False)
def pagina_entrar(u: Usuario | None = Depends(usuario_opcional)):
    return RedirectResponse("/", status_code=303) if u else _pagina("entrar.html")


@app.get("/definir-senha", include_in_schema=False)
def pagina_definir_senha():
    return _pagina("definir-senha.html")


@app.get("/admin", include_in_schema=False)
def pagina_admin(u: Usuario | None = Depends(usuario_opcional)):
    if u is None:
        return RedirectResponse("/entrar", status_code=303)
    if not u.admin:
        return RedirectResponse("/", status_code=303)
    return _pagina("admin.html")


@app.get("/saude", include_in_schema=False)
def saude():
    return {"ok": True}


# arquivos estáticos (sem dados): só as pastas de recursos, nunca o index.html direto
for pasta in ("css", "js", "vendor", "img"):
    if (FRONT / pasta).is_dir():
        app.mount(f"/{pasta}", StaticFiles(directory=FRONT / pasta), name=pasta)
