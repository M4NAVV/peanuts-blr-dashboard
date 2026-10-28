// The 🧮 Excel Builder — Excel's PivotTable, in the browser. Python (pivot_pane.py) supplies the numbers from the
// dashboard's own engine; everything you see and touch is here: the ribbon, the sheet, the PivotTable Fields pane,
// the menus and dialogs. Display choices (layout, subtotals, grand totals, ⊞/⊟, styles) never go back for a
// recalculation; a change to WHAT is measured sends the layout to Python as one "ui" event.

const STORE = (globalThis.__peanutsPivot ||= {});
const MAX_ROWS = 2500;                 // rows drawn on screen; the Excel file has every row
const SEP = "\u0001";
const LETTERS = (n) => { let s = ""; n += 1; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); } return s; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = (o) => JSON.parse(JSON.stringify(o));

// ---------------------------------------------------------------- numbers, the dashboard's way
function indian(n, dec = 0) {
  const neg = n < 0; n = Math.abs(n);
  let [w, f] = n.toFixed(dec).split(".");
  if (w.length > 3) { const head = w.slice(0, -3), tail = w.slice(-3); w = head.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + tail; }
  return (neg ? "-" : "") + w + (f ? "." + f : "");
}
const western = (n, dec = 0) => n.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
const sign = (n) => (n > 0 ? "+" : "");
function fmtVal(v, k, nf) {
  if (v === null || v === undefined || Number.isNaN(v)) return "";
  const cat = (nf && nf.cat) || "auto", dec = (nf && +nf.dec) || 0;
  if (cat === "indian") return indian(v, dec);
  if (cat === "number") return western(v, dec);
  if (cat === "currency") return (v < 0 ? "-₹" : "₹") + indian(Math.abs(v), dec);
  if (cat === "lakh") return (v / 1e5).toFixed(dec) + " L";
  if (cat === "crore") return (v / 1e7).toFixed(dec) + " Cr";
  if (cat === "percent") return (v * 100).toFixed(dec) + "%";
  switch (k) {
    case "money": case "int": case "moneyratio": return indian(v, 0);
    case "ratio": return western(v, 2);
    case "pct": return (v * 100).toFixed(1) + "%";
    case "pctchg": return sign(v) + (v * 100).toFixed(1) + "%";
    case "ppchg": return sign(v) + (v * 100).toFixed(1) + " pts";
    case "moneychg": case "intchg": return sign(v) + indian(v, 0);
    case "ratiochg": return sign(v) + v.toFixed(2);
    default: return String(v);
  }
}

// ---------------------------------------------------------------- icons
const IC = {
  pivot: '<svg viewBox="0 0 32 32"><rect x="3" y="5" width="26" height="22" fill="#fff" stroke="#6b6b6b"/><rect x="3" y="5" width="26" height="5" fill="#cfe5d6" stroke="#6b6b6b"/><rect x="3" y="5" width="7" height="22" fill="#cfe5d6" stroke="#6b6b6b"/><path d="M10 15h19M10 20h19M17 10v17M23 10v17" stroke="#9a9a9a"/></svg>',
  refresh: '<svg viewBox="0 0 32 32"><path d="M24 11a9 9 0 1 0 2 8" fill="none" stroke="#107c41" stroke-width="2.4" stroke-linecap="round"/><path d="M25 5v7h-7" fill="none" stroke="#107c41" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  excel: '<svg viewBox="0 0 32 32"><rect x="10" y="4" width="19" height="24" rx="2" fill="#fff" stroke="#107c41" stroke-width="1.5"/><path d="M14 10h11M14 15h11M14 20h11" stroke="#9cc9ae"/><rect x="3" y="9" width="14" height="14" rx="1.5" fill="#107c41"/><path d="M7 12l6 8M13 12l-6 8" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>',
  sub: '<svg viewBox="0 0 32 32"><rect x="4" y="5" width="24" height="22" fill="#fff" stroke="#6b6b6b"/><path d="M4 11h24M4 17h24M4 22h24" stroke="#bdbdbd"/><rect x="4" y="11" width="24" height="5" fill="#cfe5d6"/><rect x="4" y="22" width="24" height="5" fill="#cfe5d6"/></svg>',
  grand: '<svg viewBox="0 0 32 32"><rect x="4" y="5" width="24" height="22" fill="#fff" stroke="#6b6b6b"/><path d="M4 11h24M4 16h24M11 5v22M18 5v22" stroke="#bdbdbd"/><rect x="4" y="21" width="24" height="6" fill="#cfe5d6"/><rect x="22" y="5" width="6" height="22" fill="#cfe5d6"/></svg>',
  layout: '<svg viewBox="0 0 32 32"><rect x="4" y="5" width="24" height="22" fill="#fff" stroke="#6b6b6b"/><path d="M4 10h24" stroke="#6b6b6b"/><path d="M7 14h8M10 18h8M10 22h8" stroke="#107c41" stroke-width="2"/><path d="M20 14h6M20 18h6M20 22h6" stroke="#bdbdbd" stroke-width="2"/></svg>',
  blank: '<svg viewBox="0 0 32 32"><rect x="4" y="5" width="24" height="22" fill="#fff" stroke="#6b6b6b"/><path d="M4 10h24M4 14h24M4 22h24" stroke="#bdbdbd"/><rect x="4" y="15" width="24" height="5" fill="#fff4ce"/></svg>',
  search: '<svg viewBox="0 0 16 16"><circle cx="7" cy="7" r="5" fill="none" stroke="#333" stroke-width="1.6"/><path d="M11 11l4 4" stroke="#333" stroke-width="1.6"/></svg>',
  filter: '<svg viewBox="0 0 16 16"><path d="M2 3h12l-5 6v5l-2-1V9z" fill="none" stroke="#333" stroke-width="1.3"/></svg>',
  cols: '<svg viewBox="0 0 16 16"><path d="M3 2v12M8 2v12M13 2v12" stroke="#333" stroke-width="1.6"/></svg>',
  rows: '<svg viewBox="0 0 16 16"><path d="M2 3h12M2 8h12M2 13h12" stroke="#333" stroke-width="1.6"/></svg>',
  sigma: '<svg viewBox="0 0 16 16"><path d="M12 3H4l5 5-5 5h8" fill="none" stroke="#333" stroke-width="1.6"/></svg>',
  expand: '<svg viewBox="0 0 16 16"><rect x="2" y="2" width="12" height="12" fill="#fff" stroke="#555"/><path d="M5 8h6M8 5v6" stroke="#107c41" stroke-width="1.6"/></svg>',
  collapse: '<svg viewBox="0 0 16 16"><rect x="2" y="2" width="12" height="12" fill="#fff" stroke="#555"/><path d="M5 8h6" stroke="#c00000" stroke-width="1.6"/></svg>',
  az: '<svg viewBox="0 0 16 16"><text x="1" y="7" font-size="7" font-family="Arial">A</text><text x="1" y="15" font-size="7" font-family="Arial">Z</text><path d="M12 2v11M9 10l3 3 3-3" fill="none" stroke="#107c41" stroke-width="1.4"/></svg>',
  za: '<svg viewBox="0 0 16 16"><text x="1" y="7" font-size="7" font-family="Arial">Z</text><text x="1" y="15" font-size="7" font-family="Arial">A</text><path d="M12 2v11M9 10l3 3 3-3" fill="none" stroke="#107c41" stroke-width="1.4"/></svg>',
  clear: '<svg viewBox="0 0 16 16"><path d="M2 3h12l-5 6v5l-2-1V9z" fill="none" stroke="#333" stroke-width="1.3"/><path d="M10 10l4 4M14 10l-4 4" stroke="#c00000" stroke-width="1.4"/></svg>',
};

// ---------------------------------------------------------------- state
function freshState(data) {
  return {
    ui: clone(data.ui), rev: data.rev || 0, pending: null, collapsed: new Set(), cur: null, anchor: null,
    tab: "analyze", menu: null, dlg: null, search: "", shut: new Set(), defer: false, dirty: false,
    drag: null, withSource: false, lastDl: null, toast: null, msgClosed: "", scroll: [0, 0], fscroll: 0,
  };
}
const isData = (k) => !["layout", "subtotals", "grand_rows", "grand_cols", "repeat", "blank", "banded_rows", "banded_cols",
  "row_headers", "col_headers", "buttons", "field_headers", "style", "names"].includes(k);

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const host = parentElement.querySelector(".pv-root");
  if (!host || !data) return;
  const id = data.feed || "pivot";
  let S = STORE[id];
  if (!S) S = STORE[id] = freshState(data);
  S.data = data; S.send = setTriggerValue; S.host = host;
  if ((data.rev || 0) >= S.rev && !S.dirty) { S.ui = clone(data.ui); S.rev = data.rev || 0; }
  if (S.pending !== null && (data.rev || 0) >= S.pending) S.pending = null;
  if (data.download && data.download.id && data.download.id !== S.lastDl) { S.lastDl = data.download.id; deliver(S, data.download); }
  host.__S = S;
  if (!host.__wired) { wire(host); host.__wired = true; }
  render(S);
}

// ---------------------------------------------------------------- talking to Python
function commit(S, change) {
  // change: true = what is measured changed (needs the engine); false = display only (persist, no wait)
  S.rev += 1;
  clearTimeout(S.dispT);
  if (change && S.defer) { S.dirty = true; render(S); return; }
  if (!change) {
    // ★ A DISPLAY CHANGE IS INSTANT AND SAVES QUIETLY: drawn now, remembered (address bar, session) once the
    // clicking stops — so flicking through layouts never waits on the server.
    render(S);
    S.dispT = setTimeout(() => S.send("event", { type: "ui", ui: S.ui, rev: S.rev }), 2500);
    return;
  }
  S.dirty = false;
  S.pending = S.rev;
  S.send("event", { type: "ui", ui: S.ui, rev: S.rev });
  render(S);
}
function deliver(S, dl) {
  if (dl.error) { toast(S, dl.error); return; }
  try {
    const bin = atob(dl.b64), buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    const a = document.createElement("a"); a.href = url; a.download = dl.name; a.style.display = "none";
    S.host.appendChild(a); a.click(); setTimeout(() => a.remove(), 1000);
    toast(S, `Saved <b>${esc(dl.name)}</b> · <a href="${url}" download="${esc(dl.name)}">download again</a>`, 9000);
  } catch (e) { toast(S, "Could not save the file: " + esc(e.message)); }
}
function toast(S, html, ms = 4500) {
  S.toast = html; render(S);
  clearTimeout(S.toastT); S.toastT = setTimeout(() => { S.toast = null; render(S); }, ms);
}

