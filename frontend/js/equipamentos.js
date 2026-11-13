/* Cadastro de equipamentos: conferência, ajuste, inclusão e exclusão de unidades.
   Os dados vêm de /api/{cod}/ajustes/equipamentos (ver backend/app/api/ajustes.py). */
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
const CHAVE_MUNICIPIO = "mapa.municipio";

const st = {
  cod: null, cfg: null, tipo: null, dados: null,
  editando: null,                 // linha em edição (null = unidade nova)
  mini: null, marcador: null, ponto: null,
};

/* ---------- API ---------- */
async function requisitar(url, opts = {}) {
  const metodo = (opts.method || "GET").toUpperCase();
  const headers = { Accept: "application/json", ...(opts.headers || {}) };
  if (metodo !== "GET") headers["X-CSRF"] = "1";
  if (opts.body && typeof opts.body !== "string") { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.body); }
  const r = await fetch(url, { credentials: "same-origin", ...opts, headers });
  if (r.status === 401) { location.href = "/entrar"; throw new Error("sessão expirada"); }
  return r;
}
async function erroDe(r) {
  try {
    const j = await r.json();
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail) && j.detail[0]?.msg) return "Confira os campos: " + j.detail.map((d) => d.msg).join("; ");
  } catch { /* sem corpo */ }
  return `Não deu certo (erro ${r.status}). Tente de novo.`;
}
async function api(caminho, opts) {
  const r = await requisitar(`/api${caminho}`, opts);
  if (!r.ok) throw new Error(await erroDe(r));
  return r.json();
}

function aviso(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(aviso.timer);
  aviso.timer = setTimeout(() => { t.hidden = true; }, 3500);
}

/* ---------- Ícones dos tipos (os mesmos pinos do mapa) ---------- */
const GLIFO = {
  blocos: '<rect x="6.5" y="12.5" width="5" height="5" rx=".8"/><rect x="12.5" y="12.5" width="5" height="5" rx=".8"/><rect x="9.5" y="6.5" width="5" height="5" rx=".8"/>',
  estrela: '<path d="M12 5.8l1.9 3.9 4.3.6-3.1 3 .7 4.3L12 15.6l-3.8 2 .7-4.3-3.1-3 4.3-.6z"/>',
  livro: '<path d="M7.5 6.5h7.8a1.2 1.2 0 0 1 1.2 1.2v10.8H8.7a1.2 1.2 0 0 1-1.2-1.2z"/>',
  livro_aberto: '<path d="M5.5 8c2.4-.9 4.6-.6 6.5.8v9.4c-1.9-1.3-4.1-1.6-6.5-.8zM18.5 8c-2.4-.9-4.6-.6-6.5.8v9.4c1.9-1.3 4.1-1.6 6.5-.8z"/>',
  cruz: '<path d="M10.2 6.5h3.6v3.7h3.7v3.6h-3.7v3.7h-3.6v-3.7H6.5v-3.6h3.7z"/>',
  ponto: '<circle cx="12" cy="12" r="4"/>',
};
const icone = (c) => `<svg class="eq-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="${c.cor}"/><g fill="#fff">${GLIFO[c.icone] || GLIFO.ponto}</g></svg>`;

/* ---------- Início ---------- */
async function iniciar() {
  const munis = await api("/municipios");
  if (!munis.length) { $("#painel").innerHTML = '<p class="nota">Sua conta ainda não tem acesso a nenhum município.</p>'; return; }
  const sel = $("#municipio");
  sel.innerHTML = munis.map((m) => `<option value="${esc(m.codigo)}">${esc(m.nome)} – ${esc(m.uf)}</option>`).join("");
  let lembrado = null;
  try { lembrado = localStorage.getItem(CHAVE_MUNICIPIO); } catch { /* bloqueado */ }
  sel.value = munis.some((m) => m.codigo === lembrado) ? lembrado : munis[0].codigo;
  sel.addEventListener("change", () => carregarMunicipio(sel.value));
  $("#busca").addEventListener("input", desenhar);
  $("#filtro").addEventListener("change", desenhar);
  $("#btn-incluir").addEventListener("click", () => abrirDialogo(null));
  $("#btn-dlg-cancelar").addEventListener("click", () => $("#dlg-unidade").close());
  $("#form-unidade").addEventListener("submit", salvar);
  $("#btn-local-oficial").addEventListener("click", voltarLocalOficial);
  const tipoUrl = new URLSearchParams(location.search).get("tipo");
  await carregarMunicipio(sel.value, tipoUrl);
}

