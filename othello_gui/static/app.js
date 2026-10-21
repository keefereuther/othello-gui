/* Othello GUI front end.
 *
 * The Python server owns all game state and pushes a full `state` message
 * after every change, plus `hints` messages. This file renders those and
 * sends user intentions back ("move", "goto", "new_game", ...).
 *
 * The board is diffed rather than rebuilt so discs can animate: when a new
 * move is appended at the tip of the game, the placed disc drops in and the
 * flipped discs turn over in a ripple. Everything else (history navigation,
 * undo, new game) rebuilds instantly.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const COLS = "abcdefgh";
const sqName = (sq) => (sq < 0 ? "pa" : COLS[sq % 8] + (Math.floor(sq / 8) + 1));
const colorOf = (p) => (p === "X" ? "black" : "white");
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const cssMs = (name) => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name)) || 0;

let ws = null;
let state = null;        // last "state" message
let prevState = null;    // the one before it, for animation decisions
let hints = null;        // last "hints" message
let thor = null;         // last "thor" message
let thorVisible = true;  // is the Thor card on screen?
let thorAsked = "";      // position key we last asked the server about
let reconnectDelay = 500;
let selectedSq = -1;     // square chosen with the arrow keys, played with Enter
let selectedCursor = -1;
let lastCounts = null;

/* ───────────────────────── rules (client side, for previews) ───────────────────────── */

const DIRS = [[-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]];
function flipsFor(board, sq, player) {
  if (board[sq] !== "-") return [];
  const opp = player === "X" ? "O" : "X";
  const r0 = Math.floor(sq / 8), c0 = sq % 8, out = [];
  for (const [dr, dc] of DIRS) {
    let r = r0 + dr, c = c0 + dc;
    const line = [];
    while (r >= 0 && r < 8 && c >= 0 && c < 8 && board[r * 8 + c] === opp) { line.push(r * 8 + c); r += dr; c += dc; }
    if (line.length && r >= 0 && r < 8 && c >= 0 && c < 8 && board[r * 8 + c] === player) out.push(...line);
  }
  return out;
}

/* ───────────────────────── connection ───────────────────────── */

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { reconnectDelay = 500; setStatus("ok", "connected"); };
  ws.onclose = () => {
    setStatus("bad", "disconnected – retrying…");
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(8000, reconnectDelay * 2);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") {
      prevState = state;
      state = msg;
      if (state.cursor !== selectedCursor || !state.legal.includes(selectedSq)) { selectedSq = -1; selectedCursor = state.cursor; }
      render(liveMove(prevState, state));
      requestThor(false);
    } else if (msg.type === "thor") {
      thor = msg;
      renderThor();
    } else if (msg.type === "hints") {
      hints = msg;
      renderBoard(null);
      renderHints();
    } else if (msg.type === "error") {
      toast(msg.message);
    }
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  else toast("not connected");
}

/* A move worth animating: the user was at the tip, exactly one new move
   (plus possibly a forced pass) was appended, and we're still at the tip. */
function liveMove(prev, cur) {
  if (!prev || !cur || cur.cursor !== cur.moves.length || prev.cursor !== prev.moves.length) return null;
  const added = cur.moves.length - prev.moves.length;
  if (added < 1 || added > 2) return null;
  if (cur.transcript.slice(0, prev.transcript.length) !== prev.transcript) return null;
  const m = cur.moves[prev.moves.length];
  if (m.sq < 0) return null;
  return { sq: m.sq, color: colorOf(m.player), flips: m.flips || [] };
}

/* ───────────────────────── rendering ───────────────────────── */

function render(anim) {
  if (!state) return;
  renderStatus();
  renderScore();
  renderBoard(anim);
  renderNav();
  renderMoves(!!anim);
  renderGraph();
  renderHints();
  renderAnalysis();
  renderCoach();
  renderPuzzle();
  if (typeof renderTraining === "function") renderTraining();  // training.js loads after this file
  const ta = $("transcript");
  if (document.activeElement !== ta) ta.value = state.transcript || "";
}

function setStatus(kind, text) {
  $("status-dot").className = "dot " + kind;
  $("status-text").textContent = text;
}

function renderStatus() {
  const e = state.engine;
  $("engine-name").textContent = e.running ? `with ${e.name.replace(/\d+$/, "")}` : "engine offline";
  if (!e.running) { setStatus("bad", e.error || "engine not running"); return; }
  if (state.thinking) {
    const nodes = state.nodes ? ` · ${fmtNodes(state.nodes)} nodes` : "";
    setStatus("busy", `${state.status}${nodes}`);
  } else {
    setStatus("ok", `${e.name} · level ${state.level} · ${e.threads} threads`);
  }
}

function playerLabel(p) { return p === "edax" ? (state.engine.name || "Edax").replace(/\d+$/, "") : "Human"; }

