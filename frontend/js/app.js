/* Mapa de Equipamentos Públicos – frontend (MapLibre + OpenStreetMap) */
"use strict";

const st = {
  cod: null, cfg: null, map: null,
  equip: null,                // GeoJSON de equipamentos
  pins: {},                   // tipo -> [maplibregl.Marker]
  radares: {},                // tipo -> [maplibregl.Marker]
  cob: {},                    // tipo -> resposta /cobertura
  raio: {},                   // tipo -> raio urbano atual (m)
  visivel: {},                // tipo -> bool
  mostrar: null,              // tipo do déficit no mapa ou "prioridade"
  timers: {},
  modo: "reta",               // distância: "reta" (linha reta) ou "rede" (a pé pelas ruas)
  areas: {},                  // tipo -> GeoJSON de alcance a pé (modo rede)
  prio: {},                   // modo -> GeoJSON de prioridade
  unid: "hex",                // déficit no mapa: "hex" (hexágonos) ou "setor" (setores do IBGE)
  setores: {},                // "tipo|raio|modo" -> GeoJSON de déficit por setor
  ranking: null,              // resposta /ranking do tipo mostrado
  rankingTodos: false,
  simulando: false,           // esperando o clique no mapa
  sim: null,                  // { tipo, marcador, lngLat }
};
const APE = () => st.modo === "rede";
const txtDist = () => (APE() ? "a pé pelas ruas" : "em linha reta");
/* metros → minutos a pé (velocidade do parametros.yaml, padrão 80 m/min) */
const minutos = (m) => Math.max(1, Math.round(m / (st.cfg?.velocidade_caminhada_m_min || 80)));
const txtMin = (m) => `≈ ${minutos(m)} min a pé`;
/* "até 6 min a pé": a distância aceitável dita em tempo (a conta continua em metros) */
const ateMin = (m) => `até ${minutos(m)} min a pé`;
const cercaDe = (m) => (m >= 1000 ? `cerca de ${fmt(m / 1000, m % 1000 ? 1 : 0)} km` : `cerca de ${fmt(m)} m`);
const nomeTipo = (c) => c.rotulo.split(" (")[0].toLowerCase();

const fmt = (n, c = 0) => Number(n).toLocaleString("pt-BR", { maximumFractionDigits: c, minimumFractionDigits: c });
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* Versão estática (GitHub Pages): sem servidor Python, lê respostas pré-calculadas
   geradas por backend/scripts/exportar_estatico.py. */
let ESTATICO = null;
function rotaEstatica(caminho) {
  const u = new URL(caminho, "http://x"), q = u.searchParams;
  const [, cod, rec] = u.pathname.split("/");
  if (cod === "municipios") return "dados/municipios.json";
  if (rec === "cobertura") return `dados/${cod}/cobertura/${q.get("modo") || "reta"}/${q.get("tipo")}_${q.get("raio")}.json`;
  if (rec === "areas") return `dados/${cod}/areas/${q.get("tipo")}_${q.get("raio")}.json`;
  if (rec === "prioridade") return `dados/${cod}/prioridade_${q.get("modo") || "reta"}.json`;
  return `dados/${cod}/${rec}.json`;
}

/* Chamada à API do servidor. Escritas levam o cabeçalho X-CSRF (proteção contra
   requisições forjadas por outros sites); sessão expirada volta para o login. */
async function requisitar(url, opts = {}) {
  const metodo = (opts.method || "GET").toUpperCase();
  const headers = { Accept: "application/json", ...(opts.headers || {}) };
  if (metodo !== "GET" && metodo !== "HEAD") headers["X-CSRF"] = "1";
  const r = await fetch(url, { credentials: "same-origin", ...opts, headers });
  if (r.status === 401 && !ESTATICO) {
    location.href = "/entrar";
    throw new Error("sessão expirada");
  }
  return r;
}

async function detalheErro(r) {
  try { const j = await r.json(); if (typeof j.detail === "string") return j.detail; } catch { /* sem corpo */ }
  return `erro ${r.status}`;
}

async function api(caminho, opts) {
  const r = ESTATICO ? await fetch(rotaEstatica(caminho), opts) : await requisitar(`/api${caminho}`, opts);
  if (!r.ok) throw new Error(ESTATICO ? `${r.status} ${caminho}` : await detalheErro(r));
  return r.json();
}

/* ---------- Ícones ---------- */
const GLIFO = {
  blocos: '<rect x="6.5" y="12.5" width="5" height="5" rx=".8"/><rect x="12.5" y="12.5" width="5" height="5" rx=".8"/><rect x="9.5" y="6.5" width="5" height="5" rx=".8"/>',
  estrela: '<path d="M12 5.8l1.9 3.9 4.3.6-3.1 3 .7 4.3L12 15.6l-3.8 2 .7-4.3-3.1-3 4.3-.6z"/>',
  livro: '<path d="M7.5 6.5h7.8a1.2 1.2 0 0 1 1.2 1.2v10.8H8.7a1.2 1.2 0 0 1-1.2-1.2z"/><path d="M9.6 9.2h4.8" stroke="#000" stroke-opacity=".25" stroke-width="1.1"/>',
  livro_aberto: '<path d="M5.5 8c2.4-.9 4.6-.6 6.5.8v9.4c-1.9-1.3-4.1-1.6-6.5-.8zM18.5 8c-2.4-.9-4.6-.6-6.5.8v9.4c1.9-1.3 4.1-1.6 6.5-.8z"/>',
  cruz: '<path d="M10.2 6.5h3.6v3.7h3.7v3.6h-3.7v3.7h-3.6v-3.7H6.5v-3.6h3.7z"/>',
  ponto: '<circle cx="12" cy="12" r="4"/>',
};

function svgPin(cor, icone, aprox) {
  const anel = aprox ? '<circle cx="13" cy="12.5" r="12" fill="none" stroke="#C93A27" stroke-width="1.6" stroke-dasharray="3 2.2"/>' : "";
  return `<svg viewBox="-1 -1 28 36" width="28" height="36" aria-hidden="true">
    <path d="M13 34S2 21.2 2 12.6a11 11 0 0 1 22 0C24 21.2 13 34 13 34Z" fill="${cor}" stroke="#fff" stroke-width="1.5"/>
    <g fill="#fff" transform="translate(1 0.6)">${GLIFO[icone] || GLIFO.ponto}</g>${anel}</svg>`;
}

function svgIcone(cor, icone) {
  return `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="${cor}"/>
    <g fill="#fff">${GLIFO[icone] || GLIFO.ponto}</g></svg>`;
}