// ---------------------------------------------------------------- names
const meas = (S) => Object.fromEntries(S.data.measures.map((m) => [m.name, m]));
const fname = (S, f) => (S.ui.names && S.ui.names[f]) || f;
const SHOWX = (S, h) => S.data.show_names[h] || h;
function vnameRaw(S, v) {
  if (v.name) return v.name;
  const M = meas(S)[v.m];
  const base = M && M.additive ? "Sum of " + v.m : v.m;
  return v.how && v.how !== "Value" ? `${base} · ${SHOWX(S, v.how)}` : base;
}
function vnames(S) {
  const seen = {};
  return S.ui.values.map((v) => { let n = vnameRaw(S, v); if (seen[n]) { seen[n] += 1; n = n + " " + seen[n]; } else seen[n] = 1; return n; });
}
function selText(S, f) {
  const s = S.ui.sel && S.ui.sel[f];
  if (!s || !s.items || !s.items.length) return "(All)";
  if (s.mode === "include" && s.items.length === 1) return s.items[0];
  return "(Multiple Items)";
}
const isFiltered = (S, f) => !!(S.ui.sel && S.ui.sel[f] && S.ui.sel[f].items && S.ui.sel[f].items.length);

// ---------------------------------------------------------------- the sheet model (screen and file alike)
function model(S, forExport = false) {
  const d = S.data, ui = S.ui, g = d.grid;
  const out = { rows: [], ncol: 0, pivotTop: 0, L: 1, valCols: [], head: 0, filters: [] };
  // report filters, above the pivot
  for (const f of ui.filters_area || []) {
    out.rows.push({ type: "pf", cells: [{ t: fname(S, f), cls: "pf-name" }, { t: selText(S, f), cls: "pf-val", fb: "pf:" + f, ff: isFiltered(S, f) }] });
    out.filters.push([fname(S, f), selText(S, f)]);
  }
  // Excel: report filters from row 1, one blank row, then the pivot; with no filters it starts at row 3
  if (ui.filters_area && ui.filters_area.length) out.rows.push({ type: "blank", cells: [] });
  else out.rows.push({ type: "blank", cells: [] }, { type: "blank", cells: [] });
  out.pivotTop = out.rows.length;
  if (!g) return out;

  const R = g.rf, CF = g.cf, nv = g.nv, names = vnames(S);
  const compact = ui.layout === "compact", tabular = ui.layout === "tabular";
  const L = compact ? 1 : Math.max(1, R.length);
  out.L = L;
  const subOn = ui.subtotals !== "off", subTop = ui.subtotals === "top" && !tabular;
  // which column entries show: column subtotals follow the subtotal switch, the grand column its own
  const vis = [];
  g.colent.forEach(([k], ci) => {
    if (k === "subtotal" && !subOn) return;
    if (k === "grand" && CF.length && !ui.grand_cols) return;
    vis.push(ci);
  });
  const leaf = [];
  vis.forEach((ci) => { for (let vi = 0; vi < nv; vi++) leaf.push({ ci, vi, li: ci * nv + vi }); });
  out.valCols = leaf;
  const kinds = g.kinds;
  const fh = ui.field_headers;
  const vcell = (vals, extra = {}) => leaf.map(({ vi, li }) => ({ v: vals ? vals[li] : null, k: kinds[vi], nf: (ui.values[vi] || {}).fmt, vi, ...extra }));

  // ---- header rows
  const rowHead = () => (compact
    ? [{ t: fh ? "Row Labels" : "", fb: fh && R.length ? "rows" : null, ff: R.some((f) => isFiltered(S, f)), cls: "ph" }]
    : (R.length ? R : [""]).map((f) => ({ t: fh ? fname(S, f) : "", fb: fh && f ? "row:" + f : null, ff: f && isFiltered(S, f), cls: "ph" })));
  const blanksL = (n, cls = "ph") => Array.from({ length: n }, () => ({ t: "", cls }));
  const heads = [];
  if (CF.length) {
    heads.push([...(nv === 1 ? [{ t: names[0], cls: "ph" }, ...blanksL(L - 1)] : blanksL(L)),
      ...leaf.map((c, i) => (i === 0 ? { t: fh ? "Column Labels" : "", fb: fh ? "cols" : null, ff: CF.some((f) => isFiltered(S, f)), cls: "ph" } : { t: "", cls: "ph" }))]);
    for (let e = 0; e < CF.length; e++) {
      const last = e === CF.length - 1;
      const lab = last && nv === 1 ? rowHead() : blanksL(L);
      let prevKey = null;
      const vcells = leaf.map(({ ci, vi }) => {
        const [k, p] = g.colent[ci];
        if (vi !== 0) return { t: "", cls: "ph" };
        let t = "";
        if (k === "grand") t = e === 0 && nv === 1 ? "Grand Total" : "";
        else if (k === "subtotal") t = e === p.length - 1 ? p[e] + " Total" : (e < p.length ? p[e] : "");
        else t = p[e];
        const key = k + "|" + p.slice(0, e + 1).join(SEP);
        if (k === "item" && key === prevKey && !last) t = "";
        prevKey = key;
        return { t, cls: "ph" };
      });
      heads.push([...lab, ...vcells]);
    }
    if (nv > 1) heads.push([...rowHead(), ...leaf.map(({ ci, vi }) => ({ t: (g.colent[ci][0] === "grand" ? "Total " : "") + names[vi], cls: "ph", al: "right" }))]);
  } else {
    heads.push([...rowHead(), ...leaf.map(({ vi }) => ({ t: names[vi], cls: "ph", al: "right" }))]);
  }
  heads.forEach((cells) => out.rows.push({ type: "head", cells }));
  out.head = heads.length;

  // ---- the row tree, from the engine's rows (items, subtotals at every level, grand)
  const root = { path: [], kids: [], vals: null, map: new Map() };
  const nodes = new Map([["", root]]);
  let grand = null;
  for (const [kind, key, vals] of g.rows) {
    if (kind === "grand") { grand = vals; continue; }
    for (let dpt = 1; dpt <= key.length; dpt++) {
      const pk = key.slice(0, dpt).join(SEP);
      if (!nodes.has(pk)) {
        const n = { path: key.slice(0, dpt), kids: [], vals: null };
        nodes.set(pk, n); nodes.get(key.slice(0, dpt - 1).join(SEP)).kids.push(n);
      }
    }
    nodes.get(key.join(SEP)).vals = vals;
  }
  const body = [];
  let pend = [];                                     // tabular: ancestor labels waiting for their first row
  const labCells = (n, dpt, opts) => {
    const cells = blanksL(L, "");
    if (compact) {
      cells[0] = { t: opts.text, i: dpt - 1, tg: opts.tg, b: opts.bold, cls: "lab" + (opts.bold ? " pg" : ""), key: n.path.join(SEP), f: R[dpt - 1] };
      return cells;
    }
    const col = dpt - 1;
    for (let a = 0; a < col; a++) {
      const pa = pend[a];
      if (pa) { cells[a] = pa; pend[a] = null; }
      else if (ui.repeat) cells[a] = { t: n.path[a], cls: "lab", f: R[a] };
    }
    cells[col] = { t: opts.text, tg: opts.tg, b: opts.bold, cls: "lab" + (opts.bold ? " pg" : ""), key: n.path.join(SEP), f: R[col] };
    return cells;
  };
  function emit(n, hidden) {
    const dpt = n.path.length, isLeaf = dpt === R.length, label = n.path[dpt - 1];
    const pk = n.path.join(SEP), col = S.collapsed.has(pk);
    if (isLeaf) {
      body.push({ kind: "item", level: dpt - 1, hidden, key: pk, cells: [...labCells(n, dpt, { text: label }), ...vcell(n.vals)] });
      return;
    }
    const tg = ui.buttons ? (col ? "+" : "-") : null;
    if (tabular && !col) {
      pend[dpt - 1] = { t: label, tg, cls: "lab", key: pk, f: R[dpt - 1] };
    } else {
      const showVals = col || subTop;
      body.push({ kind: "group", level: dpt - 1, hidden, key: pk, cells: [...labCells(n, dpt, { text: label, tg, bold: true }), ...vcell(showVals ? n.vals : null, { b: true })] });
    }
    const hideKids = hidden || col;
    if (!hideKids || forExport) for (const k of n.kids) emit(k, hideKids);
    if (tabular && !col && pend[dpt - 1]) pend[dpt - 1] = null;
    if (!col && subOn && !subTop) {
      body.push({ kind: "subtotal", level: dpt - 1, hidden, key: pk, cells: [...labCells(n, dpt, { text: label + " Total", bold: true }), ...vcell(n.vals, { b: true })] });
    }
    if (ui.blank && !col) body.push({ kind: "blank", level: dpt - 1, hidden, cells: [] });
  }
  if (R.length) for (const k of root.kids) emit(k, false);
  if (ui.grand_rows || !R.length) {
    body.push({ kind: "grand", level: 0, cells: [{ t: R.length ? "Grand Total" : "", cls: "pt", b: true }, ...blanksL(L - 1, "pt"), ...vcell(grand, { b: true, cls: "pt" })] });
  }
  body.forEach((r, i) => { r.type = "body"; r.band = i; });
  out.rows.push(...body);
  out.ncol = L + leaf.length;
  out.names = names;
  return out;
}

