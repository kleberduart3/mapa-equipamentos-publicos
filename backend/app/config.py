"""Caminhos do projeto e parâmetros por município.

Parâmetros: config/parametros.yaml (padrões de todos os municípios) com as
substituições de config/municipios/{código IBGE}.yaml por cima (merge profundo).

Pastas de dados:
  dados/brutos/{ibge,inep,cnes}/      arquivos nacionais (compartilhados)
  dados/brutos/uf/{UF}/               arquivos por estado (malha de setores, equipes CNES)
  dados/brutos/municipios/{código}/   arquivos do município (CNEFE, SIDRA, OSM, prefeitura)
  dados/processados/{código}/         camadas limpas (GeoParquet)
  dados/saidas/{código}/              indicadores, mapas e relatórios
"""
from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
DADOS = RAIZ / "dados"
BRUTOS = DADOS / "brutos"
PROCESSADOS = DADOS / "processados"
SAIDAS = DADOS / "saidas"
CONFIG = RAIZ / "config" / "parametros.yaml"
CONFIG_MUNICIPIOS = RAIZ / "config" / "municipios"

CRS_GEO = "EPSG:4674"  # SIRGAS 2000 geográfico (malhas do IBGE)
_COD = re.compile(r"\d{7}")


class MunicipioDesconhecido(LookupError):
    pass


def cod_valido(cod: str) -> bool:
    """Código IBGE de 7 dígitos (também impede caminhos maliciosos nas pastas)."""
    return isinstance(cod, str) and bool(_COD.fullmatch(cod))


def _mesclar(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        out[k] = _mesclar(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


@lru_cache
def parametros_padrao() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def pasta_uf(uf: str) -> Path:
    if not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError(f"UF inválida: {uf!r}")
    return BRUTOS / "uf" / uf


class Municipio:
    """Um município configurado: identificação, parâmetros e pastas."""

    def __init__(self, cod: str, dados: dict) -> None:
        self.cod = cod
        self.nome: str = dados["nome"]
        self.uf: str = dados["uf"].upper()
        self.P: dict = _mesclar(parametros_padrao(), dados.get("parametros") or {})
        self._crs: str | None = dados.get("crs_metrico")
        self.brutos = BRUTOS / "municipios" / cod
        self.brutos_uf = pasta_uf(self.uf)
        self.prefeitura = self.brutos / "prefeitura"
        self.processados = PROCESSADOS / cod
        self.saidas = SAIDAS / cod

    def __repr__(self) -> str:
        return f"Municipio({self.cod} {self.nome}/{self.uf})"

    @property
    def cod6(self) -> str:
        """DATASUS usa o código IBGE sem o dígito verificador."""
        return self.cod[:6]

    @property
    def meta_arq(self) -> Path:
        return self.processados / "meta.json"

    @property
    def crs(self) -> str:
        """CRS métrico (UTM SIRGAS 2000). Fixado no YAML ou estimado no preparo."""
        if self._crs:
            return self._crs
        if self.meta_arq.exists():
            return json.loads(self.meta_arq.read_text(encoding="utf-8"))["crs_metrico"]
        raise RuntimeError(f"{self}: CRS ainda não definido – rode backend/scripts/preparar_municipio.py")

    @property
    def processado(self) -> bool:
        return (self.processados / "setores.parquet").exists()

    @property
    def tem_rede(self) -> bool:
        return (self.processados / "rede_arestas.parquet").exists()

    def info(self) -> dict:
        return {"codigo_ibge": self.cod, "nome": self.nome, "uf": self.uf, "codigo_ibge6": self.cod6,
                "crs_metrico": self.crs if (self._crs or self.meta_arq.exists()) else None}


@lru_cache(maxsize=None)
def municipio(cod: str) -> Municipio:
    if not cod_valido(cod):
        raise MunicipioDesconhecido(cod)
    arq = CONFIG_MUNICIPIOS / f"{cod}.yaml"
    if not arq.exists():
        raise MunicipioDesconhecido(cod)
    return Municipio(cod, yaml.safe_load(arq.read_text(encoding="utf-8")) or {})


def municipios() -> list[Municipio]:
    """Todos os municípios configurados, em ordem alfabética."""
    cods = [p.stem for p in CONFIG_MUNICIPIOS.glob("*.yaml") if cod_valido(p.stem)]
    return sorted((municipio(c) for c in cods), key=lambda m: m.nome)


def municipio_cli(argv: list[str] | None = None, descricao: str | None = None):
    """Lê --municipio COD (ou nome) da linha de comando; com um só configurado, é opcional.
    Devolve (municipio, argparse.Namespace dos argumentos restantes não lidos)."""
    import argparse

    ap = argparse.ArgumentParser(description=descricao, add_help=False)
    ap.add_argument("--municipio", "-m")
    a, resto = ap.parse_known_args(argv)
    todos = municipios()
    if a.municipio:
        alvo = a.municipio.strip().lower()
        achados = [m for m in todos if alvo in (m.cod, m.nome.lower())]
        if not achados:
            raise SystemExit(f"Município não configurado: {a.municipio}. Configurados: "
                             + ", ".join(f"{m.cod} {m.nome}" for m in todos))
        return achados[0], resto
    if len(todos) == 1:
        return todos[0], resto
    raise SystemExit("Informe --municipio CÓDIGO. Configurados: " + ", ".join(f"{m.cod} {m.nome}" for m in todos))