/* ---------- Geometria: círculo em metros ---------- */
function circulo([lng, lat], r, n = 72) {
  const dLat = r / 111320, dLng = r / (111320 * Math.cos((lat * Math.PI) / 180));
  const c = [];
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * 2 * Math.PI;
    c.push([lng + dLng * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  return c;
}

const PRECISAS = new Set(["inep_catalogo", "cnes", "cnefe_nome_no_cep", "prefeitura"]);
const raioEfetivo = (t, f) => st.raio[t] * (f.properties.rural ? st.cfg.fator_raio_rural : 1);

/* ---------- Início ---------- */
const CHAVE_MUNICIPIO = "mapa.municipio";

async function iniciar() {
  // No servidor: exige login. Sem servidor (versão estática exportada): lê os JSON pré-calculados.
  let eu = null;
  try {
    const r = await fetch("/auth/eu", { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (r.status === 401) { location.href = "/entrar"; return; }
    if (r.ok && (r.headers.get("content-type") || "").includes("json")) eu = await r.json();
  } catch { /* sem servidor */ }
  if (!eu) {
    try {
      const r = await fetch("dados/estatico.json");
      if (r.ok) ESTATICO = await r.json();
    } catch { /* nada */ }
  }
  if (ESTATICO) {
    $("#btn-pdf").textContent = "Baixar relatório PDF";
    $("#btn-pdf").title = "Versão online: relatório pronto com as distâncias padrão, no modo de medir selecionado";
  }
  if (eu) ligarConta(eu);
  const munis = await api("/municipios");
  if (!munis.length) { $("#aviso-vazio").hidden = false; return; }
  const sel = $("#municipio");
  sel.innerHTML = munis.map((m) => `<option value="${esc(m.codigo)}">${esc(m.nome)} – ${esc(m.uf)}</option>`).join("");
  sel.addEventListener("change", () => carregarMunicipio(sel.value));
  ligarUpload();
  ligarPdf();
  ligarVisoes();
  let lembrado = null;
  try { lembrado = localStorage.getItem(CHAVE_MUNICIPIO); } catch { /* armazenamento bloqueado */ }
  const link = lerLinkVisao();
  if (link && munis.some((m) => m.codigo === link.cod)) lembrado = link.cod;
  const inicial = munis.some((m) => m.codigo === lembrado) ? lembrado : munis[0].codigo;
  sel.value = inicial;
  await carregarMunicipio(inicial);
  if (link?.cod === inicial) await abrirVisaoDoLink(link.id);
}

/* ---------- Conta (menu do usuário) ---------- */
function ligarConta(eu) {
  $("#conta").hidden = false;
  const btn = $("#btn-conta"), menu = $("#menu-conta");
  btn.textContent = eu.nome.split(" ")[0];
  btn.title = eu.email;
  $("#lnk-admin").hidden = eu.papel !== "admin";
  const fechar = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  btn.onclick = (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    btn.setAttribute("aria-expanded", String(!menu.hidden));
  };
  document.addEventListener("click", (e) => { if (!menu.contains(e.target)) fechar(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") fechar(); });
  $("#btn-sair").onclick = async () => {
    await requisitar("/auth/sair", { method: "POST" }).catch(() => null);
    location.href = "/entrar";
  };
  const dlg = $("#dlg-senha");
  $("#btn-trocar-senha").onclick = () => { fechar(); $("#form-senha").reset(); $("#res-senha").textContent = ""; dlg.showModal(); };
  $("#btn-senha-fechar").onclick = () => dlg.close();
  $("#form-senha").onsubmit = async (e) => {
    e.preventDefault();
    $("#res-senha").textContent = "Salvando…";
    const r = await requisitar("/auth/trocar-senha", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ senha_atual: $("#senha-atual").value, nova: $("#senha-nova").value }),
    });
    $("#res-senha").textContent = r.ok ? "Senha alterada. As outras sessões foram encerradas." : await detalheErro(r);
    if (r.ok) $("#form-senha").reset();
  };
}

async function carregarMunicipio(cod) {
  st.cod = cod;
  st.visoes = null;
  try { localStorage.setItem(CHAVE_MUNICIPIO, cod); } catch { /* armazenamento bloqueado */ }
  st.cfg = await api(`/${cod}/config`);
  $("#btn-upload").hidden = Boolean(ESTATICO) || st.cfg.papel !== "gestor";
  const tipos = Object.keys(st.cfg.tipos);
  tipos.forEach((t) => { st.raio[t] = st.cfg.tipos[t].raio_m; st.visivel[t] = true; });
  st.modo = st.cfg.distancia_padrao || "reta";
  st.areas = {}; st.prio = {}; st.setores = {}; st.ranking = null;
  st.mostrar = tipos[0];
  limparSimulacao();
  ["sec-ranking", "sec-simular", "unid-mapa"].forEach((id) => { $(`#${id}`).hidden = Boolean(ESTATICO); });
  $("#lnk-equipamentos").hidden = Boolean(ESTATICO);

  if (!st.map) criarMapa();
  else limparMapa();

  const [limite, equip] = await Promise.all([api(`/${cod}/limite`), api(`/${cod}/equipamentos`)]);
  st.equip = equip;
  const b = st.cfg.bbox;
  st.map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 40, duration: 0 });

  await new Promise((pronto) => aoCarregar(() => {
    fonte("limite", limite);
    camada({ id: "limite-linha", type: "line", source: "limite", paint: { "line-color": "#0D1450", "line-width": 2, "line-dasharray": [3, 2] } });
    fonte("deficit", vazio());
    camada({ id: "deficit", type: "fill", source: "deficit", paint: {
      "fill-color": ["interpolate", ["linear"], ["get", "deficit"], 0, "#FFE9E5", 20, "#FFB3A8", 80, "#FF6B57", 300, "#C93A27"],
      "fill-opacity": 0.55 } });
    camada({ id: "deficit-borda", type: "line", source: "deficit", paint: {
      "line-color": "#C93A27", "line-opacity": ["case", ["==", ["get", "_unid"], "setor"], 0.35, 0], "line-width": 0.6 } });
    fonte("prioridade", vazio());
    camada({ id: "prioridade", type: "fill", source: "prioridade", layout: { visibility: "none" }, paint: {
      "fill-color": ["interpolate", ["linear"], ["get", "prioridade_geral"], 1, "#FFF1EE", 10, "#FFB3A8", 25, "#FF6B57", 45, "#8E2A1C"],
      "fill-opacity": 0.6 } });
    fonte("simulacao", vazio());
    camada({ id: "simulacao-fill", type: "fill", source: "simulacao", paint: { "fill-color": "#2F4BFF", "fill-opacity": 0.12 } });
    camada({ id: "simulacao-linha", type: "line", source: "simulacao", paint: {
      "line-color": "#2F4BFF", "line-width": 2, "line-dasharray": [2, 1.5] } });
    ligarCliquesMapa();
    tipos.forEach((t) => {
      const cor = st.cfg.tipos[t].cor;
      fonte(`raios-${t}`, vazio());
      camada({ id: `raios-fill-${t}`, type: "fill", source: `raios-${t}`, filter: ["==", ["get", "anel"], 1],
        paint: { "fill-color": cor, "fill-opacity": 0.07 } });
      camada({ id: `raios-linha-${t}`, type: "line", source: `raios-${t}`, paint: {
        "line-color": cor, "line-width": ["match", ["get", "anel"], 1, 1.6, 1],
        "line-opacity": ["match", ["get", "anel"], 1, 0.75, 2, 0.4, 0.22] } });
      desenharRaios(t);
    });
    montarLateral();
    desenharPins();
    tipos.forEach((t) => atualizarCobertura(t));
    pronto();
  }));
  carregarVisoes();
}

function criarMapa() {
  // Mapa de fundo: o servidor informa o provedor (MAPA_MOSAICOS_URL); sem servidor, OpenStreetMap.
  const base = st.cfg?.mapa_base || { url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    atribuicao: "© OpenStreetMap contributors", zoom_max: 19 };
  st.map = new maplibregl.Map({
    container: "mapa",
    style: {
      version: 8,
      sources: { osm: { type: "raster", tiles: [base.url], tileSize: 256, maxzoom: base.zoom_max,
        attribution: `${esc(base.atribuicao)} · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">dados OpenStreetMap</a>` } },
      layers: [{ id: "osm", type: "raster", source: "osm" }],
    },
    center: [-36.66, -9.75], zoom: 12, attributionControl: { compact: false },
  });
  st.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  st.map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
}

/* Roda fn quando o estilo do mapa estiver pronto. Não usa map.loaded(): ele fica
   false enquanto houver mosaicos carregando, e o evento "load" só dispara uma vez –
   se os dados chegassem depois dele, fn nunca rodaria. */
function aoCarregar(fn) { st.map.isStyleLoaded() ? fn() : st.map.once("load", fn); }

const vazio = () => ({ type: "FeatureCollection", features: [] });
function fonte(id, dados) { st.map.getSource(id) ? st.map.getSource(id).setData(dados) : st.map.addSource(id, { type: "geojson", data: dados }); }
function camada(def) { if (!st.map.getLayer(def.id)) st.map.addLayer(def); }
function limparMapa() {
  Object.values(st.pins).flat().forEach((m) => m.remove());
  Object.values(st.radares).flat().forEach((m) => m.remove());
  st.pins = {}; st.radares = {}; st.cob = {};
}

/* ---------- Raios (anéis tipo radar) ---------- */
function desenharRaios(t) {
  const feats = [];
  const ligado = st.visivel[t] && $("#tg-raios")?.checked !== false;
  if (APE()) {                                   // alcance a pé: polígonos vindos da API
    const a = st.areas[t];
    fonte(`raios-${t}`, ligado && a && a.raio === st.raio[t] ? a.dados : vazio());
    return;
  }
  if (ligado) {
    st.equip.features.filter((f) => f.properties.tipo === t).forEach((f) => {
      const r = raioEfetivo(t, f);
      [[1, 1], [2, 0.66], [3, 0.33]].forEach(([anel, k]) => feats.push({
        type: "Feature", properties: { anel },
        geometry: { type: "Polygon", coordinates: [circulo(f.geometry.coordinates, r * k)] } }));
    });
  }
  fonte(`raios-${t}`, { type: "FeatureCollection", features: feats });
}

async function carregarAreas(t) {
  const raio = st.raio[t], modo = st.modo;
  if (st.areas[t]?.raio === raio) { desenharRaios(t); return; }
  const dados = await api(`/${st.cod}/areas?tipo=${t}&raio=${raio}`);
  dados.features.forEach((f) => (f.properties.anel = 1));
  if (raio !== st.raio[t] || modo !== st.modo) return;
  st.areas[t] = { raio, dados };
  desenharRaios(t);
}

/* ---------- Pins ---------- */
function desenharPins() {
  const porId = {};
  st.equip.features.forEach((f) => (porId[f.properties.id] ??= []).push(f));
  Object.values(porId).forEach((lista) => lista.forEach((f, i) => {
    const p = f.properties, cfgT = st.cfg.tipos[p.tipo] || { cor: "#6b7280", icone: "livro", rotulo: "Ensino médio (contexto)" };
    const el = document.createElement("div");
    el.className = "pin";
    el.innerHTML = svgPin(cfgT.cor, cfgT.icone, !PRECISAS.has(p.fonte_coord));
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", `${cfgT.rotulo}: ${p.nome}`);
    const desloc = (i - (lista.length - 1) / 2) * 15;
    const pop = new maplibregl.Popup({ offset: 30, maxWidth: "320px" });
    pop.on("open", () => pop.setHTML(popupEquip(p, cfgT)));     // raio e modo atuais
    const m = new maplibregl.Marker({ element: el, anchor: "bottom", offset: [desloc, 0] })
      .setLngLat(f.geometry.coordinates).setPopup(pop).addTo(st.map);
    if (p.tipo === "contexto_medio") el.style.display = $("#tg-estaduais").checked ? "" : "none";
    (st.pins[p.tipo] ??= []).push(m);
  }));
}

function popupEquip(p, c) {
  const linhas = [["Rede", p.rede], ["Bairro", p.bairro || "–"]];
  if (p.tipo === "ubs") linhas.push(["Equipes de Saúde da Família", p.equipes], ["Endereço", p.endereco]);
  else {
    const mat = { creche: p.mat_creche, pre_escola: p.mat_pre_escola, fundamental_iniciais: p.mat_fund_iniciais,
      fundamental_finais: p.mat_fund_finais };
    [["Creche", "creche"], ["Pré-escola", "pre_escola"], ["Anos iniciais", "fundamental_iniciais"], ["Anos finais", "fundamental_finais"]]
      .forEach(([rot, k]) => { if (mat[k]) linhas.push([`Matrículas – ${rot}`, fmt(mat[k])]); });
    if (p.mat_medio) linhas.push(["Matrículas – Ensino médio", fmt(p.mat_medio)]);
  }
  if (p.capacidade != null && st.raio[p.tipo]) {
    const un = p.tipo === "ubs" ? "pessoas" : "vagas";
    linhas.push(["Capacidade usada na conta", `${fmt(p.capacidade)} ${un}${p.ajuste_prefeitura ? " · informada pela prefeitura" : ""}`]);
  }
  if (st.raio[p.tipo]) {
    const r = st.raio[p.tipo] * (p.rural ? st.cfg.fator_raio_rural : 1);
    linhas.push(["Atende quem mora", `${ateMin(r)} (${cercaDe(r)}${APE() ? "" : " em linha reta"})${p.rural ? " · zona rural" : ""}`]);
  }
  const alerta = PRECISAS.has(p.fonte_coord) ? "" :
    `<div class="alerta">Localização ${p.fonte_coord === "sem_coordenada" ? "ausente" : "aproximada"} – confirmar com a prefeitura.</div>`;
  return `<div class="pop"><span class="tag" style="background:${c.cor}">${esc(c.rotulo)}</span>
    <h4>${esc(p.nome)}</h4><dl>${linhas.map(([a, b]) => `<dt>${esc(a)}</dt><dd>${esc(b)}</dd>`).join("")}</dl>${alerta}
    ${ESTATICO || !st.raio[p.tipo] ? "" : `<a class="pop-link" href="/equipamentos?tipo=${encodeURIComponent(p.tipo)}">${st.cfg.papel === "gestor" ? "Conferir ou ajustar no cadastro" : "Ver no cadastro"} →</a>`}</div>`;
}

/* ---------- Cobertura, déficit e radar ---------- */
function atualizarCobertura(t, atraso = 0) {
  clearTimeout(st.timers[t]);
  st.timers[t] = setTimeout(async () => {
    st.pendentes = (st.pendentes || 0) + 1;
    $("#carregando").hidden = false; $("#carregando").textContent = "Calculando…";
    const raioPedido = st.raio[t], modoPedido = st.modo;
    try {
      const [d] = await Promise.all([api(`/${st.cod}/cobertura?tipo=${t}&raio=${raioPedido}&modo=${modoPedido}`),
        modoPedido === "rede" ? carregarAreas(t) : null]);
      if (raioPedido !== st.raio[t] || modoPedido !== st.modo) return;   // resposta antiga: slider ou modo mudou
      st.cob[t] = d;
      desenharRadares(t);
      if (st.mostrar === t) { atualizarDeficit(); atualizarRanking(); }
      if (st.sim?.tipo === t) simular(st.sim.lngLat);
      atualizarKpis();
      atualizarLegenda();
    } finally {
      st.pendentes -= 1;
      $("#carregando").hidden = st.pendentes > 0 ? false : true;
    }
  }, atraso);
}

function desenharRadares(t) {
  (st.radares[t] || []).forEach((m) => m.remove());
  st.radares[t] = [];
  const c = st.cfg.tipos[t], d = st.cob[t];
  if (!d) return;
  d.radar.features.forEach((f) => {
    const p = f.properties;
    const el = document.createElement("div");
    el.className = "radar";
    el.style.setProperty("--cor", c.cor);
    el.innerHTML = `<span class="onda"></span><span class="onda"></span><span class="onda"></span><span class="nucleo"></span><span class="num">${p.ordem}</span>`;
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", `Área prioritária ${p.ordem} para ${c.rotulo}`);
    const html = `<div class="pop"><span class="tag" style="background:${c.cor}">Área prioritária ${p.ordem} · ${esc(c.rotulo)}</span>
      <h4>${esc(p.bairro || "Área sem bairro definido")}</h4>
      <dl><dt>Demanda que um novo equipamento absorveria</dt><dd>${fmt(p.demanda_absorvida)} ${c.unidade}</dd>
      <dt>Hoje moram longe de qualquer unidade</dt><dd>${fmt(p.sem_cobertura)} ${c.unidade}</dd>
      <dt>Distância considerada</dt><dd>${ateMin(st.raio[t])} (${cercaDe(st.raio[t])})</dd></dl>
      <div class="nota">Área de estudo (hexágono de ~0,1 km²), não endereço definitivo.</div></div>`;
    const m = new maplibregl.Marker({ element: el }).setLngLat(f.geometry.coordinates)
      .setPopup(new maplibregl.Popup({ offset: 14, maxWidth: "300px" }).setHTML(html)).addTo(st.map);
    el.style.display = st.visivel[t] && $("#tg-radar").checked ? "" : "none";
    st.radares[t].push(m);
  });
}

async function mudarMostrar(v) {
  st.mostrar = v;
  const prio = v === "prioridade";
  st.map.setLayoutProperty("deficit", "visibility", prio ? "none" : "visible");
  st.map.setLayoutProperty("prioridade", "visibility", prio ? "visible" : "none");
  if (prio) {
    const modo = st.modo;
    $("#nota-deficit").textContent = `Índice 0–100 que combina, para todos os tipos, gente morando longe (2/3) e falta de vagas ou equipes (1/3). Calculado com as distâncias padrão, ${txtDist()}.`;
    if (!st.prio[modo]) {
      $("#carregando").hidden = false;
      try { st.prio[modo] = await api(`/${st.cod}/prioridade?modo=${modo}`); } finally { $("#carregando").hidden = !(st.pendentes > 0); }
    }
    if (st.mostrar === "prioridade" && modo === st.modo) fonte("prioridade", st.prio[modo]);
  } else {
    atualizarDeficit();
    $("#nota-deficit").textContent = `${st.unid === "setor" ? "Setores censitários" : "Hexágonos"} em coral: ${st.cfg.tipos[v].unidade} morando a mais de ${minutos(st.raio[v])} min a pé de uma ${nomeTipo(st.cfg.tipos[v])}, ou onde faltam vagas. Quanto mais escuro, maior a demanda não resolvida. Clique numa área para ver os números.`;
  }
  $("#unid-mapa").hidden = Boolean(ESTATICO) || prio;
  atualizarRanking();
  atualizarKpis();
}

/* ---------- Déficit por hexágono ou por setor censitário ---------- */
const RAMPA_HEX = [0, "#FFE9E5", 20, "#FFB3A8", 80, "#FF6B57", 300, "#C93A27"];

async function atualizarDeficit() {
  const t = st.mostrar;
  if (!st.map.getLayer("deficit") || t === "prioridade") return;
  if (st.unid === "hex" || ESTATICO) {
    st.map.setPaintProperty("deficit", "fill-color", ["interpolate", ["linear"], ["get", "deficit"], ...RAMPA_HEX]);
    fonte("deficit", st.cob[t]?.hex || vazio());
    return;
  }
  const chave = `${t}|${st.raio[t]}|${st.modo}`;
  if (!st.setores[chave]) {
    st.setores[chave] = await api(`/${st.cod}/setores?tipo=${t}&raio=${st.raio[t]}&modo=${st.modo}`);
    st.setores[chave].features.forEach((f) => (f.properties._unid = "setor"));
  }
  if (st.mostrar !== t || st.unid !== "setor" || chave !== `${t}|${st.raio[t]}|${st.modo}`) return;
  const fc = st.setores[chave];
  // setores têm tamanhos muito diferentes: a escala segue os quantis do próprio município
  const v = fc.features.map((f) => f.properties.deficit).filter((x) => x > 0.5).sort((a, b) => a - b);
  const q = (p) => v.length ? v[Math.min(v.length - 1, Math.floor(p * v.length))] : 1;
  const paradas = [0, q(0.25), q(0.6), q(0.9)].map((x, i, a) => (i && x <= a[i - 1] ? a[i - 1] + 0.01 * i : x));
  st.map.setPaintProperty("deficit", "fill-color", ["interpolate", ["linear"], ["get", "deficit"],
    paradas[0], "#FFE9E5", paradas[1], "#FFB3A8", paradas[2], "#FF6B57", paradas[3], "#C93A27"]);
  fonte("deficit", { type: "FeatureCollection", features: fc.features.filter((f) => f.properties.deficit > 0.5) });
}

/* ---------- Cliques no mapa: popup do déficit ou ponto da simulação ---------- */
function ligarCliquesMapa() {
  if (st.cliquesLigados) return;
  st.cliquesLigados = true;
  st.map.on("click", (e) => {
    if (!st.simulando) return;
    st.simulando = false;
    st.map.getCanvas().style.cursor = "";
    $("#sim-instrucao").hidden = true;
    posicionarSimulacao(e.lngLat);
  });
  st.map.on("click", "deficit", (e) => {
    if (st.simulando || st.mostrar === "prioridade") return;
    const p = e.features[0].properties, c = st.cfg.tipos[st.mostrar];
    const linhas = [];
    if (p.bairro) linhas.push(["Bairro", p.bairro]);
    linhas.push([`${c.unidade[0].toUpperCase() + c.unidade.slice(1)} que moram longe (mais de ${minutos(st.raio[st.mostrar])} min a pé)`, fmt(p.pop_descoberta)]);
    if (p.pct_fora != null) linhas.push(["Parcela que mora longe", `${fmt(p.pct_fora, 0)}%`]);
    if (p.deficit_capacidade > 0.5) linhas.push(["Falta de vagas nas unidades próximas", fmt(p.deficit_capacidade)]);
    if (p.tempo_medio_min != null && p.tempo_medio_min !== "null")
      linhas.push([`Tempo médio a pé até a ${c.rotulo.split(" (")[0].toLowerCase()} mais próxima`, `${fmt(p.tempo_medio_min, 0)} min`]);
    const titulo = p._unid === "setor" ? `Setor censitário ${p.setor}` : "Área de ~0,1 km² (hexágono)";
    new maplibregl.Popup({ maxWidth: "300px" }).setLngLat(e.lngLat).setHTML(
      `<div class="pop"><span class="tag" style="background:${c.cor}">${esc(c.rotulo)}</span><h4>${esc(titulo)}</h4>
       <dl>${linhas.map(([a, b]) => `<dt>${esc(a)}</dt><dd>${esc(b)}</dd>`).join("")}</dl>
       <div class="nota">Tempo ${APE() ? "a pé pelas ruas" : "pela distância em linha reta (fica abaixo do real)"},
         a ${fmt(st.cfg.velocidade_caminhada_m_min || 80)} m por minuto.</div></div>`).addTo(st.map);
  });
  st.map.on("mouseenter", "deficit", () => { if (!st.simulando) st.map.getCanvas().style.cursor = "pointer"; });
  st.map.on("mouseleave", "deficit", () => { if (!st.simulando) st.map.getCanvas().style.cursor = ""; });
}

/* ---------- Ranking de bairros ---------- */
async function atualizarRanking() {
  if (ESTATICO) return;
  const t = st.mostrar === "prioridade" ? null : st.mostrar;
  if (!t) {
    $("#ranking-titulo").textContent = "Escolha um serviço no passo 01 para ver os bairros com mais gente morando longe.";
    $("#ranking").innerHTML = "";
    return;
  }
  const raio = st.raio[t], modo = st.modo;
  const r = await api(`/${st.cod}/ranking?tipo=${t}&raio=${raio}&modo=${modo}`);
  if (st.mostrar !== t || st.raio[t] !== raio || st.modo !== modo) return;
  st.ranking = r;
  desenharRanking();
}

function desenharRanking() {
  const r = st.ranking, c = st.cfg.tipos[r.tipo];
  const com = r.bairros.filter((b) => b.pop_fora >= 1);
  $("#ranking-titulo").textContent = `${c.rotulo.split(" (")[0]} · longe = mais de ${minutos(r.raio_m)} min a pé`
    + ` (${cercaDe(r.raio_m)}${r.modo === "rede" ? " pelas ruas" : " em linha reta"}). ${fmt(r.total_fora)} ${r.unidade} moram longe no município.`;
  const lista = st.rankingTodos ? com : com.slice(0, 8);
  $("#ranking").innerHTML = lista.map((b, i) => `
    <li><button type="button" class="ranking-item" data-i="${i}">
      <span class="ranking-nome">${esc(b.bairro)}</span>
      <span class="ranking-num">${fmt(b.pop_fora)}</span>
      <span class="ranking-sub">${fmt(b.pct_fora, 0)}% moram longe${b.tempo_medio_min != null ? ` · ${fmt(b.tempo_medio_min, 0)} min a pé, em média, até a mais próxima` : ""}</span>
    </button></li>`).join("") || `<li class="nota">Ninguém mora longe com essa distância.</li>`;
  $("#ranking").querySelectorAll(".ranking-item").forEach((el) => (el.onclick = () => {
    const bb = lista[Number(el.dataset.i)].bbox;
    st.map.fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]], { padding: 60, maxZoom: 15 });
  }));
  $("#btn-ranking-todos").hidden = com.length <= 8;
  $("#btn-ranking-todos").textContent = st.rankingTodos ? "Ver só os 8 primeiros" : `Ver todos (${com.length})`;
  $("#btn-ranking-todos").setAttribute("aria-expanded", String(st.rankingTodos));
}