// ---------------------------------------------------------------- render
function render(S) {
  const host = S.host, d = S.data, ui = S.ui;
  const old = host.querySelector(".pv-sheet");
  if (old) S.scroll = [old.scrollTop, old.scrollLeft];
  const oldF = host.querySelector(".pv-fields");
  if (oldF) S.fscroll = oldF.scrollTop;
  const act = host.ownerDocument ? (host.getRootNode().activeElement || null) : null;
  const focusId = act && act.dataset ? act.dataset.focus : null;
  const caret = act && act.selectionStart !== undefined ? act.selectionStart : null;

  S.m = model(S);
  const busy = S.pending !== null;
  const notes = (d.notes || []).filter((n) => !S.msgClosed.includes(n));
  host.innerHTML = `<div class="pv-app" tabindex="-1">
    ${ribbon(S)}
    ${formulaBar(S)}
    <div class="pv-body">
      <div class="pv-sheetwrap">
        ${notes.length ? `<div class="pv-msg"><b>ⓘ READ THIS</b><span>${notes.map(esc).join("<br>")}</span><button class="x" data-a="closemsg">✕</button></div>` : ""}
        <div class="pv-sheet" tabindex="0" data-focus="sheet">${sheetHtml(S)}${placeholder(S)}</div>
        ${busy ? '<div class="pv-busy"><span>Calculating…</span></div>' : ""}
        ${!ui.__hidePane && S.paneHidden ? '<button class="btn pv-showpane" data-a="showpane">Show Field List</button>' : ""}
      </div>
      ${S.paneHidden ? "" : pane(S)}
    </div>
    <div class="pv-sheettabs"><span>PivotTable</span><i>${d.feed === "vfl" ? "VFL feed · one row per bill line" : "Portfolio feed · one row per store per day"}</i></div>
    ${statusBar(S)}
    ${S.menu ? menuHtml(S) : ""}
    ${S.dlg ? dialogHtml(S) : ""}
    ${S.toast ? `<div class="toast">${S.toast}</div>` : ""}
  </div>`;
  const sh = host.querySelector(".pv-sheet");
  if (sh) { sh.scrollTop = S.scroll[0]; sh.scrollLeft = S.scroll[1]; }
  const fl = host.querySelector(".pv-fields");
  if (fl) fl.scrollTop = S.fscroll;
  if (focusId) {
    const el = host.querySelector(`[data-focus="${focusId}"]`);
    if (el) { el.focus({ preventScroll: true }); if (caret !== null && el.setSelectionRange) try { el.setSelectionRange(caret, caret); } catch (e) { /* not a text box */ } }
  }
  positionMenu(S);
}