function renderScore() {
  const counts = { black: state.black, white: state.white };
  for (const c of ["black", "white"]) {
    const el = $("score-" + c);
    if (String(counts[c]) !== el.textContent) { el.textContent = counts[c]; if (lastCounts) retrigger(el, "bump"); }
  }
  lastCounts = counts;
  $("who-black").textContent = playerLabel(state.players.X);
  $("who-white").textContent = playerLabel(state.players.O);
  const o = state.opening;
  $("opening-info").textContent = !o ? ""
    : o.puzzle ? `Endgame puzzle · ${o.empties} empties · from ${o.black} – ${o.white}, ${o.tournament} ${o.year} (${o.result})`
    : o.full ? `${o.black} – ${o.white}, ${o.tournament} ${o.year} (${o.result})`
    : `Opening from ${o.black} – ${o.white}, ${o.tournament} ${o.year} (${o.result}), first ${o.plies} plies`;
  const t = $("turn");
  const atTip = state.cursor === state.moves.length;
  const over = atTip && state.game_over;
  t.classList.remove("pass-nudge");
  if (over) {
    const d = state.black - state.white;
    t.textContent = d === 0 ? "Draw" : d > 0 ? `Black wins ${state.black}–${state.white}` : `White wins ${state.white}–${state.black}`;
    t.className = "turn over";
    if (prevState && !(prevState.cursor === prevState.moves.length && prevState.game_over) && d !== 0) celebrate(d > 0 ? "black" : "white");
  } else {
    const last = state.cursor > 0 ? state.moves[state.cursor - 1] : null;
    const passed = last && last.sq < 0 ? `${last.player === "X" ? "Black" : "White"} passed · ` : "";
    t.textContent = passed + (state.to_move === "X" ? "Black" : "White") + " to move" + (atTip ? "" : " (reviewing)");
    t.className = "turn";
    if (passed) retrigger(t, "pass-nudge");
  }
}

function buildBoardOnce() {
  const board = $("board");
  if (board.children.length) return;
  for (let sq = 0; sq < 64; sq++) {
    const d = document.createElement("div");
    d.className = "square";
    d.dataset.sq = sq;
    d.setAttribute("role", "gridcell");
    const r = Math.floor(sq / 8), c = sq % 8;
    if ((r === 1 || r === 5) && (c === 1 || c === 5)) d.classList.add("star");
    d.addEventListener("click", () => onSquareClick(sq));
    d.addEventListener("mouseenter", () => { if (d.classList.contains("legal") && state) previewFlips(flipsFor(state.board, sq, state.to_move)); });
    d.addEventListener("mouseleave", () => { if (selectedSq < 0) clearPreview(); else previewFlips(flipsFor(state.board, selectedSq, state.to_move)); });
    board.appendChild(d);
  }
  $("coords-cols").innerHTML = [..."ABCDEFGH"].map((x) => `<span>${x}</span>`).join("");
  $("coords-rows").innerHTML = [1, 2, 3, 4, 5, 6, 7, 8].map((x) => `<span>${x}</span>`).join("");
}

function renderBoard(anim) {
  if (!state) return;
  buildBoardOnce();
  const board = $("board");
  board.dataset.turn = colorOf(state.to_move);
  const last = state.cursor > 0 ? state.moves[state.cursor - 1] : null;
  const lastSq = last && last.sq >= 0 ? last.sq : (last && state.cursor > 1 ? state.moves[state.cursor - 2].sq : -1);
  const legal = new Set(state.legal);
  const showHints = state.hints_enabled && hints && hints.cursor === state.cursor && hints.hints.length;
  const hintBySq = new Map();
  if (showHints) hints.hints.forEach((h) => hintBySq.set(h.sq, h));
  const bestScore = showHints ? Math.max(...hints.hints.map((h) => h.score)) : null;
  const animFlips = new Set(anim ? anim.flips : []);
  const pz = state.puzzle;
  const markSq = state.coach_alert ? state.coach_alert.best_sq
    : pz && (pz.status === "solved" || pz.status === "missed") && state.cursor === 1 ? pz.best_sq : -1;
  const marks = new Map(state.training ? state.training.marks : []);

  for (let sq = 0; sq < 64; sq++) {
    const el = board.children[sq];
    const v = state.board[sq];
    el.classList.toggle("legal", v === "-" && legal.has(sq));
    el.classList.toggle("last", sq === lastSq && v !== "-");
    el.classList.toggle("selected", sq === selectedSq);
    el.classList.toggle("peek", sq === markSq);
    el.classList.toggle("mark-good", marks.get(sq) === "good");
    el.classList.toggle("mark-bad", marks.get(sq) === "bad");
    el.classList.toggle("mark-focus", marks.get(sq) === "focus");
    el.setAttribute("aria-label", `${sqName(sq)}, ${v === "X" ? "black disc" : v === "O" ? "white disc" : legal.has(sq) ? "empty, legal move" : "empty"}`);

    let disc = el.querySelector(".disc");
    if (v === "-") {
      if (disc) disc.remove();
    } else {
      const color = colorOf(v);
      if (!disc) {
        disc = document.createElement("div");
        disc.className = "disc " + color + (anim && anim.sq === sq && !reduceMotion() ? " drop" : "");
        disc.addEventListener("animationend", () => disc.classList.remove("drop"), { once: true });
        el.appendChild(disc);
      } else if (!disc.classList.contains(color)) {
        if (animFlips.has(sq)) flipDisc(disc, color, flipDelay(anim.sq, sq));
        else { disc.classList.remove("black", "white", "preview"); disc.classList.add(color); }
      }
    }

    const oldHint = el.querySelector(".hint");
    const h = v === "-" ? hintBySq.get(sq) : null;
    if (!h) { if (oldHint) oldHint.remove(); continue; }
    const text = fmtScore(h.score), sub = h.book ? "book" : "d" + h.depth, best = h.score === bestScore;
    if (oldHint && oldHint.dataset.key === text + sub + best) continue;
    if (oldHint) oldHint.remove();
    const tag = document.createElement("div");
    tag.className = "hint" + (best ? " best" : "");
    tag.dataset.key = text + sub + best;
    tag.innerHTML = `${text}<small>${sub}</small>`;
    el.appendChild(tag);
  }
}

