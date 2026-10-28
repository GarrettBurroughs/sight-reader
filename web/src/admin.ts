// Admin panel: browse the excerpt library, inspect why an excerpt got its grade,
// and look after players (levels, attempts). Hash routes:
//   #library  #excerpt/<id>  #players  #player/<id>

import "./style.css";
import "./admin.css";
import { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import { api, levelKey, type Attempt, type Hands, type Mode, type Player } from "./api";

const view = document.querySelector<HTMLElement>("#view")!;
const PAGE = 50;
const KEYS = ["C♭", "G♭", "D♭", "A♭", "E♭", "B♭", "F", "C", "G", "D", "A", "E", "B", "F♯", "C♯"];

type Child = Node | string | number | null | undefined | false;

/** Tiny element builder: h("td", { class: "num" }, "3.4"). */
function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | boolean | ((e: Event) => void)> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (typeof v === "function") el.addEventListener(k.replace(/^on/, ""), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false) el.setAttribute(k, v);
  }
  for (const c of children) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

function table(headers: string[], rows: Child[][], numeric: number[] = []) {
  return h(
    "table",
    {},
    h("thead", {}, h("tr", {}, ...headers.map((t, i) => h("th", numeric.includes(i) ? { class: "num" } : {}, t)))),
    h("tbody", {}, ...rows.map((r) => h("tr", {}, ...r.map((c, i) => h("td", numeric.includes(i) ? { class: "num" } : {}, c))))),
  );
}

const keyName = (fifths: number) => KEYS[fifths + 7] ?? String(fifths);
const date = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");
const pct = (x: number | null) => (x === null || x === undefined ? "—" : `${Math.round(x)}%`);
const MODES: Mode[] = ["wait", "tempo"];
const HANDS: Hands[] = ["both", "right", "left"];
const HAND_LABEL: Record<Hands, string> = { both: "Both", right: "Right", left: "Left" };
const byHand = (r: number | null, l: number | null) => (r === null && l === null ? "—" : `R ${r ?? 0} · L ${l ?? 0}`);

function fail(err: unknown) {
  view.replaceChildren(
    h("p", { class: "error" }, `Couldn't reach the API server: ${err instanceof Error ? err.message : err}. Is ./dev.sh running?`),
  );
}

// ---- Library ----

const libState = { q: "", grade: "", source: "", license: false, sort: "difficulty", order: "asc", offset: 0 };