async function carregarMunicipio(cod, tipo) {
  st.cod = cod;
  try { localStorage.setItem(CHAVE_MUNICIPIO, cod); } catch { /* bloqueado */ }
  st.cfg = await api(`/${cod}/config`);
  const tipos = Object.keys(st.cfg.tipos);
  st.tipo = tipos.includes(tipo) ? tipo : tipos[0];
  $("#aviso-consulta").hidden = st.cfg.papel === "gestor";
  $("#btn-incluir").hidden = st.cfg.papel !== "gestor";
  if (st.mini) { st.mini.remove(); st.mini = null; st.marcador = null; }
  desenharAbas();
  await carregarTipo();
}

function desenharAbas() {
  $("#abas").innerHTML = Object.entries(st.cfg.tipos).map(([t, c]) =>
    `<button type="button" role="tab" class="eq-aba" data-tipo="${esc(t)}" aria-selected="${t === st.tipo}">
       ${icone(c)}<span title="${esc(c.rotulo)}">${esc(c.rotulo.split(" (")[0])}</span><span class="eq-cont" id="cont-${esc(t)}"></span></button>`).join("");
  $("#abas").querySelectorAll(".eq-aba").forEach((b) => b.addEventListener("click", () => {
    st.tipo = b.dataset.tipo;
    $("#abas").querySelectorAll(".eq-aba").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    history.replaceState(null, "", `?tipo=${encodeURIComponent(st.tipo)}`);
    carregarTipo();
  }));
  $("#abas").querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "center" });
}

async function carregarTipo() {
  $("#linhas").innerHTML = '<tr><td colspan="4" class="nota">Carregando…</td></tr>';
  try {
    st.dados = await api(`/${st.cod}/ajustes/equipamentos?tipo=${encodeURIComponent(st.tipo)}`);
  } catch (e) {
    $("#linhas").innerHTML = `<tr><td colspan="4" class="nota aviso">${esc(e.message)}</td></tr>`;
    return;
  }
  const ativas = st.dados.linhas.filter((l) => !l.excluida).length;
  const c = $(`#cont-${CSS.escape(st.tipo)}`);
  if (c) c.textContent = fmt(ativas);
  const ubs = st.dados.fonte === "cnes";
  $("#th-cap").textContent = ubs ? "Capacidade (pessoas)" : "Capacidade (vagas)";
  $("#fonte").textContent = ubs
    ? `Capacidade oficial: equipes de atenção básica no CNES × ${fmt(st.dados.pessoas_por_equipe)} pessoas por equipe. Redes: municipal.`
    : `Capacidade oficial: matrículas no Censo Escolar (INEP). Matrícula mostra quantos alunos a unidade tem, não quantos ela comporta: informe as vagas quando souber. Redes: ${st.dados.redes.join(", ").toLowerCase()}.`;
  desenhar();
}

/* ---------- Tabela ---------- */
function filtrar(linhas) {
  const q = $("#busca").value.trim().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const f = $("#filtro").value;
  return linhas.filter((l) => {
    if (f === "ajustadas" && !l.ajustada) return false;
    if (f === "novas" && !l.nova) return false;
    if (f === "excluidas" && !l.excluida) return false;
    if (f === "sem_local" && l.lat != null) return false;
    if (!q) return true;
    const alvo = [l.nome, l.endereco, l.bairro, l.id].join(" ").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    return alvo.includes(q);
  });
}