function renderNav() {
  const n = state.moves.length;
  $("nav-pos").textContent = `${state.cursor} / ${n}`;
  $("nav-first").disabled = $("nav-prev").disabled = state.cursor === 0;
  $("nav-next").disabled = $("nav-last").disabled = state.cursor === n;
  $("btn-undo").disabled = n === 0;
  $("hints-on").checked = state.hints_enabled;
  $("hints-n").value = String(state.hint_count);
  if (document.activeElement !== $("ng-level")) $("ng-level").value = state.level;
  $("ng-variety").value = String(state.variety ?? 0);
  $("ng-time").value = String(state.move_time || 0);
  $("coach-on").checked = !!(state.coach && state.coach.enabled);
  if (state.coach) $("coach-threshold").value = String(state.coach.threshold);
  const sel = $("ng-opening");
  for (const opt of sel.options) if (opt.value !== "0") opt.disabled = !state.thor_games;
  if (!state.thor_games && sel.value !== "0") sel.value = "0";
  sel.title = state.thor_games ? "Start from the first moves of a random real tournament game" : "Needs the Thor database (see the Thor card)";
}

function renderMoves(animateLast) {
  const list = $("movelist");
  list.innerHTML = "";
  const moves = state.moves;
  $("move-count").textContent = moves.length ? `${moves.length} plies` : "";
  const on = state.opening_name, el = $("opening-name");
  el.innerHTML = on ? `${esc(on.name)}${on.since ? ` <span class="since">· ${on.since} ${on.since === 1 ? "move" : "moves"} on</span>` : ""}` : "";
  el.title = on
    ? `${on.name}${on.aliases.length ? ` (also: ${on.aliases.join(", ")})` : ""} · ${on.moves}` +
      (on.since ? ` · left the named line ${on.since} ${on.since === 1 ? "move" : "moves"} ago` : "")
    : "";
  // one row per black-white pair; passes appear inline in their colour's cell
  let row = null, slots = 0, num = 0;
  const cell = (m, i) => {
    const d = document.createElement("span");
    const name = m.sq < 0 ? "pass" : sqName(m.sq).toUpperCase();
    d.className = "mv " + colorOf(m.player) + (m.sq < 0 ? " pass" : "") + (i + 1 === state.cursor ? " current" : "") + (m.opening ? " named" : "");
    if (m.opening) d.title = `Reaches the ${m.opening} opening`;
    let extra = "";
    if (m.loss != null && m.loss >= 1) extra = `<span class="loss" title="best was ${(m.best || "").toUpperCase()}">−${fmtNum(m.loss)}</span>`;
    else if (m.eval != null) extra = `<span class="ev" title="${m.eval_source}">${fmtScore(m.eval)}</span>`;
    d.innerHTML = `<span>${name}</span>${extra}`;
    d.addEventListener("click", () => send({ type: "goto", index: i + 1 }));
    return d;
  };
  moves.forEach((m, i) => {
    if (row === null || m.player === "X") {
      row = document.createElement("div");
      row.className = "move-row" + (animateLast && i >= moves.length - 2 ? " new" : "");
      const n = document.createElement("span"); n.className = "n"; n.textContent = ++num + ".";
      row.appendChild(n);
      slots = 0;
      if (m.player === "O") { const e = document.createElement("span"); e.className = "mv empty"; row.appendChild(e); slots++; }
      list.appendChild(row);
    }
    row.appendChild(cell(m, i));
    if (i + 1 === state.cursor) row.classList.add("current-row");
    if (++slots === 2) row = null;
  });
  // keep the current move visible without scrolling the page itself
  const cur = list.querySelector(".move-row.current-row");
  if (cur) {
    const top = cur.offsetTop - list.offsetTop, bottom = top + cur.offsetHeight;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight;
  }
}

