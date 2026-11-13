/* Proposta comercial: pede o código, busca a proposta e monta o orçamento. */
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const brl = (v) => Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const num = (v) => Number(v).toLocaleString("pt-BR");
const slug = location.pathname.split("/").filter(Boolean).pop() || "";
const CHAVE = `proposta.${slug}`;

let P = null;           // proposta aberta

async function abrir(codigo) {
  const r = await fetch(`/api/proposta/${encodeURIComponent(slug)}/abrir`, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF": "1" },
    body: JSON.stringify({ codigo }),
  });
  let corpo = null;
  try { corpo = await r.json(); } catch { /* sem corpo */ }
  if (!r.ok) throw new Error(typeof corpo?.detail === "string" ? corpo.detail : "Não foi possível abrir a proposta.");
  return corpo;
}

$("#form-codigo").addEventListener("submit", async (e) => {
  e.preventDefault();
  const codigo = $("#codigo").value.trim();
  const erro = $("#erro-codigo"), btn = e.target.querySelector("button");
  erro.textContent = "";
  if (codigo.length < 4) { erro.textContent = "Digite o código completo."; return; }
  btn.disabled = true;
  btn.textContent = "Abrindo…";
  try {
    mostrar(await abrir(codigo));
    try { sessionStorage.setItem(CHAVE, codigo); } catch { /* armazenamento bloqueado */ }
  } catch (err) {
    erro.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Abrir proposta";
  }
});

/* ---------- conteúdo ---------- */
function mostrar(p) {
  P = p;
  $("#portao").hidden = true;
  $("#conteudo").hidden = false;
  document.title = `Proposta para ${p.cliente} · Equicidade`;
  $("#p-eyebrow").textContent = `Proposta para ${p.cliente}`;
  $("#p-cta").textContent = `${p.contato ? p.contato.split(" ")[0] + ", vamos" : "Vamos"} ver o mapa de ${p.municipio} numa conversa de 20 minutos?`;
  $("#pop").value = p.populacao;
  minhaProposta();
  calcular();
  window.scrollTo(0, 0);
}

function minhaProposta() {
  const o = P.orcamento, validade = new Date(P.validade).toLocaleDateString("pt-BR");
  if (o.sob_proposta) {
    $("#minha").innerHTML = `<div class="minha-cartao"><span class="eyebrow">Sua proposta · ${esc(P.municipio)} – ${esc(P.uf)}</span>
      <h3>Proposta sob medida</h3><p>Para ${num(P.populacao)} habitantes, montamos o escopo e o cronograma junto com a equipe.</p>
      ${P.observacao ? `<p class="minha-obs">${esc(P.observacao)}</p>` : ""}<p class="minha-val">Válida até ${validade}</p></div>`;
    return;
  }
  $("#minha").innerHTML = `<div class="minha-cartao">
    <div class="minha-txt">
      <span class="eyebrow">Sua proposta · ${esc(P.municipio)} – ${esc(P.uf)}</span>
      <h3>${esc(P.cliente)}</h3>
      <p>${num(P.populacao)} habitantes · ${esc(o.rotulo)}</p>
      ${P.observacao ? `<p class="minha-obs">${esc(P.observacao)}</p>` : ""}
      <p class="minha-val">Válida até ${validade}</p>
    </div>
    <dl>
      <dt>Implantação</dt><dd>${brl(o.implantacao)}</dd>
      <dt>Assinatura do 1º ano${o.desconto_pct ? ` <span class="desc">−${o.desconto_pct}%</span>` : ""}</dt>
        <dd>${o.desconto_pct ? `<s>${brl(o.anual)}</s> ` : ""}${brl(o.anual_1)}</dd>
      ${o.estudo ? `<dt>Estudo de localização</dt><dd>${brl(o.estudo)}</dd>` : ""}
      <dt class="total">Total do 1º ano</dt><dd class="total">${brl(o.total_1)}</dd>
      <dt>Do 2º ano em diante</dt><dd>${brl(o.anual)}/ano</dd>
    </dl>
    ${o.cabe_dispensa ? `<span class="badge ok">✓ Cabe na dispensa de licitação</span>` : ""}
  </div>`;
}

