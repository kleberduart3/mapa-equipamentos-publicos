/* Administração de contas */
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dataHora = (d) => (d ? new Date(d.endsWith("Z") || d.includes("+") ? d : d + "Z").toLocaleString("pt-BR") : "–");

let MUNIS = [];
let USUARIOS = [];
let editando = null;

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

/* ---------- seletor de municípios (checkbox + papel) ---------- */
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

function lerAcessos(alvo) {
  return [...document.querySelectorAll(`${alvo} label`)]
    .filter((l) => l.querySelector("input").checked)
    .map((l) => ({ cod: l.querySelector("input").value, papel: l.querySelector("select").value }));
}

/* ---------- link de convite (mostrado ao admin para repassar) ---------- */
function mostrarLink(alvo, info, quem) {
  const el = $(alvo);
  el.hidden = false;
  el.innerHTML = `
    <p class="ok">${info.email_enviado ? `Enviamos o link por e-mail para ${esc(quem)}.` :
      `Envie este link para ${esc(quem)} por um canal seguro. Ele vale por ${Math.round(info.validade_horas)} horas e uma única vez.`}</p>
    <div class="caixa-link"><input readonly value="${esc(info.link)}" aria-label="Link"><button type="button" class="btn sec">Copiar</button></div>`;
  const inp = el.querySelector("input");
  el.querySelector("button").onclick = async () => {
    try { await navigator.clipboard.writeText(inp.value); } catch { inp.select(); document.execCommand("copy"); }
    el.querySelector("button").textContent = "Copiado";
  };
}

/* ---------- listas ---------- */
function nomeMuni(cod) {
  const m = MUNIS.find((x) => x.cod === cod);
  return m ? m.nome : cod;
}

function desenharUsuarios() {
  $("#usuarios").innerHTML = USUARIOS.map((u) => {
    const situ = !u.ativo ? '<span class="selo alerta">desativada</span>'
      : u.bloqueado ? '<span class="selo alerta">bloqueada</span>'
      : !u.senha_definida ? '<span class="selo">convite pendente</span>' : '<span class="selo">ativa</span>';
    const munis = u.papel === "admin" ? "todos"
      : u.acessos.map((a) => `${esc(nomeMuni(a.cod))} (${esc(a.papel)})`).join(", ") || "–";
    return `<tr data-id="${u.id}">
      <td><b>${esc(u.nome)}</b><br>${esc(u.email)}</td>
      <td>${u.papel === "admin" ? "Administrador" : "Usuário"}</td>
      <td>${munis}</td><td>${situ}</td><td>${dataHora(u.ultimo_login)}</td>
      <td><div class="acoes-linha">
        <button class="btn sec" data-acao="editar">Editar</button>
        <button class="btn sec" data-acao="link">${u.senha_definida ? "Link de nova senha" : "Novo convite"}</button>
        <button class="btn sec" data-acao="sessoes">Desconectar</button>
        <button class="btn sec" data-acao="ativo">${u.ativo ? "Desativar" : "Reativar"}</button>
      </div></td></tr>`;
  }).join("");
}

async function carregar() {
  [MUNIS, USUARIOS] = await Promise.all([req("/api/admin/municipios"), req("/api/admin/usuarios")]);
  montarAcessos("#novo-acessos");
  desenharUsuarios();
  $("#municipios").innerHTML = MUNIS.map((m) => `<tr><td>${esc(m.nome)}/${esc(m.uf)}</td><td>${esc(m.cod)}</td>
    <td>${m.processado ? "processados" : '<span class="selo alerta">não processados</span>'}</td>
    <td>${m.tem_rede ? "sim" : "não"}</td></tr>`).join("");
  const ev = await req("/api/admin/eventos?limite=200");
  $("#eventos").innerHTML = ev.map((e) => `<tr><td>${dataHora(e.quando)}</td><td>${esc(e.acao)}</td>
    <td>${esc(e.usuario || "")}</td><td>${esc(e.detalhe || "")}</td><td>${esc(e.ip || "")}</td></tr>`).join("");
}

/* ---------- nova conta ---------- */
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
    $("#novo-acessos-bloco").hidden = false;
    await carregar();
  } catch (err) { $("#erro-novo").textContent = err.message; }
};

/* ---------- ações por conta ---------- */
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

carregar().catch((e) => alert("Não foi possível carregar: " + e.message));
