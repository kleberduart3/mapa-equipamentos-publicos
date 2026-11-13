/* Administração: painel, propostas, contas, municípios e atividade */
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dataHora = (d) => (d ? new Date(d.endsWith("Z") || d.includes("+") ? d : d + "Z").toLocaleString("pt-BR") : "–");
const data = (d) => (d ? new Date(d.endsWith("Z") || d.includes("+") ? d : d + "Z").toLocaleDateString("pt-BR") : "–");
const brl = (v) => Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });

let MUNIS = [], USUARIOS = [], PROPOSTAS = [], EVENTOS = [], PRECOS = null, editando = null;

async function req(url, opts = {}) {
  const metodo = (opts.method || "GET").toUpperCase();
  const headers = { Accept: "application/json", ...(opts.headers || {}) };
  if (metodo !== "GET") { headers["X-CSRF"] = "1"; headers["Content-Type"] = "application/json"; }
  const r = await fetch(url, { credentials: "same-origin", ...opts, headers });
  if (r.status === 401) { location.href = "/entrar"; throw new Error("sessão expirada"); }
  let corpo = null;
  try { corpo = await r.json(); } catch { /* sem corpo */ }
  if (!r.ok) {
    const d = corpo?.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : `erro ${r.status}`);
  }
  return corpo;
}

async function copiar(texto, botao) {
  try { await navigator.clipboard.writeText(texto); } catch { /* sem permissão */ }
  if (botao) { const t = botao.textContent; botao.textContent = "Copiado"; setTimeout(() => (botao.textContent = t), 1500); }
}

