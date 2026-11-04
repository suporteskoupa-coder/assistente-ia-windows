/* Núcleo da HUD do Ultron: a "mente" desenhada em canvas.
   Modo Claude = Ultron (dourado, caótico). Modo local = JARVIS (ciano, ordenado).
   Trocar de modo faz um absorver o outro. API em window.Nucleo. */
(() => {
"use strict";
const cv = document.getElementById("core");
const ctx = cv.getContext("2d");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const TAU = Math.PI * 2;
const GOLD = [255, 176, 64], CYAN = [89, 214, 255], ALERT = [255, 70, 60], HOT = [255, 246, 236], STRUCT = [150, 128, 104];
const S = {
  state: "idle", local: false, game: false, night: false, compact: false,
  cpu: 0, gpu: 0, ram: 0, view: { cpu: 0, gpu: 0, ram: 0 },
  t: 0, spin: 0, phase: 0, spd: 0.3, bpm: 0.25, boot: 0, glitch: 0, wave: 0, morph: 0, flick: 0,
  px: 0, py: 0, tx: 0, ty: 0, lastInput: 0,
};
const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, Math.min(1, a))})`;
const mix = (a, b, k) => a.map((v, i) => v + (b[i] - v) * k);
const ease = (x) => 1 - Math.pow(1 - Math.max(0, Math.min(1, x)), 3);

let W = 0, H = 0, DPR = 1, bgLayer = null, bloom = null, bloomKey = "";
function resize() {
  const r = cv.getBoundingClientRect();
  DPR = Math.min(2, devicePixelRatio || 1);
  W = r.width; H = r.height;
  cv.width = Math.max(1, Math.round(W * DPR)); cv.height = Math.max(1, Math.round(H * DPR));
  bgLayer = null; bloomKey = "";
}
new ResizeObserver(resize).observe(cv);
function buildBg() { // grade de pontos desenhada uma vez
  const off = document.createElement("canvas");
  off.width = cv.width; off.height = cv.height;
  const g = off.getContext("2d"); g.scale(DPR, DPR);
  g.fillStyle = rgba(STRUCT, 0.2);
  for (let y = 11; y < H; y += 22) for (let x = 11; x < W; x += 22) g.fillRect(x, y, 1, 1);
  return off;
}
function buildBloom(R, col) { // brilho desfocado em cache
  const s = Math.max(2, Math.ceil(R * 6)), off = document.createElement("canvas");
  off.width = off.height = s;
  const g = off.getContext("2d"), m = s / 2, gr = g.createRadialGradient(m, m, 0, m, m, m);
  gr.addColorStop(0, rgba(col, 0.55)); gr.addColorStop(0.18, rgba(col, 0.35));
  gr.addColorStop(0.45, rgba(col, 0.08)); gr.addColorStop(1, rgba(col, 0));
  g.fillStyle = gr; g.fillRect(0, 0, s, s);
  return off;
}

/* ---------- a mente: Ultron (dourado, caótico) ⇄ JARVIS (ciano, ordenado) ---------- */
// cada ponto tem uma direção; no Ultron o raio "ferve" com ruído, no JARVIS fica numa esfera perfeita
const N_PTS = 1100, N_TENDRILS = 46;
function noise3(x, y, z) {
  return (Math.sin(x * 1.7 + y * 2.3) + Math.sin(y * 1.9 + z * 2.9 + 1.3) + Math.sin(z * 2.1 + x * 1.3 + 2.1)
    + 0.5 * Math.sin(x * 4.1 - z * 3.7 + 0.7)) / 3.5;
}
function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
function norm(v) { const l = Math.hypot(...v) || 1; return v.map((x) => x / l); }
function randDir() { const u = Math.random() * 2 - 1, phi = Math.random() * TAU, s = Math.sqrt(1 - u * u); return [s * Math.cos(phi), u, s * Math.sin(phi)]; }

const PTS = [];
for (let i = 0; i < N_PTS; i++) {
  const y = 1 - (i / (N_PTS - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.399963;
  const d = [Math.cos(th) * r, y, Math.sin(th) * r];
  PTS.push({ d, inner: Math.random() < 0.16 ? 0.2 + Math.random() * 0.55 : 0, tw: Math.random() * TAU, size: Math.random() });
}
// malha geodésica do JARVIS: cada ponto liga aos 2 vizinhos mais próximos na esfera perfeita
const LINKS = [];
{
  const seen = new Set();
  for (let i = 0; i < N_PTS; i++) {
    const best = [];
    for (let j = Math.max(0, i - 60); j < Math.min(N_PTS, i + 60); j++) {
      if (j === i) continue;
      const a = PTS[i].d, b = PTS[j].d, dd = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
      best.push([dd, j]);
    }
    best.sort((x, y) => x[0] - y[0]);
    if (PTS[i].inner) continue; // malha só na superfície (sem raios do centro)
    for (const [, j] of best.filter(([, j]) => !PTS[j].inner).slice(0, 2)) { const key = i < j ? i + "," + j : j + "," + i; if (!seen.has(key)) { seen.add(key); LINKS.push([i, j]); } }
  }
}
// tentáculos do Ultron: caminhos sobre a superfície que estalam e renascem em lugares aleatórios
function newTendril() {
  const axis = randDir(), t = Math.abs(axis[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
  const e1 = norm(cross(axis, t)), e2 = cross(axis, e1);
  return { e1, e2, start: Math.random() * TAU, len: 0.5 + Math.random() * 1.8, life: 0, max: 0.6 + Math.random() * 2.2,
    speed: (Math.random() - 0.5) * 2.4, hot: Math.random() < 0.2, seed: Math.random() * 100 };
}
const TENDRILS = Array.from({ length: N_TENDRILS }, () => { const t = newTendril(); t.life = Math.random() * t.max; return t; });
const SPARKS = [];
function spark(n, color) { for (let i = 0; i < n; i++) SPARKS.push({ d: randDir(), r: 0.3, v: 0.8 + Math.random() * 1.8, life: 1, color }); }

// raio do Ultron na direção d: superfície que ferve, com pontas
function chaosR(d, t, amp) {
  const n = noise3(d[0] * 2.4 + t * 0.55, d[1] * 2.4 - t * 0.4, d[2] * 2.4 + t * 0.35);
  const spike = Math.max(0, noise3(d[0] * 5 - t, d[1] * 5 + t * 0.7, d[2] * 5) - 0.55) * 1.6;
  return 0.84 + n * 0.22 * amp + spike * amp;
}

function frame(dt) {
  const b = ease(S.boot), small = W < 640;
  const mT = S.local ? 1 : 0;                      // 0 = Ultron, 1 = JARVIS
  S.morph += (mT - S.morph) * (1 - Math.exp(-dt * 1.5));
  const m = S.morph, absorbing = Math.abs(mT - S.morph) > 0.02;
  const base = mix(GOLD, CYAN, m);
  const alert = S.state === "confirm" || S.state === "remind";
  let dim = 1; if (S.night) dim *= 0.6; if (S.game) dim *= 0.4;
  const A = (a) => a * dim * b;
  const chaos = 1 - m;                              // quanto do Ultron está presente

  const load = (S.view.cpu + S.view.gpu) / 200;
  const tSpd = (S.game ? 0.15 : 1) * ({ idle: 0.3, thinking: 1.8, tool: 1.3, speaking: 0.8, seeing: 1, confirm: 0.6, remind: 0.9 }[S.state]) * (1 + load);
  const tBpm = { idle: 0.25, thinking: 1.3, tool: 0.9, speaking: 0.9, seeing: 1, confirm: 0.8, remind: 1.7 }[S.state] + load * 0.5;
  const k = 1 - Math.exp(-dt * 1.4);
  S.spd += (tSpd - S.spd) * k; S.bpm += (tBpm - S.bpm) * k;
  if (!reduce) { S.spin += dt * S.spd; S.phase += dt * TAU * S.bpm; }
  const beat = 0.5 + 0.5 * Math.sin(S.phase), sp = S.spin, t = S.t;
  S.px += (S.tx - S.px) * 0.05; S.py += (S.ty - S.py) * 0.05;
  const agit = { idle: 1, thinking: 2.2, tool: 1.7, speaking: 1.3, seeing: 1.4, confirm: 1.5, remind: 1.9 }[S.state];
  S.wave = S.state === "speaking" ? Math.min(1, S.wave + dt * 3) : Math.max(0, S.wave - dt * 2);
  // tremulação do Ultron: picos irregulares de brilho (o JARVIS não tremula)
  S.flick = (S.flick || 0) * Math.exp(-dt * 6);
  if (!reduce && Math.random() < dt * 1.6 * agit * chaos) S.flick = 0.4 + Math.random() * 0.6;

  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.clearRect(0, 0, W, H);
  if (!bgLayer) bgLayer = buildBg();
  ctx.globalAlpha = 0.8 * b; ctx.drawImage(bgLayer, 0, 0, W, H); ctx.globalAlpha = 1;

  const area = document.getElementById("core-area");
  const ce = area ? area.getBoundingClientRect() : cv.getBoundingClientRect(), sr = cv.getBoundingClientRect();
  const cx = ce.left - sr.left + ce.width / 2, cy = ce.top - sr.top + ce.height / 2;
  const R = Math.min(ce.width, ce.height) * (S.compact ? 0.33 : 0.3) * b;

  // rotação: JARVIS gira liso num eixo; Ultron oscila em vários eixos
  const wob = chaos * (0.35 * Math.sin(t * 0.73) + 0.2 * Math.sin(t * 1.9 + 1));
  const yaw = sp * 0.6 + S.px * 0.6 + wob, pitch = -0.25 + S.py * 0.4 + chaos * 0.25 * Math.sin(t * 0.51 + 2);
  const roll = chaos * 0.18 * Math.sin(t * 0.37);
  const cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), spc = Math.sin(pitch), cr0 = Math.cos(roll), sr0 = Math.sin(roll);
  const FOV = 3.2;
  const proj = (p) => {
    let x = p[0] * cyw + p[2] * syw, z = -p[0] * syw + p[2] * cyw, y = p[1];
    const y2 = y * cp - z * spc, z2 = y * spc + z * cp;
    const x3 = x * cr0 - y2 * sr0, y3 = x * sr0 + y2 * cr0;
    const f = FOV / (FOV + z2);
    return [cx + x3 * R * f, cy + y3 * R * f, z2, f];
  };
  const swirl = absorbing ? Math.sin(Math.PI * Math.min(1, Math.abs(mT - m) * 1.1)) : 0;
  const pulse = 1 + 0.03 * beat + S.wave * 0.05 * Math.sin(t * 9);
  const amp = agit * chaos;

  ctx.globalCompositeOperation = "lighter";
  const key = R.toFixed(0) + base.map((v) => v | 0).join();
  if (bloomKey !== key) { bloom = buildBloom(R * 0.5, base); bloomKey = key; }
  const bs = R * 3.2 * (0.9 + 0.15 * beat + 0.25 * S.flick);
  ctx.globalAlpha = A(0.85 + 0.15 * S.flick); ctx.drawImage(bloom, cx - bs / 2, cy - bs / 2, bs, bs); ctx.globalAlpha = 1;

  // ---- JARVIS: latitudes e longitudes limpas ----
  if (m > 0.02) {
    ctx.lineWidth = 0.9;
    const ringPts = 64;
    for (let L = -3; L <= 3; L++) {
      const yy = L / 4, rr = Math.sqrt(1 - yy * yy);
      ctx.beginPath();
      for (let i = 0; i <= ringPts; i++) {
        const a = (i / ringPts) * TAU, q = proj([Math.cos(a) * rr * pulse, yy * pulse, Math.sin(a) * rr * pulse]);
        i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]);
      }
      ctx.strokeStyle = rgba(base, A(0.16 * m)); ctx.stroke();
    }
    for (let M = 0; M < 6; M++) {
      const a0 = (M / 6) * Math.PI;
      ctx.beginPath();
      for (let i = 0; i <= ringPts; i++) {
        const a = (i / ringPts) * TAU, q = proj([Math.cos(a) * Math.cos(a0) * pulse, Math.sin(a) * pulse, Math.cos(a) * Math.sin(a0) * pulse]);
        i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]);
      }
      ctx.strokeStyle = rgba(base, A(0.12 * m)); ctx.stroke();
    }
  }

  // ---- pontos: Ultron ferve, JARVIS fica perfeito ----
  const P2 = [];
  for (let i = 0; i < N_PTS; i++) {
    const P = PTS[i], d = P.d;
    const rChaos = P.inner ? P.inner * (0.9 + 0.3 * noise3(d[0] * 3 + t, d[1] * 3, d[2] * 3 - t)) : chaosR(d, t * (0.6 + 0.5 * agit), amp + 0.15);
    let r = rChaos * chaos + (P.inner ? P.inner : 1) * m;
    let x = d[0] * r, y = d[1] * r, z = d[2] * r;
    if (chaos > 0.01) { const j = 0.012 * amp; x += Math.sin(t * 7 + P.tw) * j; y += Math.cos(t * 6.3 + P.tw) * j; z += Math.sin(t * 5.1 + P.tw * 2) * j; }
    if (swirl > 0) { const ang = swirl * 2.6 * (1 - P.size * 0.5), c2 = Math.cos(ang), s2 = Math.sin(ang), sc = 1 - swirl * 0.5; const nx = x * c2 - z * s2, nz = x * s2 + z * c2; x = nx * sc; z = nz * sc; y *= sc; }
    const q = proj([x * pulse, y * pulse, z * pulse]);
    P2.push(q);
    const depth = 0.5 - q[2] / 2;
    const tw = m > 0.5 ? 1 : 0.55 + 0.45 * Math.sin(t * (3 + P.size * 6) + P.tw);
    const col = alert && i % 3 === 0 ? ALERT : P.size > 0.93 ? HOT : base;
    ctx.fillStyle = rgba(col, A((0.25 + 0.75 * depth) * tw));
    const s = (0.8 + P.size * 1.6) * q[3];
    ctx.fillRect(q[0] - s / 2, q[1] - s / 2, s, s);
  }
  // malha do JARVIS
  if (m > 0.02) {
    ctx.strokeStyle = rgba(base, A(0.3 * m)); ctx.lineWidth = 0.7; ctx.beginPath();
    for (const [i, j] of LINKS) { if (P2[i][2] > 0.35 && P2[j][2] > 0.35) continue; ctx.moveTo(P2[i][0], P2[i][1]); ctx.lineTo(P2[j][0], P2[j][1]); }
    ctx.stroke();
  }

  // ---- tentáculos do Ultron: zigue-zague que estala e renasce ----
  if (chaos > 0.02) {
    ctx.lineCap = "round";
    for (let ti = 0; ti < TENDRILS.length; ti++) {
      const T = TENDRILS[ti];
      T.life += dt * agit;
      if (T.life > T.max) { TENDRILS[ti] = newTendril(); continue; }
      const fade = Math.sin(Math.PI * (T.life / T.max));            // nasce e morre suave
      const crackle = Math.random() < 0.15 * agit ? 0 : 1;          // estalos: some por um quadro
      const st = T.start + T.life * T.speed, segs = 22;
      ctx.beginPath();
      let zsum = 0;
      for (let i = 0; i <= segs; i++) {
        const th = st + (T.len * i) / segs;
        const d = [T.e1[0] * Math.cos(th) + T.e2[0] * Math.sin(th), T.e1[1] * Math.cos(th) + T.e2[1] * Math.sin(th), T.e1[2] * Math.cos(th) + T.e2[2] * Math.sin(th)];
        const jag = (Math.random() - 0.5) * 0.09 * agit;               // zigue-zague novo a cada quadro
        const r = chaosR(d, t * (0.6 + 0.5 * agit), amp + 0.15) * (1.02 + jag) * pulse;
        const q = proj([d[0] * r, d[1] * r, d[2] * r]); zsum += q[2];
        i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]);
      }
      const depth = 0.5 - zsum / (segs + 1) / 2;
      const col = alert ? mix(base, ALERT, 0.55 + 0.45 * beat) : T.hot ? mix(base, HOT, 0.6) : base;
      ctx.strokeStyle = rgba(col, A((0.15 + 0.8 * depth) * fade * crackle * chaos * (0.8 + 0.4 * S.flick)));
      ctx.lineWidth = T.hot ? 1.8 : 0.9;
      ctx.stroke();
    }
  }

  // ---- núcleo: Ultron tremula, JARVIS é estável ----
  const crr = R * (0.12 + 0.03 * beat + 0.05 * S.flick * chaos) * (1 - m * 0.3);
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, crr * 2.4);
  g.addColorStop(0, rgba(HOT, A(0.95))); g.addColorStop(0.3, rgba(mix(base, HOT, 0.5), A(0.7))); g.addColorStop(1, rgba(base, 0));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, crr * 2.4, 0, TAU); ctx.fill();

  // faíscas (Ultron solta sempre um pouco; mais ao pensar/agir)
  const sparkRate = chaos * ({ idle: 0.08, thinking: 0.6, tool: 0.9 }[S.state] ?? 0.2);
  if (!reduce && Math.random() < sparkRate) spark(1 + (Math.random() < 0.3 ? 2 : 0), base);
  for (let i = SPARKS.length - 1; i >= 0; i--) {
    const s = SPARKS[i];
    s.r += s.v * dt; s.life -= dt * 0.9;
    if (s.life <= 0) { SPARKS.splice(i, 1); continue; }
    const a = proj(s.d.map((v) => v * s.r)), bq = proj(s.d.map((v) => v * (s.r - 0.12)));
    ctx.strokeStyle = rgba(mix(s.color, HOT, 0.4), A(s.life)); ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(bq[0], bq[1]); ctx.lineTo(a[0], a[1]); ctx.stroke();
  }

  if (S.wave > 0.01) {
    const n = 120; ctx.strokeStyle = rgba(HOT, A(0.55 * S.wave)); ctx.lineWidth = 1; ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const a = (i / n) * TAU, am = R * 0.16 * S.wave * Math.abs(Math.sin(t * 7 + i * 0.37) * Math.sin(t * 2.3 + i * 0.11));
      const r1 = R * 1.3;
      ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); ctx.lineTo(cx + Math.cos(a) * (r1 + 2 + am), cy + Math.sin(a) * (r1 + 2 + am));
    }
    ctx.stroke();
  }
  if (S.state === "seeing") {
    const f = (t * 0.45) % 1, e = Math.sin(Math.PI * f), yy = cy + (f * 2 - 1) * R * 1.1;
    const w = Math.sqrt(Math.max(0, 1 - ((yy - cy) / (R * 1.1)) ** 2)) * R * 1.15;
    ctx.strokeStyle = rgba(HOT, A(0.8 * e)); ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.ellipse(cx, yy, w, w * 0.18, 0, 0, TAU); ctx.stroke();
    ctx.fillStyle = rgba(HOT, A(0.12 * e)); ctx.fillRect(0, f * H, W, 1);
  }
  if (alert) {
    for (let j = 0; j < 3; j++) {
      const f = ((t * (S.state === "remind" ? 0.8 : 0.45)) + j / 3) % 1;
      ctx.strokeStyle = rgba(ALERT, A(Math.sin(Math.PI * f) * 0.6)); ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.arc(cx, cy, R * (1.15 + f * 0.9), 0, TAU); ctx.stroke();
    }
  }
  ctx.globalCompositeOperation = "source-over";

  // moldura mínima
  ctx.strokeStyle = rgba(STRUCT, A(0.32)); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(cx, cy, R * 1.58, 0, TAU); ctx.stroke();
  ctx.beginPath();
  for (let i = 0; i < 120; i++) {
    const a = sp * 0.03 + (i / 120) * TAU, L = i % 10 === 0 ? 7 : 3;
    ctx.moveTo(cx + Math.cos(a) * R * 1.58, cy + Math.sin(a) * R * 1.58);
    ctx.lineTo(cx + Math.cos(a) * (R * 1.58 + L), cy + Math.sin(a) * (R * 1.58 + L));
  }
  ctx.stroke();
  for (const mid of [-sp * 0.08, -sp * 0.08 + Math.PI]) {
    ctx.strokeStyle = rgba(mix(base, HOT, 0.3), A(0.5)); ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.75, mid - 0.32, mid + 0.32); ctx.stroke();
  }
  S.glitch = Math.max(0, S.glitch - dt * 2.5);
}


// laço com orçamento: 60 qps em ação, 30 parado, 15 com jogo; pausa se a janela não está visível
let last = performance.now(), acc = 0;
function loop(now) {
  requestAnimationFrame(loop);
  if (document.hidden) { last = now; return; }
  const busy = S.state !== "idle" || S.boot < 1 || Math.abs((S.local ? 1 : 0) - S.morph) > 0.02 || now - S.lastInput < 1500;
  const fps = S.game ? 15 : busy ? 60 : 30;
  acc += now - last; last = now;
  if (acc < 1000 / fps - 1) return;
  const dt = Math.min(0.1, acc / 1000); acc = 0;
  if (!reduce) S.t += dt;
  S.boot = reduce ? 1 : Math.min(1, S.boot + dt / 1.8);
  for (const k of ["cpu", "gpu", "ram"]) S.view[k] += (S[k] - S.view[k]) * Math.min(1, dt * 3);
  if (W > 0 && H > 0) frame(dt);
}
requestAnimationFrame(loop);

const stage = cv.parentElement;
stage.addEventListener("pointermove", (e) => {
  const r = stage.getBoundingClientRect();
  S.tx = ((e.clientX - r.left) / r.width - 0.5) * 2; S.ty = ((e.clientY - r.top) / r.height - 0.5) * 2;
  S.lastInput = performance.now();
});
stage.addEventListener("pointerleave", () => { S.tx = 0; S.ty = 0; });

window.Nucleo = {
  get state() { return S.state; },
  get local() { return S.local; },
  get game() { return S.game; },
  get load() { return { cpu: S.cpu, gpu: S.gpu, ram: S.ram }; },
  setState(s) { S.state = s; },
  setLocal(on) { S.local = !!on; },
  setLoad({ cpu, gpu, ram }) { S.cpu = cpu ?? 0; S.gpu = gpu ?? 0; S.ram = ram ?? 0; },
  setGame(on) { S.game = !!on; },
  setNight(on) { S.night = !!on; },
  setCompact(on) { S.compact = !!on; },
  reboot() { S.boot = 0; },
};
})();