async function showLibrary() {
  const summary = await api.summary();
  const results = h("div");
  const controls = h(
    "form",
    {
      class: "filters",
      onsubmit: (e: Event) => {
        e.preventDefault();
        const f = new FormData(e.target as HTMLFormElement);
        Object.assign(libState, {
          q: String(f.get("q") ?? ""),
          grade: String(f.get("grade") ?? ""),
          source: String(f.get("source") ?? ""),
          license: f.get("license") === "on",
          sort: String(f.get("sort")),
          order: String(f.get("order")),
          offset: 0,
        });
        loadRows();
      },
    },
    h("input", { name: "q", type: "search", placeholder: "Title or composer", value: libState.q }),
    h(
      "select",
      { name: "grade" },
      h("option", { value: "" }, "All grades"),
      ...Array.from({ length: 9 }, (_, i) => h("option", { value: String(i + 1), selected: libState.grade === String(i + 1) }, `Grade ${i + 1}`)),
    ),
    h(
      "select",
      { name: "source" },
      h("option", { value: "" }, "All sources"),
      h("option", { value: "pdmx", selected: libState.source === "pdmx" }, "PDMX pieces"),
      h("option", { value: "generated", selected: libState.source === "generated" }, "Generated exercises"),
    ),
    h(
      "select",
      { name: "sort" },
      ...["difficulty", "grade", "title", "attempts"].map((s) => h("option", { value: s, selected: libState.sort === s }, `Sort by ${s}`)),
    ),
    h(
      "select",
      { name: "order" },
      h("option", { value: "asc", selected: libState.order === "asc" }, "Ascending"),
      h("option", { value: "desc", selected: libState.order === "desc" }, "Descending"),
    ),
    h("label", {}, h("input", { name: "license", type: "checkbox", checked: libState.license }), " No license conflict only"),
    h("button", { type: "submit" }, "Apply"),
  );

  view.replaceChildren(
    h("h2", {}, "Library"),
    h(
      "p",
      { class: "quiet" },
      `${(summary.pieces - summary.generated).toLocaleString()} PDMX pieces + ${summary.generated.toLocaleString()} generated exercises · ` +
        `${summary.excerpts.toLocaleString()} excerpts · ` +
        `${summary.players} players · ${summary.attempts} attempts` +
        (summary.license_only ? " · server serves no-license-conflict music only" : ""),
    ),
    table(
      ["Grade", "Excerpts", "Pieces", "No license conflict"],
      summary.grades.map((g) => [g.grade, g.excerpts.toLocaleString(), g.pieces.toLocaleString(), g.license_ok.toLocaleString()]),
      [1, 2, 3],
    ),
    controls,
    results,
  );

  async function loadRows() {
    const { total, rows } = await api.library({
      q: libState.q || undefined,
      grade: libState.grade ? Number(libState.grade) : undefined,
      source: libState.source || undefined,
      license_only: libState.license || undefined,
      sort: libState.sort,
      order: libState.order,
      limit: PAGE,
      offset: libState.offset,
    });
    const pager = h(
      "div",
      { class: "pager" },
      h("button", { type: "button", disabled: libState.offset === 0, onclick: () => ((libState.offset -= PAGE), loadRows()) }, "← Previous"),
      total ? `${libState.offset + 1}–${Math.min(libState.offset + PAGE, total)} of ${total.toLocaleString()}` : "No matches",
      h("button", { type: "button", disabled: libState.offset + PAGE >= total, onclick: () => ((libState.offset += PAGE), loadRows()) }, "Next →"),
    );
    results.replaceChildren(
      pager,
      table(
        ["Title", "Composer", "Grade", "Difficulty", "Time", "Key", "Notes/beat", "License OK", "Attempts"],
        rows.map((r) => [
          h("a", { href: `#excerpt/${r.id}` }, r.title),
          r.composer ?? "—",
          r.grade,
          r.difficulty.toFixed(2),
          r.time_signature,
          keyName(r.key_fifths),
          r.notes_per_quarter.toFixed(2),
          r.no_license_conflict ? "✓" : "✗",
          r.attempts,
        ]),
        [2, 3, 6, 8],
      ),
    );
  }
  await loadRows();
}

// ---- One excerpt ----

async function showExcerpt(id: string) {
  const ex = await api.excerpt(id);
  const terms = Object.entries(ex.terms).sort((a, b) => b[1] - a[1]);
  const scoreEl = h("div", { class: "score-preview" });
  const f = ex.features as Record<string, unknown>;
  const flat = Object.entries(f).flatMap(([k, v]) =>
    v && typeof v === "object" ? Object.entries(v as object).map(([k2, v2]) => [`${k}.${k2}`, v2]) : [[k, v]],
  );

  view.replaceChildren(
    h("p", {}, h("a", { href: "#library" }, "← Library")),
    h("h2", {}, ex.title),
    h(
      "p",
      { class: "quiet" },
      `${ex.composer ?? "Unknown composer"} · bars ${ex.start_bar}+ (${ex.n_bars}) · ${ex.time_signature} · ${keyName(ex.key_fifths)} major key signature · ` +
        `license ${ex.license ?? "?"}${ex.no_license_conflict ? "" : " (PDMX flags a conflict)"} · ${ex.n_favorites} favorites`,
    ),
    h(
      "p",
      {},
      h("strong", { class: "grade" }, `Grade ${ex.grade}`),
      ` difficulty ${ex.difficulty.toFixed(2)} · `,
      h("a", { href: `/?excerpt=${encodeURIComponent(ex.id)}` }, "Play this excerpt"),
    ),
    scoreEl,
    h(
      "div",
      { class: "columns" },
      h(
        "section",
        {},
        h("h3", {}, "What adds up to the difficulty"),
        table(["Term", "Points"], terms.filter(([, v]) => v > 0).map(([k, v]) => [k, v.toFixed(2)]), [1]),
      ),
      h("section", {}, h("h3", {}, "Features"), table(["Feature", "Value"], flat.map(([k, v]) => [String(k), formatValue(v)]), [1])),
    ),
    h("h3", {}, "Attempts"),
    ex.attempts.length
      ? table(
          ["When", "Player", "Mode", "Hands", "Performance", "Level"],
          ex.attempts.map((a) => [
            date(a.finished_at),
            a.player,
            a.mode,
            HAND_LABEL[a.hands],
            pct(a.performance * 100),
            `${a.level_before.toFixed(2)} → ${a.level_after.toFixed(2)}`,
          ]),
          [4],
        )
      : h("p", { class: "quiet" }, "Nobody has played this one yet."),
  );

  const osmd = new OpenSheetMusicDisplay(scoreEl, { backend: "svg", drawTitle: false, drawComposer: false, drawPartNames: false, autoResize: true });
  try {
    await osmd.load(ex.score_url);
    osmd.render();
  } catch (err) {
    scoreEl.textContent = `Couldn't render: ${err}`;
  }
}