function baixarRankingCsv() {
  const r = st.ranking;
  if (!r) return;
  const cab = ["bairro", `${r.unidade}_na_faixa`, `${r.unidade}_moram_longe`, "pct_mora_longe",
    "falta_de_capacidade", "demanda_nao_resolvida", "tempo_medio_a_pe_min", "zona_rural"];
  const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const linhas = r.bairros.map((b) => [b.bairro, b.pop_faixa, b.pop_fora, String(b.pct_fora).replace(".", ","),
    b.deficit_capacidade, b.demanda_nao_resolvida, b.tempo_medio_min == null ? "" : String(b.tempo_medio_min).replace(".", ","),
    b.rural ? "sim" : "não"].map(q).join(";"));
  const csv = "﻿" + [cab.map(q).join(";"), ...linhas].join("\r\n");
  const nome = `ranking_${r.tipo}_${r.raio_m}m_${r.modo === "rede" ? "a_pe" : "linha_reta"}.csv`;
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: nome });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

/* ---------- Simulador de nova unidade ---------- */
function ligarSimulador() {
  const sel = $("#sim-tipo");
  sel.innerHTML = Object.entries(st.cfg.tipos).map(([t, c]) => `<option value="${t}">${esc(c.rotulo)}</option>`).join("");
  sel.value = st.mostrar !== "prioridade" ? st.mostrar : Object.keys(st.cfg.tipos)[0];
  sel.onchange = () => { if (st.sim) { st.sim.tipo = sel.value; simular(st.sim.lngLat); } };
  $("#btn-simular").onclick = () => {
    st.simulando = true;
    st.map.getCanvas().style.cursor = "crosshair";
    $("#sim-instrucao").hidden = false;
  };
  $("#btn-sim-limpar").onclick = limparSimulacao;
  $("#btn-ranking-todos").onclick = () => { st.rankingTodos = !st.rankingTodos; desenharRanking(); };
  $("#btn-ranking-csv").onclick = baixarRankingCsv;
}