function renderHints() {
  const tbody = $("hints-table").querySelector("tbody");
  tbody.innerHTML = "";
  const meta = $("hints-meta");
  const have = state && state.hints_enabled && hints && hints.cursor === state.cursor && hints.hints.length;
  if (!have) {
    meta.textContent = state && state.hints_enabled ? (state.thinking ? "computing…" : "") : "off";
    const tr = document.createElement("tr"); tr.className = "empty";
    tr.innerHTML = `<td colspan="4">${state && !state.hints_enabled ? "Hints are off" : "—"}</td>`;
    tbody.appendChild(tr);
    return;
  }
  meta.textContent = `position ${hints.cursor}`;
  const best = Math.max(...hints.hints.map((h) => h.score));
  for (const h of hints.hints) {
    const tr = document.createElement("tr");
    if (h.score === best) tr.classList.add("best");
    const cls = h.score > 0 ? "pos" : h.score < 0 ? "neg" : "";
    tr.innerHTML =
      `<td>${h.name.toUpperCase()}</td>` +
      `<td class="eval ${cls}">${fmtScore(h.score)}</td>` +
      `<td class="tag">${h.book ? `book · ${h.book_games}` : h.depth}</td>` +
      `<td class="pv">${h.pv.slice(1, 7).map((x) => x.toUpperCase()).join(" ")}</td>`;
    const sqEl = $("board").children[h.sq];
    tr.addEventListener("mouseenter", () => { sqEl.classList.add("peek"); previewFlips(flipsFor(state.board, h.sq, state.to_move)); });
    tr.addEventListener("mouseleave", () => { sqEl.classList.remove("peek"); clearPreview(); });
    tr.addEventListener("click", () => onSquareClick(h.sq));
    tbody.appendChild(tr);
  }
}

function renderAnalysis() {
  const a = state.analysis;
  $("btn-analyze").disabled = a.running || !state.moves.length;
  $("an-progress").textContent = a.running ? `${a.done} / ${a.total} positions…` : a.total ? `done at level ${a.level}` : "";
}

/* Evaluation graph: x = ply, y = eval after that ply from black's point of view.
   Fills are disc-coded: dark above zero (black ahead), light below (white ahead). */
function renderGraph() {
  const svg = $("graph");
  const W = 400, H = 130, padL = 28, padR = 8, padT = 8, padB = 16;
  const moves = state.moves;
  const pts = moves.map((m, i) => ({ i, v: m.eval, src: m.eval_source })).filter((p) => p.v != null);
  let maxAbs = 8;
  for (const p of pts) maxAbs = Math.max(maxAbs, Math.abs(p.v));
  maxAbs = Math.ceil(maxAbs / 4) * 4;
  const n = Math.max(moves.length, 1);
  const x = (i) => padL + ((i + 1) / (n + 1)) * (W - padL - padR);
  const y = (v) => padT + (1 - (v + maxAbs) / (2 * maxAbs)) * (H - padT - padB);
  const f = (v) => v.toFixed(1);
  let s = `<line class="eval-guide" x1="${padL}" y1="${padT}" x2="${padL}" y2="${H - padB}"/>`;
  s += `<line class="eval-axis" x1="${padL}" y1="${f(y(0))}" x2="${W - padR}" y2="${f(y(0))}"/>`;
  s += `<text x="2" y="${f(y(maxAbs) + 4)}">+${maxAbs}</text><text x="2" y="${f(y(0) + 4)}">0</text><text x="2" y="${f(y(-maxAbs) + 2)}">−${maxAbs}</text>`;
  if (pts.length) {
    const line = pts.map((p) => `${f(x(p.i))},${f(y(p.v))}`).join(" ");
    const area = (sign) => {
      const seq = pts.map((p) => `${f(x(p.i))},${f(y(sign > 0 ? Math.max(0, p.v) : Math.min(0, p.v)))}`).join(" ");
      return `M${f(x(pts[0].i))},${f(y(0))} L${seq} L${f(x(pts[pts.length - 1].i))},${f(y(0))} Z`;
    };
    s += `<path class="eval-area-black" d="${area(1)}"/><path class="eval-area-white" d="${area(-1)}"/>`;
    s += `<polyline class="eval-line" points="${line}"/>`;
    for (const p of pts) {
      s += `<circle class="eval-dot ${p.src === "engine" ? "engine" : ""}" cx="${f(x(p.i))}" cy="${f(y(p.v))}" r="3.5" data-i="${p.i}"><title>ply ${p.i + 1}: ${fmtScore(p.v)}</title></circle>`;
    }
  }
  if (state.cursor > 0) s += `<line class="eval-cursor" x1="${f(x(state.cursor - 1))}" y1="${padT}" x2="${f(x(state.cursor - 1))}" y2="${H - padB}"/>`;
  svg.innerHTML = s;
  svg.querySelectorAll(".eval-dot").forEach((c) => c.addEventListener("click", () => send({ type: "goto", index: Number(c.dataset.i) + 1 })));
}

