"""Ajustes de equipamentos informados pela prefeitura: corrigir o local, editar nome e
capacidade, desativar uma unidade que fechou ou incluir uma que não está no INEP/CNES.

Os dados oficiais (INEP, CNES) não são alterados: os ajustes ficam num arquivo da prefeitura
(dados/brutos/municipios/{cód}/prefeitura/ajustes_equipamentos.json, que entra na cópia de
segurança) e são aplicados por cima toda vez que o município é carregado ou recalculado. Assim
continuam valendo quando o Censo Escolar ou o CNES forem atualizados, e cada um pode ser desfeito.

As matrículas usadas nas metas do PNE continuam as oficiais do Censo Escolar (indicador legal);
a capacidade ajustada vale para o cálculo de vagas perto de casa.
"""
from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from .config import Municipio

ARQUIVO = "ajustes_equipamentos.json"
WGS84 = "EPSG:4326"
FONTE_COORD = "prefeitura"
_trava = threading.Lock()

# coluna de capacidade e de oferta de cada tipo de escola (as UBS usam equipes_ab)
COLUNAS_ESCOLA = {"creche": ("mat_creche", "oferta_creche"), "pre_escola": ("mat_pre_escola", "oferta_pre_escola"),
                  "fundamental_iniciais": ("mat_fund_iniciais", "oferta_fund_iniciais"),
                  "fundamental_finais": ("mat_fund_finais", "oferta_fund_finais")}


class AjusteInvalido(ValueError):
    pass


def _arquivo(m: Municipio) -> Path:
    return m.prefeitura / ARQUIVO


def carregar(m: Municipio) -> dict[str, dict]:
    arq = _arquivo(m)
    if not arq.exists():
        return {}
    return json.loads(arq.read_text(encoding="utf-8")).get("itens", {})