function posicionarSimulacao(lngLat) {
  const tipo = $("#sim-tipo").value;
  if (!st.sim) {
    const el = document.createElement("div");
    el.className = "sim-marcador";
    el.setAttribute("aria-label", "Local da nova unidade (arraste para mudar)");
    const marcador = new maplibregl.Marker({ element: el, draggable: true }).setLngLat(lngLat).addTo(st.map);
    marcador.on("dragend", () => { st.sim.lngLat = marcador.getLngLat(); simular(st.sim.lngLat); });
    st.sim = { tipo, marcador, lngLat };
  } else {
    st.sim.tipo = tipo;
    st.sim.lngLat = lngLat;
    st.sim.marcador.setLngLat(lngLat);
  }
  $("#btn-sim-limpar").hidden = false;
  simular(lngLat);
}

async function simular(lngLat) {
  if (!st.sim) return;
  const t = st.sim.tipo, c = st.cfg.tipos[t], raio = st.raio[t], modo = st.modo;
  const caixa = $("#sim-resultado");
  const pedido = (st.simPedido = (st.simPedido || 0) + 1);       // só vale a resposta do último pedido
  caixa.hidden = false;
  caixa.innerHTML = `<p class="nota">Calculando…</p>`;
  let r;
  try {
    r = await api(`/${st.cod}/simular?tipo=${t}&raio=${raio}&modo=${modo}&lon=${lngLat.lng.toFixed(6)}&lat=${lngLat.lat.toFixed(6)}`);
  } catch (e) {
    if (pedido !== st.simPedido) return;
    caixa.innerHTML = `<p class="erro">${esc(e.message)}</p>`;
    fonte("simulacao", vazio());
    return;
  }
  if (pedido !== st.simPedido || !st.sim) return;
  fonte("simulacao", { type: "FeatureCollection", features: [r.area] });
  const nome = c.rotulo.split(" (")[0].toLowerCase();
  caixa.innerHTML = `
    <div class="sim-num">${fmt(r.novos_atendidos)}</div>
    <p>${esc(c.unidade)} que hoje moram longe de uma ${esc(nome)} passariam a ter uma ${ateMin(r.raio_efetivo_m)}
      (${cercaDe(r.raio_efetivo_m)}${modo === "rede" ? " pelas ruas" : " em linha reta"}).</p>
    <dl>
      <dt>Local</dt><dd>${esc(r.bairro || (r.rural ? "Zona rural" : "Área sem bairro definido"))}</dd>
      <dt>${esc(c.unidade[0].toUpperCase() + c.unidade.slice(1))} da faixa ${ateMin(r.raio_efetivo_m)} do local</dt><dd>${fmt(r.pop_no_raio)}</dd>
      <dt>Cobertura do município</dt><dd>${fmt(r.pct_coberta_antes, 1)}% → ${fmt(r.pct_coberta_depois, 1)}%</dd>
      <dt>${t === "ubs" ? "Pessoas a atender" : "Vagas pela meta"} sem atendimento hoje</dt><dd>${fmt(r.demanda_sem_cobertura_absorvida)}</dd>
      <dt>Somando a falta de vagas nas unidades próximas</dt><dd>${fmt(r.demanda_total_absorvivel)}</dd>
    </dl>
    <p class="nota">Supõe uma unidade dimensionada para essa demanda. Arraste o marcador para comparar terrenos.</p>`;
}

