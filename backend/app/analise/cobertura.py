"""Cobertura de equipamentos: raio de atendimento + demanda × capacidade (2SFCA).

Fluxo:
1. pontos_demanda: a população de cada setor é repartida igualmente entre os
   endereços residenciais do CNEFE do setor (método dasimétrico simples).
2. ofertas: equipamentos que atendem cada tipo, com capacidade.
3. calcular: para cada ponto, se há equipamento dentro do raio (cobertura) e
   quanto de capacidade "chega" a ele (2SFCA – two-step floating catchment area):
      passo 1  R_j = S_j / Σ d_i   (capacidade do equipamento ÷ demanda no seu raio)
      passo 2  A_i = Σ R_j          (soma das razões dos equipamentos que alcançam i)
   A_i = 1 significa capacidade igual à demanda-meta.
   - demanda_sem_cobertura_i = d_i                 se nenhum equipamento alcança i
   - deficit_capacidade_i    = d_i · max(0, 1−A_i) só para pontos cobertos
   (as duas parcelas são disjuntas: um ponto descoberto não conta duas vezes).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

FAIXAS = ["pop_total", "pop_0_3", "pop_4_5", "pop_6_10", "pop_11_14", "pop_15_17"]
REDE_PUBLICA = ["Municipal", "Estadual", "Federal"]


# --------------------------------------------------------------------------- #
# 1. Demanda
# --------------------------------------------------------------------------- #
def pontos_demanda(setores: gpd.GeoDataFrame, enderecos: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Um ponto por endereço residencial, com a fração da população do setor."""
    n = enderecos.groupby("CD_SETOR").size().rename("n_end")
    atrib = setores[["CD_SETOR", "SITUACAO", *FAIXAS]].merge(n, on="CD_SETOR", how="left")
    pts = enderecos[["CD_SETOR", "geometry"]].merge(atrib, on="CD_SETOR", how="left")
    for c in FAIXAS:
        pts[c] = pts[c] / pts["n_end"]
    # setores com população e sem endereço: um ponto no interior do polígono
    sem = atrib[(atrib["n_end"].isna()) & (atrib["pop_total"] > 0)]
    if len(sem):
        geo = setores.set_index("CD_SETOR").loc[sem["CD_SETOR"], "geometry"].representative_point()
        extra = gpd.GeoDataFrame(sem.drop(columns="n_end").assign(geometry=geo.values), crs=setores.crs)
        pts = pd.concat([pts.drop(columns="n_end"), extra], ignore_index=True)
    else:
        pts = pts.drop(columns="n_end")
    pts = gpd.GeoDataFrame(pts, geometry="geometry", crs=setores.crs)
    pts["rural"] = pts["SITUACAO"] != "Urbana"
    return pts.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 2. Oferta
