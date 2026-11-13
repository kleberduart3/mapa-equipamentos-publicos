"""Distância a pé pela malha viária do OpenStreetMap (fase 2).

Cada ponto (endereço, equipamento ou centro de hexágono) é ligado à via mais
próxima: anda em linha reta até ela (s) e segue pela via. Com a posição `pos`
ao longo da aresta (u→v, comprimento L):
    até u:  a = s + pos        até v:  b = s + L − pos
A distância entre um morador i e um equipamento j é o menor dos quatro
caminhos  (lado de i) + Dijkstra(nó, nó) + (lado de j), ou, se os dois estão
na mesma aresta, s_i + |pos_i − pos_j| + s_j.

A distância pela rede nunca é menor que a distância em linha reta; isso é
conferido a cada cálculo (`checagem`).
"""
from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import shapely
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from ..config import Municipio

LOTE = 250          # destinos por rodada de Dijkstra (memória: 2·LOTE × nós)


@dataclass
class Ligacao:
    aresta: np.ndarray
    u: np.ndarray
    v: np.ndarray
    a: np.ndarray       # distância até o nó u (acesso + trecho da via)
    b: np.ndarray       # distância até o nó v
    s: np.ndarray       # trecho em linha reta até a via
    pos: np.ndarray     # posição ao longo da aresta, a partir de u