function limparSimulacao() {
  st.simulando = false;
  if (st.sim) st.sim.marcador.remove();
  st.sim = null;
  if (st.map?.getSource("simulacao")) fonte("simulacao", vazio());
  if (st.map) st.map.getCanvas().style.cursor = "";
  $("#sim-resultado").hidden = true;
  $("#sim-instrucao").hidden = true;
  $("#btn-sim-limpar").hidden = true;
}

/* ---------- Painel lateral ---------- */
function montarLateral() {
  const tipos = st.cfg.tipos;
  const qtd = {};
  st.equip.features.forEach((f) => (qtd[f.properties.tipo] = (qtd[f.properties.tipo] || 0) + 1));

  $("#camadas").innerHTML = Object.entries(tipos).map(([t, c]) => `
    <label class="toggle"><input type="checkbox" data-tipo="${t}"${st.visivel[t] === false ? "" : " checked"}><span class="trilho"></span>
      ${svgIcone(c.cor, c.icone)}<span>${esc(c.rotulo)} <span class="qtd">(${qtd[t] || 0})</span></span></label>`).join("");
  $("#camadas").querySelectorAll("input").forEach((i) => i.addEventListener("change", () => {
    const t = i.dataset.tipo;
    st.visivel[t] = i.checked;
    (st.pins[t] || []).forEach((m) => (m.getElement().style.display = i.checked ? "" : "none"));
    (st.radares[t] || []).forEach((m) => (m.getElement().style.display = i.checked && $("#tg-radar").checked ? "" : "none"));
    desenharRaios(t);
    atualizarLegenda();
  }));
  $("#tg-raios").onchange = () => Object.keys(tipos).forEach(desenharRaios);
  $("#tg-radar").onchange = () => Object.keys(tipos).forEach((t) =>
    (st.radares[t] || []).forEach((m) => (m.getElement().style.display = st.visivel[t] && $("#tg-radar").checked ? "" : "none")));
  $("#tg-estaduais").onchange = () => (st.pins.contexto_medio || []).forEach((m) =>
    (m.getElement().style.display = $("#tg-estaduais").checked ? "" : "none"));

  $("#sel-deficit").innerHTML = Object.entries(tipos).map(([t, c]) => `<option value="${t}">Déficit – ${esc(c.rotulo)}</option>`).join("")
    + `<option value="prioridade">Prioridade geral (todos os tipos)</option>`;
  $("#sel-deficit").value = st.mostrar;
  $("#sel-deficit").onchange = (e) => mudarMostrar(e.target.value);
  $("#unid-mapa").querySelectorAll("input").forEach((i) => {
    i.checked = i.value === st.unid;
    i.onchange = () => { st.unid = i.value; mudarMostrar(st.mostrar); };
  });
  if (!ESTATICO) ligarSimulador();

  $("#raios").innerHTML = Object.entries(tipos).map(([t, c]) => `
    <div class="raio" style="--cor:${c.cor}">
      <div class="raio-topo"><span>${esc(c.rotulo.split(" (")[0])}</span><b id="rv-${t}">até ${minutos(st.raio[t])} min</b></div>
      <div class="raio-min" id="rm-${t}">a pé · ${cercaDe(st.raio[t])}</div>
      <input type="range" min="${ESTATICO?.raio_min ?? 200}" max="${ESTATICO?.raio_max ?? 3000}" step="${ESTATICO?.passo ?? 50}" value="${st.raio[t]}" data-tipo="${t}" aria-label="Distância aceitável a pé – ${esc(c.rotulo)}">
    </div>`).join("");
  $("#raios").querySelectorAll("input").forEach((i) => i.addEventListener("input", () => {
    const t = i.dataset.tipo;
    st.raio[t] = Number(i.value);
    $(`#rv-${t}`).textContent = `até ${minutos(st.raio[t])} min`;
    $(`#rm-${t}`).textContent = `a pé · ${cercaDe(st.raio[t])}`;
    desenharRaios(t);
    atualizarCobertura(t, 350);
  }));
  const seg = $("#modo-dist");
  seg.querySelectorAll("input").forEach((i) => {
    i.checked = i.value === st.modo;
    i.disabled = i.value === "rede" && !st.cfg.tem_rede;
    i.onchange = () => mudarModo(i.value);
  });
  notaModo();
  mudarMostrar(st.mostrar);
}

