/* Baixar o mapa como está na tela: imagem PNG ou PDF de uma página (A4/A3 deitado).
   Tudo no navegador: copia o desenho do MapLibre, redesenha por cima os marcadores
   (que são elementos HTML, fora do canvas) e monta cabeçalho, legenda, escala e fontes.
   Usa o estado e as funções de app.js (st, $, fmt, esc, svgPin, PRECISAS…). */
"use strict";

const COR = { texto: "#0D1450", texto2: "#4A5072", borda: "#D5D9EA", primaria: "#2F4BFF", coral: "#FF6B57", deficit: "#C93A27" };
const FONTE = '"Instrument Sans", system-ui, sans-serif', MONO = '"IBM Plex Mono", ui-monospace, monospace';

function ligarExportar() {
  const btn = $("#btn-baixar-mapa"), menu = $("#menu-baixar");
  if (!btn) return;
  const fechar = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  btn.onclick = (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    btn.setAttribute("aria-expanded", String(!menu.hidden));
  };
  document.addEventListener("click", (e) => { if (!menu.contains(e.target)) fechar(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") fechar(); });
  menu.querySelectorAll("[data-formato]").forEach((b) => (b.onclick = () => { fechar(); baixarMapa(b.dataset.formato); }));
}

async function baixarMapa(formato) {
  if (!st.map || !st.cfg) return;
  const btn = $("#btn-baixar-mapa"), txt = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Gerando…";
  try {
    if (document.fonts?.ready) await document.fonts.ready;
    const { canvas, escala } = await capturarMapa();
    const final = await compor(canvas, escala);
    const nome = nomeArquivo();
    if (formato === "png") {
      baixarBlob(await new Promise((r) => final.toBlob(r, "image/png")), `${nome}.png`);
    } else {
      const jpeg = await new Promise((r) => final.toBlob(r, "image/jpeg", 0.92));
      const pdf = pdfComImagem(new Uint8Array(await jpeg.arrayBuffer()), final.width, final.height, formato);
      baixarBlob(new Blob([pdf], { type: "application/pdf" }), `${nome}.pdf`);
    }
  } catch (e) {
    console.error(e);
    alert("Não foi possível gerar o mapa: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = txt;
  }
}

function baixarBlob(blob, nome) {
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: nome });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

const semAcento = (s) => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "");
const slug = (s) => semAcento(s).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

function nomeArquivo() {
  const muni = $("#municipio").selectedOptions[0]?.textContent.split(" – ")[0] || st.cod;
  const oque = st.mostrar === "prioridade" ? "prioridade" : st.mostrar;
  const raio = st.mostrar === "prioridade" ? "" : `_${st.raio[st.mostrar]}m`;
  const hoje = new Date().toISOString().slice(0, 10);
  return `mapa_${slug(muni)}_${oque}${raio}_${st.modo === "rede" ? "a_pe" : "linha_reta"}_${hoje}`;
}

/* ---------- 1. O mapa (canvas do MapLibre) em alta resolução ---------- */
function esperarOcioso(map, maxMs = 15000) {
  return new Promise((ok) => {
    const t = setTimeout(ok, maxMs);                         // não trava se algum mosaico não vier
    map.once("idle", () => { clearTimeout(t); ok(); });
    map.triggerRepaint();
  });
}

async function capturarMapa() {
  const map = st.map, original = map.getPixelRatio();
  const alvo = Math.max(2, window.devicePixelRatio || 1);
  if (original !== alvo) map.setPixelRatio(alvo);
  try {
    await esperarOcioso(map);
    // Lê o canvas WebGL no próprio evento de desenho (antes de o navegador limpá-lo)
    const canvas = await new Promise((ok) => {
      map.once("render", () => {
        const g = map.getCanvas(), c = document.createElement("canvas");
        c.width = g.width; c.height = g.height;
        c.getContext("2d").drawImage(g, 0, 0);
        ok(c);
      });
      map.triggerRepaint();
    });
    const escala = canvas.width / map.getContainer().clientWidth;
    await desenharMarcadores(canvas.getContext("2d"), escala);
    return { canvas, escala };
  } finally {
    if (original !== alvo) map.setPixelRatio(original);
  }
}

const _imgs = new Map();
function imagemSvg(svg) {
  if (!_imgs.has(svg)) {
    const src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" '));
    _imgs.set(svg, new Promise((ok, erro) => {
      const im = new Image();
      im.onload = () => ok(im);
      im.onerror = () => erro(new Error("ícone"));
      im.src = src;
    }));
  }
  return _imgs.get(svg);
}

const visivel = (m) => m.getElement().style.display !== "none";

async function desenharMarcadores(g, k) {
  const map = st.map, L = map.getContainer().clientWidth, A = map.getContainer().clientHeight;
  const dentro = (x, y, folga = 40) => x > -folga && y > -folga && x < L + folga && y < A + folga;
  // equipamentos (pino ancorado embaixo, com o deslocamento de quem divide o endereço)
  for (const ms of Object.values(st.pins)) {
    for (const m of ms) {
      if (!visivel(m)) continue;
      const p = map.project(m.getLngLat()), o = m.getOffset();
      const x = p.x + o.x, y = p.y + o.y;
      if (!dentro(x, y)) continue;
      const svg = m.getElement().querySelector("svg");
      const im = await imagemSvg(svg.outerHTML);
      g.drawImage(im, (x - 14) * k, (y - 36) * k, 28 * k, 36 * k);
    }
  }
  // áreas prioritárias (radar): anel, núcleo e número
  for (const [t, ms] of Object.entries(st.radares)) {
    const cor = st.cfg.tipos[t]?.cor || COR.coral;
    for (const m of ms) {
      if (!visivel(m)) continue;
      const p = map.project(m.getLngLat());
      if (!dentro(p.x, p.y)) continue;
      const x = p.x * k, y = p.y * k;
      g.save();
      g.globalAlpha = 0.45; g.strokeStyle = cor; g.lineWidth = 2 * k;
      g.beginPath(); g.arc(x, y, 16 * k, 0, 2 * Math.PI); g.stroke();
      g.globalAlpha = 1; g.fillStyle = cor; g.strokeStyle = "#fff";
      g.beginPath(); g.arc(x, y, 6 * k, 0, 2 * Math.PI); g.fill(); g.lineWidth = 2 * k; g.stroke();
      const num = m.getElement().querySelector(".num")?.textContent || "";
      if (num) {
        g.font = `600 ${11 * k}px ${MONO}`;
        const w = g.measureText(num).width + 10 * k, h = 16 * k, bx = x + 8 * k, by = y - 18 * k;
        g.fillStyle = cor; caixa(g, bx, by, w, h, 8 * k); g.fill();
        g.fillStyle = "#fff"; g.textBaseline = "middle"; g.fillText(num, bx + 5 * k, by + h / 2 + 0.5 * k);
      }
      g.restore();
    }
  }
  // unidade simulada
  if (st.sim) {
    const p = map.project(st.sim.lngLat);
    if (dentro(p.x, p.y)) {
      const x = p.x * k, y = p.y * k;
      g.save();
      g.fillStyle = COR.primaria; g.beginPath(); g.arc(x, y, 15 * k, 0, 2 * Math.PI); g.fill();
      g.fillStyle = "#fff"; g.beginPath(); g.arc(x, y, 13 * k, 0, 2 * Math.PI); g.fill();
      g.fillStyle = COR.primaria; g.beginPath(); g.arc(x, y, 10 * k, 0, 2 * Math.PI); g.fill();
      g.fillStyle = COR.coral; g.beginPath(); g.arc(x, y, 3.5 * k, 0, 2 * Math.PI); g.fill();
      g.restore();
    }
  }
}

function caixa(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}

/* ---------- 2. Página: cabeçalho, mapa, escala, legenda e fontes ---------- */
function textos() {
  const tipos = st.cfg.tipos;
  const muni = $("#municipio").selectedOptions[0]?.textContent || st.cod;
  const curto = (t) => tipos[t].rotulo.split(" (")[0];
  let titulo, nota;
  if (st.mostrar === "prioridade") {
    titulo = "Prioridade geral – todos os tipos de equipamento";
    nota = "Índice 0–100: gente fora do raio (2/3) e falta de capacidade (1/3), com os raios padrão.";
  } else {
    const c = tipos[st.mostrar];
    titulo = `Onde falta ${curto(st.mostrar).toLowerCase()}: ${c.unidade} fora do raio ou sem vaga`;
    nota = `${st.unid === "setor" ? "Setores censitários do IBGE" : "Hexágonos de ~0,1 km²"}; quanto mais escuro, maior a demanda não resolvida.`;
  }
  const raios = Object.keys(tipos).filter((t) => st.visivel[t] !== false)
    .map((t) => `${curto(t)} ${fmt(st.raio[t])} m (${minutos(st.raio[t])} min)`).join(" · ");
  return { muni, titulo, nota, sub: `Distância ${txtDist()} · Raios: ${raios || "nenhum tipo visível"}` };
}

function escalaMetros(zoom, lat) {
  const mpp = (40075016.686 * Math.cos((lat * Math.PI) / 180)) / (512 * 2 ** zoom);   // metros por pixel CSS
  const opcoes = [20, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 50000];
  const m = opcoes.filter((d) => d / mpp <= 130).pop() || opcoes[0];
  return { metros: m, px: m / mpp };
}

function quebrar(g, texto, largura) {
  const linhas = [];
  let atual = "";
  for (const p of texto.split(" ")) {
    const t = atual ? `${atual} ${p}` : p;
    if (g.measureText(t).width > largura && atual) { linhas.push(atual); atual = p; } else atual = t;
  }
  if (atual) linhas.push(atual);
  return linhas;
}

async function carregarImagem(src) {
  return new Promise((ok) => { const im = new Image(); im.onload = () => ok(im); im.onerror = () => ok(null); im.src = src; });
}

async function compor(mapa, k) {
  const W = mapa.width, M = 24 * k;
  const tx = textos();
  const medir = document.createElement("canvas").getContext("2d");

  // legenda: itens (ícone + texto) em linhas
  const itens = [];
  if (st.mostrar === "prioridade") itens.push({ rampa: ["#FFF1EE", "#FFB3A8", "#FF6B57", "#8E2A1C"], txt: "Prioridade geral (0 → 100)" });
  else itens.push({ rampa: ["#FFE9E5", "#FFB3A8", "#FF6B57", "#C93A27"], txt: "Demanda não resolvida (menor → maior)" });
  Object.entries(st.cfg.tipos).filter(([t]) => st.visivel[t] !== false).forEach(([, c]) =>
    itens.push({ pino: svgPin(c.cor, c.icone, false), txt: c.rotulo }));
  if ($("#tg-estaduais").checked && st.pins.contexto_medio?.length)
    itens.push({ pino: svgPin("#6b7280", "livro", false), txt: "Escola estadual de ensino médio (contexto)" });
  if ($("#tg-raios").checked) itens.push({ anel: true, txt: APE() ? "Alcance a pé pelas ruas" : "Raio de atendimento" });
  if ($("#tg-radar").checked) itens.push({ radar: true, txt: "Área prioritária sugerida" });
  if (st.equip.features.some((f) => !PRECISAS.has(f.properties.fonte_coord))) itens.push({ aprox: true, txt: "Localização a confirmar" });
  if (st.sim) itens.push({ sim: true, txt: "Nova unidade simulada" });

  medir.font = `500 ${12.5 * k}px ${FONTE}`;
  const larguraItem = (it) => 26 * k + medir.measureText(it.txt).width + 22 * k;
  const linhas = [[]];
  let x = 0;
  for (const it of itens) {
    const w = larguraItem(it);
    if (x + w > W - 2 * M && linhas.at(-1).length) { linhas.push([]); x = 0; }
    linhas.at(-1).push({ ...it, w }); x += w;
  }
  const base = st.cfg.mapa_base?.atribuicao || "© OpenStreetMap contributors";
  const quando = new Date().toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  const fontes = `Fontes: IBGE – Censo 2022 e Cadastro Nacional de Endereços; INEP – Censo Escolar; Ministério da Saúde – CNES; `
    + `malha viária e mapa de fundo: ${base}. Gerado em ${quando} na Equicidade (equicidade.com.br).`;
  medir.font = `400 ${11 * k}px ${FONTE}`;
  const linhasFontes = quebrar(medir, fontes, W - 2 * M);

  const HC = 78 * k, LH = 24 * k;
  const HR = M * 0.75 + linhas.length * LH + 6 * k + linhasFontes.length * 15 * k + M * 0.75;
  const c = document.createElement("canvas");
  c.width = W; c.height = Math.round(HC + mapa.height + HR);
  const g = c.getContext("2d");
  g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);

  // cabeçalho
  const logo = await carregarImagem("img/equicidade-horizontal.svg");
  let lx = M;
  if (logo) { const h = 26 * k, w = (logo.naturalWidth / logo.naturalHeight) * h || 115 * k; g.drawImage(logo, W - M - w, 16 * k, w, h); }
  g.fillStyle = COR.texto; g.textBaseline = "alphabetic";
  g.font = `700 ${19 * k}px ${FONTE}`;
  g.fillText(`${tx.muni} · ${tx.titulo}`, lx, 32 * k, W - 2 * M - 140 * k);
  g.fillStyle = COR.texto2; g.font = `500 ${12.5 * k}px ${FONTE}`;
  g.fillText(tx.sub, lx, 52 * k, W - 2 * M);
  g.fillText(tx.nota, lx, 69 * k, W - 2 * M);

  // mapa com moldura
  g.drawImage(mapa, 0, HC);
  g.strokeStyle = COR.borda; g.lineWidth = 1 * k;
  g.beginPath(); g.moveTo(0, HC); g.lineTo(W, HC); g.moveTo(0, HC + mapa.height); g.lineTo(W, HC + mapa.height); g.stroke();

  // escala (canto inferior esquerdo do mapa)
  const { metros, px } = escalaMetros(st.map.getZoom(), st.map.getCenter().lat);
  const rot = metros >= 1000 ? `${fmt(metros / 1000, metros % 1000 ? 1 : 0)} km` : `${metros} m`;
  g.font = `600 ${11 * k}px ${MONO}`;
  const ew = Math.max(px * k, g.measureText(rot).width) + 20 * k, eh = 34 * k, ex = 12 * k, ey = HC + mapa.height - eh - 12 * k;
  g.fillStyle = "rgba(255,255,255,.92)"; caixa(g, ex, ey, ew, eh, 8 * k); g.fill();
  g.fillStyle = COR.texto; g.fillText(rot, ex + 10 * k, ey + 14 * k);
  g.fillRect(ex + 10 * k, ey + 22 * k, px * k, 3 * k);
  g.fillRect(ex + 10 * k, ey + 18 * k, 1.5 * k, 7 * k); g.fillRect(ex + 10 * k + px * k - 1.5 * k, ey + 18 * k, 1.5 * k, 7 * k);

  // legenda
  let y = HC + mapa.height + M * 0.75;
  for (const linha of linhas) {
    let lxx = M;
    for (const it of linha) {
      await desenharIconeLegenda(g, it, lxx, y + 2 * k, k);
      g.fillStyle = COR.texto; g.font = `500 ${12.5 * k}px ${FONTE}`; g.textBaseline = "middle";
      g.fillText(it.txt, lxx + 26 * k, y + 10 * k);
      lxx += it.w;
    }
    y += LH;
  }
  y += 6 * k;
  g.fillStyle = COR.texto2; g.font = `400 ${11 * k}px ${FONTE}`; g.textBaseline = "alphabetic";
  for (const l of linhasFontes) { g.fillText(l, M, y + 11 * k); y += 15 * k; }
  return c;
}

async function desenharIconeLegenda(g, it, x, y, k) {
  const cx = x + 10 * k, cy = y + 8 * k;
  g.save();
  if (it.rampa) {
    const gr = g.createLinearGradient(x, 0, x + 20 * k, 0);
    it.rampa.forEach((cor, i) => gr.addColorStop(i / (it.rampa.length - 1), cor));
    g.fillStyle = gr; caixa(g, x, y + 1 * k, 20 * k, 14 * k, 3 * k); g.fill();
  } else if (it.pino) {
    g.drawImage(await imagemSvg(it.pino), x + 3 * k, y - 3 * k, 14 * k, 18 * k);
  } else if (it.anel) {
    g.strokeStyle = COR.texto2; g.lineWidth = 1.4 * k; g.fillStyle = "rgba(74,80,114,.08)";
    g.beginPath(); g.arc(cx, cy, 8 * k, 0, 2 * Math.PI); g.fill(); g.stroke();
  } else if (it.radar) {
    g.strokeStyle = COR.coral; g.globalAlpha = 0.45; g.lineWidth = 1.6 * k;
    g.beginPath(); g.arc(cx, cy, 8.5 * k, 0, 2 * Math.PI); g.stroke();
    g.globalAlpha = 1; g.fillStyle = COR.coral; g.beginPath(); g.arc(cx, cy, 4.5 * k, 0, 2 * Math.PI); g.fill();
  } else if (it.aprox) {
    g.strokeStyle = COR.deficit; g.lineWidth = 1.5 * k; g.setLineDash([3 * k, 2.2 * k]);
    g.beginPath(); g.arc(cx, cy, 8 * k, 0, 2 * Math.PI); g.stroke();
  } else if (it.sim) {
    g.fillStyle = COR.primaria; g.beginPath(); g.arc(cx, cy, 8.5 * k, 0, 2 * Math.PI); g.fill();
    g.fillStyle = COR.coral; g.beginPath(); g.arc(cx, cy, 3 * k, 0, 2 * Math.PI); g.fill();
  }
  g.restore();
}

/* ---------- 3. PDF de uma página com a imagem (JPEG) ---------- */
function pdfComImagem(jpeg, larg, alt, formato) {
  const [PW, PH] = formato === "a3" ? [1190.55, 841.89] : [841.89, 595.28];   // pontos, deitado
  const m = 18, s = Math.min((PW - 2 * m) / larg, (PH - 2 * m) / alt);
  const iw = larg * s, ih = alt * s, ix = (PW - iw) / 2, iy = (PH - ih) / 2;
  const n = (v) => Number(v.toFixed(2));
  const cont = `q ${n(iw)} 0 0 ${n(ih)} ${n(ix)} ${n(iy)} cm /Im0 Do Q`;
  const enc = new TextEncoder(), partes = [], offs = [];
  let tam = 0;
  const add = (x) => { const b = typeof x === "string" ? enc.encode(x) : x; partes.push(b); tam += b.length; };
  const obj = (i, corpo) => { offs[i] = tam; add(`${i} 0 obj\n${corpo}\nendobj\n`); };
  add("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n");
  obj(1, "<< /Type /Catalog /Pages 2 0 R >>");
  obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
  obj(3, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PW} ${PH}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>`);
  offs[4] = tam;
  add(`4 0 obj\n<< /Type /XObject /Subtype /Image /Width ${larg} /Height ${alt} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`);
  add(jpeg);
  add("\nendstream\nendobj\n");
  obj(5, `<< /Length ${cont.length} >>\nstream\n${cont}\nendstream`);
  const xref = tam;
  add(`xref\n0 6\n0000000000 65535 f \n${offs.slice(1).map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`);
  add(`trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
  const out = new Uint8Array(tam);
  let p = 0;
  for (const b of partes) { out.set(b, p); p += b.length; }
  return out;
}

ligarExportar();