/* ---------- abas ---------- */
const ABAS = ["painel", "propostas", "contas", "municipios", "atividade"];
function mostrarAba() {
  const aba = ABAS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "painel";
  ABAS.forEach((a) => { $(`#aba-${a}`).hidden = a !== aba; });
  document.querySelectorAll(".adm-nav a").forEach((l) => l.toggleAttribute("aria-current", l.dataset.aba === aba));
  document.querySelectorAll(".adm-nav a[aria-current]").forEach((l) => l.setAttribute("aria-current", "page"));
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", mostrarAba);
document.querySelectorAll("[data-ir]").forEach((a) => a.addEventListener("click", () => {
  setTimeout(() => (a.dataset.ir === "nova-proposta" ? abrirNovaProposta() : abrirNovaConta()), 0);
}));

/* ---------- painel ---------- */
const ACOES = {
  login_ok: "Entrou", login_falha: "Falha de login", usuario_criado: "Conta criada", usuario_editado: "Conta editada",
  link_gerado: "Link de senha gerado", sessoes_encerradas: "Sessões encerradas", proposta_criada: "Proposta criada",
  proposta_editada: "Proposta editada", proposta_codigo: "Novo código de proposta", proposta_aberta: "Proposta aberta pelo cliente",
  proposta_codigo_errado: "Código de proposta errado", visao_salva: "Visão salva", visao_apagada: "Visão apagada",
};
const nomeAcao = (a) => ACOES[a] || a.replace(/_/g, " ");

function desenharPainel() {
  const h = new Date().getHours();
  $("#aba-painel h1").textContent = h < 12 ? "Bom dia" : h < 18 ? "Boa tarde" : "Boa noite";
  $("#painel-data").textContent = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  const ativas = PROPOSTAS.filter((p) => p.ativa && !p.expirada);
  const abertas = PROPOSTAS.filter((p) => p.aberturas > 0);
  const valor = ativas.reduce((s, p) => s + (p.orcamento.total_1 || 0), 0);
  const kpi = (rot, val, det, href, cls = "") =>
    `<a class="kpi-adm ${cls}" href="${href}"><span class="rot">${rot}</span><span class="val">${val}</span><span class="det">${det}</span></a>`;
  $("#kpis-adm").innerHTML =
    kpi("Propostas ativas", ativas.length, `${brl(valor)} em 1º ano`, "#propostas", "destaque")
    + kpi("Abertas pelo cliente", abertas.length, `de ${PROPOSTAS.length} enviadas`, "#propostas")
    + kpi("Contas ativas", USUARIOS.filter((u) => u.ativo).length, `${USUARIOS.filter((u) => !u.senha_definida).length} convites pendentes`, "#contas")
    + kpi("Municípios no ar", MUNIS.filter((m) => m.processado).length, `${MUNIS.filter((m) => m.tem_rede).length} com distância a pé`, "#municipios");
  $("#painel-propostas").innerHTML = PROPOSTAS.slice(0, 6).map((p) => `<li><span><b>${esc(p.cliente)}</b><br>
    <span class="meta">${p.aberturas ? `aberta ${p.aberturas}× · ${dataHora(p.ultima_abertura)}` : "ainda não aberta"}</span></span>
    <span class="meta">${situacao(p)}</span></li>`).join("") || '<li class="vazio">Nenhuma proposta ainda.</li>';
  $("#painel-eventos").innerHTML = EVENTOS.slice(0, 8).map((e) => `<li><span>${esc(nomeAcao(e.acao))}
    <br><span class="meta">${esc(e.usuario || e.detalhe || "")}</span></span><span class="meta">${dataHora(e.quando)}</span></li>`).join("")
    || '<li class="vazio">Sem atividade.</li>';
}

/* ---------- propostas ---------- */
function orc(pop, desc, estudo) {
  if (!PRECOS) return null;
  const i = PRECOS.faixas.findIndex((f) => pop <= f.ate);
  if (i === -1) return { sob_proposta: true };
  const f = PRECOS.faixas[i], anual1 = Math.round(f.anual * (100 - desc) / 100), e = estudo ? PRECOS.estudo : 0;
  return { rotulo: f.rotulo, implantacao: f.implantacao, anual: f.anual, anual_1: anual1, estudo: e,
    total_1: f.implantacao + anual1 + e, cabe: f.implantacao + anual1 + e <= PRECOS.teto_dispensa };
}

function previa() {
  const pop = Number($("#pr-pop").value) || 0, desc = Number($("#pr-desc").value) || 0;
  const o = orc(pop, desc, $("#pr-estudo").checked);
  if (!pop || !o) { $("#pr-previa").innerHTML = '<span class="rot">Prévia</span><p class="aviso">Digite a população para ver o valor.</p>'; return; }
  if (o.sob_proposta) { $("#pr-previa").innerHTML = '<span class="rot">Prévia</span><p class="aviso">Acima de 300 mil habitantes: a página mostra "proposta sob medida".</p>'; return; }
  $("#pr-previa").innerHTML = `<span class="rot">Prévia · ${esc(o.rotulo)}</span><dl>
    <dt>Implantação</dt><dd>${brl(o.implantacao)}</dd>
    <dt>Assinatura 1º ano${desc ? ` (−${desc}%)` : ""}</dt><dd>${brl(o.anual_1)}</dd>
    ${o.estudo ? `<dt>Estudo</dt><dd>${brl(o.estudo)}</dd>` : ""}
    <dt class="total">Total 1º ano</dt><dd class="total">${brl(o.total_1)}</dd>
    <dt>Depois</dt><dd>${brl(o.anual)}/ano</dd></dl>
    <p class="aviso ${o.cabe ? "" : "ruim"}">${o.cabe ? "Cabe na dispensa de licitação." : "Passa do limite de dispensa."}</p>`;
}
["pr-pop", "pr-desc", "pr-estudo"].forEach((id) => $(`#${id}`).addEventListener("input", previa));

function abrirNovaProposta() {
  $("#bloco-nova-proposta").hidden = false;
  $("#entrega-proposta").hidden = true;
  previa();
  $("#pr-cliente").focus();
}
$("#btn-nova-proposta").onclick = abrirNovaProposta;
$("#btn-cancelar-proposta").onclick = () => { $("#bloco-nova-proposta").hidden = true; $("#form-proposta").reset(); };

$("#form-proposta").onsubmit = async (e) => {
  e.preventDefault();
  $("#erro-proposta").textContent = "";
  const dados = {
    cliente: $("#pr-cliente").value.trim(), municipio: $("#pr-municipio").value.trim(), uf: $("#pr-uf").value.trim(),
    populacao: Number($("#pr-pop").value), contato: $("#pr-contato").value.trim() || null,
    desconto_pct: Number($("#pr-desc").value) || 0, incluir_estudo: $("#pr-estudo").checked,
    validade_dias: Number($("#pr-val").value) || 30, observacao: $("#pr-obs").value.trim() || null,
  };
  try {
    const p = await req("/api/admin/propostas", { method: "POST", body: JSON.stringify(dados) });
    $("#form-proposta").reset();
    $("#bloco-nova-proposta").hidden = true;
    entregar(p, "Proposta criada");
    await carregar();
  } catch (err) { $("#erro-proposta").textContent = err.message; }
};

function entregar(p, titulo) {
  const msg = `Olá${p.contato ? ", " + p.contato.split(/[ ,]/)[0] : ""}! Segue a proposta da Equicidade para ${p.cliente}:\n${p.link}\n\nCódigo de acesso: ${p.codigo}\n\nA proposta vale até ${data(p.validade)}. Qualquer dúvida, é só chamar.`;
  const el = $("#entrega-proposta");
  el.hidden = false;
  el.innerHTML = `<h2>${esc(titulo)}: ${esc(p.cliente)}</h2>
    <div class="par"><span>Link</span><input readonly value="${esc(p.link)}"><button type="button" class="btn sec" data-c="link">Copiar</button></div>
    <div class="par"><span>Código de acesso</span><input readonly class="codigo" value="${esc(p.codigo)}"><button type="button" class="btn sec" data-c="codigo">Copiar</button></div>
    <p class="aviso">Anote o código agora: ele não aparece de novo. Se perder, gere outro na lista.</p>
    <label class="campo-rot">Mensagem pronta para WhatsApp ou e-mail<textarea rows="6" readonly>${esc(msg)}</textarea></label>
    <div class="form-acoes"><a class="btn sec" href="${esc(p.link)}" target="_blank" rel="noopener">Ver a página</a>
      <button type="button" class="btn" data-c="msg">Copiar mensagem</button></div>`;
  el.querySelectorAll("[data-c]").forEach((b) => (b.onclick = () =>
    copiar(b.dataset.c === "link" ? p.link : b.dataset.c === "codigo" ? p.codigo : msg, b)));
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function situacao(p) {
  if (!p.ativa) return '<span class="selo neutro">desativada</span>';
  if (p.expirada) return '<span class="selo alerta">expirada</span>';
  if (p.travada) return '<span class="selo alerta">bloqueada</span>';
  return p.aberturas ? '<span class="selo ok">aberta</span>' : '<span class="selo">enviada</span>';
}

function desenharPropostas() {
  $("#propostas-vazio").hidden = PROPOSTAS.length > 0;
  $("#propostas").innerHTML = PROPOSTAS.map((p) => `<tr data-id="${p.id}">
    <td><b>${esc(p.cliente)}</b><br><span class="fraco">${esc(p.municipio)}/${esc(p.uf)} · ${p.populacao.toLocaleString("pt-BR")} hab.${p.contato ? " · " + esc(p.contato) : ""}</span></td>
    <td class="num">${p.orcamento.sob_proposta ? "sob medida" : brl(p.orcamento.total_1)}${p.desconto_pct ? `<br><span class="fraco">−${p.desconto_pct}%</span>` : ""}</td>
    <td>${situacao(p)}</td>
    <td class="num">${p.aberturas}<br><span class="fraco">${p.ultima_abertura ? dataHora(p.ultima_abertura) : "–"}</span></td>
    <td class="num">${data(p.validade)}</td>
    <td><div class="acoes-linha">
      <button class="btn sec" data-acao="link">Copiar link</button>
      <button class="btn sec" data-acao="codigo">Novo código</button>
      <button class="btn sec" data-acao="prazo">+30 dias</button>
      <button class="btn sec" data-acao="ativa">${p.ativa ? "Desativar" : "Reativar"}</button>
    </div></td></tr>`).join("");
}

$("#propostas").onclick = async (e) => {
  const b = e.target.closest("button[data-acao]");
  if (!b) return;
  const p = PROPOSTAS.find((x) => x.id === Number(b.closest("tr").dataset.id));
  try {
    if (b.dataset.acao === "link") return copiar(p.link, b);
    if (b.dataset.acao === "codigo") {
      if (!confirm(`Gerar um código novo para ${p.cliente}? O código atual deixa de funcionar.`)) return;
      entregar(await req(`/api/admin/propostas/${p.id}/codigo`, { method: "POST" }), "Novo código");
    } else if (b.dataset.acao === "prazo") {
      await req(`/api/admin/propostas/${p.id}`, { method: "PATCH", body: JSON.stringify({ validade_dias: 30, ativa: true }) });
    } else if (b.dataset.acao === "ativa") {
      await req(`/api/admin/propostas/${p.id}`, { method: "PATCH", body: JSON.stringify({ ativa: !p.ativa }) });
    }
    await carregar();
  } catch (err) { alert(err.message); }
};

/* ---------- contas ---------- */
function montarAcessos(alvo, acessos = []) {
  const atual = Object.fromEntries(acessos.map((a) => [a.cod, a.papel]));
  $(alvo).innerHTML = MUNIS.map((m) => `
    <label><input type="checkbox" value="${esc(m.cod)}" ${atual[m.cod] ? "checked" : ""}>
      <span>${esc(m.nome)}/${esc(m.uf)}</span>
      <select aria-label="Papel em ${esc(m.nome)}">
        <option value="consulta" ${atual[m.cod] !== "gestor" ? "selected" : ""}>consulta</option>
        <option value="gestor" ${atual[m.cod] === "gestor" ? "selected" : ""}>gestor</option>
      </select></label>`).join("") || '<p class="nota">Nenhum município configurado.</p>';
}
const lerAcessos = (alvo) => [...document.querySelectorAll(`${alvo} label`)]
  .filter((l) => l.querySelector("input").checked)
  .map((l) => ({ cod: l.querySelector("input").value, papel: l.querySelector("select").value }));

function mostrarLink(alvo, info, quem) {
  const el = $(alvo);
  el.hidden = false;
  el.innerHTML = `<p class="ok">${info.email_enviado ? `Enviamos o link por e-mail para ${esc(quem)}.` :
      `Envie este link para ${esc(quem)} por um canal seguro. Ele vale por ${Math.round(info.validade_horas)} horas e uma única vez.`}</p>
    <div class="par"><span>Link de acesso</span><input readonly value="${esc(info.link)}"><button type="button" class="btn sec">Copiar</button></div>`;
  el.querySelector("button").onclick = (e) => copiar(info.link, e.target);
}
const nomeMuni = (cod) => MUNIS.find((x) => x.cod === cod)?.nome || cod;

function desenharUsuarios() {
  const f = $("#filtro-contas").value.trim().toLowerCase();
  $("#usuarios").innerHTML = USUARIOS.filter((u) => !f || `${u.nome} ${u.email} ${u.acessos.map((a) => nomeMuni(a.cod)).join(" ")}`.toLowerCase().includes(f))
    .map((u) => {
      const situ = !u.ativo ? '<span class="selo alerta">desativada</span>' : u.bloqueado ? '<span class="selo alerta">bloqueada</span>'
        : !u.senha_definida ? '<span class="selo">convite pendente</span>' : '<span class="selo ok">ativa</span>';
      const munis = u.papel === "admin" ? "todos" : u.acessos.map((a) => `${esc(nomeMuni(a.cod))} (${esc(a.papel)})`).join(", ") || "–";
      return `<tr data-id="${u.id}"><td><b>${esc(u.nome)}</b><br><span class="fraco">${esc(u.email)}</span></td>
        <td>${u.papel === "admin" ? "Administrador" : "Usuário"}</td><td>${munis}</td><td>${situ}</td>
        <td class="fraco">${dataHora(u.ultimo_login)}</td>
        <td><div class="acoes-linha">
          <button class="btn sec" data-acao="editar">Editar</button>
          <button class="btn sec" data-acao="link">${u.senha_definida ? "Link de nova senha" : "Novo convite"}</button>
          <button class="btn sec" data-acao="sessoes">Desconectar</button>
          <button class="btn sec" data-acao="ativo">${u.ativo ? "Desativar" : "Reativar"}</button>
        </div></td></tr>`;
    }).join("");
}
$("#filtro-contas").addEventListener("input", desenharUsuarios);

function abrirNovaConta() { $("#bloco-nova-conta").hidden = false; $("#novo-nome").focus(); }
$("#btn-nova-conta").onclick = abrirNovaConta;
$("#btn-cancelar-conta").onclick = () => { $("#bloco-nova-conta").hidden = true; $("#form-novo").reset(); };
$("#novo-papel").onchange = () => { $("#novo-acessos-bloco").hidden = $("#novo-papel").value === "admin"; };
$("#form-novo").onsubmit = async (e) => {
  e.preventDefault();
  $("#erro-novo").textContent = "";
  const papel = $("#novo-papel").value;
  const dados = { nome: $("#novo-nome").value.trim(), email: $("#novo-email").value.trim(), papel,
    acessos: papel === "admin" ? [] : lerAcessos("#novo-acessos") };
  if (papel === "admin" && !confirm("Administradores veem todos os municípios e gerenciam todas as contas. Confirmar?")) return;
  try {
    const r = await req("/api/admin/usuarios", { method: "POST", body: JSON.stringify(dados) });
    mostrarLink("#link-novo", r.convite, r.usuario.email);
    $("#form-novo").reset();
    $("#bloco-nova-conta").hidden = true;
    $("#novo-acessos-bloco").hidden = false;
    await carregar();
  } catch (err) { $("#erro-novo").textContent = err.message; }
};

$("#usuarios").onclick = async (e) => {
  const b = e.target.closest("button[data-acao]");
  if (!b) return;
  const u = USUARIOS.find((x) => x.id === Number(b.closest("tr").dataset.id));
  try {
    if (b.dataset.acao === "editar") return abrirEdicao(u);
    if (b.dataset.acao === "link") {
      mostrarLink("#link-usuario", await req(`/api/admin/usuarios/${u.id}/link`, { method: "POST" }), u.email);
    } else if (b.dataset.acao === "sessoes") {
      await req(`/api/admin/usuarios/${u.id}/encerrar-sessoes`, { method: "POST" });
      alert(`${u.email} foi desconectado de todos os dispositivos.`);
    } else if (b.dataset.acao === "ativo") {
      if (u.ativo && !confirm(`Desativar ${u.email}? A pessoa perde o acesso na hora.`)) return;
      await req(`/api/admin/usuarios/${u.id}`, { method: "PATCH", body: JSON.stringify({ ativo: !u.ativo }) });
    }
    await carregar();
  } catch (err) { alert(err.message); }
};

function abrirEdicao(u) {
  editando = u;
  $("#ed-email").textContent = u.email;
  $("#ed-nome").value = u.nome;
  $("#ed-papel").value = u.papel;
  $("#ed-acessos-bloco").hidden = u.papel === "admin";
  montarAcessos("#ed-acessos", u.acessos);
  $("#erro-ed").textContent = "";
  $("#dlg-editar").showModal();
}
$("#ed-papel").onchange = () => { $("#ed-acessos-bloco").hidden = $("#ed-papel").value === "admin"; };
$("#ed-fechar").onclick = () => $("#dlg-editar").close();
$("#form-editar").onsubmit = async (e) => {
  e.preventDefault();
  const papel = $("#ed-papel").value;
  const dados = { nome: $("#ed-nome").value.trim(), papel, acessos: papel === "admin" ? [] : lerAcessos("#ed-acessos") };
  try {
    await req(`/api/admin/usuarios/${editando.id}`, { method: "PATCH", body: JSON.stringify(dados) });
    $("#dlg-editar").close();
    await carregar();
  } catch (err) { $("#erro-ed").textContent = err.message; }
};

/* ---------- municípios e atividade ---------- */
function desenharMunicipios() {
  $("#municipios").innerHTML = MUNIS.map((m) => {
    const n = USUARIOS.filter((u) => u.papel !== "admin" && u.acessos.some((a) => a.cod === m.cod)).length;
    return `<tr><td><b>${esc(m.nome)}</b>/${esc(m.uf)}</td><td class="num">${esc(m.cod)}</td>
      <td>${m.processado ? '<span class="selo ok">no ar</span>' : '<span class="selo alerta">não processado</span>'}</td>
      <td>${m.tem_rede ? "sim" : "não"}</td><td class="num">${n}</td></tr>`;
  }).join("");
}

function desenharEventos() {
  const f = $("#filtro-eventos").value.trim().toLowerCase();
  $("#eventos").innerHTML = EVENTOS.filter((e) => !f || `${nomeAcao(e.acao)} ${e.acao} ${e.usuario} ${e.detalhe} ${e.ip}`.toLowerCase().includes(f))
    .map((e) => `<tr><td class="num">${dataHora(e.quando)}</td><td>${esc(nomeAcao(e.acao))}</td>
      <td>${esc(e.usuario || "")}</td><td class="fraco">${esc(e.detalhe || "")}</td><td class="num fraco">${esc(e.ip || "")}</td></tr>`).join("");
}
$("#filtro-eventos").addEventListener("input", desenharEventos);

/* ---------- carga ---------- */
async function carregar() {
  [MUNIS, USUARIOS, PROPOSTAS, EVENTOS, PRECOS] = await Promise.all([
    req("/api/admin/municipios"), req("/api/admin/usuarios"), req("/api/admin/propostas"),
    req("/api/admin/eventos?limite=500"), PRECOS ? PRECOS : req("/api/admin/precos")]);
  montarAcessos("#novo-acessos");
  desenharUsuarios();
  desenharPropostas();
  desenharMunicipios();
  desenharEventos();
  desenharPainel();
}

mostrarAba();
carregar().catch((e) => alert("Não foi possível carregar: " + e.message));
