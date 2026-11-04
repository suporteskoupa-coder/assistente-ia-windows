"use strict";
/* Lógica da HUD: conversa, chats, confirmações, lembretes, resumo, servidor e dados do PC.
   O desenho do núcleo fica em nucleo.js (window.Nucleo). */
const $ = (s) => document.querySelector(s);
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const N = window.Nucleo || { setState() {}, setLocal() {}, setLoad() {}, setGame() {}, setNight() {}, setCompact() {}, reboot() {} };
const state = { reminders: [], chats: [], chatId: null, brain: "claude", ws: null, pending: [], assistantEl: null, queue: [], sound: false };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json", "X-Ultron-Token": TOKEN }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

const MOOD_TEXT = {
  idle: ["OCIOSO", "aguardando comando"], thinking: ["PENSANDO", "analisando o pedido"], tool: ["FERRAMENTA", "executando ações"],
  speaking: ["RESPONDENDO", "escrevendo a resposta"], seeing: ["LENDO A TELA", "olhando o monitor principal"],
  confirm: ["CONFIRMAÇÃO", "aguardando sua autorização"], remind: ["LEMBRETE", "chegou a hora"],
};
function setMood(m) {
  const mood = state.pending.length ? "confirm" : state.reminders.length ? "remind" : m;
  document.body.classList.remove("idle", "thinking", "tool", "confirm", "remind", "speaking", "seeing");
  document.body.classList.add(mood);
  N.setState(mood);
  const [name, sub] = MOOD_TEXT[mood] || MOOD_TEXT.idle;
  $("#state-name").textContent = name; $("#state-sub").textContent = sub;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// Markdown mínimo e seguro: escapa o HTML antes de aplicar negrito e código.
function md(text) {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
}
function setText(e, text) {
  e.dataset.raw = text;
  if (e.classList.contains("assistant")) { e.innerHTML = md(text); e.appendChild(likeButton(e)); } else e.textContent = text;
}
// 👍: guarda a resposta no banco de exemplos (Ultron/Exemplos.md), que ensina o tom ao Ultron.
function likeButton(msgEl) {
  const b = el("button", "like", "👍");
  b.title = "Gostei: guardar como exemplo de como o Ultron fala";
  b.onclick = async () => {
    if (b.classList.contains("on") || state.chatId === null) return;
    try {
      await api(`/api/chats/${state.chatId}/like`, { method: "POST", body: JSON.stringify({ reply: msgEl.dataset.raw }) });
      b.classList.add("on"); b.title = "Guardado em Ultron/Exemplos.md";
    } catch (err) { b.title = err.message; b.classList.add("fail"); setTimeout(() => b.classList.remove("fail"), 1500); }
  };
  return b;
}
function addMsg(role, text) {
  const e = el("div", "msg " + role);
  setText(e, text);
  $("#history").appendChild(e);
  $("#history").scrollTop = $("#history").scrollHeight;
  if (role === "assistant" || role === "error") $("#bubble").textContent = text;
  return e;
}

function fmtDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function renderChats() {
  const box = $("#chats");
  box.replaceChildren();
  for (const c of state.chats) {
    const b = el("button", "chat chat-item" + (c.id === state.chatId ? " on" : ""), c.title);
    b.appendChild(el("small", "", (c.brain === "claude" ? "claude" : "local") + " · " + fmtDate(c.updated)));
    b.onclick = () => openChat(c.id);
    box.appendChild(b);
  }
  const cur = state.chats.find((c) => c.id === state.chatId);
  $("#stat-brain").textContent = cur ? (cur.brain === "claude" ? "CLAUDE" : "LOCAL") : "—";
  $("#chat-title").textContent = cur ? cur.title : "novo chat";
}
async function loadChats() { state.chats = await api("/api/chats"); renderChats(); }
async function openChat(id) {
  state.chatId = id;
  renderChats();
  const msgs = await api(`/api/chats/${id}/messages`);
  $("#history").replaceChildren(); $("#bubble").textContent = "";
  for (const m of msgs) addMsg(m.role, m.content);
}
async function newChat() {
  const c = await api("/api/chats", { method: "POST", body: JSON.stringify({ brain: state.brain }) });
  state.chatId = c.id;
  $("#history").replaceChildren(); $("#bubble").textContent = "";
  await loadChats();
  return c;
}

function selectBrain(brain, save = true) {
  const changed = state.brain !== brain;
  state.brain = brain;
  document.querySelectorAll(".brain-select button").forEach((b) => b.classList.toggle("on", b.dataset.brain === brain));
  document.body.classList.toggle("local", brain === "ollama");
  $("#mode-label").textContent = brain === "ollama" ? "JARVIS · LOCAL" : "ULTRON · CLAUDE";
  N.setLocal(brain === "ollama");
  if (changed && save) beep(brain === "ollama" ? 980 : 520, 0.14, "triangle");
  // o modo vale para chats novos e para quem responde no servidor do Discord
  if (save) api("/api/mode", { method: "POST", body: JSON.stringify({ brain }) }).catch(() => {});
}
async function loadMode() { try { selectBrain((await api("/api/mode")).brain, false); } catch (_) {} }

async function send(text) {
  if (!text.trim()) return;
  if (state.chatId === null) await newChat();
  addMsg("user", text);
  beep(660, 0.05);
  state.assistantEl = null;
  setMood("thinking");
  const msg = { type: "send", chat_id: state.chatId, text };
  if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(msg));
  else state.queue.push(msg);
}