function notaModo() {
  $("#nota-rural").textContent = (APE()
    ? "Tempo a pé pelas ruas e caminhos do OpenStreetMap, a passo normal. As manchas mostram até onde se chega nesse tempo. "
    : "Distância em linha reta a partir da unidade, convertida em minutos a passo normal (o caminho real é mais longo). ")
    + `Na zona rural vale ${st.cfg.fator_raio_rural === 3 ? "o triplo" : `${fmt(st.cfg.fator_raio_rural, 1)} vezes`}.`
    + (st.cfg.tem_rede ? "" : " Malha viária ainda não preparada para este município.");
}

function mudarModo(modo) {
  st.modo = modo;
  notaModo();
  Object.keys(st.cfg.tipos).forEach((t) => { desenharRaios(t); atualizarCobertura(t); });
  if (st.mostrar === "prioridade") mudarMostrar("prioridade");
  if (st.sim) simular(st.sim.lngLat);
  atualizarLegenda();
}

/* ---------- Indicadores ---------- */
/* nome curto para barras e legenda (os rótulos completos ficam no painel) */
const nomeCurto = (c) => c.rotulo.split(" (")[0].replace("Fundamental – anos ", "Fund. anos ").replace("Unidade Básica de Saúde", "UBS");

function atualizarKpis() {
  const tipos = st.cfg.tipos;
  const pop = st.cob.ubs?.indicadores.pop_faixa;
  const t = st.mostrar !== "prioridade" ? st.mostrar : "creche";
  const it = st.cob[t]?.indicadores;
  const nRadar = Object.values(st.cob).reduce((s, d) => s + d.radar.features.length, 0);
  const barras = Object.entries(tipos).map(([k, c]) => {
    const v = st.cob[k]?.indicadores.pct_coberta;
    return `<div class="barra"><span>${esc(nomeCurto(c))}</span>
      <span class="trilha"><span class="cheio" style="width:${v ?? 0}%;background:${c.cor}"></span></span><b>${v == null ? "…" : fmt(v, 0) + "%"}</b></div>`;
  }).join("");
  $("#kpis").innerHTML = `
    <div class="kpi"><div class="rot">População</div><div class="val">${pop ? fmt(pop) : "…"}</div><div class="sub">Censo 2022</div></div>
    <div class="kpi"><div class="rot">Moram longe de uma ${esc(nomeTipo(tipos[t]))}</div>
      <div class="val">${it ? fmt(it.pop_descoberta) : "…"}</div><div class="sub">${tipos[t].unidade} a mais de ${minutos(st.raio[t])} min a pé</div>
      ${st.cob[t]?.acesso?.tempo_medio_min != null ? `<div class="sub">Tempo médio a pé até a mais próxima: <b>${fmt(st.cob[t].acesso.tempo_medio_min, 0)} min</b></div>` : ""}</div>
    <div class="kpi cobertura"><div class="rot">Quem mora perto da unidade · ${txtDist()}</div>${barras}
      <div class="sub kpi-rodape"><span class="ponto-coral"></span>${nRadar} áreas prioritárias sugeridas no mapa</div></div>`;
}

