/* Othello GUI · training card.
 *
 * Loaded after app.js and shares its globals (state, send, $, esc, fmtScore,
 * fmtNum). render() in app.js calls renderTraining() on every state message.
 * The server side lives in othello_gui/training.py and curriculum.py.
 */
"use strict";

/* ───────────────────────── training ───────────────────────── */

/* The curriculum (lesson text, unit list) comes once from /api/curriculum; the
   dynamic part (progress, current drill, scrimmage review) arrives in every
   state message as state.training. The card is rebuilt only when that changes. */
let curriculum = null;
let trainTab = null;      // "lesson" | "drills" | "scrim", chosen on the client
let trainKey = "";
const STALE_SERVER = "The app server is older than this page. Restart the app (close its window and launch it again) to use training.";
fetch("api/curriculum")
  .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
  .then((c) => { curriculum = c; trainKey = ""; renderTraining(); })
  .catch(() => { $("training").textContent = STALE_SERVER; });

const COLOR = { X: "Black", O: "White" };
const pctText = (x) => `${Math.round(100 * x)}%`;

function unitBadge(p) {
  if (p.passed) return `<span class="train-badge done">Passed</span>`;
  if (!p.unlocked) return `<span class="train-badge">Locked</span>`;
  if (p.drills || p.scrimmages || p.lesson) return `<span class="train-badge">${p.drills ? pctText(p.rate) + " drills" : "Started"}</span>`;
  return `<span class="train-badge">Open</span>`;
}

function renderTraining() {
  const el = $("training");
  if (state && !("training" in state)) { el.textContent = STALE_SERVER; return; }
  if (!curriculum || !state || !state.training) return;
  const t = state.training;
  const key = JSON.stringify(t) + "|" + trainTab;
  if (key === trainKey) return;
  trainKey = key;
  const passed = curriculum.filter((u) => t.units[u.id].passed).length;
  $("train-meta").textContent = `${passed} / ${curriculum.length} units passed`;
  if (!t.unit) { el.innerHTML = trainingPath(t); return; }
  const unit = curriculum.find((u) => u.id === t.unit);
  if (!trainTab) trainTab = t.mode === "scrimmage" ? "scrim" : t.mode === "drill" ? "drills" : "lesson";
  el.innerHTML = trainingUnit(unit, t);
}

function trainingPath(t) {
  let html = `<p class="muted">A path through Brian Rose's <i>Othello: A Minute to Learn… A Lifetime to Master</i>. ` +
    `Each unit: a lesson, drills graded by Edax (pass: ${pctText(t.pass_rate)} of the last ${t.window}), and a themed scrimmage.</p>`;
  for (const part of [1, 2]) {
    html += `<div class="train-part">${part === 1 ? "Part I · in order" : "Part II · any order, after Part I"}</div>`;
    curriculum.filter((u) => u.part === part).forEach((u) => {
      const p = t.units[u.id], n = curriculum.indexOf(u) + 1;
      html += `<button class="train-unit" data-act="open" data-unit="${u.id}" ${p.unlocked ? "" : "disabled"}>` +
        `<span class="num">${n}</span><span>${esc(u.title)}<span class="ch">Chapter ${u.chapter} · pp. ${u.pages}</span></span>${unitBadge(p)}</button>`;
    });
  }
  return html;
}

function trainingUnit(u, t) {
  const p = t.units[u.id];
  const step = (id, title, sub, done) =>
    `<button class="train-step${trainTab === id ? " on" : ""}${done ? " done" : ""}" data-act="tab" data-tab="${id}"><b>${title}</b>${sub}</button>`;
  let html = `<div class="train-head"><h3>${esc(u.title)}</h3><button class="btn secondary small" data-act="close">All units</button></div>` +
    `<div class="muted">Chapter ${u.chapter} · book pp. ${u.pages}</div>` +
    `<div class="train-steps">` +
    step("lesson", "1 Lesson", p.lesson ? "read" : "start here", p.lesson) +
    step("drills", "2 Drills", p.drills ? `${pctText(p.rate)} of last ${p.drills}` : `${t.window} to pass`, p.drills_passed) +
    step("scrim", "3 Scrimmage", p.scrimmages ? `${p.scrimmages} played` : `level ${p.level}`, p.scrimmage_passed) +
    `</div>`;
  if (trainTab === "lesson") html += trainingLesson(u, t);
  else if (trainTab === "drills") html += trainingDrills(u, t, p);
  else html += trainingScrimmage(u, t, p);
  return html;
}

function trainingLesson(u, t) {
  let html = `<div class="train-lesson">${u.lesson.map((x) => `<p>${esc(x)}</p>`).join("")}` +
    `<h4>Key ideas</h4><ul>${u.ideas.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` +
    `<h4>Ask yourself</h4><ul>${u.look_for.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`;
  const ex = t.mode === "example" ? t.example : null;
  if (ex) html += `<div class="train-box">${esc(ex.text)}${ex.status === "ready" ? `<span class="muted">Yellow ring: Edax's best move · coral ring: the instructive mistake. Hover or play moves to explore.</span>` : ""}</div>`;
  html += `<div class="btn-row">`;
  if (!u.drill_kinds.includes("squares")) html += `<button class="btn secondary small" data-act="example">${ex ? "Another example" : "Show an example"}</button>`;
  html += `<button class="btn small" data-act="to-drills">${t.units[u.id].lesson ? "Go to drills" : "I've read it: start drills"}</button></div>`;
  return html;
}