function onEvent(m) {
  if (m.type === "confirm") return showConfirm(m);
  if (m.type === "reminder") return showReminder(m);
  if (m.type === "server_reply") return showServerReply(m);
  if (m.chat_id !== state.chatId) { if (m.type === "done") loadChats(); return; }
  if (m.type === "text") {
    if (state.assistantEl) {
      setText(state.assistantEl, state.assistantEl.dataset.raw + "\n\n" + m.text);
      $("#bubble").textContent = state.assistantEl.dataset.raw;
    } else state.assistantEl = addMsg("assistant", m.text);
    setMood("speaking");
  } else if (m.type === "tool") {
    const args = Object.entries(m.data.input || {}).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" ");
    addMsg("tool", `› ${m.data.name} ${args}`);
    state.assistantEl = null;
    setMood(m.data.name === "ver_tela" ? "seeing" : "tool");
    beep(540, 0.04, "square", 0.02);
  } else if (m.type === "error") {
    addMsg("error", m.text);
    setMood("idle"); loadChats();
  } else if (m.type === "done") {
    setMood("idle"); loadChats(); refreshStatus();
  }
}

const ACTIONS = {
  discord_enviar: (d) => `Enviar no Discord, canal #${d.canal}:`,
  organizar_pasta: (d) => `Executar o plano de organização ${d.plano_id} (mover arquivos).`,
  desfazer_organizacao: (d) => `Desfazer o plano de organização ${d.plano_id}.`,
  Bash: (d) => `Rodar no terminal:\n${d.command}`,
  Write: (d) => `Criar/substituir o arquivo:\n${d.file_path}`,
  Edit: (d) => `Editar o arquivo:\n${d.file_path}`,
};
function showConfirm(item) {
  if (!state.pending.some((p) => p.id === item.id)) { state.pending.push(item); beep(440, 0.15, "triangle"); }
  renderConfirm();
}
function renderConfirm() {
  const card = $("#confirm-card"), item = state.pending[0];
  if (!item) { card.hidden = true; setMood("idle"); return; }
  const d = item.detail || {}, describe = ACTIONS[item.action];
  $("#confirm-desc").textContent = describe ? describe(d) : `${item.action}\n${JSON.stringify(d, null, 1)}`;
  const ta = $("#confirm-text");
  ta.hidden = item.action !== "discord_enviar";
  ta.value = d.texto || "";
  card.hidden = false;
  setMood("confirm");
  if (window.pywebview && window.pywebview.api && window.pywebview.api.attention) window.pywebview.api.attention();
}
async function answer(allow) {
  const item = state.pending.shift();
  if (!item) return;
  const body = { allow };
  if (allow && item.action === "discord_enviar") body.edited = { ...item.detail, texto: $("#confirm-text").value };
  beep(allow ? 760 : 300, 0.08);
  renderConfirm();
  await api(`/api/confirm/${item.id}`, { method: "POST", body: JSON.stringify(body) });
}

