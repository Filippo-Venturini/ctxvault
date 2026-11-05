// What the page computes from the vaults, with no DOM involved: the
// bitemporal state of each statement, groups, chains, health, the time axis.
//
// A statement's state at (held at tv, known at tk) mirrors
// sqlite_store.select_episodes: unknown until recorded, retracted once a
// revision replaced it, future before valid_from, closed after valid_to
// unless the vault had not yet recorded that end by tk, else open.

const CV = (() => {
  const DAY = 864e5;
  // A timestamp without an offset is read as UTC, as the episodic store reads
  // what callers hand it; Date.parse alone would read it in the browser's zone.
  const ts = (iso) => (iso ? Date.parse(/T/.test(iso) && !/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso + "Z" : iso) : null);

  // The clock and the span of the time axis. `now` is the moment the data was
  // read (or the snapshot taken); `t0` the earliest instant of the open vault.
  const R = { now: Date.now(), t0: Date.now() - 30 * DAY };
  const setNow = (t) => { R.now = t; };
  const setRange = (t0) => { R.t0 = Math.min(t0, R.now - 60e3); };

  const TYPES = [
    { id: "semantic", label: "semantic" },
    { id: "episodic", label: "episodic" },
    // the map names kinds of memory (semantic, episodic, procedural); the vault
    // that holds the third is a skill vault, and is called that everywhere else
    { id: "skill", label: "procedural" },
  ];

  // ---- the overview, as the topology draws it ----
  function agentsOf(summaries) {
    const all = new Set();
    for (const v of summaries) for (const a of v.allowed_agents || []) all.add(a);
    return [...all].sort();
  }

  function vaultsOf(summaries, agents) {
    return summaries.map((v) => {
      const c = v.counts || {};
      const type = v.type === "skill" || v.type === "episodic" ? v.type : "semantic";
      const restricted = !!v.restricted;
      return {
        id: v.name, type, scope: v.scope === "global" ? "global" : "local",
        access: restricted ? "restricted" : "public",
        readers: restricted ? v.allowed_agents || [] : agents,
        size: type === "episodic" ? c.total || 0 : type === "skill" ? c.skills || 0 : c.documents || 0,
        chunks: c.chunks || 0, model: v.embedding_model || null, modelDefault: !!v.embedding_default,
        last: ts(v.last_activity), path: v.path || "", error: v.error || null, problem: v.problem || null,
        disk: v.disk_bytes || 0, activity: v.activity || [],
        counts: v.counts || {},
      };
    });
  }

  // ---- an episodic vault's statements ----
  const metaText = (v) => (v == null ? "—" : Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v));

  function statements(episodes) {
    const prev = new Map();
    for (const e of episodes) {
      if (e.superseded_by) prev.set(e.superseded_by, { id: e.id, kind: "superseded" });
      if (e.revised_by) prev.set(e.revised_by, { id: e.id, kind: "revised" });
    }
    return episodes.map((e) => {
      const tf = ts(e.recorded_at);
      const meta = {};
      for (const [k, v] of Object.entries(e.metadata || {})) meta[k] = metaText(v);
      return {
        id: e.id, text: e.content, entities: e.entities || [], source: e.source || "—",
        conf: e.confidence ?? 1, sal: e.salience ?? 0.5,
        vf: ts(e.valid_from) ?? tf, vt: ts(e.valid_to), tf, tt: ts(e.invalidated_at), rev: !!e.revised_by,
        prev: prev.get(e.id) || null, disputes: e.disputed_with || [],
        dispute: (e.disputed_with || [])[0] || null,
        att: 1 + (e.confirmed_count || 0), lastAtt: ts(e.last_confirmed_at) || tf,
        recalls: e.recall_count || 0, lastRecall: ts(e.last_recalled_at), occ: ts(e.occurred_at), meta,
        attestations: (e.attestations || []).map((a) => ({ t: ts(a.at), source: a.source || null })),
        disputeLog: (e.disputes || []).map((d) => ({ with: d.with, t: ts(d.noticed_at), note: d.note || null })),
      };
    });
  }

  function earliest(all) {
    let t = Infinity;
    for (const s of all) t = Math.min(t, s.vf ?? Infinity, s.tf ?? Infinity);
    if (t === Infinity) return R.now - 30 * DAY;
    return t - (R.now - t) * 0.02;
  }

  function stateOf(s, tv, tk) {
    if (s.tf > tk) return "unknown";                              // the vault had not recorded it yet
    if (s.rev && s.tt != null && s.tt <= tk) return "retracted";  // restated by a revision by then
    if (s.vf > tv) return "future";                               // known, but not yet true at tv
    const vt = s.tt != null && s.tt > tk ? null : s.vt;           // an end the vault had not yet learned
    if (vt != null && vt <= tv) return "closed";
    return "open";
  }
  function isDisputed(s, byId, tv, tk) {
    if (!s.disputes.length || stateOf(s, tv, tk) !== "open") return false;
    return s.disputes.some((id) => { const o = byId.get(id); return !!o && stateOf(o, tv, tk) === "open"; });
  }
  function health(all, byId, tv, tk) {
    const h = { open: 0, closed: 0, retracted: 0, unknown: 0, future: 0, disputed: 0, confirmed: 0, unrecalled: 0, total: all.length };
    for (const s of all) {
      const st = stateOf(s, tv, tk); h[st]++;
      if (st === "open") { if (s.att >= 2) h.confirmed++; if (!s.recalls) h.unrecalled++; if (isDisputed(s, byId, tv, tk)) h.disputed++; }
    }
    const known = h.open + h.closed + h.retracted || 1;
    h.known = known; h.pOpen = h.open / known; h.pClosed = h.closed / known; h.pRetracted = h.retracted / known; h.pDisputed = h.disputed / known;
    h.pConfirmed = h.open ? h.confirmed / h.open : 0; h.pUnrecalled = h.open ? h.unrecalled / h.open : 0;
    return h;
  }
  // What the rows can be grouped by: "none" (one lane per statement), the
  // episode's own fields that name a category (entities, source), then every
  // metadata key the vault's writers attached, most used first. The page does
  // not judge which custom keys matter: that is up to the project.
  function metaKeys(all) {
    const count = new Map();
    for (const s of all) for (const m in s.meta) count.set(m, (count.get(m) || 0) + 1);
    const custom = [...count.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([k]) => k)
      .filter((k) => k !== "entity" && k !== "source" && k !== "none");
    return ["none", "entity", "source", ...custom];
  }
  function groupBy(all, key) {
    if (key === "none") return [{ name: "all statements", items: all, count: all.length }];
    const m = new Map();
    for (const s of all) {
      const ks = key === "entity" ? (s.entities.length ? s.entities : ["—"]) : key === "source" ? [s.source || "—"] : [s.meta[key] ?? "—"];
      for (const k of ks) { if (!m.has(k)) m.set(k, []); m.get(k).push(s); }
    }
    return [...m.entries()].map(([name, items]) => ({ name, items, count: items.length })).sort((a, b) => b.count - a.count);
  }
  function chainOf(s, all, byId) {
    const next = new Map();
    for (const x of all) if (x.prev) next.set(x.prev.id, x);
    const back = []; let cur = s; const seen = new Set([s.id]);
    while (cur.prev) { const p = byId.get(cur.prev.id); if (!p || seen.has(p.id)) break; seen.add(p.id); back.unshift({ s: p, kind: cur.prev.kind }); cur = p; }
    const fwd = []; cur = s;
    for (;;) { const n = next.get(cur.id); if (!n || seen.has(n.id)) break; seen.add(n.id); fwd.push({ s: n, kind: n.prev.kind }); cur = n; }
    return [...back, { s, kind: null, self: true }, ...fwd];
  }
  // What happened to the vault, as changes the memory recorded, in the
  // library's own words: a statement recorded, one superseded by a successor,
  // one revised (restated, same fact), one closed with nothing in its place.
  function successors(all) {
    const next = new Map();
    for (const x of all) if (x.prev) next.set(x.prev.id, { s: x, kind: x.prev.kind });
    return next;
  }
  function events(all, byId) {
    const next = successors(all), out = [];
    for (const x of all) {
      const was = x.prev ? byId.get(x.prev.id) || null : null;
      const kind = !x.prev ? "recorded" : x.prev.kind === "revised" ? "revised" : "superseded";
      if (x.tf != null) out.push({ t: x.tf, kind, s: x, was });
      if (!next.has(x.id)) {
        const end = x.tt ?? (x.vt != null && x.vt <= R.now ? x.vt : null);
        if (end != null) out.push({ t: end, kind: "closed", s: x, was: null });
      }
    }
    return out.sort((a, b) => b.t - a.t);
  }
  // Statements in dispute, as pairs that both hold in `current`.
  function disputePairs(all, current) {
    const byId = new Map(all.map((x) => [x.id, x])), seen = new Set(), out = [];
    for (const x of all) if (current.has(x)) for (const id of x.disputes) {
      const o = byId.get(id), key = [x.id, id].sort().join("|");
      if (o && current.has(o) && !seen.has(key)) { seen.add(key); out.push([x, o]); }
    }
    return out;
  }
  // What the memory held as true on a day, as it stood that day.
  const heldAt = (all, t) => new Set(all.filter((x) => stateOf(x, t, t) === "open"));

  function search(all, q) {
    q = q.trim().toLowerCase(); if (!q) return all;
    return all.filter((s) => s.text.toLowerCase().includes(q) || s.entities.some((e) => e.toLowerCase().includes(q)) || Object.values(s.meta).some((v) => v.toLowerCase().includes(q)) || s.id.startsWith(q));
  }

  // ---- the time axis ----
  const frac = (t) => Math.min(1, Math.max(0, (t - R.t0) / (R.now - R.t0)));
  const pct = (t) => (frac(t) * 100).toFixed(2) + "%";
  const atFrac = (f) => R.t0 + Math.min(1, Math.max(0, f)) * (R.now - R.t0);
  const span = () => R.now - R.t0;

  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const pad = (n) => String(n).padStart(2, "0");
  const hm = (d) => pad(d.getHours()) + ":" + pad(d.getMinutes());
  function fmt(t) {
    if (t == null) return "—";
    if (Math.abs(t - R.now) < 60e3) return "now";
    const d = new Date(t);
    const day = d.getDate() + " " + MON[d.getMonth()] + " " + d.getFullYear();
    return span() < 7 * DAY ? day + " " + hm(d) : day;
  }
  function fmtShort(t) {
    const d = new Date(t);
    return span() < 60 * DAY ? d.getDate() + " " + MON[d.getMonth()] : MON[d.getMonth()] + " " + d.getFullYear();
  }
  function fmtStamp(t) { const d = new Date(t); return d.getDate() + " " + MON[d.getMonth()] + " " + d.getFullYear() + " " + hm(d); }
  function ago(t) {
    const s = Math.max(0, (R.now - t) / 1e3);
    if (s < 90) return Math.round(s) + " s"; if (s < 5400) return Math.round(s / 60) + " min";
    if (s < 2 * 86400) return Math.round(s / 3600) + " h"; return Math.round(s / 86400) + " d";
  }
  const bytes = (n) => {
    const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
    while (n >= 1000 && i < u.length - 1) { n /= 1000; i++; }
    return (i && n < 10 ? n.toFixed(1) : Math.round(n)) + " " + u[i];
  };
  const num = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n));

  // Ticks at calendar boundaries, as coarse as the span asks for.
  function ticks() {
    const sp = span(), out = [];
    const months = sp / (30 * DAY);
    const push = (t, label) => { if (t > R.t0 && t <= R.now) out.push({ t, label, f: frac(t) }); };
    if (months > 4) {
      const step = months > 48 ? 12 : months > 12 ? 3 : 1;
      const d = new Date(R.t0); d.setDate(1); d.setHours(0, 0, 0, 0);
      while (d.getTime() <= R.now) {
        if (d.getMonth() % step === 0) push(d.getTime(), d.getMonth() === 0 ? String(d.getFullYear()) : MON[d.getMonth()]);
        d.setMonth(d.getMonth() + 1);
      }
    } else if (sp > 3 * DAY) {
      const step = sp > 21 * DAY ? 7 : 1;
      const d = new Date(R.t0); d.setHours(0, 0, 0, 0);
      while (d.getTime() <= R.now) {
        if (step === 1 || d.getDay() === 1) push(d.getTime(), d.getDate() + " " + MON[d.getMonth()]);
        d.setDate(d.getDate() + 1);
      }
    } else {
      const step = sp > 12 * 3600e3 ? 6 : sp > 3 * 3600e3 ? 1 : 0.25;
      const ms = step * 3600e3, start = Math.ceil(R.t0 / ms) * ms;
      for (let t = start; t <= R.now; t += ms) push(t, hm(new Date(t)));
    }
    if (out.length <= 12) return out;
    const k = Math.ceil(out.length / 12);
    return out.filter((_, i) => i % k === 0);
  }

  // ---- url state ----
  function readHash() {
    const h = Object.fromEntries(new URLSearchParams(location.hash.slice(1))); const o = {};
    if (h.v) { o.view = "vault"; o.vault = h.v; } if (h.ep) o.sel = h.ep;
    if (h.m === "t") o.mode = "time"; if (h.at) o.at = +h.at;
    return o;
  }
  function hashOf(s, withSel = true) {
    const p = new URLSearchParams();
    if (s.view === "vault" && s.vault) p.set("v", s.vault);
    if (withSel && s.sel) p.set("ep", s.sel);
    if (s.view === "vault" && s.mode === "time") { p.set("m", "t"); if (s.at != null) p.set("at", Math.round(s.at)); }
    return p.toString();
  }
  function writeHash(s) {
    const h = hashOf(s);
    const want = h ? "#" + h : "";
    if (location.hash !== want) history.replaceState(null, "", want || location.pathname + location.search);
  }
  function shareLinks(s) {
    const base = location.href.split("#")[0];
    const out = [];
    if (s.sel) out.push(base + "#" + hashOf(s));
    out.push(base + "#" + hashOf(s, false));
    return out;
  }

  const basename = (p) => String(p || "").split(/[\\/]/).pop() || String(p || "");

  return { DAY, R, ts, setNow, setRange, TYPES, agentsOf, vaultsOf, statements, earliest, stateOf, isDisputed, health,
           metaKeys, groupBy, chainOf, successors, events, heldAt, disputePairs, search, frac, pct, atFrac, fmt, fmtShort, fmtStamp, ago, num, bytes, ticks,
           readHash, writeHash, shareLinks, basename };
})();