function trainingDrills(u, t, p) {
  const d = t.mode === "drill" ? t.drill : null;
  let html = `<div class="train-meter" title="Last ${p.drills} drills"><span style="width:${100 * p.rate}%"></span></div>` +
    `<div class="muted">${p.drills ? `${pctText(p.rate)} over the last ${p.drills} drill${p.drills === 1 ? "" : "s"}` : "No drills yet"} · pass at ${pctText(t.pass_rate)} over ${t.window}${p.drills_passed ? " · passed ✓" : ""}</div>`;
  if (!d) return html + `<div class="btn-row"><button class="btn small" data-act="drill">Start a drill</button></div>`;
  const cls = d.status !== "answered" ? "" : d.credit >= 1 ? " right" : d.credit > 0 ? " half" : " wrong";
  html += `<div class="train-box${cls}"><div>${esc(d.prompt)}</div>`;
  if (d.choices) {
    html += `<div class="train-choices">` + d.choices.map((c, i) => {
      const k = d.status === "answered" ? (i === d.correct ? " correct" : "") + (i === d.chosen ? " chosen" : "") : "";
      return `<button class="btn secondary small${k}" data-act="answer" data-choice="${i}" ${d.status === "ask" ? "" : "disabled"}>${esc(c)}</button>`;
    }).join("") + `</div>`;
  }
  if (d.status === "answered") {
    html += `<div>${esc(d.feedback)}</div>`;
    if (d.ranking) html += `<div class="train-ranking">Edax: ${d.ranking.map(([m, v]) => `${m.toUpperCase()} ${fmtScore(v)}`).join(" · ")}</div>`;
    if (d.kind === "move") html += `<div class="muted">Yellow ring: best · coral ring: your move. Hints are back on so you can explore.</div>`;
  }
  html += `</div>`;
  if (d.status === "answered") html += `<div class="btn-row"><button class="btn small" data-act="drill">Next drill</button></div>`;
  return html;
}

function trainingScrimmage(u, t, p) {
  const sc = t.mode === "scrimmage" ? t.scrimmage : null;
  let html = `<p>${esc(u.scrimmage)}</p>` +
    `<div class="muted">Edax level ${p.level} (rises when you win, drops after a heavy loss). You alternate colours. Hints are off; the coach is on.</div>`;
  if (sc && sc.status === "playing") {
    html += `<div class="train-box">You are ${COLOR[sc.color]} against level ${sc.level}. ` +
      `Coach pauses so far: ${sc.flagged}. Pass by finishing with none.</div>`;
  }
  const r = t.review;
  if (sc && sc.status === "done" && r) {
    html += `<div class="train-box ${r.passed ? "right" : "wrong"}"><div><b>You ${r.result}${r.diff ? ` by ${Math.abs(r.diff)}` : ""}.</b> ${esc(r.verdict)}</div>`;
    if (r.mistakes.length) {
      html += `<div class="muted">Moves that cost ${sc.threshold}+ discs (underlined: this unit's kind). Click to see the position.</div>`;
      html += r.mistakes.map((m) => `<div class="train-mistake${m.related ? " related" : ""}" data-act="goto" data-ply="${m.ply - 1}">` +
        `<b>${m.move.toUpperCase()}</b> −${fmtNum(m.loss)}, best ${m.best.toUpperCase()}. ${esc(m.why)}</div>`).join("");
    } else html += `<div>No costly moves at all. Excellent.</div>`;
    html += `<div class="muted">Tip: press Analyze game for the full evaluation graph.</div></div>`;
  }
  html += `<div class="btn-row"><button class="btn small" data-act="scrimmage">${sc ? "New scrimmage" : "Start scrimmage"}</button></div>`;
  return html;
}

$("training").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (!b || b.disabled) return;
  const act = b.dataset.act;
  if (act === "open") { trainTab = null; send({ type: "train_open", unit: b.dataset.unit }); }
  else if (act === "close") { trainTab = null; send({ type: "train_close" }); }
  else if (act === "tab") { trainTab = b.dataset.tab; renderTraining(); }
  else if (act === "example") send({ type: "train_example" });
  else if (act === "to-drills") {
    trainTab = "drills";
    if (!state.training.units[state.training.unit].lesson) send({ type: "train_lesson_done" });
    send({ type: "train_drill" });
  }
  else if (act === "drill") send({ type: "train_drill" });
  else if (act === "answer") send({ type: "train_answer", choice: Number(b.dataset.choice) });
  else if (act === "scrimmage") { trainTab = "scrim"; send({ type: "train_scrimmage" }); }
  else if (act === "goto") send({ type: "goto", index: Number(b.dataset.ply) });  // the position before the mistake
});