/* ───────────────────────── coach & puzzles ───────────────────────── */

function renderCoach() {
  const a = state.coach_alert, el = $("coach-banner");
  if (!a) { el.hidden = true; return; }
  el.hidden = false;
  $("coach-text").innerHTML =
    `<b>${a.move.toUpperCase()}</b> cost about <span class="loss">${fmtNum(a.loss)} discs</span>. ` +
    `Better was <b>${a.best.toUpperCase()}</b> (${fmtScore(a.best_score)} instead of ${fmtScore(a.played_score)}).` +
    (a.why ? `<div class="coach-why">${esc(a.why)}</div>` : "");
}

function renderPuzzle() {
  const pz = state.puzzle, el = $("puzzle-text"), meta = $("puzzle-meta");
  $("btn-puzzle").disabled = !state.thor_games || (pz && pz.status === "solving");
  $("btn-puzzle").textContent = pz ? "Next puzzle" : "New puzzle";
  if (!pz) {
    el.className = "puzzle-text";
    el.textContent = state.thor_games
      ? "Find the best move in a real tournament endgame, solved exactly by Edax."
      : "Needs the Thor database (see the Thor card).";
    meta.textContent = "";
    return;
  }
  meta.textContent = `${pz.empties} empties · level ${pz.level}`;
  const side = pz.to_move === "X" ? "Black" : "White";
  if (pz.status === "solving") { el.className = "puzzle-text"; el.textContent = `${side} to move. Edax is solving the position…`; }
  else if (pz.status === "ask") { el.className = "puzzle-text ask"; el.textContent = `${side} to move. Find the best move (exact result).`; }
  else if (pz.status === "solved") {
    el.className = "puzzle-text solved";
    el.innerHTML = `Correct: ${pz.played.toUpperCase()} is the best move (${fmtScore(pz.best_score)} for ${side.toLowerCase()}).` +
      `<small>Play it out against Edax's perfect defence, or take the next puzzle.</small>`;
  } else {
    el.className = "puzzle-text missed";
    el.innerHTML = `${pz.played.toUpperCase()} loses ${fmtNum(pz.loss)} discs. Best was ${pz.best.toUpperCase()} (${fmtScore(pz.best_score)} instead of ${fmtScore(pz.played_score)}).` +
      `<small>Undo to try again, play it out, or take the next puzzle.</small>`;
  }
}

$("btn-puzzle").onclick = () => send({ type: "puzzle", empties: Number($("puzzle-empties").value) });
$("coach-undo").onclick = () => send({ type: "undo" });
$("coach-continue").onclick = () => send({ type: "coach_continue" });
$("ng-time").onchange = () => send({ type: "set_move_time", seconds: Number($("ng-time").value) || null });
$("coach-on").onchange = () => send({ type: "set_coach", enabled: $("coach-on").checked, threshold: Number($("coach-threshold").value) });
$("coach-threshold").onchange = () => send({ type: "set_coach", enabled: $("coach-on").checked, threshold: Number($("coach-threshold").value) });

/* ───────────────────────── Thor database card ───────────────────────── */

const posKey = () => (state ? state.board + state.to_move : "");

/* Ask the server for Thor statistics when the position changed and the card is
   on screen (or always, with force). */
function requestThor(force) {
  if (!state || (!thorVisible && !force) || $("thor-card").classList.contains("collapsed")) return;
  if (!force && thorAsked === posKey()) return;
  thorAsked = posKey();
  send({ type: "thor_lookup" });
}

function pct(n, total) { return total ? Math.round((100 * n) / total) : 0; }

function resultBar(b, d, w) {
  const t = b + d + w || 1;
  return `<div class="result-bar" title="Black ${pct(b, t)}% · draw ${pct(d, t)}% · white ${pct(w, t)}%">` +
    `<span class="b" style="width:${(100 * b) / t}%"></span><span class="d" style="width:${(100 * d) / t}%"></span>` +
    `<span class="w" style="width:${(100 * w) / t}%"></span></div>`;
}