function formatValue(v: unknown) {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === "boolean") return v ? "yes" : "no";
  return v === null ? "—" : String(v);
}

// ---- Players ----

async function showPlayers() {
  const players = await api.players();
  const msg = h("p", { class: "quiet" });
  view.replaceChildren(
    h("h2", {}, "Players"),
    table(
      ["Name", "Wait (R · L)", "Tempo (R · L)", "Attempts", "Last played"],
      players.map((p) => [
        h("a", { href: `#player/${p.id}` }, p.name),
        levelSummary(p, "wait"),
        levelSummary(p, "tempo"),
        p.attempts,
        date(p.last_played),
      ]),
      [1, 2, 3],
    ),
    h("h3", {}, "Add a player"),
    h(
      "form",
      {
        class: "filters",
        onsubmit: async (e: Event) => {
          e.preventDefault();
          const f = new FormData(e.target as HTMLFormElement);
          try {
            await api.createPlayer(String(f.get("name")), Number(f.get("level")));
            showPlayers();
          } catch (err) {
            msg.textContent = String(err instanceof Error ? err.message : err);
          }
        },
      },
      h("input", { name: "name", placeholder: "Name", required: true, maxlength: "40" }),
      h("label", {}, "Starting level ", h("input", { name: "level", type: "number", min: "1", max: "9", step: "0.1", value: "2" })),
      h("button", { type: "submit" }, "Add"),
    ),
    msg,
  );
}

async function showPlayer(id: number) {
  const player = (await api.players()).find((p) => p.id === id);
  if (!player) {
    view.replaceChildren(h("p", {}, "No such player. ", h("a", { href: "#players" }, "Back to players")));
    return;
  }
  const attempts = await api.attempts(id, 500);
  const msg = h("span", { class: "quiet" });

  view.replaceChildren(
    h("p", {}, h("a", { href: "#players" }, "← Players")),
    h("h2", {}, player.name),
    h("p", { class: "quiet" }, `Since ${date(player.created_at)} · ${player.attempts} attempts · last played ${date(player.last_played)}`),
    playerForm(player, msg),
    h("h3", {}, "Which hand slips (hands-together runs)"),
    handBreakdown(attempts),
    h("h3", {}, "Per grade"),
    gradeBreakdown(attempts),
    h("h3", {}, "Attempts, newest first"),
    attempts.length
      ? table(
          ["When", "Piece", "Grade", "Mode", "Hands", "BPM", "Wrong", "Missed", "Notes", "Timing", "Performance", "Level"],
          attempts.map((a) => [
            date(a.finished_at),
            h("a", { href: `#excerpt/${a.excerpt_id}` }, a.title ?? a.excerpt_id),
            a.grade,
            a.mode,
            HAND_LABEL[a.hands],
            a.bpm ?? "—",
            a.hands === "both" ? byHand(a.wrong_right, a.wrong_left) : a.wrong,
            a.mode === "tempo" ? byHand(a.missed_right, a.missed_left) : "—",
            pct(a.note_pct),
            pct(a.timing_pct),
            pct(a.performance * 100),
            levelChange(a),
          ]),
          [2, 5, 8, 9, 10],
        )
      : h("p", { class: "quiet" }, "No attempts yet."),
  );
}