// ---------------------------------------------------------------- ribbon
function ribbon(S) {
  const d = S.data, ui = S.ui, t = S.tab;
  const tabs = `<div class="pv-tabs"><span class="file">Excel Builder</span>
    <button class="pv-tab ${t === "analyze" ? "on" : ""}" data-a="tab" data-v="analyze"><span class="ctx">PivotTable Tools</span>PivotTable Analyze</button>
    <button class="pv-tab ${t === "design" ? "on" : ""}" data-a="tab" data-v="design"><span class="ctx">&nbsp;</span>Design</button>
    <span class="spacer"></span><span class="hint">Data ${esc(d.dmin)} to ${esc(d.dmax)} · drag fields in the pane, right-click the table for more</span></div>`;
  let body = "";
  if (t === "analyze") {
    const af = activeField(S);
    const cur = curCell(S);
    body = `
      <div class="rg"><div class="rb"><button class="big" data-a="menu" data-v="presets"><span class="ic">${IC.pivot}</span><span class="dd">Recommended<br>PivotTables</span></button></div><div class="rl">PivotTable</div></div>
      <div class="rg"><div class="rb"><div class="stack">
          <select class="rsel" data-a="period">${d.periods.map((p) => `<option ${p === ui.period ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
          ${ui.period === "Custom" ? `<div style="display:flex;gap:4px;align-items:center"><input type="date" class="rdate" data-a="from" min="${d.dmin}" max="${d.dmax}" value="${esc(ui.from || "")}">–<input type="date" class="rdate" data-a="to" min="${d.dmin}" max="${d.dmax}" value="${esc(ui.to || "")}"></div>` : ""}
          <span style="font-size:11px;color:#666;max-width:240px;white-space:normal">${esc(d.period_dates)}</span>
        </div></div><div class="rl">Dates</div></div>
      <div class="rg"><div class="rb"><div class="stack">
          <span style="font-size:11px;color:#555">Active Field:</span><span class="af">${esc(af ? fname(S, af) : cur && cur.vi !== undefined ? vnames(S)[cur.vi] : "—")}</span>
          <div style="display:flex;gap:2px"><button class="sm" data-a="expfield" ${af ? "" : "disabled"}>${IC.expand}Expand Field</button><button class="sm" data-a="colfield" ${af ? "" : "disabled"}>${IC.collapse}Collapse Field</button></div>
          <button class="sm" data-a="vfs" data-v="${cur && cur.vi !== undefined ? cur.vi : ""}" ${cur && cur.vi !== undefined ? "" : "disabled"}>Σ Value Field Settings…</button>
        </div></div><div class="rl">Active Field</div></div>
      <div class="rg"><div class="rb"><div class="stack">
          <button class="sm" data-a="sortlab" data-v="asc">${IC.az}Sort A to Z</button>
          <button class="sm" data-a="sortlab" data-v="desc">${IC.za}Sort Z to A</button>
          <button class="sm" data-a="clearall" ${Object.values(ui.sel || {}).some((s) => s.items && s.items.length) ? "" : "disabled"}>${IC.clear}Clear Filters</button>
        </div></div><div class="rl">Sort &amp; Filter</div></div>
      <div class="rg"><div class="rb"><button class="big" data-a="refresh"><span class="ic">${IC.refresh}</span><span>Refresh</span></button></div><div class="rl">Data</div></div>
      <div class="rg"><div class="rb"><div class="stack">
          <label class="chk"><input type="checkbox" data-a="togglepane" ${S.paneHidden ? "" : "checked"}>Field List</label>
          <label class="chk"><input type="checkbox" data-a="opt" data-v="buttons" ${ui.buttons ? "checked" : ""}>+/- Buttons</label>
          <label class="chk"><input type="checkbox" data-a="opt" data-v="field_headers" ${ui.field_headers ? "checked" : ""}>Field Headers</label>
        </div></div><div class="rl">Show</div></div>
      <div class="rg"><div class="rb"><button class="big" data-a="export"><span class="ic">${IC.excel}</span><span>Export to<br>Excel</span></button>
          <div class="stack" style="padding-top:6px"><label class="chk"><input type="checkbox" data-a="withsrc" ${S.withSource ? "checked" : ""}>with the source rows</label>
          <button class="sm" data-a="savelayout">Save this layout…</button></div></div><div class="rl">Export</div></div>`;
  } else {
    const styles = [["light16", "#ddebf7", "#eef5fb", "Light 16"], ["light9", "#ffffff", "#f2f2f2", "Light 9"], ["medium2", "#4472c4", "#d9e1f2", "Medium 2"], ["peanuts", "#7a1f2b", "#f6efe4", "Peanuts"]];
    body = `
      <div class="rg"><div class="rb">
        <button class="big" data-a="menu" data-v="subtotals"><span class="ic">${IC.sub}</span><span class="dd">Subtotals</span></button>
        <button class="big" data-a="menu" data-v="grand"><span class="ic">${IC.grand}</span><span class="dd">Grand<br>Totals</span></button>
        <button class="big" data-a="menu" data-v="layout"><span class="ic">${IC.layout}</span><span class="dd">Report<br>Layout</span></button>
        <button class="big" data-a="menu" data-v="blank"><span class="ic">${IC.blank}</span><span class="dd">Blank<br>Rows</span></button>
      </div><div class="rl">Layout</div></div>
      <div class="rg"><div class="rb"><div class="two" style="display:grid;grid-template-columns:1fr 1fr;gap:0 10px">
          <label class="chk"><input type="checkbox" data-a="opt" data-v="row_headers" ${ui.row_headers ? "checked" : ""}>Row Headers</label>
          <label class="chk"><input type="checkbox" data-a="opt" data-v="banded_rows" ${ui.banded_rows ? "checked" : ""}>Banded Rows</label>
          <label class="chk"><input type="checkbox" data-a="opt" data-v="col_headers" ${ui.col_headers ? "checked" : ""}>Column Headers</label>
          <label class="chk"><input type="checkbox" data-a="opt" data-v="banded_cols" ${ui.banded_cols ? "checked" : ""}>Banded Columns</label>
        </div></div><div class="rl">PivotTable Style Options</div></div>
      <div class="rg"><div class="rb"><div class="swatches">${styles.map(([k, h, b, n]) => `<div class="sw ${ui.style === k ? "on" : ""}" title="${n}" data-a="style" data-v="${k}"><i style="background:${h}"></i><i style="background:#fff;border-bottom:1px solid #ddd"></i><i style="background:${b}"></i><i style="background:#fff;border-bottom:1px solid #ddd"></i><i style="background:${h}"></i></div>`).join("")}</div></div><div class="rl">PivotTable Styles</div></div>`;
  }
  return tabs + `<div class="pv-ribbon">${body}</div>`;
}

function formulaBar(S) {
  const c = curCell(S);
  let nb = "", fv = "";
  if (c) {
    nb = LETTERS(c.c) + (c.r + 1);
    if (c.cell) fv = c.cell.v !== undefined ? (c.cell.v === null ? "" : String(Math.round(c.cell.v * 100) / 100)) : (c.cell.t || "");
  }
  return `<div class="pv-fx"><input class="nb" value="${esc(nb)}" readonly><span class="fxi">fx</span><div class="fv">${esc(fv)}</div></div>`;
}

// ---------------------------------------------------------------- the sheet
function sheetHtml(S) {
  const m = S.m, ui = S.ui;
  const extraC = 4, rowsShown = Math.min(m.rows.length, m.pivotTop + m.head + MAX_ROWS + 2);
  const ncol = Math.max(m.ncol, 2) + extraC;
  const extraR = Math.max(6, 30 - rowsShown);
  // column widths: fitted to what they hold, as Excel's "AutoFit on update"
  const W = Array.from({ length: ncol }, () => 64);
  m.rows.slice(0, rowsShown).forEach((r) => r.cells.forEach((c, j) => {
    const txt = c.v !== undefined ? fmtVal(c.v, c.k, c.nf) : (c.t || "");
    const px = txt.length * (c.b || r.type === "head" ? 8.1 : 7.6) + (c.i ? c.i * 14 : 0) + (c.tg ? 18 : 0) + (c.fb ? 22 : 0) + 16;
    if (r.type === "pf" && j === 0) { W[j] = Math.max(W[j], Math.min(px, 220)); return; }
    W[j] = Math.max(W[j], Math.min(px, j < m.L ? 330 : 240));
  }));
  S.colW = W;
  const sel = selRange(S);
  const cur = S.cur;
  const tw = 44 + W.reduce((x, y) => x + Math.round(y), 0);     // fixed layout needs the real width, or columns shrink
  let h = `<table class="xl ps-${ui.style}${ui.col_headers ? "" : " nohead"}" style="width:${tw}px"><colgroup><col style="width:44px">${W.map((w) => `<col style="width:${Math.round(w)}px">`).join("")}</colgroup>`;
  h += `<thead><tr><th class="rn corner"></th>${W.map((_, j) => `<th class="${sel && j >= sel.c0 && j <= sel.c1 ? "on" : ""}">${LETTERS(j)}</th>`).join("")}</tr></thead><tbody>`;
  for (let r = 0; r < rowsShown + extraR; r++) {
    const row = m.rows[r];
    const inSelR = sel && r >= sel.r0 && r <= sel.r1;
    h += `<tr><th class="rn ${inSelR ? "on" : ""}">${r + 1}</th>`;
    for (let c = 0; c < ncol; c++) {
      const cell = row && row.cells[c];
      const cls = [];
      const inPivot = row && (row.type === "head" || row.type === "body") && c < m.ncol;
      if (cell && cell.cls) cls.push(cell.cls);
      if (inPivot && row.type === "body") {
        if (row.kind === "grand") cls.push("pt");
        else if ((row.kind === "group" || row.kind === "subtotal") && ui.row_headers) cls.push("pg");
        if (ui.banded_rows && row.kind === "item" && row.band % 2) cls.push("pb");
        if (ui.banded_cols && c >= m.L && ((c - m.L) % 2)) cls.push("pb");
        if (!ui.row_headers) { const i = cls.indexOf("pg"); if (i >= 0) cls.splice(i, 1); }
      }
      if (inPivot && row.type === "head") cls.push("ph");
      if (sel && r >= sel.r0 && r <= sel.r1 && c >= sel.c0 && c <= sel.c1) cls.push("sel");
      if (cur && cur.r === r && cur.c === c) cls.push("cur");
      let inner = "";
      if (cell) {
        if (cell.v !== undefined) {
          const txt = fmtVal(cell.v, cell.k, cell.nf);
          cls.push("n");
          if (cell.v !== null && String(cell.k).endsWith("chg") && cell.v < 0) cls.push("neg");
          inner = esc(txt);
        } else {
          const pad = cell.i ? `<span style="display:inline-block;width:${cell.i * 14}px"></span>` : "";
          const tg = cell.tg ? `<span class="tg" data-a="toggle" data-k="${esc(cell.key)}">${cell.tg === "+" ? "+" : "−"}</span>` : "";
          const fb = cell.fb ? `<span class="fb ${cell.ff ? "f" : ""}" data-a="fmenu" data-v="${esc(cell.fb)}">${cell.ff ? "⏷" : "▼"}</span>` : "";
          if (cell.al === "right") cls.push("n");
          inner = fb + pad + tg + esc(cell.t || "");
        }
      }
      const tip = cell && cell.v === undefined && cell.t && cell.t.length > 14 ? ` title="${esc(cell.t)}"` : "";
      h += `<td class="${cls.join(" ")}" data-r="${r}" data-c="${c}"${tip}>${inner}</td>`;
    }
    h += "</tr>";
  }
  h += "</tbody></table>";
  if (m.rows.length > rowsShown) h += `<div style="padding:8px 52px;color:#666;font-size:12px">Showing the first ${MAX_ROWS.toLocaleString()} rows of ${(m.rows.length - m.pivotTop - m.head).toLocaleString()}. Export to Excel for all of them, or add a filter.</div>`;
  return h;
}

function placeholder(S) {
  const d = S.data;
  if (d.grid) return "";
  if (d.error && S.ui.values.length) return `<div class="pv-ph err"><b>This PivotTable can't be drawn</b><div style="margin-top:6px">${esc(d.error)}</div></div>`;
  return `<div class="pv-ph">${IC.pivot}<div style="margin-top:8px"><b>PivotTable</b></div><div style="margin-top:6px">To build a report, choose fields from the PivotTable Field List.</div></div>`;
}

function statusBar(S) {
  const sel = selRange(S);
  let right = "";
  if (sel && S.m) {
    let n = 0, sum = 0, cnt = 0;
    for (let r = sel.r0; r <= sel.r1; r++) {
      const row = S.m.rows[r]; if (!row) continue;
      for (let c = sel.c0; c <= sel.c1; c++) {
        const cell = row.cells[c]; if (!cell) continue;
        if (cell.v !== undefined) { if (cell.v !== null) { n++; sum += cell.v; cnt++; } }
        else if (cell.t) cnt++;
      }
    }
    if (cnt > 1) {
      const k = S.cur && S.m.rows[S.cur.r] && S.m.rows[S.cur.r].cells[S.cur.c];
      const f = (x) => (k && k.v !== undefined ? fmtVal(x, k.k, k.nf) : indian(x, 0));
      right = n ? `<span>Average: ${f(sum / n)}</span><span>Count: ${cnt}</span><span>Sum: ${f(sum)}</span>` : `<span>Count: ${cnt}</span>`;
    }
  }
  const g = S.data.grid;
  const left = S.pending !== null ? "Calculating…" : S.dirty ? "Layout changed — press Update in the field list" : "Ready";
  const info = g ? `<span style="color:#666">${esc(g.span)} · ${g.rows_used.toLocaleString("en-IN")} source rows${g.applied && g.applied.length ? " · " + esc(g.applied.join(" · ")) : ""}</span>` : "";
  return `<div class="pv-status"><span>${left}</span>${info}<span class="r">${right}</span></div>`;
}

// ---------------------------------------------------------------- the PivotTable Fields pane
function pane(S) {
  const d = S.data, ui = S.ui, q = S.search.trim().toLowerCase();
  const used = new Set([...ui.rows, ...ui.cols, ...(ui.filters_area || [])]);
  const inVals = new Set(ui.values.map((v) => v.m));
  const groups = [];
  const byGroup = {};
  d.fields.forEach((f) => { (byGroup[f.group] ||= []).push(f.name); });
  for (const [gname, fl] of Object.entries(byGroup)) groups.push([gname, fl.map((n) => ({ n, mea: false }))]);
  groups.push(["Σ Measures", d.measures.map((m) => ({ n: m.name, mea: true }))]);
  let list = "";
  for (const [gname, fl] of groups) {
    const hits = fl.filter((f) => !q || f.n.toLowerCase().includes(q));
    if (!hits.length) continue;
    const shut = S.shut.has(gname) && !q;
    list += `<div class="fgrp ${shut ? "shut" : ""}" data-a="fold" data-v="${esc(gname)}">${esc(gname)}</div>`;
    if (shut) continue;
    for (const f of hits) {
      const on = f.mea ? inVals.has(f.n) : used.has(f.n);
      list += `<div class="fld" draggable="true" data-drag="field" data-f="${esc(f.n)}" data-mea="${f.mea ? 1 : 0}">
        <input type="checkbox" data-a="tick" data-f="${esc(f.n)}" data-mea="${f.mea ? 1 : 0}" ${on ? "checked" : ""}>
        <span class="${on ? "on" : ""}">${esc(f.n)}</span>${!f.mea && isFiltered(S, f.n) ? `<span class="ic f" title="Filtered">${IC.filter}</span>` : ""}</div>`;
    }
  }
  const chips = (area) => {
    let arr;
    if (area === "values") arr = ui.values.map((v, i) => ({ t: vnames(S)[i], i }));
    else arr = (area === "filters" ? ui.filters_area || [] : ui[area]).map((f, i) => ({ t: fname(S, f), i, f }));
    let h = arr.map((c) => `<div class="chip" draggable="true" data-drag="chip" data-area="${area}" data-i="${c.i}">${c.f && isFiltered(S, c.f) ? '<span class="flt">⏷</span>' : ""}<span class="nm" title="${esc(c.t)}">${esc(c.t)}</span><button class="dd" data-a="chipmenu" data-area="${area}" data-i="${c.i}">▼</button></div>`).join("");
    if (area === "cols" && ui.values.length > 1) h += `<div class="chip fixed" title="Excel's Σ Values field: the values sit side by side across the columns"><span class="nm">Σ Values</span></div>`;
    return h;
  };
  const area = (k, label, icon) => `<div class="area"><div class="ah">${icon}${label}</div><div class="ab" data-drop="${k}">${chips(k)}</div></div>`;
  return `<div class="pv-pane">
    <div class="ttl"><h3>PivotTable Fields</h3><button data-a="hidepane" title="Close">✕</button></div>
    <div class="sub"><span>Choose fields to add to report:</span></div>
    <div class="srch">${IC.search}<input data-a="search" data-focus="fsearch" placeholder="Search" value="${esc(S.search)}"></div>
    <div class="pv-fields" data-drop="list">${list || '<div style="padding:8px;color:#777;font-size:12px">No field matches.</div>'}</div>
    <div class="lbl2">Drag fields between areas below:</div>
    <div class="areas">
      ${area("filters", "FILTERS", IC.filter)}${area("cols", "COLUMNS", IC.cols)}
      ${area("rows", "ROWS", IC.rows)}${area("values", "Σ VALUES", IC.sigma)}
    </div>
    <div class="foot"><label class="chk"><input type="checkbox" data-a="defer" ${S.defer ? "checked" : ""}>Defer Layout Update</label><button class="btn ${S.dirty ? "pri" : ""}" data-a="update" ${S.defer ? "" : "disabled"}>Update</button></div>
  </div>`;
}

// ---------------------------------------------------------------- selection
function selRange(S) {
  if (!S.cur) return null;
  const a = S.anchor || S.cur;
  return { r0: Math.min(a.r, S.cur.r), r1: Math.max(a.r, S.cur.r), c0: Math.min(a.c, S.cur.c), c1: Math.max(a.c, S.cur.c) };
}
function curCell(S) {
  if (!S.cur || !S.m) return null;
  const row = S.m.rows[S.cur.r];
  const cell = row && row.cells[S.cur.c];
  return { ...S.cur, cell, row, vi: cell && cell.vi };
}
function activeField(S) {
  const c = curCell(S);
  if (!c || !c.cell || c.cell.v !== undefined) return null;
  if (c.cell.f) return c.cell.f;
  return null;
}

// ---------------------------------------------------------------- menus
function menuHtml(S) {
  const M = S.menu, ui = S.ui, d = S.data;
  const it = (a, label, opts = {}) => `<div class="mi ${opts.dis ? "dis" : ""} ${opts.tick ? "tick" : ""}" ${opts.dis ? "" : `data-a="${a}"`} ${opts.v !== undefined ? `data-v="${esc(opts.v)}"` : ""} ${opts.i !== undefined ? `data-i="${opts.i}"` : ""} ${opts.area ? `data-area="${opts.area}"` : ""}><span class="k">${opts.k || ""}</span>${label}</div>`;
  const sep = '<div class="sep"></div>';
  let h = "";
  if (M.type === "presets") {
    h = `<div class="hd">Recommended PivotTables</div>` + Object.keys(d.presets).map((n) => it("preset", esc(n), { v: n, k: "▦" })).join("");
    const sv = Object.keys(d.saved || {});
    if (sv.length) h += sep + `<div class="hd">My layouts (this session)</div>` + sv.map((n) => it("saved", esc(n), { v: n, k: "★" })).join("");
    h += sep + it("blankpivot", "Blank PivotTable", { k: "☐" });
  } else if (M.type === "subtotals") {
    h = it("set", "Do Not Show Subtotals", { v: "subtotals=off", tick: ui.subtotals === "off" })
      + it("set", "Show all Subtotals at Bottom of Group", { v: "subtotals=bottom", tick: ui.subtotals === "bottom" })
      + it("set", "Show all Subtotals at Top of Group", { v: "subtotals=top", tick: ui.subtotals === "top", dis: ui.layout === "tabular" });
  } else if (M.type === "grand") {
    const gr = ui.grand_rows, gc = ui.grand_cols;
    h = it("set", "Off for Rows and Columns", { v: "grand=00", tick: !gr && !gc }) + it("set", "On for Rows and Columns", { v: "grand=11", tick: gr && gc })
      + it("set", "On for Rows Only", { v: "grand=01", tick: !gr && gc }) + it("set", "On for Columns Only", { v: "grand=10", tick: gr && !gc })
      + `<div class="hd" style="font-weight:400;max-width:250px;white-space:normal">Rows Only = a Grand Total column at the right of each row; Columns Only = a Grand Total row under each column.</div>`;
  } else if (M.type === "layout") {
    h = it("set", "Show in Compact Form", { v: "layout=compact", tick: ui.layout === "compact" }) + it("set", "Show in Outline Form", { v: "layout=outline", tick: ui.layout === "outline" })
      + it("set", "Show in Tabular Form", { v: "layout=tabular", tick: ui.layout === "tabular" }) + sep
      + it("set", "Repeat All Item Labels", { v: "repeat=1", tick: ui.repeat, dis: ui.layout === "compact" }) + it("set", "Do Not Repeat Item Labels", { v: "repeat=0", tick: !ui.repeat, dis: ui.layout === "compact" });
  } else if (M.type === "blank") {
    h = it("set", "Insert Blank Line after Each Item", { v: "blank=1", tick: ui.blank }) + it("set", "Remove Blank Line after Each Item", { v: "blank=0", tick: !ui.blank });
  } else if (M.type === "chip") {
    const area = M.area, i = M.i, arr = area === "values" ? ui.values : area === "filters" ? ui.filters_area : ui[area];
    const n = arr.length, isV = area === "values";
    h = it("move", "Move Up", { v: "up", dis: i === 0, area, i }) + it("move", "Move Down", { v: "down", dis: i === n - 1, area, i })
      + it("move", "Move to Beginning", { v: "first", dis: i === 0, area, i }) + it("move", "Move to End", { v: "last", dis: i === n - 1, area, i }) + sep
      + it("moveto", "Move to Report Filter", { v: "filters", dis: isV || area === "filters", area, i, k: IC.filter.replace("<svg", '<svg width="12" height="12"') })
      + it("moveto", "Move to Row Labels", { v: "rows", dis: isV || area === "rows", area, i, k: IC.rows.replace("<svg", '<svg width="12" height="12"') })
      + it("moveto", "Move to Column Labels", { v: "cols", dis: isV || area === "cols", area, i, k: IC.cols.replace("<svg", '<svg width="12" height="12"') })
      + it("moveto", "Move to Values", { v: "values", dis: true, area, i, k: "Σ" }) + sep
      + it("remove", "Remove Field", { area, i, k: "✕" }) + sep
      + (isV ? it("vfs", "Value Field Settings…", { v: i, k: "⚙" }) : it("fs", "Field Settings…", { v: arr[i], k: "⚙" }));
  } else if (M.type === "ctx") {
    const c = M.cell;
    if (c && c.v !== undefined) {
      const v = ui.values[c.vi], meta = meas(S)[v.m];
      h = it("copy", "Copy", { k: "⧉" }) + sep + it("fmt", "Number Format…", { v: c.vi }) + it("refresh", "Refresh", { k: "⟳" }) + sep
        + `<div class="hd">Show Values As</div>` + meta.show.map((s) => it("showas", esc(SHOWX(S, s)), { v: c.vi + "|" + s, tick: v.how === s })).join("") + sep
        + it("vfs", "Value Field Settings…", { v: c.vi, k: "⚙" }) + it("removev", `Remove "${esc(vnames(S)[c.vi])}"`, { v: c.vi, k: "✕" });
    } else if (c && c.f) {
      h = it("copy", "Copy", { k: "⧉" }) + sep + it("sortlab", "Sort A to Z", { v: "asc", k: "↑" }) + it("sortlab", "Sort Z to A", { v: "desc", k: "↓" }) + sep
        + (c.key !== undefined && c.tg ? it("toggle1", S.collapsed.has(c.key) ? "Expand" : "Collapse", { v: c.key, k: S.collapsed.has(c.key) ? "+" : "−" }) : "")
        + it("expfield", "Expand Entire Field", { v: c.f, k: "⊞" }) + it("colfield", "Collapse Entire Field", { v: c.f, k: "⊟" }) + sep
        + it("fmenu2", `Filter "${esc(fname(S, c.f))}"…`, { v: "row:" + c.f, k: "⏷" }) + it("fs", "Field Settings…", { v: c.f, k: "⚙" })
        + it("removef", `Remove "${esc(fname(S, c.f))}"`, { v: c.f, k: "✕" });
    } else {
      h = it("copy", "Copy", { k: "⧉" }) + it("refresh", "Refresh", { k: "⟳" }) + sep + it(S.paneHidden ? "showpane" : "hidepane", S.paneHidden ? "Show Field List" : "Hide Field List", { k: "☰" });
    }
  } else if (M.type === "filter") {
    return filterMenu(S);
  }
  return `<div class="menu" style="left:${M.x}px;top:${M.y}px" data-menu="1">${h}</div>`;
}

function filterFields(S, which) {
  const ui = S.ui;
  if (which === "rows") return ui.rows;
  if (which === "cols") return ui.cols;
  if (which.startsWith("row:")) return [which.slice(4)];
  if (which.startsWith("pf:")) return [which.slice(3)];
  return [];
}
function filterMenu(S) {
  const M = S.menu, ui = S.ui, d = S.data;
  const fields = filterFields(S, M.which);
  const f = M.field && fields.includes(M.field) ? M.field : fields[0];
  M.field = f;
  const info = (d.items && d.items[f]) || { items: [], more: 0 };
  const q = (M.q || "").toLowerCase();
  if (!M.work || M.workField !== f) {          // the tick-list being edited, before OK
    const s = (ui.sel || {})[f];
    const all = new Set(info.items);
    let on;
    if (!s || !s.items || !s.items.length) on = new Set(all);
    else if (s.mode === "include") on = new Set(s.items.filter((x) => all.has(x)));
    else { on = new Set(all); s.items.forEach((x) => on.delete(x)); }
    M.work = on; M.workField = f;
  }
  const items = info.items.filter((x) => !q || x.toLowerCase().includes(q));
  const allOn = info.items.length && info.items.every((x) => M.work.has(x));
  const isRowLike = !M.which.startsWith("pf:") && ui.rows.includes(f);
  const mv = Object.keys(meas(S));
  const sortRow = isRowLike ? `
      <div class="mi" data-a="sortlab" data-v="asc"><span class="k">${IC.az}</span>Sort A to Z</div>
      <div class="mi" data-a="sortlab" data-v="desc"><span class="k">${IC.za}</span>Sort Z to A</div>
      <div class="row"><span style="font-size:12px;white-space:nowrap">Sort by value:</span><select data-a="sortval"><option value="">—</option>${[...new Set(ui.values.map((v) => v.m))].map((m) => `<option value="${esc(m)}|1" ${ui.sort.by === m && ui.sort.desc ? "selected" : ""}>${esc(m)} · largest first</option><option value="${esc(m)}|0" ${ui.sort.by === m && !ui.sort.desc ? "selected" : ""}>${esc(m)} · smallest first</option>`).join("")}</select></div>
      <div class="sep"></div>
      <div class="row"><span style="font-size:12px;white-space:nowrap">Top</span><input type="number" min="0" max="500" value="${ui.top || 0}" data-a="topn" style="width:60px;flex:none"><span style="font-size:11px;color:#666">items by ${esc(ui.sort.by !== "label" && mv.includes(ui.sort.by) ? ui.sort.by : (ui.values[0] || {}).m || "value")} (0 = all; innermost row field)</span></div>
      <div class="sep"></div>` : "";
  const picker = fields.length > 1 ? `<div class="row"><span style="font-size:12px">Select field:</span><select data-a="ffield">${fields.map((x) => `<option ${x === f ? "selected" : ""} value="${esc(x)}">${esc(fname(S, x))}</option>`).join("")}</select></div>` : "";
  return `<div class="menu fmenu" style="left:${M.x}px;top:${M.y}px" data-menu="1">
    ${picker}${sortRow}
    <div class="mi ${isFiltered(S, f) ? "" : "dis"}" ${isFiltered(S, f) ? 'data-a="clearf"' : ""} data-v="${esc(f)}"><span class="k">${IC.clear}</span>Clear Filter From "${esc(fname(S, f))}"</div>
    <div class="srch2">${IC.search}<input data-a="fq" data-focus="fq" placeholder="Search" value="${esc(M.q || "")}"></div>
    <div class="items">
      <label><input type="checkbox" data-a="fall" ${allOn ? "checked" : ""}>(Select All${q ? " Search Results" : ""})</label>
      ${items.map((x) => `<label><input type="checkbox" data-a="fitem" data-v="${esc(x)}" ${M.work.has(x) ? "checked" : ""}>${esc(x)}</label>`).join("")}
    </div>
    ${info.more ? `<div class="more">+ ${info.more.toLocaleString()} more — search to find them</div>` : ""}
    <div class="ok"><button class="btn pri" data-a="fok">OK</button><button class="btn" data-a="fcancel">Cancel</button></div>
  </div>`;
}

function positionMenu(S) {
  const el = S.host.querySelector("[data-menu]");
  if (!el) return;
  const app = S.host.querySelector(".pv-app").getBoundingClientRect(), r = el.getBoundingClientRect();
  let x = S.menu.x, y = S.menu.y;
  if (r.right > app.right - 4) x = Math.max(4, x - (r.right - app.right) - 8);
  if (r.bottom > app.bottom - 4) y = Math.max(4, y - (r.bottom - app.bottom) - 8);
  el.style.left = x + "px"; el.style.top = y + "px";
}

// ---------------------------------------------------------------- dialogs
const CATS = [["auto", "General (dashboard)"], ["indian", "Number · 12,34,567"], ["number", "Number · 1,234,567"], ["currency", "Currency · ₹"], ["lakh", "Lakhs · 12.35 L"], ["crore", "Crores · 1.23 Cr"], ["percent", "Percentage"]];
function dialogHtml(S) {
  const D = S.dlg;
  let title = "", body = "", foot = "";
  if (D.type === "vfs") {
    const v = S.ui.values[D.i], meta = meas(S)[v.m];
    title = "Value Field Settings";
    const sumList = meta.additive
      ? ["Sum", "Count", "Average", "Max", "Min", "Product"].map((x) => `<div class="${x === "Sum" ? "on" : "dis"}">${x}</div>`).join("")
      : `<div class="on">${esc(v.m)} (calculated)</div>`;
    const needsBase = ["Change vs previous column", "% change vs previous column", "Running total across"].includes(D.how);
    body = `<div class="fr"><label>Source Name:</label><span>${esc(v.m)}</span></div>
      <div class="fr"><label>Custom Name:</label><input type="text" data-a="dname" data-focus="dname" value="${esc(D.name)}"></div>
      <div class="dtabs"><button class="${D.tab === "sum" ? "on" : ""}" data-a="dtab" data-v="sum">Summarize Values By</button><button class="${D.tab === "show" ? "on" : ""}" data-a="dtab" data-v="show">Show Values As</button></div>`;
    if (D.tab === "sum") {
      body += `<div style="font-size:12px;margin-bottom:4px">Summarize value field by</div><div class="lst">${sumList}</div>
        <div class="note">${meta.additive ? "This measure is a total, so it adds up (Sum). Count, Average and the rest would break the dashboard's tie to its own reports, so they are not offered."
          : `This measure is a ratio, worked out afresh at every row and total from its parts (${esc(meta.parts.join(" ÷ "))}) — never an average of the rows above it.`}</div>`;
    } else {
      body += `<div class="fr"><label>Show values as</label><select data-a="dhow">${meta.show.map((s) => `<option value="${esc(s)}" ${s === D.how ? "selected" : ""}>${esc(SHOWX(S, s))}</option>`).join("")}</select></div>
        <div class="two" style="${needsBase ? "" : "opacity:.45"}"><div><div style="font-size:12px;margin-bottom:3px">Base field:</div><div class="lst" style="height:90px">${(S.ui.cols.length ? S.ui.cols : ["(needs a field in Columns)"]).map((c, i) => `<div class="${needsBase && i === S.ui.cols.length - 1 ? "on" : "dis"}">${esc(fname(S, c))}</div>`).join("")}</div></div>
        <div><div style="font-size:12px;margin-bottom:3px">Base item:</div><div class="lst" style="height:90px"><div class="${needsBase ? "on" : "dis"}">(previous)</div></div></div></div>
        <div class="note">${needsBase ? "Compared with the previous item of the innermost column field — month on month, or this year against last when Financial Year is in Columns." + (S.ui.cols.length ? "" : " <b>Put a field in Columns first</b>, or these read blank.") : "Shares are worked out from the same rows as the values, so every row and column adds up to 100%."}</div>`;
    }
    foot = `<button class="btn" data-a="dnumfmt">Number Format</button><span class="gap"></span><button class="btn pri" data-a="dok">OK</button><button class="btn" data-a="dcancel">Cancel</button>`;
  } else if (D.type === "fmt") {
    title = "Format Cells";
    const sample = fmtVal(D.sample, D.kind, { cat: D.cat, dec: D.dec });
    body = `<div class="two"><div><div style="font-size:12px;margin-bottom:3px">Category:</div><div class="lst cats">${CATS.map(([k, n]) => `<div class="${D.cat === k ? "on" : ""}" data-a="dcat" data-v="${k}">${esc(n)}</div>`).join("")}</div></div>
      <div><div style="font-size:12px;margin-bottom:3px">Sample</div><div class="sample">${esc(sample || "—")}</div>
      ${D.cat !== "auto" ? `<div class="fr" style="margin-top:10px"><label style="width:auto">Decimal places:</label><input type="number" min="0" max="4" value="${D.dec}" data-a="ddec" style="width:60px"></div>` : `<div class="note">The dashboard's own format for this measure: Indian grouping for rupees and counts, two decimals for ratios, one for percentages.</div>`}</div></div>`;
    foot = `<span class="gap"></span><button class="btn pri" data-a="fmtok">OK</button><button class="btn" data-a="fmtcancel">Cancel</button>`;
  } else if (D.type === "fs") {
    title = "Field Settings";
    body = `<div class="fr"><label>Source Name:</label><span>${esc(D.f)}</span></div><div class="fr"><label>Custom Name:</label><input type="text" data-a="dname" data-focus="dname" value="${esc(D.name)}"></div>
      <div class="note">The custom name is what the table's headers and the field list's chips show. Subtotals and layout for every field are set on the Design tab.</div>`;
    foot = `<span class="gap"></span><button class="btn pri" data-a="fsok">OK</button><button class="btn" data-a="dcancel">Cancel</button>`;
  } else if (D.type === "save") {
    title = "Save this layout";
    body = `<div class="fr"><label>Name:</label><input type="text" data-a="dname" data-focus="dname" placeholder="e.g. Monday review" value="${esc(D.name)}"></div>
      <div class="note">Kept for this session under Recommended PivotTables → My layouts. To keep a table for good, bookmark the page: the address bar always holds the exact table on screen.</div>`;
    foot = `<span class="gap"></span><button class="btn pri" data-a="saveok" ${D.name ? "" : "disabled"}>Save</button><button class="btn" data-a="dcancel">Cancel</button>`;
  }
  return `<div class="modal" data-a="modalbg"><div class="dlg" data-dlg="1"><div class="dh">${esc(title)}<button data-a="dcancel">✕</button></div><div class="db">${body}</div><div class="df">${foot}</div></div></div>`;
}

// ---------------------------------------------------------------- layout edits (what Excel's pane does)
function arr(S, area) { return area === "values" ? S.ui.values : area === "filters" ? (S.ui.filters_area ||= []) : S.ui[area]; }
function removeEverywhere(S, f) {
  for (const a of ["rows", "cols", "filters"]) { const x = arr(S, a), i = x.indexOf(f); if (i >= 0) x.splice(i, 1); }
}
function dropSel(S, f) { if (S.ui.sel && S.ui.sel[f]) delete S.ui.sel[f]; }
function newValue(m) { return { m, how: "Value", name: "", fmt: { cat: "auto", dec: 0 } }; }
function fixSort(S) {
  if (S.ui.sort.by !== "label" && !S.ui.values.some((v) => v.m === S.ui.sort.by)) S.ui.sort = { by: "label", desc: false };
}
function placeField(S, f, mea, area, idx) {
  if (mea) {
    if (area !== "values") { toast(S, "Measures go in <b>Σ VALUES</b>. Drag a field from the other groups to Filters, Columns or Rows."); return false; }
    const x = S.ui.values; x.splice(idx === undefined ? x.length : idx, 0, newValue(f)); return true;
  }
  if (area === "values") { toast(S, "Only Σ Measures can go in Values here — each one is the dashboard's own definition, so it ties to every report."); return false; }
  removeEverywhere(S, f);
  const x = arr(S, area); x.splice(idx === undefined ? x.length : Math.min(idx, x.length), 0, f);
  return true;
}
function moveChip(S, from, i, to, idx) {
  if (from === "values" || to === "values") {
    if (from !== to) { toast(S, "Values stay in Σ VALUES; dimensions stay out of it."); return false; }
    const x = S.ui.values, [v] = x.splice(i, 1); x.splice(idx > i ? idx - 1 : idx, 0, v); return true;
  }
  const src = arr(S, from), f = src[i];
  src.splice(i, 1);
  const dst = arr(S, to);
  let j = idx; if (from === to && idx > i) j -= 1;
  dst.splice(Math.min(j, dst.length), 0, f);
  return true;
}

// ---------------------------------------------------------------- events
function wire(host) {
  const S_ = () => host.__S;
  const closest = (e, sel) => (e.target.closest ? e.target.closest(sel) : null);

  host.addEventListener("mousedown", (e) => {
    const S = S_();
    const td = closest(e, "td[data-r]");
    if (td && !closest(e, "[data-a]") && e.button === 0) {
      const r = +td.dataset.r, c = +td.dataset.c;
      if (e.shiftKey && S.cur) S.cur = { r, c };
      else { S.cur = { r, c }; S.anchor = { r, c }; }
      S.dragSel = true;
      if (S.menu) S.menu = null;
      render(S);
      host.querySelector(".pv-sheet").focus({ preventScroll: true });
    }
  });
  host.addEventListener("mouseover", (e) => {
    const S = S_();
    if (!S.dragSel || !(e.buttons & 1)) { S.dragSel = false; return; }
    const td = closest(e, "td[data-r]");
    if (td) { const r = +td.dataset.r, c = +td.dataset.c; if (!S.cur || S.cur.r !== r || S.cur.c !== c) { S.cur = { r, c }; render(S); } }
  });
  host.addEventListener("mouseup", () => { const S = S_(); S.dragSel = false; });

  host.addEventListener("contextmenu", (e) => {
    const S = S_();
    const td = closest(e, "td[data-r]");
    if (!td) return;
    e.preventDefault();
    const r = +td.dataset.r, c = +td.dataset.c;
    const sel = selRange(S);
    if (!sel || r < sel.r0 || r > sel.r1 || c < sel.c0 || c > sel.c1) { S.cur = { r, c }; S.anchor = { r, c }; }
    const row = S.m.rows[r], cell = row && row.cells[c];
    S.menu = { type: "ctx", cell, ...pos(host, e) };
    render(S);
  });

  host.addEventListener("click", (e) => {
    const S = S_();
    const el = closest(e, "[data-a]");
    if (S.menu && !closest(e, "[data-menu]") && !(el && (el.dataset.a === "menu" || el.dataset.a === "fmenu" || el.dataset.a === "chipmenu"))) { S.menu = null; if (!el) { render(S); return; } }
    if (!el) return;
    const a = el.dataset.a, v = el.dataset.v, ui = S.ui;
    if (["period", "from", "to", "search", "fq", "dname", "ddec", "dhow", "ffield", "sortval", "topn"].includes(a)) return;   // handled on change/input
    const T = el.type === "checkbox";
    switch (a) {
      case "tab": S.tab = v; render(S); break;
      case "menu": S.menu = S.menu && S.menu.type === v ? null : { type: v, ...below(host, el) }; render(S); break;
      case "preset": S.ui = { ...clone(S.data.presets[v]) }; S.collapsed.clear(); S.menu = null; commit(S, true); break;
      case "saved": S.ui = clone(S.data.saved[v]); S.collapsed.clear(); S.menu = null; commit(S, true); break;
      case "blankpivot": Object.assign(ui, { rows: [], cols: [], filters_area: [], values: [], sel: {} }); S.menu = null; commit(S, true); break;
      case "set": {
        const [k, val] = v.split("=");
        if (k === "grand") { ui.grand_rows = val[0] === "1"; ui.grand_cols = val[1] === "1"; }
        else if (k === "repeat" || k === "blank") ui[k] = val === "1";
        else { ui[k] = val; if (k === "layout" && val === "tabular" && ui.subtotals === "top") ui.subtotals = "bottom"; }
        S.menu = null; commit(S, false); break;
      }
      case "opt": ui[v] = el.checked; commit(S, false); break;
      case "style": ui.style = v; commit(S, false); break;
      case "togglepane": S.paneHidden = !el.checked; render(S); break;
      case "hidepane": S.paneHidden = true; S.menu = null; render(S); break;
      case "showpane": S.paneHidden = false; S.menu = null; render(S); break;
      case "closemsg": S.msgClosed = (S.data.notes || []).join("\n"); render(S); break;
      case "refresh": S.menu = null; S.pending = S.rev + 1; commit(S, true); break;
      case "withsrc": S.withSource = el.checked; break;
      case "export": exportNow(S); break;
      case "savelayout": S.dlg = { type: "save", name: "" }; render(S); break;
      case "toggle": { const k = el.dataset.k; S.collapsed.has(k) ? S.collapsed.delete(k) : S.collapsed.add(k); render(S); break; }
      case "toggle1": S.collapsed.has(v) ? S.collapsed.delete(v) : S.collapsed.add(v); S.menu = null; render(S); break;
      case "expfield": case "colfield": {
        const f = v || activeField(S); if (!f) break;
        const lvl = ui.rows.indexOf(f) + 1;
        const keys = (S.data.grid ? S.data.grid.rows : []).filter((r) => r[0] === "subtotal" && r[1].length === lvl).map((r) => r[1].join(SEP));
        keys.forEach((k) => (a === "colfield" ? S.collapsed.add(k) : S.collapsed.delete(k)));
        S.menu = null; render(S); break;
      }
      case "sortlab": ui.sort = { by: "label", desc: v === "desc" }; S.menu = null; commit(S, true); break;
      case "clearall": ui.sel = {}; ui.top = 0; commit(S, true); break;
      case "clearf": dropSel(S, v); S.menu = null; commit(S, true); break;
      case "fold": S.shut.has(v) ? S.shut.delete(v) : S.shut.add(v); render(S); break;
      case "tick": {
        const f = el.dataset.f, mea = el.dataset.mea === "1";
        if (mea) {
          if (el.checked) ui.values.push(newValue(f)); else { ui.values = ui.values.filter((x) => x.m !== f); fixSort(S); }
        } else if (el.checked) {
          ui.rows.push(f);                          // Excel: a text field goes to Rows
        } else { removeEverywhere(S, f); dropSel(S, f); }
        commit(S, true); break;
      }
      case "chipmenu": { const area = el.dataset.area, i = +el.dataset.i; S.menu = { type: "chip", area, i, ...below(host, el) }; render(S); break; }
      case "move": {
        const area = el.dataset.area, i = +el.dataset.i, x = arr(S, area), [it] = x.splice(i, 1);
        const j = v === "up" ? i - 1 : v === "down" ? i + 1 : v === "first" ? 0 : x.length;
        x.splice(j, 0, it); S.menu = null; commit(S, true); break;
      }
      case "moveto": { const area = el.dataset.area, i = +el.dataset.i; moveChip(S, area, i, v, arr(S, v).length); S.menu = null; commit(S, true); break; }
      case "remove": {
        const area = el.dataset.area, i = +el.dataset.i;
        if (area === "values") { ui.values.splice(i, 1); fixSort(S); } else { const f = arr(S, area)[i]; arr(S, area).splice(i, 1); dropSel(S, f); }
        S.menu = null; commit(S, true); break;
      }
      case "removef": removeEverywhere(S, v); dropSel(S, v); S.menu = null; commit(S, true); break;
      case "removev": ui.values.splice(+v, 1); fixSort(S); S.menu = null; commit(S, true); break;
      case "showas": { const [i, how] = v.split("|"); ui.values[+i].how = how; S.menu = null; commit(S, true); break; }
      case "vfs": { if (v === "" || v === undefined) break; const i = +v, val = ui.values[i]; S.menu = null; S.dlg = { type: "vfs", i, tab: "show", name: val.name || "", how: val.how || "Value", fmt: { ...(val.fmt || { cat: "auto", dec: 0 }) } }; render(S); break; }
      case "fs": S.menu = null; S.dlg = { type: "fs", f: v, name: (ui.names || {})[v] || "" }; render(S); break;
      case "fmt": { const i = +v; S.menu = null; openFmt(S, i, null); break; }
      case "dtab": S.dlg.tab = v; render(S); break;
      case "dnumfmt": openFmt(S, S.dlg.i, S.dlg); break;
      case "dcat": S.dlg.cat = v; if (v === "lakh" || v === "crore") S.dlg.dec = Math.max(S.dlg.dec, 2); render(S); break;
      case "fmtok": {
        const D = S.dlg;
        if (D.back) { D.back.fmt = { cat: D.cat, dec: D.dec }; S.dlg = D.back; render(S); }
        else { ui.values[D.i].fmt = { cat: D.cat, dec: D.dec }; S.dlg = null; commit(S, false); }
        break;
      }
      case "fmtcancel": S.dlg = S.dlg.back || null; render(S); break;
      case "dok": {
        const D = S.dlg, val = ui.values[D.i], dataChange = val.how !== D.how;
        val.name = D.name.trim(); val.how = D.how; val.fmt = D.fmt; S.dlg = null; commit(S, dataChange); break;
      }
      case "fsok": { const D = S.dlg; ui.names = { ...(ui.names || {}) }; if (D.name.trim()) ui.names[D.f] = D.name.trim(); else delete ui.names[D.f]; S.dlg = null; commit(S, false); break; }
      case "saveok": { const n = S.dlg.name.trim(); if (!n) break; S.send("event", { type: "save", name: n }); S.dlg = null; toast(S, `Saved “${esc(n)}” — find it under Recommended PivotTables.`); break; }
      case "dcancel": S.dlg = null; render(S); break;
      case "modalbg": if (e.target === el) { S.dlg = null; render(S); } break;
      case "copy": copySel(S); S.menu = null; render(S); break;
      case "fmenu": case "fmenu2": {
        const which = v;
        S.menu = { type: "filter", which, q: "", ...(a === "fmenu" ? below(host, el) : { x: S.menu ? S.menu.x : 40, y: S.menu ? S.menu.y : 60 }) };
        render(S); break;
      }
      case "fall": { const M = S.menu, info = S.data.items[M.field] || { items: [] }, q = (M.q || "").toLowerCase(); info.items.filter((x) => !q || x.toLowerCase().includes(q)).forEach((x) => (el.checked ? M.work.add(x) : M.work.delete(x))); render(S); break; }
      case "fitem": { const M = S.menu; el.checked ? M.work.add(v) : M.work.delete(v); render(S); break; }
      case "fok": {
        const M = S.menu, f = M.field, info = S.data.items[f] || { items: [] };
        const on = [...M.work], off = info.items.filter((x) => !M.work.has(x));
        if (!on.length) { toast(S, "Tick at least one item."); break; }
        ui.sel = { ...(ui.sel || {}) };
        if (!off.length) delete ui.sel[f];
        else ui.sel[f] = on.length <= off.length || info.more ? { mode: "include", items: on } : { mode: "exclude", items: off };
        S.menu = null; commit(S, true); break;
      }
      case "fcancel": S.menu = null; render(S); break;
      case "defer": S.defer = el.checked; if (!S.defer && S.dirty) commit(S, true); else render(S); break;
      case "update": if (S.dirty) { S.dirty = false; S.pending = S.rev; S.send("event", { type: "ui", ui: S.ui, rev: S.rev }); render(S); } break;
      default: break;
    }
    if (T) e.stopPropagation();
  });

  host.addEventListener("dblclick", (e) => {
    const S = S_();
    const td = closest(e, "td[data-r]");
    if (!td) return;
    const row = S.m.rows[+td.dataset.r], cell = row && row.cells[+td.dataset.c];
    if (cell && cell.key !== undefined && cell.tg) { S.collapsed.has(cell.key) ? S.collapsed.delete(cell.key) : S.collapsed.add(cell.key); render(S); }
    else if (cell && cell.v !== undefined) toast(S, "Show Details (the rows behind a number) arrives in the next phase.");
  });

  host.addEventListener("change", (e) => {
    const S = S_(), el = e.target, a = el.dataset && el.dataset.a, ui = S.ui;
    if (a === "period") { ui.period = el.value; if (el.value === "Custom" && !ui.from) { ui.from = S.data.dmin; ui.to = S.data.dmax; } commit(S, true); }
    else if (a === "from" || a === "to") { ui[a] = el.value; if (ui.from && ui.to) commit(S, true); }
    else if (a === "ffield") { S.menu.field = el.value; S.menu.work = null; render(S); }
    else if (a === "sortval" && el.value) { const [m, desc] = el.value.split("|"); ui.sort = { by: m, desc: desc === "1" }; S.menu = null; commit(S, true); }
    else if (a === "topn") { ui.top = Math.max(0, Math.min(500, +el.value || 0)); if (ui.sort.by === "label" && ui.values[0]) ui.sort = { by: ui.values[0].m, desc: true }; S.menu = null; commit(S, true); }
    else if (a === "dhow") {
      S.dlg.how = el.value;
      // a share or a % change is a percentage: a rupee scale picked earlier would print it as "0.02 L"
      if (/^%/.test(el.value) && ["lakh", "crore", "currency"].includes(S.dlg.fmt.cat)) S.dlg.fmt = { cat: "auto", dec: 0 };
      render(S);
    }
    else if (a === "ddec") { S.dlg.dec = Math.max(0, Math.min(4, +el.value || 0)); render(S); }
  });

  host.addEventListener("input", (e) => {
    const S = S_(), el = e.target, a = el.dataset && el.dataset.a;
    if (a === "search") { S.search = el.value; render(S); }
    else if (a === "fq") { S.menu.q = el.value; render(S); }
    else if (a === "dname") { S.dlg.name = el.value; if (S.dlg.type === "save") render(S); }
  });

  host.addEventListener("keydown", (e) => {
    const S = S_();
    if (e.key === "Escape") { if (S.menu || S.dlg) { S.menu = null; S.dlg = null; render(S); } return; }
    if (e.key === "Enter" && S.dlg && e.target.dataset && e.target.dataset.a === "dname") {
      const okA = S.dlg.type === "vfs" ? "dok" : S.dlg.type === "fs" ? "fsok" : "saveok";
      const b = host.querySelector(`[data-a="${okA}"]`); if (b) b.click(); return;
    }
    const inSheet = e.target.classList && e.target.classList.contains("pv-sheet");
    if (!inSheet || !S.cur) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "c") { copySel(S); e.preventDefault(); return; }
    const mv = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], Tab: [0, 1], Enter: [1, 0] }[e.key];
    if (!mv) return;
    e.preventDefault();
    const nr = Math.max(0, S.cur.r + mv[0]), nc = Math.max(0, S.cur.c + mv[1]);
    if (!e.shiftKey) S.anchor = { r: nr, c: nc };
    S.cur = { r: nr, c: nc };
    render(S);
    const td = host.querySelector(`td[data-r="${nr}"][data-c="${nc}"]`);
    if (td) td.scrollIntoView({ block: "nearest", inline: "nearest" });
    host.querySelector(".pv-sheet").focus({ preventScroll: true });
  });

  // ---- drag and drop: fields → areas, chips between areas, chips back to the list (= remove)
  host.addEventListener("dragstart", (e) => {
    const S = S_();
    const el = closest(e, "[data-drag]");
    if (!el) return;
    S.drag = el.dataset.drag === "field"
      ? { kind: "field", f: el.dataset.f, mea: el.dataset.mea === "1" }
      : { kind: "chip", area: el.dataset.area, i: +el.dataset.i };
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", el.dataset.f || el.dataset.area); } catch (x) { /* some browsers */ }
    if (el.classList.contains("chip")) setTimeout(() => el.classList.add("ghost"), 0);
  });
  host.addEventListener("dragover", (e) => {
    const S = S_();
    const box = closest(e, "[data-drop]");
    if (!box || !S.drag) return;
    e.preventDefault();
    host.querySelectorAll(".ab.over").forEach((x) => x !== box && x.classList.remove("over"));
    host.querySelectorAll(".dropline").forEach((x) => x.remove());
    if (box.dataset.drop === "list") return;
    box.classList.add("over");
    const idx = dropIndex(box, e.clientY);
    const line = document.createElement("div"); line.className = "dropline";
    const chips = [...box.querySelectorAll(".chip:not(.fixed)")];
    if (idx < chips.length) box.insertBefore(line, chips[idx]); else { const fx = box.querySelector(".chip.fixed"); fx ? box.insertBefore(line, fx) : box.appendChild(line); }
  });
  host.addEventListener("dragleave", (e) => {
    const box = closest(e, "[data-drop]");
    if (box && !box.contains(e.relatedTarget)) { box.classList.remove("over"); box.querySelectorAll(".dropline").forEach((x) => x.remove()); }
  });
  host.addEventListener("drop", (e) => {
    const S = S_();
    const box = closest(e, "[data-drop]");
    if (!box || !S.drag) return;
    e.preventDefault();
    const to = box.dataset.drop, D = S.drag; S.drag = null;
    let ok = false;
    if (to === "list") {
      if (D.kind === "chip") {
        if (D.area === "values") { S.ui.values.splice(D.i, 1); fixSort(S); } else { const f = arr(S, D.area)[D.i]; arr(S, D.area).splice(D.i, 1); dropSel(S, f); }
        ok = true;
      }
    } else {
      const idx = dropIndex(box, e.clientY);
      ok = D.kind === "field" ? placeField(S, D.f, D.mea, to, idx) : moveChip(S, D.area, D.i, to, idx);
    }
    if (ok) commit(S, true); else render(S);
  });
  host.addEventListener("dragend", () => { const S = S_(); S.drag = null; render(S); });
}