function desenhar() {
  const d = st.dados;
  if (!d) return;
  const gestor = d.pode_editar;
  const linhas = filtrar(d.linhas);
  const ativas = d.linhas.filter((l) => !l.excluida);
  const total = ativas.reduce((s, l) => s + l.capacidade, 0);
  const oficial = d.linhas.filter((l) => l.capacidade_oficial != null && !l.nova).reduce((s, l) => s + l.capacidade_oficial, 0);
  const ajustes = d.linhas.filter((l) => l.ajustada || l.nova).length;
  const un = d.unidade_capacidade;
  $("#resumo").innerHTML = `<span><strong>${fmt(ativas.length)}</strong> em funcionamento</span>
    <span>Capacidade total <strong>${fmt(total)}</strong> ${un}${total !== oficial ? ` <small>(oficial ${fmt(oficial)})</small>` : ""}</span>
    <span>${ajustes ? `<strong>${fmt(ajustes)}</strong> com ajuste da prefeitura` : "Nenhum ajuste ainda"}</span>`;
  $("#vazio").hidden = linhas.length > 0;
  $("#linhas").innerHTML = linhas.map((l) => {
    const selos = [
      l.nova ? '<span class="selo novo">Incluída pela prefeitura</span>' : "",
      l.ajustada && !l.excluida ? '<span class="selo ajuste">Ajustada</span>' : "",
      l.excluida ? '<span class="selo fora">Fora de funcionamento</span>' : "",
      l.lat == null ? '<span class="selo alerta">Sem local no mapa</span>' : "",
    ].join("");
    const dif = l.capacidade_oficial != null && l.capacidade !== l.capacidade_oficial && !l.nova;
    const cap = `<strong>${fmt(l.capacidade)}</strong>${dif ? `<small class="oficial" title="Dado oficial">${fmt(l.capacidade_oficial)}</small>` : ""}
      ${d.fonte === "cnes" ? `<small>${fmt(l.equipes)} equipe${l.equipes === 1 ? "" : "s"}${l.capacidade_informada ? " · capacidade informada" : ""}</small>`
        : `<small>${l.capacidade_informada ? "vagas informadas" : "matrículas"}</small>`}`;
    const quem = l.alterado_por ? `<small class="quem">Alterado por ${esc(l.alterado_por)} em ${new Date(l.alterado_em).toLocaleDateString("pt-BR")}</small>` : "";
    const acoes = gestor ? `<div class="acoes-linha">
        <button type="button" class="btn sec" data-acao="editar" data-chave="${esc(l.chave)}">Editar</button>
        ${l.nova ? `<button type="button" class="btn sec perigo" data-acao="remover" data-chave="${esc(l.chave)}">Remover</button>`
          : l.excluida ? `<button type="button" class="btn sec" data-acao="reativar" data-chave="${esc(l.chave)}">Reativar</button>`
          : `<button type="button" class="btn sec" data-acao="excluir" data-chave="${esc(l.chave)}">Marcar como fechada</button>`}
        ${l.ajustada ? `<button type="button" class="btn fantasma" data-acao="desfazer" data-chave="${esc(l.chave)}" title="Apaga todos os ajustes desta unidade e volta ao dado oficial">Voltar ao oficial</button>` : ""}
      </div>` : "";
    return `<tr class="${l.excluida ? "excluida" : ""}">
      <td><div class="eq-nome">${esc(l.nome)}</div><small class="codigo">${l.nova ? "Código interno" : d.fonte === "cnes" ? "CNES" : "INEP"} ${esc(l.id)} · ${esc(l.rede)}</small>
        <div class="selos">${selos}</div>${quem}</td>
      <td>${esc(l.endereco || "Sem endereço")}${l.bairro ? `<small>${esc(l.bairro)}${l.rural ? " · zona rural" : ""}</small>` : ""}</td>
      <td class="num">${cap}</td>
      <td>${acoes}</td></tr>`;
  }).join("");
  $("#linhas").querySelectorAll("button[data-acao]").forEach((b) => b.addEventListener("click", () => acao(b.dataset.acao, b.dataset.chave)));
}

/* ---------- Ações da linha ---------- */
const linhaDe = (chave) => st.dados.linhas.find((l) => l.chave === chave);

function confirmar(titulo, texto, botao) {
  const dlg = $("#dlg-confirmar");
  $("#conf-titulo").textContent = titulo;
  $("#conf-texto").textContent = texto;
  $("#conf-sim").textContent = botao;
  dlg.returnValue = "";
  dlg.showModal();
  return new Promise((ok) => dlg.addEventListener("close", () => ok(dlg.returnValue === "sim"), { once: true }));
}