def _gravar(m: Municipio, itens: dict[str, dict]) -> None:
    arq = _arquivo(m)
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps({"versao": 1, "itens": itens}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(arq)


def chave(fonte: str, ref: str) -> str:
    return f"{fonte}:{ref}"


def salvar(m: Municipio, k: str | None, item: dict, por: str) -> str:
    """Grava (ou substitui) um ajuste. k=None cria uma unidade nova. Devolve a chave."""
    item = {c: v for c, v in item.items() if v is not None}
    with _trava:
        itens = carregar(m)
        if k is None:
            k = chave(item["fonte"], "PREF-" + secrets.token_hex(3).upper())
            item = {**item, "novo": True}
        elif k in itens:
            item = {**itens[k], **item}
        itens[k] = {**item, "por": por, "em": datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")}
        _gravar(m, itens)
    return k


def remover(m: Municipio, k: str) -> dict | None:
    with _trava:
        itens = carregar(m)
        item = itens.pop(k, None)
        if item is not None:
            _gravar(m, itens)
    return item


def _ponto(item: dict, crs) -> Point | None:
    if item.get("lat") is None or item.get("lon") is None:
        return None
    return gpd.GeoSeries([Point(float(item["lon"]), float(item["lat"]))], crs=WGS84).to_crs(crs).iloc[0]


def aplicar(m: Municipio, escolas: gpd.GeoDataFrame, ubs: gpd.GeoDataFrame
            ) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Escolas e UBS com os ajustes da prefeitura por cima dos dados oficiais."""
    itens = carregar(m)
    if not itens:
        return escolas, ubs
    escolas, ubs = escolas.copy(), ubs.copy()
    for k, it in itens.items():
        fonte, ref = k.split(":", 1)
        if fonte == "escola":
            escolas = _aplicar_escola(escolas, ref, it)
        elif fonte == "ubs":
            ubs = _aplicar_ubs(ubs, ref, it)
    return escolas, ubs


def _aplicar_escola(e: gpd.GeoDataFrame, ref: str, it: dict) -> gpd.GeoDataFrame:
    if it.get("novo"):
        linha = {c: None for c in e.columns}
        linha.update({"codigo_inep": ref, "escola": it["nome"], "NO_ENTIDADE": it["nome"], "dependencia": "Municipal",
                      "situacao": "FUNCIONANDO", "em_funcionamento": True, "dentro_municipio": True,
                      "endereco": it.get("endereco"), "fonte_coord": FONTE_COORD, "mat_medio": 0, "oferta_medio": False,
                      "ano_censo_escolar": 0})
        for col, of in COLUNAS_ESCOLA.values():
            linha[col], linha[of] = 0, False
        e = pd.concat([e, gpd.GeoDataFrame([linha], geometry=[None], crs=e.crs)], ignore_index=True)
        e["geometry"] = e.geometry.set_crs(e.crs, allow_override=True)
    sel = e["codigo_inep"] == ref
    if not sel.any():
        return e                          # escola saiu do Censo Escolar: o ajuste fica guardado, sem efeito
    if it.get("nome"):
        e.loc[sel, "escola"] = it["nome"]
    if it.get("ativo") is not None:
        e.loc[sel, "em_funcionamento"] = bool(it["ativo"])
    for t, n in (it.get("capacidade") or {}).items():
        if t in COLUNAS_ESCOLA:
            col, of = COLUNAS_ESCOLA[t]
            e.loc[sel, col] = int(n)
            e.loc[sel, of] = int(n) > 0
    p = _ponto(it, e.crs)
    if p is not None:
        e.loc[sel, ["latitude", "longitude"]] = [float(it["lat"]), float(it["lon"])]
        e.loc[sel, "geometry"] = gpd.GeoSeries([p] * int(sel.sum()), index=e.index[sel], crs=e.crs)
        e.loc[sel, "fonte_coord"] = FONTE_COORD
        e.loc[sel, "dentro_municipio"] = True
    return e


def _aplicar_ubs(u: gpd.GeoDataFrame, ref: str, it: dict) -> gpd.GeoDataFrame:
    if it.get("novo"):
        linha = {c: None for c in u.columns}
        linha.update({"cnes": ref, "nome": it["nome"], "tipo": "UBS (prefeitura)", "ativa": True, "equipes_ab": 0,
                      "competencia_equipes": "prefeitura", "logradouro": it.get("endereco") or "", "numero": "",
                      "bairro": "", "cep": "", "fonte_coord": FONTE_COORD, "dentro_municipio": True})
        u = pd.concat([u, gpd.GeoDataFrame([linha], geometry=[None], crs=u.crs)], ignore_index=True)
        u["geometry"] = u.geometry.set_crs(u.crs, allow_override=True)
    sel = u["cnes"] == ref
    if not sel.any():
        return u
    if it.get("nome"):
        u.loc[sel, "nome"] = it["nome"]
    if it.get("ativo") is not None:
        u.loc[sel, "ativa"] = bool(it["ativo"])
    if "ubs" in (it.get("capacidade") or {}):
        u.loc[sel, "equipes_ab"] = int(it["capacidade"]["ubs"])
    p = _ponto(it, u.crs)
    if p is not None:
        u.loc[sel, ["lat", "lon"]] = [float(it["lat"]), float(it["lon"])]
        u.loc[sel, "geometry"] = gpd.GeoSeries([p] * int(sel.sum()), index=u.index[sel], crs=u.crs)
        u.loc[sel, "fonte_coord"] = FONTE_COORD
        u.loc[sel, "dentro_municipio"] = True
    return u


def resumo(item: dict) -> str:
    """Descrição curta do ajuste, para a lista e o relatório."""
    if item.get("novo"):
        return "unidade incluída pela prefeitura"
    partes = []
    if item.get("lat") is not None:
        partes.append("local corrigido")
    if item.get("nome"):
        partes.append("nome")
    if item.get("capacidade"):
        partes.append("capacidade")
    if item.get("ativo") is False:
        partes.append("desativada")
    elif item.get("ativo") is True:
        partes.append("reativada")
    return ", ".join(partes) or "sem alteração"