function showServerReply(m) {
  const box = $("#server-log");
  if (!box.dataset.used) box.replaceChildren();
  box.dataset.used = "1";
  const e = el("div", "concl", `${m.author}: ${m.question}`);
  e.appendChild(el("small", "", `Ultron: ${m.reply}`));
  box.prepend(e);
  while (box.children.length > 3) box.lastChild.remove();
}

function showReminder(r) {
  if (!state.reminders.some((x) => x.id === r.id)) {
    state.reminders.push(r);
    beep(988, 0.12, "triangle"); setTimeout(() => beep(1318, 0.16, "triangle"), 160);
  }
  renderReminder();
}
function renderReminder() {
  const card = $("#reminder-card"), r = state.reminders[0];
  if (!r) { card.hidden = true; setMood("idle"); return; }
  $("#reminder-title").textContent = r.late ? "LEMBRETE ATRASADO" : "LEMBRETE";
  $("#reminder-text").textContent = r.text;
  card.hidden = false;
  setMood("remind");
}
async function reminderAction(action) {
  const r = state.reminders.shift();
  renderReminder();
  if (r) await api(`/api/reminders/${r.id}/${action}`, { method: "POST" }).catch(() => {});
}

async function loadBriefing() {
  let b;
  try { b = await api("/api/briefing"); } catch (_) { return; }
  const body = $("#briefing-body");
  body.replaceChildren();
  const line = (text, cls) => body.appendChild(el("div", cls || "", text));
  for (const r of b.reminders_today) line(`⏰ ${r.when} · ${r.text}`);
  if (b.pending_count) line(`${b.pending_count} pendência${b.pending_count > 1 ? "s" : ""} aberta${b.pending_count > 1 ? "s" : ""} no Obsidian`);
  for (const c of b.new_conclusions) line(`Nova conclusão: ${c.text} (${c.confidence})`, "muted");
  for (const r of b.missed) line(`Perdido: ${r.text} (${r.when})`, "muted");
  if (body.children.length) $("#briefing").hidden = false;
  try { for (const r of await api("/api/reminders/active")) showReminder(r); } catch (_) {}
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    $("#stat-notes").textContent = `${s.notes} notas`;
    $("#stat-actions").textContent = `${s.actions_today} ações`;
    $("#stat-games").textContent = `${s.games} jogos`;
    $("#stat-claude").textContent = s.claude ? "OK" : "AUSENTE";
    $("#stat-ollama").textContent = s.ollama ? "OK" : "DESLIGADO";
  } catch (_) { /* núcleo reiniciando */ }
  try {
    const items = await api("/api/conclusions");
    const box = $("#conclusions");
    box.replaceChildren();
    for (const c of items.slice(0, 3)) {
      const e = el("div", "concl", c.text);
      e.appendChild(el("small", "", `${c.confidence} · ${c.seen}×`));
      box.appendChild(e);
    }
    if (!items.length) box.appendChild(el("div", "concl", "Nada ainda."));
  } catch (_) {}
}