async function acao(tipoAcao, chave) {
  const l = linhaDe(chave);
  if (!l) return;
  const url = `/${st.cod}/ajustes/equipamentos/${encodeURIComponent(chave)}`;
  try {
    if (tipoAcao === "editar") return abrirDialogo(l);
    if (tipoAcao === "excluir") {
      if (!(await confirmar("Marcar como fechada?", `${l.nome} deixa de contar no mapa e no relatório. Dá para reativar depois.`, "Marcar como fechada"))) return;
      await api(url, { method: "PUT", body: { tipo: st.tipo, excluida: true } });
      aviso("Unidade marcada como fechada.");
    } else if (tipoAcao === "reativar") {
      await api(url, { method: "PUT", body: { tipo: st.tipo, excluida: false } });
      aviso("Unidade reativada.");
    } else if (tipoAcao === "desfazer") {
      if (!(await confirmar("Voltar ao dado oficial?", `Os ajustes de ${l.nome} (${l.campos_ajustados.map(nomeCampo).join(", ")}) serão apagados.`, "Voltar ao oficial"))) return;
      await api(url, { method: "DELETE" });
      aviso("Ajustes desfeitos.");
    } else if (tipoAcao === "remover") {
      if (!(await confirmar("Remover a unidade?", `${l.nome} foi incluída pela prefeitura e será apagada do cadastro.`, "Remover"))) return;
      await api(url, { method: "DELETE" });
      aviso("Unidade removida.");
    }
    await carregarTipo();
  } catch (e) {
    aviso(e.message);
  }
}

const nomeCampo = (c) => ({ nome: "nome", endereco: "endereço", lat: "local", capacidade: "capacidade", equipes: "equipes", excluida: "situação" }[c] || c);

/* ---------- Diálogo de edição / inclusão ---------- */
function abrirDialogo(l) {
  st.editando = l;
  const d = st.dados, ubs = d.fonte === "cnes", nova = !l;
  $("#dlg-erro").hidden = true;
  $("#dlg-titulo").textContent = nova ? `Incluir ${st.cfg.tipos[st.tipo].rotulo.split(" (")[0].toLowerCase()}` : "Editar unidade";
  $("#dlg-sub").textContent = nova ? "Para uma unidade que não está no Censo Escolar ou no CNES, como uma que abriu depois do último censo."
    : `${l.nova ? "Código interno" : ubs ? "CNES" : "INEP"} ${l.id}`;
  $("#f-nome").value = l?.nome || "";
  $("#f-endereco").value = l?.endereco || "";
  $("#rot-rede").hidden = ubs || !nova;
  $("#f-rede").value = "Municipal";
  $("#rot-equipes").hidden = !ubs;
  $("#f-equipes").value = ubs ? (l ? l.equipes : "") : "";
  $("#rot-cap").textContent = ubs ? "Capacidade em pessoas (opcional)" : "Vagas";
  $("#f-cap").value = l?.capacidade_informada ? l.capacidade : "";
  $("#f-cap").required = !ubs && nova;
  $("#ajuda-cap").textContent = ubs
    ? `Sem capacidade informada, a conta usa equipes × ${fmt(d.pessoas_por_equipe)} pessoas.${l?.equipes_oficial != null ? ` No CNES: ${l.equipes_oficial} equipe${l.equipes_oficial === 1 ? "" : "s"}.` : ""}`
    : l && !l.nova ? `Matrículas no Censo Escolar: ${fmt(l.capacidade_oficial ?? 0)}. Deixe em branco para usar as matrículas; 0 tira a unidade desta etapa.`
    : "Quantas crianças ou alunos a unidade comporta nesta etapa.";
  st.ponto = l && l.lat != null ? [l.lon, l.lat] : null;
  $("#btn-local-oficial").hidden = !(l && !l.nova && l.campos_ajustados.includes("lat"));
  $("#dlg-unidade").showModal();
  prepararMini();
  setTimeout(() => $("#f-nome").focus(), 50);
}