function atualizarLegenda() {
  const itens = Object.entries(st.cfg.tipos).filter(([t]) => st.visivel[t]).map(([t, c]) => `
    <div class="leg-item"><span class="leg-icos">${svgIcone(c.cor, c.icone)}
      <svg class="leg-radar" viewBox="0 0 22 22" aria-hidden="true"><circle cx="11" cy="11" r="10" fill="${c.cor}" fill-opacity=".1" stroke="${c.cor}" stroke-width="1.4"/>
        <circle cx="11" cy="11" r="6.6" fill="none" stroke="${c.cor}" stroke-opacity=".5"/><circle cx="11" cy="11" r="3.3" fill="none" stroke="${c.cor}" stroke-opacity=".3"/></svg></span>
      <span class="leg-txt">${esc(nomeCurto(c))}<small><b>${ateMin(st.raio[t])}</b> · ${cercaDe(st.raio[t])}</small></span></div>`).join("");
  $("#legenda").innerHTML = `<h3>Equipamentos e alcance ${APE() ? "(a pé)" : ""}</h3>${itens}
    <div class="leg-sep"></div>
    <div class="leg-item"><span class="radar" style="--cor:#FF6B57;width:18px;height:18px"><span class="nucleo"></span></span><span>Área prioritária sugerida</span></div>
    <div class="leg-item"><span class="leg-hex"></span><span>Demanda não resolvida</span></div>
    <div class="leg-item"><svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="#C93A27" stroke-width="1.6" stroke-dasharray="3 2.2"/></svg><span>Localização a confirmar</span></div>
    <div class="nota">${APE() ? "Mancha: alcance a pé pelas ruas. " : ""}Zona rural: distância × ${fmt(st.cfg.fator_raio_rural, 1)}</div>`;
}

/* ---------- Visões salvas ---------- */
/* O estado é o que a tela mostra; o servidor valida campo a campo (api/visoes.py). */
function capturarEstado() {
  const c = st.map.getCenter(), r6 = (x) => Number(x.toFixed(6));
  const e = {
    mostrar: st.mostrar, modo: st.modo, unid: st.unid, raios: { ...st.raio }, visiveis: { ...st.visivel },
    camadas: { raios: $("#tg-raios").checked, radar: $("#tg-radar").checked, estaduais: $("#tg-estaduais").checked },
    mapa: { lng: r6(c.lng), lat: r6(c.lat), zoom: Number(st.map.getZoom().toFixed(2)) },
  };
  if (st.sim) e.sim = { tipo: st.sim.tipo, lng: r6(st.sim.lngLat.lng), lat: r6(st.sim.lngLat.lat) };
  return e;
}

function aplicarVisibilidade() {
  Object.entries(st.pins).forEach(([t, ms]) => ms.forEach((m) => (m.getElement().style.display =
    (t === "contexto_medio" ? $("#tg-estaduais").checked : st.visivel[t] !== false) ? "" : "none")));
  Object.entries(st.radares).forEach(([t, ms]) => ms.forEach((m) => (m.getElement().style.display =
    st.visivel[t] !== false && $("#tg-radar").checked ? "" : "none")));
}

function aplicarEstado(e) {
  const tipos = Object.keys(st.cfg.tipos);
  const [rmin, rmax] = [ESTATICO?.raio_min ?? 200, ESTATICO?.raio_max ?? 3000];
  limparSimulacao();
  tipos.forEach((t) => {
    const r = e.raios?.[t];
    if (Number.isFinite(r)) st.raio[t] = Math.min(rmax, Math.max(rmin, r));
    st.visivel[t] = e.visiveis?.[t] ?? true;
  });
  $("#tg-raios").checked = e.camadas?.raios ?? false;      // padrão: o mapa abre só com os equipamentos
  $("#tg-radar").checked = e.camadas?.radar ?? false;
  $("#tg-estaduais").checked = e.camadas?.estaduais ?? false;
  st.unid = e.unid === "setor" ? "setor" : "hex";
  st.modo = e.modo === "rede" && st.cfg.tem_rede ? "rede" : "reta";
  st.mostrar = e.mostrar === "prioridade" || st.cfg.tipos[e.mostrar] ? e.mostrar : tipos[0];
  montarLateral();                     // controles a partir de st (e chama mudarMostrar)
  aplicarVisibilidade();
  tipos.forEach((t) => { desenharRaios(t); atualizarCobertura(t); });
  atualizarLegenda();
  if (e.mapa) st.map.jumpTo({ center: [e.mapa.lng, e.mapa.lat], zoom: e.mapa.zoom });
  if (e.sim && st.cfg.tipos[e.sim.tipo] && !ESTATICO) {
    $("#sim-tipo").value = e.sim.tipo;
    posicionarSimulacao(new maplibregl.LngLat(e.sim.lng, e.sim.lat));
  }
}

/* Link de uma visão: #m=CÓDIGO&v=ID (o fragmento não vai para o servidor nem para os logs) */
function lerLinkVisao() {
  const q = new URLSearchParams(location.hash.slice(1));
  const cod = q.get("m"), id = Number(q.get("v"));
  return /^\d{7}$/.test(cod || "") && Number.isInteger(id) && id > 0 ? { cod, id } : null;
}

async function abrirVisaoDoLink(id) {
  history.replaceState(null, "", location.pathname + location.search);
  const v = (st.visoes || await carregarVisoes()).find((x) => x.id === id);
  if (v) aplicarEstado(v.estado);
  else alert("Essa visão não existe mais (pode ter sido apagada).");
}

async function carregarVisoes() {
  if (ESTATICO) { $("#sec-visoes").hidden = true; return []; }
  const cod = st.cod;
  try {
    const lista = await api(`/${cod}/visoes`);
    if (cod !== st.cod) return lista;
    st.visoes = lista;
  } catch { st.visoes = []; }
  desenharVisoes();
  return st.visoes;
}

