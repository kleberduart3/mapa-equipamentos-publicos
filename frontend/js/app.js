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
};
const APE = () => st.modo === "rede";
const txtDist = () => (APE() ? "a pé pelas ruas" : "em linha reta");

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
  const anel = aprox ? '<circle cx="13" cy="12.5" r="12" fill="none" stroke="#d62828" stroke-width="1.6" stroke-dasharray="3 2.2"/>' : "";
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

const PRECISAS = new Set(["inep_catalogo", "cnes", "cnefe_nome_no_cep"]);
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
    $("#btn-pdf").title = "Versão online: relatório pronto com os raios padrão, no modo de distância selecionado";
  }
  if (eu) ligarConta(eu);
  const munis = await api("/municipios");
  if (!munis.length) { $("#aviso-vazio").hidden = false; return; }
  const sel = $("#municipio");
  sel.innerHTML = munis.map((m) => `<option value="${esc(m.codigo)}">${esc(m.nome)} – ${esc(m.uf)}</option>`).join("");
  sel.addEventListener("change", () => carregarMunicipio(sel.value));
  ligarUpload();
  ligarPdf();
  let lembrado = null;
  try { lembrado = localStorage.getItem(CHAVE_MUNICIPIO); } catch { /* armazenamento bloqueado */ }
  const inicial = munis.some((m) => m.codigo === lembrado) ? lembrado : munis[0].codigo;
  sel.value = inicial;
  await carregarMunicipio(inicial);
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
  try { localStorage.setItem(CHAVE_MUNICIPIO, cod); } catch { /* armazenamento bloqueado */ }
  st.cfg = await api(`/${cod}/config`);
  $("#btn-upload").hidden = Boolean(ESTATICO) || st.cfg.papel !== "gestor";
  const tipos = Object.keys(st.cfg.tipos);
  tipos.forEach((t) => { st.raio[t] = st.cfg.tipos[t].raio_m; st.visivel[t] = true; });
  st.modo = st.cfg.distancia_padrao || "reta";
  st.areas = {}; st.prio = {};
  st.mostrar = tipos[0];

  if (!st.map) criarMapa();
  else limparMapa();

  const [limite, equip] = await Promise.all([api(`/${cod}/limite`), api(`/${cod}/equipamentos`)]);
  st.equip = equip;
  const b = st.cfg.bbox;
  st.map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 40, duration: 0 });

  aoCarregar(() => {
    fonte("limite", limite);
    camada({ id: "limite-linha", type: "line", source: "limite", paint: { "line-color": "#0f6b6b", "line-width": 2, "line-dasharray": [3, 2] } });
    fonte("deficit", vazio());
    camada({ id: "deficit", type: "fill", source: "deficit", paint: {
      "fill-color": ["interpolate", ["linear"], ["get", "deficit"], 0, "#fde8e6", 20, "#f19c92", 80, "#c0392b", 300, "#7d1a12"],
      "fill-opacity": 0.55 } });
    fonte("prioridade", vazio());
    camada({ id: "prioridade", type: "fill", source: "prioridade", layout: { visibility: "none" }, paint: {
      "fill-color": ["interpolate", ["linear"], ["get", "prioridade_geral"], 1, "#fff3c4", 10, "#f8a35b", 25, "#d1495b", 45, "#3d0d4f"],
      "fill-opacity": 0.6 } });
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
  });
}