function playerForm(player: Player, msg: HTMLElement) {
  let confirmDelete = false;
  const deleteBtn = h(
    "button",
    {
      type: "button",
      class: "danger",
      onclick: async () => {
        // Two clicks instead of confirm(): dialogs don't show inside the iPad shell.
        if (!confirmDelete) {
          confirmDelete = true;
          deleteBtn.textContent = "Really delete, with all attempts?";
          return;
        }
        await api.deletePlayer(player.id);
        location.hash = "#players";
      },
    },
    "Delete player",
  );
  return h(
    "form",
    {
      class: "filters",
      onsubmit: async (e: Event) => {
        e.preventDefault();
        const f = new FormData(e.target as HTMLFormElement);
        const levels = Object.fromEntries(MODES.flatMap((m) => HANDS.map((hd) => [levelKey(m, hd), Number(f.get(levelKey(m, hd)))])));
        await api.updatePlayer(player.id, { name: String(f.get("name")), levels });
        msg.textContent = "Saved.";
        showPlayer(player.id);
      },
    },
    h("label", {}, "Name ", h("input", { name: "name", value: player.name, required: true, maxlength: "40" })),
    table(
      ["Levels", ...HANDS.map((hands) => HAND_LABEL[hands])],
      MODES.map((mode) => [
        mode === "wait" ? "Wait" : "Tempo",
        ...HANDS.map((hands) =>
          h("input", {
            name: levelKey(mode, hands),
            type: "number",
            min: "1",
            max: "9",
            step: "0.01",
            value: player.levels[levelKey(mode, hands)].toFixed(2),
            "aria-label": `${mode} ${hands} level`,
          }),
        ),
      ]),
    ),
    h("button", { type: "submit" }, "Save"),
    deleteBtn,
    msg,
  );
}

function levelSummary(p: Player, mode: Mode) {
  const lv = (hands: Hands) => p.levels[levelKey(mode, hands)].toFixed(1);
  return `${lv("both")} (${lv("right")} · ${lv("left")})`;
}

function handBreakdown(attempts: Attempt[]) {
  const together = attempts.filter((a) => a.hands === "both");
  if (!together.length) return h("p", { class: "quiet" }, "No hands-together runs yet.");
  const sum = (key: "wrong_right" | "wrong_left" | "missed_right" | "missed_left") => together.reduce((s, a) => s + (a[key] ?? 0), 0);
  const tempoRuns = together.filter((a) => a.mode === "tempo").length;
  return table(
    ["", "Right hand", "Left hand"],
    [
      ["Wrong notes", sum("wrong_right"), sum("wrong_left")],
      ["Missed notes (tempo)", tempoRuns ? sum("missed_right") : "—", tempoRuns ? sum("missed_left") : "—"],
    ],
    [1, 2],
  );
}

function gradeBreakdown(attempts: Attempt[]) {
  if (!attempts.length) return h("p", { class: "quiet" }, "—");
  const by = new Map<string, Attempt[]>();
  for (const a of attempts) {
    const key = `${a.mode}|${a.hands}|${a.grade}`;
    by.set(key, [...(by.get(key) ?? []), a]);
  }
  const rows = [...by.entries()]
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([key, list]) => {
      const [mode, hands, grade] = key.split("|");
      const avg = list.reduce((s, a) => s + a.performance, 0) / list.length;
      return [mode, HAND_LABEL[hands as Hands], grade, list.length, pct(avg * 100)];
    });
  return table(["Mode", "Hands", "Grade", "Attempts", "Average performance"], rows, [2, 3, 4]);
}

function levelChange(a: Attempt) {
  const d = a.level_after - a.level_before;
  const cls = d > 0 ? "up" : d < 0 ? "down" : "";
  return h("span", { class: cls }, `${a.level_before.toFixed(2)} → ${a.level_after.toFixed(2)}`);
}

// ---- Routing ----

async function route() {
  const [name, arg] = location.hash.slice(1).split("/");
  for (const a of document.querySelectorAll<HTMLAnchorElement>("[data-nav]")) {
    a.classList.toggle("active", a.dataset.nav === (name === "excerpt" ? "library" : name === "player" ? "players" : name || "library"));
  }
  window.scrollTo(0, 0);
  try {
    if (name === "excerpt" && arg) await showExcerpt(decodeURIComponent(arg));
    else if (name === "players") await showPlayers();
    else if (name === "player" && arg) await showPlayer(Number(arg));
    else await showLibrary();
  } catch (err) {
    fail(err);
  }
}

window.addEventListener("hashchange", route);
route();