function dropIndex(box, y) {
  const chips = [...box.querySelectorAll(".chip:not(.fixed)")];
  for (let i = 0; i < chips.length; i++) { const r = chips[i].getBoundingClientRect(); if (y < r.top + r.height / 2) return i; }
  return chips.length;
}
function pos(host, e) { const r = host.querySelector(".pv-app").getBoundingClientRect(); return { x: e.clientX - r.left + 2, y: e.clientY - r.top + 2 }; }
function below(host, el) { const r = host.querySelector(".pv-app").getBoundingClientRect(), b = el.getBoundingClientRect(); return { x: b.left - r.left, y: b.bottom - r.top + 2 }; }

function openFmt(S, i, back) {
  const v = S.ui.values[i], g = S.data.grid;
  let sample = 1234567.891;
  if (g) for (const r of g.rows) { const x = r[2][i]; if (x !== null && x !== undefined) { sample = x; break; } }
  const f = back ? back.fmt : v.fmt || { cat: "auto", dec: 0 };
  S.menu = null;
  S.dlg = { type: "fmt", i, back, cat: f.cat || "auto", dec: +f.dec || 0, sample, kind: g ? g.kinds[i] : "money" };
  render(S);
}

function copySel(S) {
  const sel = selRange(S); if (!sel) return;
  const lines = [];
  for (let r = sel.r0; r <= sel.r1; r++) {
    const row = S.m.rows[r], out = [];
    for (let c = sel.c0; c <= sel.c1; c++) { const cell = row && row.cells[c]; out.push(!cell ? "" : cell.v !== undefined ? (cell.v === null ? "" : String(cell.v)) : (cell.t || "")); }
    lines.push(out.join("\t"));
  }
  const txt = lines.join("\n");
  try { navigator.clipboard.writeText(txt).then(() => toast(S, `Copied ${sel.r1 - sel.r0 + 1} × ${sel.c1 - sel.c0 + 1} cells — paste into Excel or Sheets.`)); }
  catch (e) { toast(S, "Copy is blocked by the browser here."); }
}