function criarMapa() {
  st.map = new maplibregl.Map({
    container: "mapa",
    style: {
      version: 8,
      sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap contributors</a>' } },
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
  if (st.raio[p.tipo]) linhas.push(["Raio de atendimento", `${fmt(st.raio[p.tipo] * (p.rural ? st.cfg.fator_raio_rural : 1))} m ${txtDist()}${p.rural ? " (zona rural)" : ""}`]);
  const alerta = PRECISAS.has(p.fonte_coord) ? "" :
    `<div class="alerta">Localização ${p.fonte_coord === "sem_coordenada" ? "ausente" : "aproximada"} – confirmar com a prefeitura.</div>`;
  return `<div class="pop"><span class="tag" style="background:${c.cor}">${esc(c.rotulo)}</span>
    <h4>${esc(p.nome)}</h4><dl>${linhas.map(([a, b]) => `<dt>${esc(a)}</dt><dd>${esc(b)}</dd>`).join("")}</dl>${alerta}</div>`;
}

/* ---------- Cobertura, déficit e radar ---------- */
function atualizarCobertura(t, atraso = 0) {
  clearTimeout(st.timers[t]);
  st.timers[t] = setTimeout(async () => {
    st.pendentes = (st.pendentes || 0) + 1;
    $("#carregando").hidden = false;
    const raioPedido = st.raio[t], modoPedido = st.modo;
    try {
      const [d] = await Promise.all([api(`/${st.cod}/cobertura?tipo=${t}&raio=${raioPedido}&modo=${modoPedido}`),
        modoPedido === "rede" ? carregarAreas(t) : null]);
      if (raioPedido !== st.raio[t] || modoPedido !== st.modo) return;   // resposta antiga: slider ou modo mudou
      st.cob[t] = d;
      desenharRadares(t);
      if (st.mostrar === t) fonte("deficit", d.hex);
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
      <dt>Sem nenhum equipamento no raio hoje</dt><dd>${fmt(p.sem_cobertura)} ${c.unidade}</dd>
      <dt>Raio considerado</dt><dd>${fmt(st.raio[t])} m ${txtDist()}</dd></dl>
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
    $("#nota-deficit").textContent = `Índice 0–100 que combina, para todos os tipos, gente fora do raio (2/3) e falta de capacidade (1/3). Calculado com os raios padrão, distância ${txtDist()}.`;
    if (!st.prio[modo]) {
      $("#carregando").hidden = false;
      try { st.prio[modo] = await api(`/${st.cod}/prioridade?modo=${modo}`); } finally { $("#carregando").hidden = !(st.pendentes > 0); }
    }
    if (st.mostrar === "prioridade" && modo === st.modo) fonte("prioridade", st.prio[modo]);
  } else {
    fonte("deficit", st.cob[v]?.hex || vazio());
    $("#nota-deficit").textContent = `Hexágonos vermelhos: ${st.cfg.tipos[v].unidade} sem ${st.cfg.tipos[v].rotulo.toLowerCase()} no raio ou onde a capacidade não dá conta. Quanto mais escuro, maior a demanda não resolvida.`;
  }
  atualizarKpis();
}

/* ---------- Painel lateral ---------- */
function montarLateral() {
  const tipos = st.cfg.tipos;
  const qtd = {};
  st.equip.features.forEach((f) => (qtd[f.properties.tipo] = (qtd[f.properties.tipo] || 0) + 1));

  $("#camadas").innerHTML = Object.entries(tipos).map(([t, c]) => `
    <label class="toggle"><input type="checkbox" data-tipo="${t}" checked><span class="trilho"></span>
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

  $("#raios").innerHTML = Object.entries(tipos).map(([t, c]) => `
    <div class="raio" style="--cor:${c.cor}">
      <div class="raio-topo"><span>${esc(c.rotulo.split(" (")[0])}</span><b id="rv-${t}">${fmt(st.raio[t])} m</b></div>
      <input type="range" min="${ESTATICO?.raio_min ?? 200}" max="${ESTATICO?.raio_max ?? 3000}" step="${ESTATICO?.passo ?? 50}" value="${st.raio[t]}" data-tipo="${t}" aria-label="Raio – ${esc(c.rotulo)}">
    </div>`).join("");
  $("#raios").querySelectorAll("input").forEach((i) => i.addEventListener("input", () => {
    const t = i.dataset.tipo;
    st.raio[t] = Number(i.value);
    $(`#rv-${t}`).textContent = `${fmt(st.raio[t])} m`;
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
    ? "Distância percorrida a pé pelas ruas e caminhos do OpenStreetMap. As manchas mostram até onde se chega dentro do raio. "
    : "Distância em linha reta a partir do equipamento. ")
    + `Na zona rural o raio é multiplicado por ${fmt(st.cfg.fator_raio_rural, 1)}.`
    + (st.cfg.tem_rede ? "" : " Malha viária ainda não preparada para este município.");
}

function mudarModo(modo) {
  st.modo = modo;
  notaModo();
  Object.keys(st.cfg.tipos).forEach((t) => { desenharRaios(t); atualizarCobertura(t); });
  if (st.mostrar === "prioridade") mudarMostrar("prioridade");
  atualizarLegenda();
}

/* ---------- Indicadores ---------- */
function atualizarKpis() {
  const tipos = st.cfg.tipos;
  const pop = st.cob.ubs?.indicadores.pop_faixa;
  const t = st.mostrar !== "prioridade" ? st.mostrar : "creche";
  const it = st.cob[t]?.indicadores;
  const nRadar = Object.values(st.cob).reduce((s, d) => s + d.radar.features.length, 0);
  const barras = Object.entries(tipos).map(([k, c]) => {
    const v = st.cob[k]?.indicadores.pct_coberta;
    return `<div class="barra"><span>${esc(c.rotulo.split(" (")[0].replace("Fundamental – ", ""))}</span>
      <span class="trilha"><span class="cheio" style="width:${v ?? 0}%;background:${c.cor}"></span></span><b>${v == null ? "…" : fmt(v, 0) + "%"}</b></div>`;
  }).join("");
  $("#kpis").innerHTML = `
    <div class="kpi"><div class="rot">População</div><div class="val">${pop ? fmt(pop) : "…"}</div><div class="sub">Censo 2022</div></div>
    <div class="kpi"><div class="rot">Sem ${esc(tipos[t].rotulo.split(" (")[0].toLowerCase())} no raio</div>
      <div class="val">${it ? fmt(it.pop_descoberta) : "…"}</div><div class="sub">${tipos[t].unidade} · raio ${fmt(st.raio[t])} m ${APE() ? "a pé" : ""}</div></div>
    <div class="kpi cobertura"><div class="rot">População coberta pelo raio de cada equipamento · ${txtDist()}</div>${barras}
      <div class="sub" style="margin-top:6px">${nRadar} áreas prioritárias sugeridas no mapa</div></div>`;
}

function atualizarLegenda() {
  const itens = Object.entries(st.cfg.tipos).filter(([t]) => st.visivel[t]).map(([t, c]) => `
    <div class="leg-item">${svgIcone(c.cor, c.icone)}
      <svg class="leg-radar" viewBox="0 0 22 22" aria-hidden="true"><circle cx="11" cy="11" r="10" fill="${c.cor}" fill-opacity=".1" stroke="${c.cor}" stroke-width="1.4"/>
        <circle cx="11" cy="11" r="6.6" fill="none" stroke="${c.cor}" stroke-opacity=".5"/><circle cx="11" cy="11" r="3.3" fill="none" stroke="${c.cor}" stroke-opacity=".3"/></svg>
      <span>${esc(c.rotulo.split(" (")[0])} – <b>${fmt(st.raio[t])} m</b></span></div>`).join("");
  $("#legenda").innerHTML = `<h3>Equipamentos e raios ${APE() ? "(a pé)" : ""}</h3>${itens}
    <div class="leg-item"><span class="radar" style="--cor:#c0392b;width:18px;height:18px"><span class="nucleo"></span></span><span>Área prioritária (radar)</span></div>
    <div class="leg-item"><span class="leg-hex"></span><span>Demanda não resolvida</span></div>
    <div class="leg-item"><svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="#d62828" stroke-width="1.6" stroke-dasharray="3 2.2"/></svg><span>Localização a confirmar</span></div>
    <div class="nota">${APE() ? "Mancha: alcance a pé pelas ruas. " : ""}Zona rural: raio × ${fmt(st.cfg.fator_raio_rural, 1)}</div>`;
}

/* ---------- Relatório PDF ---------- */
function ligarPdf() {
  const btn = $("#btn-pdf");
  btn.onclick = async () => {
    if (ESTATICO) {
      if (!ESTATICO.pdf?.[st.modo]) { alert("Esta cópia do mapa não inclui o relatório PDF."); return; }
      const padrao = Object.entries(st.cfg.tipos).every(([t, c]) => st.raio[t] === c.raio_m);
      if (!padrao && !confirm("A versão online tem o relatório pronto só com os raios padrão. Baixar mesmo assim?")) return;
      const a = Object.assign(document.createElement("a"), { href: ESTATICO.pdf[st.modo], download: "" });
      document.body.appendChild(a); a.click(); a.remove();
      return;
    }
    const q = new URLSearchParams([...Object.entries(st.raio).map(([t, r]) => [t, String(r)]), ["modo", st.modo]]);
    const txt = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Gerando relatório… (cerca de 40 s)";
    try {
      const r = await requisitar(`/api/${st.cod}/relatorio.pdf?${q}`, { headers: { Accept: "application/pdf" } });
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
  };
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