function planos(ativa) {
  $("#planos").innerHTML = P.precos.faixas.map((f, i) => `<article class="plano${i === ativa ? " ativo" : ""}">
    ${i === ativa ? '<span class="selo-top">Sua faixa</span>' : ""}
    <span class="faixa-pop">${esc(f.rotulo)}</span>
    <div class="mes">${brl(f.anual / 12)}<small> /mês</small></div>
    <dl><dt>Assinatura anual</dt><dd>${brl(f.anual)}</dd><dt>Implantação</dt><dd>${brl(f.implantacao)}</dd>
    <dt class="tot">1º ano completo</dt><dd class="tot">${brl(f.implantacao + f.anual)}</dd></dl></article>`).join("");
}

function calcular() {
  if (!P) return;
  const pop = Number($("#pop").value) || 0;
  const faixas = P.precos.faixas, i = faixas.findIndex((f) => pop <= f.ate);
  planos(i);
  const res = $("#res");
  if (i === -1) {
    res.innerHTML = `<h3>${num(pop)} habitantes</h3><p style="margin:0">Para cidades acima de 300 mil habitantes, montamos uma proposta sob medida.</p>`;
    return;
  }
  const f = faixas[i], piloto = $("#piloto").checked, estudo = $("#estudo").checked ? P.precos.estudo : 0;
  const anual = piloto ? f.anual / 2 : f.anual, total = f.implantacao + anual + estudo;
  res.innerHTML = `<h3>${num(pop)} habitantes · ${esc(f.rotulo)}</h3>
    <dl><dt>Implantação</dt><dd>${brl(f.implantacao)}</dd>
    <dt>Assinatura do 1º ano${piloto ? " (piloto)" : ""}</dt><dd>${brl(anual)}</dd>
    ${estudo ? `<dt>Estudo de localização (média)</dt><dd>${brl(estudo)}</dd>` : ""}
    <dt class="total">Total do 1º ano</dt><dd class="total">${brl(total)}</dd>
    <dt>Do 2º ano em diante</dt><dd>${brl(f.anual)}/ano</dd></dl>
    ${total <= P.precos.teto_dispensa ? `<span class="badge ok">✓ Cabe na dispensa de licitação</span>`
      : `<span class="badge alerta">Passa do limite de dispensa: o estudo pode ficar para outro exercício</span>`}`;
}
["pop", "estudo", "piloto"].forEach((id) => $(`#${id}`).addEventListener("input", calcular));

/* ---------- gráfico de Arapiraca ---------- */
const BARRAS = [["Creche", "0 a 3 anos · 500 m", 36, 24], ["Pré-escola", "4 e 5 anos · 500 m", 53, 35],
  ["Fundamental – anos iniciais", "6 a 10 anos · 1 km", 82, 67], ["Fundamental – anos finais", "11 a 14 anos · 1,5 km", 90, 79],
  ["UBS", "toda a população · 1 km", 86, 67]];
$("#barras").innerHTML = BARRAS.map(([n, s, r, p], i) => `<div class="b-linha"><div class="b-nome">${n}<small>${s}</small></div>
  <div class="b-trilhos"><div class="b-trilho reta" role="img" aria-label="${n}: ${r}% em linha reta"><i style="width:${r}%;animation-delay:${i * 0.1}s"></i><b>${r}%</b></div>
  <div class="b-trilho pe" role="img" aria-label="${n}: ${p}% a pé"><i style="width:${p}%;animation-delay:${i * 0.1 + 0.15}s"></i><b>${p}%</b></div></div></div>`).join("");

$("#copiar").addEventListener("click", async (e) => {
  try { await navigator.clipboard.writeText("82988189617"); e.target.textContent = "Número copiado"; }
  catch {
    const r = document.createRange(); r.selectNodeContents($("#tel"));
    const s = getSelection(); s.removeAllRanges(); s.addRange(r); e.target.textContent = "Copie com Ctrl+C";
  }
});

/* ---------- reabre na mesma aba sem pedir o código de novo ---------- */
(async () => {
  let salvo = null;
  try { salvo = sessionStorage.getItem(CHAVE); } catch { /* armazenamento bloqueado */ }
  if (!salvo) { $("#codigo").focus(); return; }
  try { mostrar(await abrir(salvo)); } catch { try { sessionStorage.removeItem(CHAVE); } catch { /* nada */ } }
})();