// dados reais do PC → painel SISTEMA e núcleo
function setNum(key, value) {
  const n = $("#n-" + key), t = $("#t-" + key);
  if (value === null || value === undefined) { n.textContent = "—"; t.style.width = "0"; return; }
  const v = Math.round(value);
  n.replaceChildren(document.createTextNode(String(v)), el("small", "", "%"));
  t.style.width = v + "%"; t.classList.toggle("warn", v > 85);
}
async function refreshSystem() {
  try {
    const s = await api("/api/system");
    setNum("cpu", s.cpu); setNum("gpu", s.gpu); setNum("ram", s.ram);
    N.setLoad({ cpu: s.cpu || 0, gpu: s.gpu || 0, ram: s.ram || 0 });
    N.setGame(!!s.game);
    $("#k-game").textContent = s.game || "—";
    $("#k-game-tag").textContent = s.game ? "EM JOGO" : "";
  } catch (_) {}
  const h = new Date().getHours();
  N.setNight(h < 6);
  $("#clock").textContent = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws?t=${encodeURIComponent(TOKEN)}`);
  state.ws = ws;
  ws.onopen = () => { while (state.queue.length) ws.send(JSON.stringify(state.queue.shift())); };
  ws.onmessage = (e) => onEvent(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 1500);
}

// sons curtos e discretos (desligados por padrão)
let audio = null;
function beep(freq, dur = 0.08, type = "sine", vol = 0.04) {
  if (!state.sound) return;
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = type; o.frequency.value = freq; g.gain.value = vol;
    g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + dur);
    o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + dur);
  } catch (_) {}
}
try { state.sound = localStorage.getItem("ultron-sound") === "1"; } catch (_) {}
$("#sound").setAttribute("aria-pressed", String(state.sound));
$("#sound").onclick = () => {
  state.sound = !state.sound;
  $("#sound").setAttribute("aria-pressed", String(state.sound));
  try { localStorage.setItem("ultron-sound", state.sound ? "1" : "0"); } catch (_) {}
  beep(700, 0.06);
};

function toggleCompact() {
  const compact = !document.body.classList.contains("compact");
  setCompact(compact);
  if (window.pywebview && window.pywebview.api) window.pywebview.api.set_compact(compact);
}
function setCompact(on) { document.body.classList.toggle("compact", on); N.setCompact(on); }
window.ultron = { setCompact };

$("#form").addEventListener("submit", (e) => { e.preventDefault(); const t = $("#input").value; $("#input").value = ""; send(t); });
$("#new-chat").onclick = () => newChat();
$("#allow").onclick = () => answer(true);
$("#deny").onclick = () => answer(false);
$("#rem-ok").onclick = () => reminderAction("ok");
$("#rem-snooze").onclick = () => reminderAction("snooze");
$("#briefing-close").onclick = () => { $("#briefing").hidden = true; };
$("#toggle-compact").onclick = toggleCompact;
$("#close").onclick = () => (window.pywebview && window.pywebview.api ? window.pywebview.api.quit() : window.close());
document.querySelectorAll(".brain-select button").forEach((b) => (b.onclick = () => selectBrain(b.dataset.brain)));
$("#switch-brain").onclick = async () => {
  const cur = state.chats.find((c) => c.id === state.chatId);
  if (!cur) return;
  const other = cur.brain === "claude" ? "ollama" : "claude";
  setMood("thinking");
  const c = await api(`/api/chats/${cur.id}/switch`, { method: "POST", body: JSON.stringify({ brain: other }) });
  selectBrain(other);
  await loadChats();
  await openChat(c.id);
  setMood("idle");
};
$("#close-chat").onclick = async () => {
  if (state.chatId === null) return;
  setMood("thinking");
  await api(`/api/chats/${state.chatId}/close`, { method: "POST" });
  state.chatId = null;
  $("#history").replaceChildren();
  $("#bubble").textContent = "Resumo salvo no Obsidian.";
  await loadChats();
  setMood("idle");
};

setMood("idle");
connect();
loadChats();
loadBriefing();
loadMode();
refreshStatus();
refreshSystem();
setInterval(refreshStatus, 15000);
setInterval(refreshSystem, 2000);