function renderThor() {
  const meta = $("thor-meta"), summary = $("thor-summary"), tbody = $("thor-moves").querySelector("tbody");
  const list = $("thor-games"), head = $("thor-games-head");
  tbody.innerHTML = ""; list.innerHTML = ""; head.textContent = "";
  const t = thor;
  const tr = state && state.training;
  if (tr && tr.mode === "drill" && tr.drill && tr.drill.status !== "answered") {
    meta.textContent = "";
    summary.innerHTML = `<div class="thor-note">Hidden during the drill, so it can't give the answer away.</div>`;
    return;
  }
  if (!t || !t.available) {
    meta.textContent = "";
    summary.innerHTML = t
      ? `<div class="thor-note">No Thor database yet. Download the free WTHOR files from
         <a href="https://www.ffothello.org/informatique/la-base-wthor/" target="_blank" rel="noopener">ffothello.org</a>
         (WTHOR.JOU, WTHOR.TRN and the WTH_YYYY.wtb game files), put them in a <code>wthor</code> folder
         inside the app folder, and restart the app.</div>`
      : `<div class="thor-note">…</div>`;
    return;
  }
  if (!t.ready) {
    meta.textContent = "";
    summary.innerHTML = `<div class="thor-note">${t.error ? "Index failed: " + t.error : `Indexing… ${Math.round(100 * (t.progress || 0))}%`}</div>`;
    return;
  }
  const f = t.filters || {};
  if (document.activeElement !== $("thor-year")) $("thor-year").value = f.min_year || "";
  if (document.activeElement !== $("thor-player")) $("thor-player").value = f.player || "";
  const stale = state && t.board !== state.board;
  meta.textContent = (f.min_year || f.player ? "filtered" : "") + (stale ? " · updating…" : "");
  if (!t.games) {
    summary.innerHTML = `<div class="thor-note">No games reached this position${f.min_year || f.player ? " with these filters" : ""}.</div>`;
    return;
  }
  summary.innerHTML =
    `<div><span class="count">${t.games.toLocaleString()}</span> ${t.games === 1 ? "game" : "games"}</div>` +
    resultBar(t.black_wins, t.draws, t.white_wins) +
    `<div class="split">Black ${pct(t.black_wins, t.games)}% · draw ${pct(t.draws, t.games)}% · white ${pct(t.white_wins, t.games)}%</div>`;

  const legal = new Set(state ? state.legal : []);
  for (const c of t.continuations.slice(0, 12)) {
    const tr = document.createElement("tr");
    const black = c.black_wins, white = c.white_wins;
    tr.innerHTML =
      `<td>${c.name.toUpperCase()}</td><td class="eval">${c.games.toLocaleString()}</td>` +
      `<td>${resultBar(black, c.draws, white)}</td><td class="eval">${Math.round(c.black_win_pct)}%</td>`;
    if (!stale && legal.has(c.move)) {
      const sqEl = $("board").children[c.move];
      tr.addEventListener("mouseenter", () => { sqEl.classList.add("peek"); previewFlips(flipsFor(state.board, c.move, state.to_move)); });
      tr.addEventListener("mouseleave", () => { sqEl.classList.remove("peek"); clearPreview(); });
      tr.addEventListener("click", () => { sqEl.classList.remove("peek"); onSquareClick(c.move); });
      tr.title = `Play ${c.name.toUpperCase()}`;
    }
    tbody.appendChild(tr);
  }
  if (!t.continuations.length) {
    const tr = document.createElement("tr"); tr.className = "empty";
    tr.innerHTML = `<td colspan="4">The games end here or go beyond the indexed 40 moves.</td>`;
    tbody.appendChild(tr);
  }

  head.textContent = t.games > t.sample.length ? `Latest ${t.sample.length} games` : "Games";
  for (const g of t.sample) {
    const row = document.createElement("div");
    row.className = "thor-game";
    const [bd] = g.result.split("-").map(Number);
    row.innerHTML =
      `<span class="yr">${g.year}</span>` +
      `<span class="who">${esc(g.black)} – ${esc(g.white)}<small>${esc(g.tournament)}</small></span>` +
      `<span class="res ${bd > 32 ? "bw" : bd < 32 ? "ww" : ""}">${g.result}</span>`;
    row.title = "Load this game for review";
    row.addEventListener("click", () => send({ type: "thor_game", index: g.index }));
    list.appendChild(row);
  }
}

function esc(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

if ("IntersectionObserver" in window) {
  new IntersectionObserver((entries) => {
    thorVisible = entries.some((e) => e.isIntersecting);
    if (thorVisible) requestThor(false);
  }).observe($("thor-card"));
}

let thorFilterTimer = null;
function sendThorFilters() {
  clearTimeout(thorFilterTimer);
  thorFilterTimer = setTimeout(() => {
    const year = $("thor-year").value.trim();
    send({ type: "thor_filters", min_year: year ? Number(year) : null, player: $("thor-player").value });
  }, 350);
}
$("thor-year").addEventListener("change", sendThorFilters);
$("thor-player").addEventListener("input", sendThorFilters);

/* ───────────────────────── motion helpers ───────────────────────── */

const chebyshev = (a, b) => Math.max(Math.abs((a >> 3) - (b >> 3)), Math.abs((a & 7) - (b & 7)));
const flipDelay = (from, to) => cssMs("--t-drop") * 0.6 + Math.max(0, chebyshev(from, to) - 1) * cssMs("--ripple");

/* Flip one disc: squash to an edge while lifting, swap colour at the midpoint, spring back. */
async function flipDisc(disc, toColor, delay = 0) {
  const swap = () => { disc.classList.remove("black", "white", "preview"); disc.classList.add(toColor); };
  if (reduceMotion()) { swap(); return; }
  const half = cssMs("--t-flip") / 2;
  const out = disc.animate(
    [{ transform: "translateY(0) scaleX(1)" }, { transform: "translateY(-6px) scaleX(0)" }],
    { duration: half, delay, easing: "cubic-bezier(0.4, 0, 1, 1)", fill: "forwards" }
  );
  try { await out.finished; } catch { return; }   // cancelled by a rebuild
  swap();
  const back = disc.animate(
    [{ transform: "translateY(-6px) scaleX(0)" }, { transform: "translateY(0) scaleX(1)" }],
    { duration: half + 40, easing: "cubic-bezier(0.34, 1.56, 0.64, 1)" }
  );
  out.cancel();
  try { await back.finished; } catch { /* ignore */ }
}

function previewFlips(flips) {
  clearPreview();
  const board = $("board");
  for (const i of flips) board.children[i].querySelector(".disc")?.classList.add("preview");
}
function clearPreview() {
  $("board").querySelectorAll(".disc.preview").forEach((d) => d.classList.remove("preview"));
}

function retrigger(el, cls) { el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls); }

