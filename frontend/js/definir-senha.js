/* Definir senha a partir do link de convite / redefinição.
   O token vem no fragmento (#...) da URL: não vai para o servidor nos logs de acesso
   nem para outros sites no cabeçalho Referer. Assim que lido, sai da barra de endereço. */
"use strict";

const $ = (s) => document.querySelector(s);
const token = decodeURIComponent(location.hash.slice(1));
history.replaceState(null, "", location.pathname);

async function postar(url, dados) {
  const r = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF": "1" },
    body: JSON.stringify(dados),
  });
  let corpo = {};
  try { corpo = await r.json(); } catch { /* sem corpo */ }
  return { ok: r.ok, corpo };
}

function mostrar(id) {
  for (const x of ["carregando", "form-senha", "feito", "invalido"]) $("#" + x).hidden = x !== id;
}

async function iniciar() {
  if (!token) { mostrar("invalido"); return; }
  const r = await postar("/auth/convite", { token }).catch(() => ({ ok: false }));
  if (!r.ok) { mostrar("invalido"); return; }
  $("#titulo").textContent = r.corpo.motivo === "redefinicao" ? "Nova senha" : "Criar senha";
  $("#quem").textContent = `${r.corpo.nome} · ${r.corpo.email}`;
  $("#email").value = r.corpo.email;          // ajuda o gerenciador de senhas a associar a conta
  mostrar("form-senha");
  $("#senha").focus();
}

$("#form-senha").addEventListener("submit", async (e) => {
  e.preventDefault();
  const s1 = $("#senha").value, s2 = $("#senha2").value;
  $("#erro").textContent = "";
  if (s1.length < 12) { $("#erro").textContent = "A senha precisa ter pelo menos 12 caracteres."; return; }
  if (s1 !== s2) { $("#erro").textContent = "As duas senhas não são iguais."; return; }
  $("#btn-salvar").disabled = true;
  const r = await postar("/auth/definir-senha", { token, senha: s1 }).catch(() => ({ ok: false, corpo: {} }));
  $("#btn-salvar").disabled = false;
  if (r.ok) { mostrar("feito"); return; }
  $("#erro").textContent = r.corpo.detail || "Não foi possível salvar. Tente de novo.";
});

iniciar();
