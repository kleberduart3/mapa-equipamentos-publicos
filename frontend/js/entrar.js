/* Página de login */
"use strict";

const $ = (s) => document.querySelector(s);

async function postar(url, dados) {
  const r = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF": "1" },
    body: JSON.stringify(dados),
  });
  let corpo = {};
  try { corpo = await r.json(); } catch { /* sem corpo */ }
  return { ok: r.ok, status: r.status, corpo };
}

$("#form-entrar").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#btn-entrar");
  $("#erro").textContent = "";
  const email = $("#email").value.trim(), senha = $("#senha").value;
  if (!email || !senha) { $("#erro").textContent = "Preencha e-mail e senha."; return; }
  btn.disabled = true;
  try {
    const r = await postar("/auth/entrar", { email, senha });
    if (r.ok) { location.href = "/"; return; }
    $("#erro").textContent = r.corpo.detail || "Não foi possível entrar.";
    $("#senha").value = "";
    $("#senha").focus();
  } catch {
    $("#erro").textContent = "Sem conexão com o servidor.";
  } finally {
    btn.disabled = false;
  }
});

$("#lnk-esqueci").addEventListener("click", (e) => {
  e.preventDefault();
  $("#form-entrar").hidden = true;
  $("#form-esqueci").hidden = false;
  $("#email-esqueci").value = $("#email").value;
  $("#email-esqueci").focus();
});
$("#lnk-voltar").addEventListener("click", (e) => {
  e.preventDefault();
  $("#form-esqueci").hidden = true;
  $("#form-entrar").hidden = false;
});
$("#form-esqueci").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await postar("/auth/esqueci", { email: $("#email-esqueci").value.trim() }).catch(() => null);
  $("#msg-esqueci").textContent = r?.corpo?.mensagem || "Não foi possível enviar agora. Tente mais tarde.";
});

$("#email").focus();