function celebrate(color) {
  if (reduceMotion()) return;
  [...$("board").children].forEach((sq, i) => {
    const d = sq.querySelector(".disc." + color);
    if (!d) return;
    d.style.setProperty("--delay", ((i >> 3) + (i & 7)) * 40 + "ms");
    retrigger(d, "wave");
  });
}

/* ───────────────────────── interaction ───────────────────────── */

function onSquareClick(sq) {
  if (!state || !state.legal.includes(sq)) return;
  if (state.thinking && state.cursor === state.moves.length && state.players[state.to_move] === "edax") return;
  clearPreview();
  send({ type: "move", sq });
}

/* Candidate moves in the order the arrow keys cycle: clockwise around the
   centre of the board starting from 12 o'clock (↓ clockwise, ↑ counter-
   clockwise). Squares on the same bearing go inner to outer. */
function candidateMoves() {
  if (!state) return [];
  const bearing = (sq) => {
    const dx = (sq % 8) - 3.5, dy = Math.floor(sq / 8) - 3.5;      // screen coords: y grows downward
    const a = Math.atan2(dx, -dy);                                   // 0 = north, increasing clockwise
    return { sq, angle: a < 0 ? a + 2 * Math.PI : a, dist: dx * dx + dy * dy };
  };
  return state.legal.map(bearing)
    .sort((p, q) => (Math.abs(p.angle - q.angle) > 1e-9 ? p.angle - q.angle : p.dist - q.dist))
    .map((p) => p.sq);
}

function cycleSelection(step) {
  const c = candidateMoves();
  if (!c.length) return;
  const i = c.indexOf(selectedSq);
  selectedSq = c[(i + step + c.length) % c.length];
  selectedCursor = state.cursor;
  renderBoard(null);
  previewFlips(flipsFor(state.board, selectedSq, state.to_move));
}

document.addEventListener("keydown", (e) => {
  if (!state || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (e.key === "ArrowDown" || (e.key === "Tab" && !e.shiftKey)) { cycleSelection(+1); e.preventDefault(); }
  else if (e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey)) { cycleSelection(-1); e.preventDefault(); }
  else if (e.key === "Enter" || e.key === " ") {
    if (selectedSq >= 0) { const sq = selectedSq; selectedSq = -1; onSquareClick(sq); e.preventDefault(); }
  }
  else if (e.key === "h" || e.key === "H") { send({ type: "set_hints", enabled: !state.hints_enabled, count: state.hint_count }); }
  else if (e.key === "ArrowLeft") { send({ type: "goto", index: state.cursor - 1 }); e.preventDefault(); }
  else if (e.key === "ArrowRight") { send({ type: "goto", index: state.cursor + 1 }); e.preventDefault(); }
  else if (e.key === "Home") { send({ type: "goto", index: 0 }); e.preventDefault(); }
  else if (e.key === "End") { send({ type: "goto", index: state.moves.length }); e.preventDefault(); }
});

$("nav-first").onclick = () => send({ type: "goto", index: 0 });
$("nav-prev").onclick = () => send({ type: "goto", index: state.cursor - 1 });
$("nav-next").onclick = () => send({ type: "goto", index: state.cursor + 1 });
$("nav-last").onclick = () => send({ type: "goto", index: state.moves.length });
$("btn-undo").onclick = () => send({ type: "undo" });
$("hints-on").onchange = () => send({ type: "set_hints", enabled: $("hints-on").checked, count: Number($("hints-n").value) });
$("hints-n").onchange = () => send({ type: "set_hints", enabled: $("hints-on").checked, count: Number($("hints-n").value) });
$("btn-new").onclick = () => {
  const plies = Number($("ng-opening").value);
  send({
    type: "new_game", black: $("ng-black").value, white: $("ng-white").value, level: Number($("ng-level").value),
    opening: plies > 0 ? { type: "thor", plies } : null,
  });
};
$("ng-level").onchange = () => send({ type: "set_level", level: Number($("ng-level").value) });
$("ng-variety").onchange = () => send({ type: "set_variety", discs: Number($("ng-variety").value) });
$("btn-analyze").onclick = () => send({ type: "analyze", level: Number($("an-level").value) });
$("btn-load").onclick = () => send({ type: "load_transcript", text: $("transcript").value });
$("btn-copy").onclick = async () => {
  try { await navigator.clipboard.writeText(state.transcript || ""); toast("transcript copied"); }
  catch { toast("clipboard not available"); }
};