# --------------------------------------------------------------------------- #
def ofertas(tipo: str, cfg: dict, escolas: gpd.GeoDataFrame, ubs: gpd.GeoDataFrame,
            redes: list[str] | None = None) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Equipamentos que atendem o tipo. Devolve (com coordenada, sem coordenada)."""
    if cfg["fonte_dados"] == "cnes":
        f = ubs[ubs["ativa"]].copy()
        f["capacidade"] = f[cfg["capacidade"]] * cfg["pessoas_por_equipe"]
        f["id"], f["rede"] = f["cnes"], "Municipal"
    else:
        redes = redes or cfg["redes"]
        redes = [r.capitalize() for r in redes]
        f = escolas[escolas["em_funcionamento"].astype(bool) & escolas[cfg["oferta"]].astype(bool)
                    & escolas["dependencia"].isin(redes)].copy()
        f["capacidade"] = f[cfg["capacidade"]].astype(float)
        f["id"], f["nome"], f["rede"] = f["codigo_inep"], f["escola"], f["dependencia"]
    cols = ["id", "nome", "rede", "capacidade", "fonte_coord", "geometry"]
    tem = ~(f.geometry.isna() | f.geometry.is_empty)
    return f.loc[tem, cols].reset_index(drop=True), pd.DataFrame(f.loc[~tem, cols[:-1]])


# --------------------------------------------------------------------------- #
# 3. Cálculo
# --------------------------------------------------------------------------- #
@dataclass
class Resultado:
    tipo: str
    coberto: np.ndarray            # bool por ponto
    demanda: np.ndarray            # d_i (população da faixa × meta)
    pop_faixa: np.ndarray          # população da faixa (sem meta)
    acesso: np.ndarray             # A_i
    sem_cobertura: np.ndarray      # demanda sem cobertura
    deficit_cap: np.ndarray        # déficit de capacidade (só cobertos)
    fac: pd.DataFrame              # por equipamento: demanda no raio, razão
    sem_coord: pd.DataFrame
    checagem: dict = field(default_factory=dict)


def _pares(xy_pts: np.ndarray, raio_pts: np.ndarray, xy_fac: np.ndarray, tree: cKDTree):
    """Pares (ponto, equipamento) com distância ≤ raio do próprio ponto."""
    rmax = float(raio_pts.max())
    ii, jj = [], []
    for j, viz in enumerate(tree.query_ball_point(xy_fac, rmax)):
        if not viz:
            continue
        viz = np.asarray(viz)
        d = np.hypot(*(xy_pts[viz] - xy_fac[j]).T)
        ok = viz[d <= raio_pts[viz]]
        ii.append(ok)
        jj.append(np.full(len(ok), j))
    if not ii:
        return np.array([], int), np.array([], int)
    return np.concatenate(ii), np.concatenate(jj)


class LinhaReta:
    """Medidor padrão: distância em linha reta."""
    modo = "reta"

    def __init__(self, xy: np.ndarray, tree: cKDTree) -> None:
        self.xy, self.tree = xy, tree

    def pares(self, raio_pts, xy_alvo, ativos=None):
        return _pares(self.xy, raio_pts, xy_alvo, self.tree)


class APe:
    """Distância a pé pela malha viária (backend/app/analise/rede.py)."""
    modo = "rede"

    def __init__(self, rede, xy: np.ndarray, tree: cKDTree) -> None:
        self.rede, self.xy, self.tree = rede, xy, tree
        self.lig = rede.ligar(xy)
        self.violacoes = 0          # pares com distância a pé < linha reta (não deve haver)

    def pares(self, raio_pts, xy_alvo, ativos=None):
        ii, jj, dd, reta = self.rede.pares(self.xy, self.lig, raio_pts, xy_alvo, self.tree, ativos)
        self.violacoes += int((dd < reta - 1e-6).sum())
        return ii, jj


def raios(pts: gpd.GeoDataFrame, raio_m: float, fator_rural: float) -> np.ndarray:
    return np.where(pts["rural"].to_numpy(), raio_m * fator_rural, raio_m).astype(float)


def calcular(tipo: str, cfg: dict, pts: gpd.GeoDataFrame, fac: gpd.GeoDataFrame, sem_coord: pd.DataFrame,
             fator_rural: float, escala_raio: float = 1.0, tree: cKDTree | None = None,
             medidor=None) -> Resultado:
    xy = np.column_stack([pts.geometry.x, pts.geometry.y])
    tree = tree or cKDTree(xy)
    medidor = medidor or LinhaReta(xy, tree)
    medidor.violacoes = 0
    r = raios(pts, cfg["raio_m"] * escala_raio, fator_rural)
    pop = pts[cfg["faixa_demanda"]].to_numpy(float)
    d = pop * cfg.get("taxa_atendimento_meta", 1.0)
    n = len(pts)
    if len(fac) == 0:
        zero = np.zeros(n)
        return Resultado(tipo, zero.astype(bool), d, pop, zero, d.copy(), zero, pd.DataFrame(), sem_coord)

    xy_f = np.column_stack([fac.geometry.x, fac.geometry.y])
    ii, jj = medidor.pares(r, xy_f)
    coberto = np.zeros(n, bool)
    coberto[ii] = True

    S = fac["capacidade"].to_numpy(float)
    D = np.bincount(jj, weights=d[ii], minlength=len(fac))          # passo 1
    R = np.divide(S, D, out=np.zeros_like(S), where=D > 0)
    A = np.bincount(ii, weights=R[jj], minlength=n)                   # passo 2

    sem_cob = np.where(coberto, 0.0, d)
    deficit = np.where(coberto, d * np.clip(1 - A, 0, None), 0.0)

    f = fac.drop(columns="geometry").copy()
    f["demanda_no_raio"] = D
    f["capacidade_por_demanda"] = np.where(D > 0, R, np.nan)
    f["sem_demanda_no_raio"] = D == 0

    soma_A = float((A * d).sum())
    soma_S = float(S[D > 0].sum())
    chk = {
        "2sfca_soma_acesso": round(soma_A, 2),
        "2sfca_soma_capacidade_com_demanda": round(soma_S, 2),
        "2sfca_consistente": bool(np.isclose(soma_A, soma_S, rtol=1e-6)),
        "capacidade_total": float(S.sum() + sem_coord["capacidade"].sum()),
        "capacidade_sem_coordenada": float(sem_coord["capacidade"].sum()),
        "capacidade_sem_demanda_no_raio": float(S[D == 0].sum()),
        "equipamentos_sem_demanda_no_raio": f.loc[f["sem_demanda_no_raio"], "nome"].tolist(),
        "distancia": medidor.modo,
    }
    if medidor.modo == "rede":
        chk["pares_a_pe_menores_que_linha_reta"] = medidor.violacoes
    return Resultado(tipo, coberto, d, pop, A, sem_cob, deficit, f, sem_coord, chk)


def pct_coberto(res: Resultado) -> float:
    tot = res.pop_faixa.sum()
    return float(100 * res.pop_faixa[res.coberto].sum() / tot) if tot else float("nan")


# --------------------------------------------------------------------------- #
# 4. Agregações
# --------------------------------------------------------------------------- #
def colunas_ponto(res: Resultado) -> dict[str, np.ndarray]:
    t = res.tipo
    return {
        f"{t}_pop": res.pop_faixa,
        f"{t}_pop_coberta": np.where(res.coberto, res.pop_faixa, 0.0),
        f"{t}_pop_descoberta": np.where(res.coberto, 0.0, res.pop_faixa),
        f"{t}_demanda": res.demanda,
        f"{t}_demanda_sem_cobertura": res.sem_cobertura,
        f"{t}_deficit_capacidade": res.deficit_cap,
        f"{t}_acesso_ponderado": res.acesso * res.demanda,   # para média ponderada
    }


def agregar(base: pd.DataFrame, chave: str, tipos: list[str]) -> pd.DataFrame:
    soma = [c for c in base.columns if any(c.startswith(t + "_") for t in tipos)]
    g = base.groupby(chave)[soma].sum()
    for t in tipos:
        g[f"{t}_pct_coberta"] = 100 * g[f"{t}_pop_coberta"] / g[f"{t}_pop"].replace(0, np.nan)
        g[f"{t}_acesso_medio"] = g[f"{t}_acesso_ponderado"] / g[f"{t}_demanda"].replace(0, np.nan)
        g = g.drop(columns=f"{t}_acesso_ponderado")
    return g.reset_index()


def indice_prioridade(hex_: pd.DataFrame, tipos: list[str], pesos: dict) -> pd.DataFrame:
    """Índice 0–100 por tipo e geral. Cada componente é normalizado pelo máximo
    entre os hexágonos; os pesos são renormalizados sem a parcela de expansão
    urbana quando não há cadastro do IPTU."""
    w1, w2 = pesos["populacao_nao_atendida"], pesos["deficit_capacidade"]
    s = w1 + w2
    w1, w2 = w1 / s, w2 / s
    for t in tipos:
        a = hex_[f"{t}_demanda_sem_cobertura"]
        b = hex_[f"{t}_deficit_capacidade"]
        na = a / a.max() if a.max() > 0 else 0 * a
        nb = b / b.max() if b.max() > 0 else 0 * b
        hex_[f"{t}_prioridade"] = 100 * (w1 * na + w2 * nb)
    hex_["prioridade_geral"] = hex_[[f"{t}_prioridade" for t in tipos]].mean(axis=1)
    return hex_


# --------------------------------------------------------------------------- #
# 5. Sugestão de locais (máxima cobertura, guloso)
# --------------------------------------------------------------------------- #
def sugerir_locais(tipo: str, res: Resultado, pts: gpd.GeoDataFrame, cand_xy: np.ndarray,
                   cand_id: np.ndarray, raio_pts: np.ndarray, k: int, ganho_min: float,
                   tree: cKDTree, medidor=None) -> pd.DataFrame:
    """A cada rodada escolhe o hexágono cujo centro, com o raio do tipo, alcança
    a maior demanda ainda não resolvida (sem cobertura + déficit de capacidade).
    Assume que o novo equipamento é dimensionado para absorver essa demanda."""
    xy = np.column_stack([pts.geometry.x, pts.geometry.y])
    medidor = medidor or LinhaReta(xy, tree)
    resid_sem = res.sem_cobertura.copy()
    resid = res.sem_cobertura + res.deficit_cap
    ii, jj = medidor.pares(raio_pts, cand_xy, ativos=resid > 0)
    ordem = np.argsort(jj, kind="stable")
    ii, jj = ii[ordem], jj[ordem]
    limites = np.searchsorted(jj, np.arange(len(cand_xy) + 1))
    escolhidos = []
    for rodada in range(k):
        ganho = np.add.reduceat(resid[ii], limites[:-1]) if len(ii) else np.zeros(len(cand_xy))
        ganho[limites[:-1] == limites[1:]] = 0
        j = int(np.argmax(ganho))
        if ganho[j] < ganho_min:
            break
        alc = ii[limites[j]:limites[j + 1]]
        escolhidos.append({
            "tipo": tipo, "ordem": rodada + 1, "h3": cand_id[j], "x": cand_xy[j, 0], "y": cand_xy[j, 1],
            "demanda_absorvida": float(resid[alc].sum()),
            "demanda_sem_cobertura_absorvida": float(resid_sem[alc].sum()),
            "pop_faixa_no_raio": float(res.pop_faixa[alc].sum()),
        })
        resid[alc] = 0
        resid_sem[alc] = 0
    return pd.DataFrame(escolhidos)