function desenharVisoes() {
  const lista = st.visoes || [];
  const data = (iso) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
  $("#visoes-vazio").hidden = lista.length > 0;
  $("#visoes").innerHTML = lista.map((v, i) => `
    <li class="visao">
      <button type="button" class="visao-abrir" data-i="${i}" title="Abrir esta visão no mapa">
        <span class="visao-nome">${esc(v.nome)}</span>
        <span class="visao-sub">${esc(v.autor)} · ${data(v.criada_em)}${v.atualizada_em
          ? ` · atualizada em ${data(v.atualizada_em)}${v.atualizada_por && v.atualizada_por !== v.autor ? ` por ${esc(v.atualizada_por)}` : ""}` : ""}</span>
      </button>
      <span class="visao-acoes">
        <button type="button" class="lnk" data-relatorio="${i}" title="Gerar o relatório PDF com as distâncias e o modo de medir desta visão">Relatório</button>
        ${v.pode_editar ? `<button type="button" class="lnk" data-atualizar="${i}" title="Guardar nesta visão o que está na tela agora">Atualizar</button>` : ""}
        <button type="button" class="lnk" data-link="${i}" title="Copiar o link desta visão">Link</button>
        ${v.pode_apagar ? `<button type="button" class="lnk perigo" data-apagar="${i}" title="Apagar esta visão">Apagar</button>` : ""}
      </span>
    </li>`).join("");
  $("#visoes").querySelectorAll("[data-i]").forEach((b) => (b.onclick = () => aplicarEstado(lista[b.dataset.i].estado)));
  $("#visoes").querySelectorAll("[data-relatorio]").forEach((b) => (b.onclick = () => {
    const v = lista[b.dataset.relatorio];
    baixarRelatorio(`/api/${st.cod}/relatorio.pdf?visao=${v.id}`, b, "Gerando… (~40 s)");
  }));
  $("#visoes").querySelectorAll("[data-atualizar]").forEach((b) => (b.onclick = async () => {
    const v = lista[b.dataset.atualizar];
    if (!confirm(`Substituir a visão “${v.nome}” pelo que está na tela agora (serviço, distâncias, modo de medir, camadas e enquadramento)?`)) return;
    b.disabled = true;
    const r = await requisitar(`/api/${st.cod}/visoes/${v.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ estado: capturarEstado() }),
    });
    b.disabled = false;
    if (!r.ok) { alert(r.status === 422 ? "Não foi possível atualizar: a configuração da tela não é válida." : await detalheErro(r)); return; }
    st.visoes = null;
    await carregarVisoes();
  }));
  $("#visoes").querySelectorAll("[data-link]").forEach((b) => (b.onclick = async () => {
    const v = lista[b.dataset.link];
    const url = `${location.origin}${location.pathname}#m=${st.cod}&v=${v.id}`;
    try { await navigator.clipboard.writeText(url); b.textContent = "Copiado!"; setTimeout(() => (b.textContent = "Link"), 1800); }
    catch { prompt("Copie o link da visão:", url); }
  }));
  $("#visoes").querySelectorAll("[data-apagar]").forEach((b) => (b.onclick = async () => {
    const v = lista[b.dataset.apagar];
    if (!confirm(`Apagar a visão “${v.nome}”? A equipe do município também deixa de vê-la.`)) return;
    const r = await requisitar(`/api/${st.cod}/visoes/${v.id}`, { method: "DELETE" });
    if (!r.ok) { alert(await detalheErro(r)); return; }
    carregarVisoes();
  }));
}

function ligarVisoes() {
  if (ESTATICO) { $("#sec-visoes").hidden = true; return; }
  const dlg = $("#dlg-visao");
  $("#btn-salvar-visao").onclick = () => { $("#form-visao").reset(); $("#res-visao").textContent = ""; dlg.showModal(); };
  $("#btn-visao-fechar").onclick = () => dlg.close();
  $("#form-visao").onsubmit = async (ev) => {
    ev.preventDefault();
    $("#res-visao").textContent = "Salvando…";
    const r = await requisitar(`/api/${st.cod}/visoes`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome: $("#visao-nome").value, estado: capturarEstado() }),
    });
    if (!r.ok) { $("#res-visao").textContent = r.status === 422 ? "Não foi possível salvar: confira o nome." : await detalheErro(r); return; }
    dlg.close();
    carregarVisoes();
  };
  window.addEventListener("hashchange", async () => {
    const link = lerLinkVisao();
    if (!link) return;
    if (link.cod !== st.cod) {
      if (![...$("#municipio").options].some((o) => o.value === link.cod)) return;
      $("#municipio").value = link.cod;
      st.visoes = null;
      await carregarMunicipio(link.cod);
    }
    await abrirVisaoDoLink(link.id);
  });
}

/* ---------- Relatório PDF ---------- */
function ligarPdf() {
  const btn = $("#btn-pdf");
  btn.onclick = async () => {
    if (ESTATICO) {
      if (!ESTATICO.pdf?.[st.modo]) { alert("Esta cópia do mapa não inclui o relatório PDF."); return; }
      const padrao = Object.entries(st.cfg.tipos).every(([t, c]) => st.raio[t] === c.raio_m);
      if (!padrao && !confirm("A versão online tem o relatório pronto só com as distâncias padrão. Baixar mesmo assim?")) return;
      const a = Object.assign(document.createElement("a"), { href: ESTATICO.pdf[st.modo], download: "" });
      document.body.appendChild(a); a.click(); a.remove();
      return;
    }
    const q = new URLSearchParams([...Object.entries(st.raio).map(([t, r]) => [t, String(r)]), ["modo", st.modo]]);
    baixarRelatorio(`/api/${st.cod}/relatorio.pdf?${q}`, btn, "Gerando relatório… (cerca de 40 s)");
  };
}

/* Gera o PDF no servidor e baixa; o botão mostra o andamento. */
async function baixarRelatorio(url, btn, textoEspera) {
  const txt = btn.textContent;
  btn.disabled = true;
  btn.textContent = textoEspera;
  try {
    const r = await requisitar(url, { headers: { Accept: "application/pdf" } });
    if (!r.ok) throw new Error(await detalheErro(r));
    const blob = await r.blob();
    const nome = (r.headers.get("content-disposition") || "").match(/filename="?([^";]+)/)?.[1] || "relatorio.pdf";
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: nome });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  } catch (e) {
    alert("Não foi possível gerar o relatório: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = txt;
  }
}

/* ---------- Upload IPTU ---------- */
function ligarUpload() {
  const dlg = $("#dlg-upload");
  $("#btn-upload").onclick = () => { $("#res-upload").textContent = ""; dlg.showModal(); };
  $("#btn-enviar").onclick = async () => {
    const arqs = $("#arq-iptu").files;
    if (!arqs.length) { $("#res-upload").textContent = "Escolha ao menos um arquivo."; return; }
    const fd = new FormData();
    [...arqs].forEach((a) => fd.append("arquivos", a));
    $("#res-upload").textContent = "Enviando…";
    try {
      const r = await api(`/${st.cod}/upload-iptu`, { method: "POST", body: fd });
      $("#res-upload").textContent = r.ok
        ? `${fmt(r.registros)} registros lidos, ${fmt(r.pct_dentro_municipio, 1)}% dentro do município. ${r.mensagem}`
        : r.mensagem;
    } catch (e) { $("#res-upload").textContent = `Erro no envio: ${e.message}`; }
  };
}

iniciar().catch((e) => { console.error(e); alert("Não foi possível carregar o mapa: " + e.message); });