/* ───────────────────────── game files ───────────────────────── */

/* Generic Game Format record of the current game (passes written as PA). */
function gameToGGF(st) {
  const o = st.opening || {};
  const clean = (x) => String(x || "?").replace(/[\]\[]/g, "");
  const name = (p, side) => (o.full ? clean(side) : st.players[p] === "edax" ? "Edax" : "Human");
  const moves = st.moves.map((m) => `${m.player === "X" ? "B" : "W"}[${m.sq < 0 ? "PA" : sqName(m.sq).toUpperCase()}]`).join("");
  const d = new Date();
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  // result from black's view: recorded result for Thor games, else the live count at the end of a finished game
  let diff = null;
  if (o.full && o.result) { const [b, w] = o.result.split("-").map(Number); diff = b - w; }
  else if (st.game_over && st.cursor === st.moves.length) diff = st.black - st.white;
  const result = diff === null ? "?" : `${diff >= 0 ? "+" : ""}${diff}`;
  const start = "---------------------------O*------*O---------------------------";
  return `(;GM[Othello]PC[${o.full ? clean(o.tournament) : "Othello GUI"}]DT[${o.full ? o.year : date}]` +
    `PB[${name("X", o.black)}]PW[${name("O", o.white)}]RE[${result}]TI[0//0]TY[8]BO[8 ${start} *]${moves};)\n`;
}

$("btn-save").onclick = () => {
  if (!state || !state.moves.length) { toast("nothing to save yet"); return; }
  const o = state.opening || {};
  const base = o.full ? `${o.year} ${o.black} - ${o.white}` : `othello-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}`;
  const blob = new Blob([gameToGGF(state)], { type: "text/plain" });
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: base.replace(/[\/:*?"<>|]/g, "") + ".ggf" });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast("game saved");
};
$("btn-open").onclick = () => $("file-open").click();
$("file-open").onchange = async () => {
  const file = $("file-open").files[0];
  $("file-open").value = "";
  if (!file) return;
  if (file.size > 1_000_000) { toast("file too large"); return; }
  send({ type: "load_transcript", text: await file.text() });
};

/* theme: follows the OS until the user picks one; the choice is remembered */
$("theme-toggle").onclick = () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch { /* private mode */ }
};

/* ───────────────────────── sidebar panels ───────────────────────── */

/* Each card can be collapsed to its title so the panels that matter for the
   current task sit next to the board. Everything except New game starts
   collapsed; after that, each panel's open/closed choice is remembered. */
const OPEN_BY_DEFAULT = new Set(["newgame"]);
const PANELS_KEY = "panels";
function loadPanels() { try { return JSON.parse(localStorage.getItem(PANELS_KEY)) || {}; } catch { return {}; } }
document.querySelectorAll(".sidebar .card[data-panel]").forEach((card) => {
  const name = card.dataset.panel, head = card.querySelector(":scope > .t-label");
  const chevron = document.createElement("span");
  chevron.className = "card-toggle"; chevron.setAttribute("aria-hidden", "true");
  head.appendChild(chevron);
  head.setAttribute("role", "button"); head.tabIndex = 0; head.title = "Show / hide this panel";
  const set = (collapsed) => { card.classList.toggle("collapsed", collapsed); head.setAttribute("aria-expanded", String(!collapsed)); };
  const saved = loadPanels()[name];
  set(saved === undefined ? !OPEN_BY_DEFAULT.has(name) : !!saved);
  const flip = () => {
    set(!card.classList.contains("collapsed"));
    const p = loadPanels(); p[name] = card.classList.contains("collapsed");
    try { localStorage.setItem(PANELS_KEY, JSON.stringify(p)); } catch { /* private mode */ }
    if (name === "thor" && !p[name]) requestThor(false);
  };
  head.addEventListener("click", flip);
  head.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { flip(); e.preventDefault(); e.stopPropagation(); } });
});

/* ───────────────────────── helpers ───────────────────────── */

function fmtScore(v) {
  const r = Math.round(v);
  return r > 0 ? `+${r}` : r < 0 ? `−${Math.abs(r)}` : "0";
}
function fmtNum(v) { return Number.isInteger(v) ? String(v) : v.toFixed(1); }
function fmtNodes(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "G";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + "k";
  return String(n);
}
let toastTimer = null;
function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2800);
}

connect();