class Rede:
    def __init__(self, nos: gpd.GeoDataFrame, arestas: gpd.GeoDataFrame) -> None:
        self.n = len(nos)
        self.xy_nos = np.column_stack([nos.geometry.x, nos.geometry.y])
        self.u = arestas["u"].to_numpy()
        self.v = arestas["v"].to_numpy()
        self.L = arestas["comprimento_m"].to_numpy(float)
        self.geo = arestas.geometry.to_numpy()
        self.km = float(self.L.sum() / 1000)
        self.G = csr_matrix((np.r_[self.L, self.L], (np.r_[self.u, self.v], np.r_[self.v, self.u])),
                            shape=(self.n, self.n))
        self.arvore = shapely.STRtree(self.geo)

    @classmethod
    def carregar(cls, m: Municipio) -> "Rede | None":
        pn, pa = m.processados / "rede_nos.parquet", m.processados / "rede_arestas.parquet"

        if not (pn.exists() and pa.exists()):
            return None
        return cls(gpd.read_parquet(pn), gpd.read_parquet(pa))

    # ------------------------------------------------------------------ #
    def ligar(self, xy: np.ndarray) -> Ligacao:
        p = shapely.points(xy)
        ii, ee = self.arvore.query_nearest(p, all_matches=False)
        e = np.empty(len(xy), int)
        e[ii] = ee
        g = self.geo[e]
        s = shapely.distance(p, g)
        pos = np.clip(shapely.line_locate_point(g, p), 0, self.L[e])
        return Ligacao(e, self.u[e], self.v[e], s + pos, s + self.L[e] - pos, s, pos)

    def _dijkstra(self, origens: np.ndarray, limite: float) -> np.ndarray:
        return dijkstra(self.G, directed=True, indices=origens, limit=limite)

    def pares(self, xy_pts: np.ndarray, lig_pts: Ligacao, raio_pts: np.ndarray, xy_alvo: np.ndarray,
              tree: cKDTree, ativos: np.ndarray | None = None):
        """Pares (ponto, destino) com distância a pé ≤ raio do ponto.

        Só calcula a rede para pontos dentro do raio em linha reta (limite
        inferior da distância a pé). `ativos`: máscara de pontos que interessam
        (ex.: com demanda residual) — os demais nem entram."""
        rmax = float(raio_pts.max())
        la = self.ligar(xy_alvo)
        II, JJ, DD, RETA = [], [], [], []
        for ini in range(0, len(xy_alvo), LOTE):
            js = np.arange(ini, min(ini + LOTE, len(xy_alvo)))
            viz_lote = [np.asarray(v, int) for v in tree.query_ball_point(xy_alvo[js], rmax)]
            if ativos is not None:
                viz_lote = [v[ativos[v]] for v in viz_lote]
            precisa = [k for k, viz in enumerate(viz_lote) if len(viz)]
            if not precisa:
                continue
            orig = np.r_[la.u[js[precisa]], la.v[js[precisa]]]
            uni, inv = np.unique(orig, return_inverse=True)
            D = self._dijkstra(uni, rmax)
            m = len(precisa)
            for k, idx in enumerate(precisa):
                j = js[idx]
                viz = viz_lote[idx]
                reta = np.hypot(*(xy_pts[viz] - xy_alvo[j]).T)
                viz, reta = viz[reta <= raio_pts[viz]], reta[reta <= raio_pts[viz]]
                if not len(viz):
                    continue
                du, dv = D[inv[k]], D[inv[m + k]]
                ui, vi, ai, bi = lig_pts.u[viz], lig_pts.v[viz], lig_pts.a[viz], lig_pts.b[viz]
                c, e = la.a[j], la.b[j]
                d = np.minimum.reduce([c + du[ui] + ai, c + du[vi] + bi, e + dv[ui] + ai, e + dv[vi] + bi])
                mesma = lig_pts.aresta[viz] == la.aresta[j]
                if mesma.any():
                    d[mesma] = np.minimum(d[mesma], lig_pts.s[viz][mesma] + np.abs(lig_pts.pos[viz][mesma] - la.pos[j])
                                          + la.s[j])
                ok = d <= raio_pts[viz]
                II.append(viz[ok])
                JJ.append(np.full(ok.sum(), j))
                DD.append(d[ok])
                RETA.append(reta[ok])
        if not II:
            z = np.array([], int)
            return z, z, np.array([]), np.array([])
        return np.concatenate(II), np.concatenate(JJ), np.concatenate(DD), np.concatenate(RETA)

    # ------------------------------------------------------------------ #
    def distancia_mais_proxima(self, lig_pts: Ligacao, xy_alvo: np.ndarray, limite: float = 30_000) -> np.ndarray:
        """Distância a pé de cada ponto até o destino MAIS PRÓXIMO, num Dijkstra só:
        um nó virtual ligado às duas pontas da via de cada destino (com o trecho
        até elas) vira a origem. Sem caminho até `limite` metros: inf."""
        from scipy.sparse import coo_matrix

        la = self.ligar(xy_alvo)
        n = self.n
        # pesos do nó virtual: o menor trecho até cada nó (vários destinos podem dividir um nó)
        nos = np.r_[la.u, la.v]
        pes = np.r_[la.a, la.b] + 1e-6           # > 0: a csgraph ignora arestas de peso zero
        ordem = np.lexsort((pes, nos))
        nos, pes = nos[ordem], pes[ordem]
        primeiro = np.r_[True, nos[1:] != nos[:-1]]
        nos, pes = nos[primeiro], pes[primeiro]
        g = self.G.tocoo()
        G2 = coo_matrix((np.r_[g.data, pes], (np.r_[g.row, np.full(len(nos), n)], np.r_[g.col, nos])),
                        shape=(n + 1, n + 1)).tocsr()
        D = dijkstra(G2, directed=True, indices=n, limit=limite)
        d = np.minimum(lig_pts.a + D[lig_pts.u], lig_pts.b + D[lig_pts.v])
        # quem mora na mesma via de um destino pode ir direto, sem passar pelas pontas
        for j in range(len(xy_alvo)):
            mesma = np.flatnonzero(lig_pts.aresta == la.aresta[j])
            if len(mesma):
                direto = lig_pts.s[mesma] + np.abs(lig_pts.pos[mesma] - la.pos[j]) + la.s[j]
                d[mesma] = np.minimum(d[mesma], direto)
        return d

    def areas_servico(self, xy_alvo: np.ndarray, raios: np.ndarray, buffer_m: float = 40) -> list:
        """Polígono de alcance a pé de cada destino: as vias alcançáveis dentro
        do raio, com uma faixa de `buffer_m` de cada lado (os lotes de frente)."""
        from shapely.ops import substring

        la = self.ligar(xy_alvo)
        out = []
        for ini in range(0, len(xy_alvo), LOTE):
            js = np.arange(ini, min(ini + LOTE, len(xy_alvo)))
            orig = np.r_[la.u[js], la.v[js]]
            uni, inv = np.unique(orig, return_inverse=True)
            D = self._dijkstra(uni, float(raios[js].max()))
            m = len(js)
            for k, j in enumerate(js):
                r = float(raios[j]) - la.s[j]
                if r <= 0:
                    out.append(shapely.Point(xy_alvo[j]).buffer(float(raios[j])))
                    continue
                dn = np.minimum(la.a[j] - la.s[j] + D[inv[k]], la.b[j] - la.s[j] + D[inv[m + k]])
                du, dv = dn[self.u], dn[self.v]
                fu, fv = np.clip(r - du, 0, None), np.clip(r - dv, 0, None)   # quanto se anda a partir de cada ponta
                inteira = fu + fv >= self.L
                linhas = list(self.geo[inteira])
                parc = np.flatnonzero(~inteira & ((fu > 0) | (fv > 0)))
                for e in parc:
                    if fu[e] > 0:
                        linhas.append(substring(self.geo[e], 0, fu[e]))
                    if fv[e] > 0:
                        linhas.append(substring(self.geo[e], self.L[e] - fv[e], self.L[e]))
                # a própria via do equipamento, para os dois lados
                e0, p0 = la.aresta[j], la.pos[j]
                linhas.append(substring(self.geo[e0], max(p0 - r, 0), min(p0 + r, self.L[e0])))
                linhas.append(shapely.LineString([xy_alvo[j], shapely.get_coordinates(
                    shapely.line_interpolate_point(self.geo[e0], p0))[0]]))
                g = shapely.buffer(shapely.multilinestrings([l for l in linhas if not l.is_empty and l.length > 0]),
                                   buffer_m, quad_segs=2)
                out.append(shapely.simplify(g, 8))
        return out


def diagnostico_ligacao(lig: Ligacao, peso: np.ndarray, rural: np.ndarray) -> dict:
    """Quanto da população precisa andar fora das vias mapeadas até chegar a uma."""
    out = {}
    for nome, m in (("urbana", ~rural), ("rural", rural)):
        s, w = lig.s[m], peso[m]
        if not len(s) or w.sum() == 0:
            continue
        ordem = np.argsort(s)
        acum = np.cumsum(w[ordem]) / w.sum()
        out[nome] = {
            "mediana_m": round(float(s[ordem][np.searchsorted(acum, 0.5)]), 1),
            "p90_m": round(float(s[ordem][np.searchsorted(acum, 0.9)]), 1),
            "pct_pop_acima_200m": round(float(100 * w[s > 200].sum() / w.sum()), 1),
            "pct_pop_acima_500m": round(float(100 * w[s > 500].sum() / w.sum()), 1),
        }
    return out