function prepararMini() {
  const base = st.cfg.mapa_base || { url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", atribuicao: "© OpenStreetMap contributors", zoom_max: 19 };
  if (!st.mini) {
    st.mini = new maplibregl.Map({
      container: "mini",
      style: { version: 8, sources: { osm: { type: "raster", tiles: [base.url], tileSize: 256, maxzoom: base.zoom_max,
        attribution: `${esc(base.atribuicao)} · dados OpenStreetMap` } }, layers: [{ id: "osm", type: "raster", source: "osm" }] },
      bounds: st.cfg.bbox, fitBoundsOptions: { padding: 20 }, attributionControl: { compact: true },
    });
    st.mini.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    st.mini.on("click", (e) => marcar([e.lngLat.lng, e.lngLat.lat]));
  }
  st.mini.resize();
  if (st.marcador) { st.marcador.remove(); st.marcador = null; }
  if (st.ponto) {
    marcar(st.ponto);
    st.mini.jumpTo({ center: st.ponto, zoom: 16 });
    $("#ajuda-local").textContent = "Clique no mapa ou arraste o marcador para corrigir o local.";
  } else {
    st.mini.fitBounds(st.cfg.bbox, { padding: 20, duration: 0 });
    $("#ajuda-local").textContent = st.editando ? "Esta unidade está sem local no mapa. Clique onde ela fica." : "Clique no mapa onde fica a unidade.";
  }
}

function marcar(lngLat) {
  st.ponto = lngLat;
  if (!st.marcador) {
    const cor = st.cfg.tipos[st.tipo].cor;
    st.marcador = new maplibregl.Marker({ color: cor, draggable: true }).setLngLat(lngLat).addTo(st.mini);
    st.marcador.on("dragend", () => { const p = st.marcador.getLngLat(); st.ponto = [p.lng, p.lat]; });
  } else {
    st.marcador.setLngLat(lngLat);
  }
}

function voltarLocalOficial() {
  st.ponto = "oficial";
  if (st.marcador) { st.marcador.remove(); st.marcador = null; }
  $("#ajuda-local").textContent = "O local volta ao do cadastro oficial quando você salvar.";
}

async function salvar(e) {
  e.preventDefault();
  const l = st.editando, ubs = st.dados.fonte === "cnes";
  const erro = (msg) => { $("#dlg-erro").textContent = msg; $("#dlg-erro").hidden = false; };
  const nome = $("#f-nome").value.trim(), endereco = $("#f-endereco").value.trim();
  const capTxt = $("#f-cap").value.trim(), eqTxt = $("#f-equipes").value.trim();
  const cap = capTxt === "" ? null : Number(capTxt), eq = eqTxt === "" ? null : Number(eqTxt);
  const btn = $("#btn-dlg-salvar");
  btn.disabled = true;
  try {
    if (!l) {
      if (!st.ponto || st.ponto === "oficial") return erro("Marque no mapa onde fica a unidade.");
      const corpo = { tipo: st.tipo, nome, endereco: endereco || null, lat: st.ponto[1], lon: st.ponto[0], capacidade: cap };
      if (ubs) corpo.equipes = eq; else corpo.rede = $("#f-rede").value;
      await api(`/${st.cod}/ajustes/equipamentos`, { method: "POST", body: corpo });
      aviso(`${nome} incluída. O mapa já conta com ela.`);
    } else {
      const corpo = { tipo: st.tipo };
      if (nome !== l.nome) corpo.nome = nome;
      if (endereco !== (l.endereco || "")) corpo.endereco = endereco || null;
      if (st.ponto === "oficial") { corpo.lat = null; corpo.lon = null; }
      else if (st.ponto && (l.lat == null || Math.abs(st.ponto[1] - l.lat) > 1e-6 || Math.abs(st.ponto[0] - l.lon) > 1e-6)) {
        corpo.lat = st.ponto[1]; corpo.lon = st.ponto[0];
      }
      const capAtual = l.capacidade_informada ? l.capacidade : null;
      if (cap !== capAtual) corpo.capacidade = cap;
      if (ubs && eq !== null && eq !== l.equipes) corpo.equipes = eq;
      if (Object.keys(corpo).length === 1) { $("#dlg-unidade").close(); return; }
      await api(`/${st.cod}/ajustes/equipamentos/${encodeURIComponent(l.chave)}`, { method: "PUT", body: corpo });
      aviso("Alterações salvas. O mapa e o relatório já usam os números novos.");
    }
    $("#dlg-unidade").close();
    await carregarTipo();
  } catch (err) {
    erro(err.message);
  } finally {
    btn.disabled = false;
  }
}

iniciar().catch((e) => { $("#linhas").innerHTML = `<tr><td colspan="4" class="nota aviso">${esc(e.message)}</td></tr>`; });