// ---------------------------------------------------------------- export: the sheet exactly as drawn
function exportNow(S) {
  if (!S.data.grid) { toast(S, "Nothing to export yet — add a value."); return; }
  const m = model(S, true), ui = S.ui;
  const W = S.colW || [];
  const head = m.rows.filter((r) => r.type === "head").map((r) => r.cells.map((c) => ({ t: c.t || "", al: c.al || "left" })));
  const body = m.rows.filter((r) => r.type === "body").map((r) => ({
    kind: r.kind, level: r.kind === "grand" ? 0 : (ui.layout === "tabular" && r.kind === "item" ? r.level : r.kind === "item" ? r.level : r.level), hidden: !!r.hidden,
    cells: r.cells.map((c) => (c.v !== undefined ? { v: c.v, k: c.k, nf: c.nf, b: !!c.b } : { t: c.t || "", i: c.i || 0, b: !!c.b })),
  }));
  const sheet = { cols: W.slice(0, m.ncol), head, body, filters: m.filters, style: ui.style, banded_rows: ui.banded_rows, col_headers: ui.col_headers,
    summary_below: ui.subtotals !== "top" || ui.layout === "tabular", freeze: [m.head, m.L] };
  const id = String(Date.now());
  S.send("event", { type: "export", sheet, source: !!S.withSource, id });
  toast(S, "Writing the Excel file…", 20000);
}
