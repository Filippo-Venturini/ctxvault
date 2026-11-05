// The memory viewer: a topology of every vault on this machine, and one page
// per vault type. Preact over the JSON the server (or the snapshot) provides;
// the bitemporal logic is CV, in data.js, markdown is MD, in markdown.js.
// Styles sit inline on the markup,
// next to what they shape; styles.css holds only the tokens and the font.

const { h, render } = preact;
const { useState, useEffect, useMemo, useRef, useCallback } = preactHooks;
const html = htm.bind(h);

// --- where the data comes from ------------------------------------------------

function liveSource() {
  const get = async (path) => {
    const r = await fetch(path);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  };
  return {
    live: true,
    overview: () => get("api/overview"),
    vault: (name) => get(`api/vaults/${encodeURIComponent(name)}`),
    document: (name, id) => get(`api/vaults/${encodeURIComponent(name)}/documents/${encodeURIComponent(id)}`),
    search: (name, q) => get(`api/vaults/${encodeURIComponent(name)}/search?q=${encodeURIComponent(q)}&n=6`),
    reveal: async (name) => {
      const r = await fetch(`api/vaults/${encodeURIComponent(name)}/reveal`, { method: "POST" });
      if (r.ok) return;
      const detail = (await r.json().catch(() => ({}))).detail;
      // a bare "Not Found" is the route missing, not the vault: an older server
      throw new Error(detail && detail !== "Not Found" ? detail : "This server predates the button: restart ctxvault ui.");
    },
  };
}

function snapshotSource(snap) {
  const byName = new Map(snap.vaults.map((v) => [v.name, v]));
  return {
    live: false,
    generatedAt: snap.generated_at,
    overview: async () => ({ ...snap, vaults: snap.vaults.map(({ payload, ...rest }) => rest) }),
    vault: async (name) => {
      const v = byName.get(name);
      if (!v || !v.payload) throw new Error(v && v.error ? v.error : `Vault '${name}' is not in this snapshot.`);
      return v.payload;
    },
    document: async (name, id) => {
      const p = (byName.get(name) || {}).payload || {};
      const content = (p.contents || {})[id];
      if (!content) throw new Error("Document text is not part of this snapshot.");
      return content;
    },
    search: async () => { throw new Error("Search needs a live vault."); },
  };
}

const source = window.CTXVAULT_SNAPSHOT ? snapshotSource(window.CTXVAULT_SNAPSHOT) : liveSource();
const ASSETS = window.CTXVAULT_ASSETS || { logoDark: "static/logo-dark.svg", logoLight: "static/logo-light.svg" };
const THEME = new URLSearchParams(location.search).get("theme") === "light" ? "light" : "dark";
// what a snapshot says about itself to whoever opens it cold (ctxvault ui --export --note)
const NOTE = typeof window.CTXVAULT_NOTE === "string" ? window.CTXVAULT_NOTE : null;
const REFRESH_MS = 15000;

window.addEventListener("error", (event) => {
  const box = document.createElement("div");
  box.className = "failure";
  box.textContent = `The page hit an error: ${event.message} (${String(event.filename).split("/").pop()}:${event.lineno})`;
  document.body.prepend(box);
});

// --- palette ------------------------------------------------------------------

const FAM = {
  episodic: ["var(--ep1)", "var(--ep2)", "var(--ep3)", "var(--ep4)"],
  semantic: ["var(--se1)", "var(--se2)", "var(--se3)", "var(--se4)"],
  skill: ["var(--pr1)", "var(--pr2)", "var(--pr3)", "var(--pr4)"],
};
const mix = (c, a) => `color-mix(in oklab, ${c} ${a}%, var(--bg))`;
const DEFAULT_AC = "oklch(78% 0.16 300)", DEFAULT_ACS = "oklch(78% 0.16 300 / .16)";

// --- state --------------------------------------------------------------------

function useMergeState(init) {
  const [state, set] = useState(init);
  const setState = useCallback((patch) => set((s) => ({ ...s, ...(typeof patch === "function" ? patch(s) : patch) })), []);
  return [state, setState];
}

function App() {
  const [s, setState] = useMergeState(() => Object.assign(
    { view: "home", vault: null, sel: null, group: "none", gsel: null, q: "", qq: "", doc: 0, mode: "now", at: null, diff: null, hv: null, ha: null },
    CV.readHash()));
  const [overview, setOverview] = useState(null);
  const [failure, setFailure] = useState(null);
  const [payloads, setPayloads] = useState({});   // name -> {data} | {error}
  const [tick, setTick] = useState(0);
  const [note, setNote] = useState(NOTE);

  // the overview, and the open vault, re-read every few seconds while live
  useEffect(() => {
    if (!source.live) return;
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    let gone = false;
    source.overview().then((o) => {
      if (gone) return;
      CV.setNow(source.live ? Date.now() : Date.parse(source.generatedAt));
      setOverview(o); setFailure(null);
    }).catch((e) => !gone && setFailure(String(e.message || e)));
    return () => { gone = true; };
  }, [tick]);
  useEffect(() => {
    if (s.view !== "vault" || !s.vault) return;
    let gone = false;
    const name = s.vault;
    source.vault(name)
      .then((data) => !gone && setPayloads((p) => ({ ...p, [name]: { data } })))
      .catch((e) => !gone && setPayloads((p) => ({ ...p, [name]: { error: String(e.message || e) } })));
    return () => { gone = true; };
  }, [s.view, s.vault, tick]);
  useEffect(() => { CV.writeHash(s); });

  const agents = useMemo(() => (overview ? CV.agentsOf(overview.vaults) : []), [overview]);
  const vaults = useMemo(() => (overview ? CV.vaultsOf(overview.vaults, agents) : []), [overview, agents]);
  const vault = s.view === "vault" && s.vault ? vaults.find((v) => v.id === s.vault) || { id: s.vault, type: (payloads[s.vault]?.data || {}).type || "semantic", path: "" } : null;
  const loaded = vault ? payloads[vault.id] : null;

  // handlers shared by the views
  const C = useMemo(() => ({
    go: () => setState({ view: "home", vault: null, sel: null, gsel: null, q: "", qq: "", hv: null, ha: null, keep: false }),
    openVault: (v) => () => { if (v.error) return; setState({ view: "vault", vault: v.id, sel: null, gsel: null, q: "", qq: "", doc: 0, mode: "now", at: null, diff: null, hv: null, ha: null, keep: false }); },
    select: (id) => () => setState((st) => ({ sel: st.sel === id ? null : id })),
    selectGroup: (name) => () => setState((st) => ({ gsel: st.gsel === name ? null : name, sel: null })),
    setGroup: (k) => () => setState({ group: k, gsel: null }),
    // episodic: "now" is what the memory holds today; "time" is the memory
    // as it stood on one day (at), compared with today
    setMode: (mode, at) => () => setState({ mode, gsel: null, diff: null, ...(at !== undefined ? { at } : {}) }),
    setAt: (t) => setState({ at: t }),
    setDiff: (k) => () => setState((st) => ({ diff: st.diff === k ? null : k })),
    setState,
  }), []);

  const vac = vault ? FAM[vault.type][0] : DEFAULT_AC;
  const vacs = vault ? `color-mix(in oklab, ${vac} 16%, transparent)` : DEFAULT_ACS;

  let body;
  if (!vault) body = html`<${Home} s=${s} C=${C} vaults=${vaults} agents=${agents} overview=${overview} />`;
  else if (!loaded) body = html`<${Note} text="reading the vault…" />`;
  else if (loaded.error) body = html`<${Note} text=${loaded.error} color="var(--rd)" />`;
  else if (vault.type === "episodic") body = html`<${Episodic} key=${vault.id} s=${s} C=${C} vault=${vault} payload=${loaded.data} />`;
  else if (vault.type === "skill") body = html`<${Skill} key=${vault.id} s=${s} C=${C} payload=${loaded.data} />`;
  else body = html`<${Semantic} key=${vault.id} s=${s} C=${C} vault=${vault} payload=${loaded.data} />`;

  return html`
<div class="cv" data-theme=${THEME} data-skin="default" style="min-height:100%;height:100%;display:flex;flex-direction:column;font-size:14px;--ac:${vac};--acs:${vacs}">
<div style="display:flex;align-items:center;gap:12px;padding:16px 40px;font-family:var(--mono);font-size:11px;color:var(--mt);border-bottom:1px solid var(--ln)">
<a href="#" onClick=${(e) => { e.preventDefault(); C.go(); }} style="cursor:pointer;display:flex;align-items:center"><img src=${THEME === "light" ? ASSETS.logoLight : ASSETS.logoDark} alt="ctxvault" style="height:46px;display:block" /></a>
${!source.live && html`<span style="margin-left:auto;font-size:11px;letter-spacing:.1em;text-transform:uppercase">snapshot · ${CV.fmtStamp(Date.parse(source.generatedAt))}</span>`}
</div>
${note && html`<div style="display:flex;align-items:baseline;gap:20px;padding:14px 40px;font-size:15px;line-height:1.5;background:var(--acs);border-bottom:1px solid var(--ln)"><span style="flex:1;text-wrap:pretty">${note}</span><button class="hv-ac" onClick=${() => setNote(null)} style="font:inherit;font-size:13px;color:var(--mt);background:none;border:0;padding:0;cursor:pointer;white-space:nowrap">Dismiss</button></div>`}
${vault && overview && html`<${VaultHeader} key=${vault.id} vault=${vault} payload=${loaded && loaded.data} home=${overview && overview.home}
  bar=${vault.type === "episodic" && loaded && loaded.data ? EpisodicBar({ s, C, count: (loaded.data.episodes || []).length }) : null} />`}
${body}
${failure && html`<div class="failure">${failure}</div>`}
</div>`;
}

// --- a vault's header: what it is, where it lives, and the numbers that matter

const BIG = "font-family:var(--head);font-size:var(--hsz,32px);font-weight:var(--hw,500);letter-spacing:var(--hls,-.02em);line-height:1.1";

function kpisOf(vault, payload) {
  const c = vault.counts || {};
  const last = { n: vault.last ? CV.ago(vault.last) + " ago" : "never", k: vault.type === "semantic" ? "last indexed" : "last change" };
  const disk = { n: CV.bytes(vault.disk || 0), k: "on disk" };
  if (vault.type === "episodic") {
    // the library's own counts (stats): what a default query returns now,
    // and the disputes whose two sides both hold
    return [
      { n: CV.num(c.total ?? 0), k: "statements" },
      { n: c.holding != null ? CV.num(c.holding) : "–", k: "true now" },
      { n: c.disputes != null ? CV.num(c.disputes) : "–", k: "in dispute", warn: (c.disputes || 0) > 0 },
      disk, last,
    ];
  }
  if (vault.type === "skill") {
    return [
      { n: CV.num(c.skills ?? 0), k: c.skills === 1 ? "skill" : "skills" },
      disk, last,
    ];
  }
  return [
    { n: CV.num(c.documents ?? 0), k: c.documents === 1 ? "document" : "documents" },
    { n: CV.num(c.chunks ?? 0), k: "chunks" },
    { n: CV.num(c.out_of_sync ?? 0), k: "out of sync", warn: (c.out_of_sync || 0) > 0 },
    ...(c.unindexed ? [{ n: CV.num(c.unindexed), k: "not indexed", warn: true }] : []),
    disk, last,
  ];
}

// The header reads as an identity card: the type as the map labels its zone,
// the name as the page's title, then where the vault lives, who sees it and
// who may read it as labelled facts, each value set at reading size.
const LABEL = "font-family:var(--zl,var(--head));font-size:12px;font-weight:var(--zlw,500);letter-spacing:var(--zlls,.18em);text-transform:var(--zlup,uppercase);color:var(--mt)";

function shortPath(path, home) {
  if (home && (path === home || path.startsWith(home + "/") || path.startsWith(home + "\\"))) return "~" + path.slice(home.length);
  return path;
}

function VaultHeader({ vault, payload, home, bar }) {
  const [note, setNote] = useState(null);
  const flash = (text) => { setNote(text); setTimeout(() => setNote(null), 4000); };
  const open = () => source.live
    ? source.reveal(vault.id).then(() => flash("opened in the file manager")).catch((e) => flash(String(e.message || e)))
    : navigator.clipboard.writeText(vault.path).then(() => flash("path copied"), () => flash("copy failed"));

  // the folder's own name carries the weight; the directories above it are context
  const shown = shortPath(vault.path || "", home);
  const cut = Math.max(shown.lastIndexOf("/"), shown.lastIndexOf("\\")) + 1;
  const readers = vault.readers || [];

  const facts = [
    ["Location", html`<div style="display:flex;align-items:center;flex-wrap:wrap;gap:10px 16px">
<span title=${vault.path} style="font-family:var(--mono);font-size:16px;overflow-wrap:anywhere"><span style="color:var(--mt)">${shown.slice(0, cut)}</span><span style="color:var(--fg)">${shown.slice(cut)}</span></span>
<button class="hv-btn" onClick=${open} disabled=${!vault.path} style="font:inherit;font-size:13px;color:var(--fg);background:transparent;border:1px solid var(--ln);border-radius:6px;padding:4px 12px;cursor:pointer;white-space:nowrap">${source.live ? "Open folder" : "Copy path"}</button>
${note && html`<span style="font-size:13px;color:var(--mt)">${note}</span>`}
</div>`],
    ["Scope", vault.scope === "global" ? "Global" : "Local"],
    // the library's own words: a vault is public or restricted, and agents
    // are attached to a restricted one (ctxvault attach / detach / make-public)
    ["Access", vault.access === "restricted" ? "Restricted" : "Public"],
    ["Attached agents", vault.access === "restricted"
      ? (readers.length
        ? readers.join(", ")
        : html`<span style="color:var(--rd)">None: no agent can use it</span>`)
      : html`<span style="color:var(--mt)">None needed: any agent can reach it</span>`],
  ];
  if (vault.type === "semantic") facts.push(["Embedding", vault.model
    ? html`<span><span style="font-family:var(--mono)">${vault.model.split("/").pop()}</span>${vault.modelDefault && html`<span style="color:var(--mt)"> · library default</span>`}</span>`
    : html`<span style="color:var(--mt)">library default</span>`]);

  return html`
<div style="padding:36px 40px ${bar ? 0 : 34}px;border-bottom:1px solid var(--ln)">
<div style="${LABEL};font-size:20px;letter-spacing:.16em;line-height:1;color:${FAM[vault.type][0]}">${TYPE_NAME[vault.type] || "vault"}</div>
<h1 style="margin:14px 0 0;font-family:var(--head);font-size:52px;font-weight:var(--hw,500);letter-spacing:var(--hls,-.03em);line-height:1.05;overflow-wrap:anywhere">${vault.id}</h1>
<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:32px 80px;margin-top:28px">
<div style="display:grid;grid-template-columns:max-content minmax(0,1fr);gap:14px 32px;align-items:baseline;font-size:16px;min-width:0;flex:1 1 480px;max-width:760px">
${facts.map(([k, v]) => html`<div style=${LABEL}>${k}</div><div style="min-width:0">${v}</div>`)}
</div>
${!vault.error && html`<div style="display:flex;flex-wrap:wrap;gap:24px 56px">
${kpisOf(vault, payload).map((x) => html`<div><div style=${LABEL}>${x.k}</div><div style="${BIG};margin-top:10px;white-space:nowrap;color:${x.warn ? "var(--rd)" : "var(--fg)"}">${x.n}</div></div>`)}
</div>`}
</div>
${bar && html`<div style="display:flex;align-items:flex-end;gap:40px;margin-top:40px">${bar}</div>`}
</div>`;
}

function Note({ text, color = "var(--mt)" }) {
  return html`<div style="padding:40px;font-family:var(--mono);font-size:12px;color:${color}">${text}</div>`;
}

// --- home: the topology -------------------------------------------------------

// Degrees kept free on each side of a sector: at the inner radius (210) this
// clears the largest sphere (radius 35) plus the name beneath it.
const SECTOR_PAD = 22;
// The map is wider than tall, so equal angles would not give equal room: a
// sector facing sideways reaches much further before the edge. One border
// goes straight up and the other two open 112° from it, which splits the
// visible area into thirds (33/33/33%) and keeps left and right mirrored.
const SEPARATORS = [270, 22, 158];
const ZONE_ARCS = { episodic: [270, 382], skill: [22, 158], semantic: [158, 270] };
// The agents sit in a hexagon, point up, as in the ctxvault mark. Filled with
// the page colour, it also hides where the sector borders meet.
const HEX = [0, 1, 2, 3, 4, 5].map((k) => { const a = ((270 + 60 * k) * Math.PI) / 180; return (500 + 146 * Math.cos(a)).toFixed(1) + "," + (310 + 146 * Math.sin(a)).toFixed(1); }).join(" ");

// What each kind of memory is, in the terms an agent meets it: shown under the
// sector's name while one of its vaults is hovered.
// One line each, after the standard division of long-term memory (Tulving;
// Squire; for agents, CoALA): procedural is knowing how, episodic is what
// happened and when, semantic is knowledge with no context of when it was
// learned. The key word, in the type's colour, is what tells them apart.
const TYPE_DEF = {
  semantic: { lead: "An archive searched by ", key: "meaning", how: "Mixed documents, retrieved by semantic similarity rather than exact words." },
  episodic: { lead: "A record of what ", key: "happened", how: "Dated facts: when each held, and when the memory learned it." },
  skill: { lead: "", key: "How", tail: " to do things", how: "Skills the agent loads and follows when a task calls for them." },
};
const TYPE_NAME = { episodic: "episodic vault", semantic: "semantic vault", skill: "skill vault" };

function Home({ s, C, vaults, agents, overview }) {
  const setState = C.setState;
  const W = 1000, H = 620, cx = 500, cy = 310;
  const P = (x, y) => ({ left: ((x / W) * 100).toFixed(2) + "%", top: ((y / H) * 100).toFixed(2) + "%" });
  const rad = (d) => (d * Math.PI) / 180;
  const home = vaults.map((v) => Object.assign({}, v, {
    open: C.openVault(v), failed: !!v.error, agoTxt: v.last ? CV.ago(v.last) : "",
    isEp: v.type === "episodic", isSem: v.type === "semantic", isSkill: v.type === "skill",
    pub: v.access === "public", restricted: v.access === "restricted",
  }));

  const seps = SEPARATORS.map((d) => ({ x1: cx, y1: cy, x2: (cx + 2400 * Math.cos(rad(d))).toFixed(1), y2: (cy + 2400 * Math.sin(rad(d))).toFixed(1) }));
  const pos = {};
  const hv = s.hv ? home.find((v) => v.id === s.hv) || null : null;
  const hz = hv ? hv.type : null;   // the sector of the hovered vault is tinted
  const wedge = (a0, a1) => { const R = 2400, r0 = 0.01, p = (a, r) => [cx + r * Math.cos(rad(a)), cy + r * Math.sin(rad(a))]; const [x0, y0] = p(a0, r0), [x1, y1] = p(a0, R), [x2, y2] = p(a1, R), [x3, y3] = p(a1, r0); return `M${x0} ${y0} L${x1} ${y1} A${R} ${R} 0 0 1 ${x2} ${y2} L${x3} ${y3} A${r0} ${r0} 0 0 0 ${x0} ${y0}`; };
  const zoneArcs = ZONE_ARCS;
  const zones = CV.TYPES.map((t) => ({ id: t.id, d: wedge(...zoneArcs[t.id]), fill: FAM[t.id][0], op: hz === t.id ? 0.09 : 0 }));
  const zonePos = { episodic: "right:4%;top:8%", semantic: "left:4%;top:8%", skill: "left:4%;bottom:max(12%, 132px)" };
  const zoneLabels = CV.TYPES.map((t) => ({ id: t.id, label: t.label, op: hz && hz !== t.id ? 0.3 : 1, c: FAM[t.id][0], at: zonePos[t.id], def: hz === t.id ? TYPE_DEF[t.id] : null, right: t.id === "episodic" }));

  // A sphere's area follows how much its vault holds, measured against the
  // largest vault of the same type: a fact, a document and a skill are
  // different units, so sizes compare within a sector, never across.
  const largest = {};
  for (const v of home) if (!v.failed) largest[v.type] = Math.max(largest[v.type] || 0, v.size);
  const vnodes = [];
  for (const t of CV.TYPES) {
    const vs = home.filter((v) => v.type === t.id).sort((a, b) => b.size - a.size);
    const n = vs.length;
    // Spread over the sector's own arc, kept clear of its two borders by
    // enough for the largest sphere and the name under it, so no vault ever
    // sits across a separator.
    const [a0, a1] = zoneArcs[t.id];
    const lo = a0 + SECTOR_PAD, hi = a1 - SECTOR_PAD;
    vs.forEach((v, i) => {
      const ang = rad(n === 1 ? (lo + hi) / 2 : lo + (i * (hi - lo)) / (n - 1));
      const r = 226 + (n > 2 && i % 2 ? 56 : 0) + (v.failed ? 36 : 0);   // clear of the hexagon
      const x = cx + r * Math.cos(ang), y = cy + r * Math.sin(ang);
      pos[v.id] = [x, y];
      const sz = ((v.failed ? 26 : 22 + 48 * Math.sqrt(largest[t.id] ? v.size / largest[t.id] : 0)) / 10).toFixed(2);
      const lit = s.ha ? v.readers.includes(s.ha) && !v.failed : true;
      const dim = !lit || (hv && hv.id !== v.id);
      const c = FAM[v.type][0];
      const hot = hv && hv.id === v.id;
      vnodes.push(Object.assign({}, v, P(x, y), { s: sz, ok: !v.failed, c1: c, fill: hot ? mix(c, 70) : mix(c, 32), halo: hot ? mix(c, 35) : "transparent", glowPx: hot ? "2cqw" : "0", tagBorder: hot ? c : "var(--ln)", cursor: v.failed ? "not-allowed" : "pointer", op: dim ? 0.22 : 1, nameColor: v.failed ? "var(--rd)" : "var(--fg)" }));
    });
  }
  const anodes = agents.map((a, i) => {
    // around the label in the middle; turned half a step so that no agent
    // sits straight above the label or out by the hexagon's sides
    const n = agents.length, ang = rad(-90 + (n > 1 ? 180 / n : 0) + (i * 360) / n);
    const x = cx + 82 * Math.cos(ang), y = cy + 72 * Math.sin(ang);
    pos[a] = [x, y];
    const lit = hv ? hv.readers.includes(a) : true;
    const on = s.ha === a || (hv && lit);
    return Object.assign({ a, fill: on ? mix("var(--ac)", 60) : "var(--cl)", ring: on ? "var(--ac)" : "var(--mt)", color: on ? "var(--fg)" : "var(--mt)", op: (s.ha && s.ha !== a) || !lit ? 0.22 : 1 }, P(x, y));
  });
  const links = [];
  // Centre to centre: the spheres are drawn over the SVG, so each end of the
  // line disappears under its own node.
  const link = (a, v) => {
    const [ax, ay] = pos[a], [vx, vy] = pos[v.id];
    links.push({ x1: ax.toFixed(1), y1: ay.toFixed(1), x2: vx.toFixed(1), y2: vy.toFixed(1), dash: v.restricted ? "4 5" : "none", color: FAM[v.type][0] });
  };
  if (s.ha) { for (const v of home) if (!v.failed && v.readers.includes(s.ha) && pos[s.ha]) link(s.ha, v); }
  else if (hv && !hv.failed) { for (const a of hv.readers) if (pos[a]) link(a, hv); }

  let hvInfo = null;
  if (hv) {
    const ago = hv.agoTxt ? ", last " : "";
    const lead = hv.failed ? hv.error
      : hv.isEp ? CV.num(hv.size) + " statements" + (hv.agoTxt ? ", last written " + hv.agoTxt + " ago." : ".")
      : hv.isSem ? hv.size + " documents in " + CV.num(hv.chunks) + " chunks" + (hv.agoTxt ? ago + "indexed " + hv.agoTxt + " ago." : ".")
      : hv.size + " skills" + (hv.agoTxt ? ", last changed " + hv.agoTxt + " ago." : ".");
    const facts = [
      { k: "Access", v: hv.pub ? "Public" : "Restricted", color: "var(--fg)" },
      { k: "Attached agents", v: hv.pub ? "None needed: any agent can reach it" : hv.readers.join(", ") || "None: no agent can use it", color: hv.pub ? "var(--mt)" : hv.readers.length ? "var(--fg)" : "var(--rd)" },
      { k: "On disk", v: CV.bytes(hv.disk || 0), color: "var(--fg)" },
    ];
    const kpis = kpisOf(hv, null).filter((x) => x.k !== "on disk").slice(0, 4);
    const days = (hv.activity || []).slice(-((overview && overview.activity_days) || 30));
    hvInfo = Object.assign({}, hv, { typeTxt: TYPE_NAME[hv.type], typeColor: FAM[hv.type][0], kpis, days, peak: Math.max(1, ...days), facts });
  }
  // An agent here is a name attached to a restricted vault: the library keeps
  // no other register of agents. It can reach the vaults it is attached to and
  // every public one; whether it reads them is not something the vaults record.
  const haList = s.ha ? home.filter((v) => !v.failed && v.readers.includes(s.ha)) : null;
  let haInfo = null;
  if (haList) {
    // what the agent's memory is made of, by type, as on the vault cards
    const count = (t) => haList.filter((v) => v.type === t).length;
    const kpis = [{ n: haList.length, k: haList.length === 1 ? "vault" : "vaults" },
      { n: count("semantic"), k: "semantic" }, { n: count("skill"), k: "skill" }, { n: count("episodic"), k: "episodic" }];
    // its activity: every change in the vaults it reaches, by type
    const DAYS_A = (overview && overview.activity_days) || 30;
    const adays = Array.from({ length: DAYS_A }, (_, i) => {
      const per = {};
      for (const v of haList) per[v.type] = (per[v.type] || 0) + ((v.activity || [])[i] || 0);
      return per;
    });
    const atotal = (d) => (d.episodic || 0) + (d.semantic || 0) + (d.skill || 0);
    // who else sees each vault: that is the isolation, made visible
    const reads = haList.map((v) => {
      const others = v.readers.filter((a) => a !== s.ha);
      return { id: v.id, open: v.open, c: FAM[v.type][0], pub: v.pub, others };
    });
    haInfo = { a: s.ha, kpis, adays, apeak: Math.max(1, ...adays.map(atotal)), achanges: adays.reduce((x, d) => x + atotal(d), 0), reads };
  }
  // --- the machine, when nothing is hovered: size, what is broken, what moved
  const disk = home.reduce((a, v) => a + v.disk, 0);
  const hasDisk = !!overview && overview.vaults.some((v) => "disk_bytes" in v);
  const hasActivity = !!overview && "activity_days" in overview;
  const stats = [{ n: home.length, k: home.length === 1 ? "vault" : "vaults" }, { n: agents.length, k: agents.length === 1 ? "attached agent" : "attached agents" }]
    .concat(hasDisk ? [{ n: CV.bytes(disk), k: "on disk" }] : []);
  const looked = overview ? "read from " + (overview.registry.local || "no project .ctxvault") + " and " + overview.registry.global : "";
  const problems = home.filter((v) => v.failed);
  const DAYS = (overview && overview.activity_days) || 30;
  const days = Array.from({ length: DAYS }, (_, i) => {
    const per = {};
    for (const v of home) per[v.type] = (per[v.type] || 0) + (v.activity[i] || 0);
    return per;
  });
  const dayTotal = (d) => (d.episodic || 0) + (d.semantic || 0) + (d.skill || 0);
  const peak = Math.max(1, ...days.map(dayTotal));
  const changes = days.reduce((a, d) => a + dayTotal(d), 0);
  const dayLabel = (i) => { const d = new Date(Date.parse(overview.today + "T12:00:00")); d.setDate(d.getDate() - (DAYS - 1 - i)); return d.toLocaleDateString(undefined, { day: "numeric", month: "short" }); };
  const idle = home.filter((v) => !v.failed && (!v.last || CV.R.now - v.last > DAYS * CV.DAY));
  const noHover = (!hv && !haInfo) || !!s.keep;

  const head = "font-family:var(--head);font-size:var(--hsz,34px);font-weight:var(--hw,700);letter-spacing:var(--hls,-.02em);line-height:1.1;margin-top:10px";
  // Section headings take the style of the sector labels on the map
  // (uppercase, tracked), so the panel and the map read as one system.
  const heading = "margin-top:48px;display:flex;justify-content:space-between;align-items:baseline;font-family:var(--zl,var(--head));font-size:var(--zlsz,14px);font-weight:var(--zlw,500);letter-spacing:var(--zlls,.18em);text-transform:var(--zlup,uppercase);color:var(--fg)";
  const headingNote = "font-family:var(--mono);font-size:12px;letter-spacing:0;text-transform:none;color:var(--mt);font-weight:400";
  const big = "font-family:var(--head);font-size:var(--hsz,32px);font-weight:var(--hw,500);letter-spacing:var(--hls,-.02em);line-height:1.1";
  const factRow = (f) => html`<div style="display:grid;grid-template-columns:110px 1fr;gap:16px;padding:11px 0;border-bottom:1px solid var(--ln);font-size:14px;line-height:1.4"><span style="color:var(--mt)">${f.k}</span><span style="color:${f.color};overflow-wrap:anywhere">${f.v}</span></div>`;

  return html`
<div style="flex:1;display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,380px);min-height:0">
<div style="position:relative;overflow:hidden;container-type:size;background-image:radial-gradient(var(--dot) 1px, transparent 1.2px);background-size:22px 22px;background-position:11px 11px">
<div style="position:absolute;inset:0;background:radial-gradient(ellipse at 50% 50%, transparent 40%, var(--bg) 100%);pointer-events:none"></div>
<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(100%, calc((100cqh - 120px) * 1000 / 620));aspect-ratio:1000/620;container-type:inline-size">
<svg viewBox="0 0 1000 620" style="position:absolute;inset:0;width:100%;height:100%;display:block;overflow:visible">
${zones.map((z) => html`<path d=${z.d} style="fill:${z.fill};opacity:${z.op};transition:opacity .25s;pointer-events:none"></path>`)}
${seps.map((l) => html`<line x1=${l.x1} y1=${l.y1} x2=${l.x2} y2=${l.y2} style="stroke:var(--ln);stroke-dasharray:2 6;pointer-events:none"></line>`)}
<polygon points=${HEX} style="fill:var(--bg);stroke:var(--ln);stroke-linejoin:round"></polygon>
${links.map((l) => html`<line x1=${l.x1} y1=${l.y1} x2=${l.x2} y2=${l.y2} style="stroke:${l.color};stroke-width:1.5;opacity:.85;stroke-dasharray:${l.dash};pointer-events:none"></line>`)}
</svg>
${vnodes.map((v) => html`
<div key=${v.id} onClick=${v.open} onMouseEnter=${() => setState({ hv: v.id })} onMouseLeave=${() => setState({ hv: null })} style="position:absolute;transform:translate(-50%,-50%);cursor:${v.cursor};opacity:${v.op};transition:opacity .25s;left:${v.left};top:${v.top}">
<div style="width:${v.s}cqw;height:${v.s}cqw;position:relative;display:flex;align-items:center;justify-content:center">
${v.pub && html`<div style="position:absolute;inset:-30%;border-radius:50%;background:radial-gradient(circle, ${v.c1} 0, transparent 70%);opacity:.3;filter:blur(8px)"></div>`}
${v.restricted && html`<div style="position:absolute;inset:-22%;border-radius:50%;border:1.5px dashed ${v.c1};opacity:.7"></div>`}
${v.ok && html`<div style="position:absolute;inset:0;border-radius:50%;background:${v.fill};border:2px solid ${v.c1};box-shadow:0 0 0 0.5cqw ${v.halo}, 0 0 ${v.glowPx} ${v.halo}"></div>`}
${v.failed && html`<div style="position:absolute;inset:0;border-radius:50%;border:2px dashed var(--rd);opacity:.8"></div><span style="position:relative;color:var(--rd);font-size:1.4cqw;line-height:1">×</span>`}
</div>
<div style="position:absolute;top:calc(100% + 8px);left:50%;transform:translateX(-50%);font-family:var(--mono);font-size:clamp(9px,1.05cqw,12px);font-weight:400;white-space:nowrap;padding:3px 8px;border-radius:var(--tagr,4px);background:var(--tagbg,var(--sf));border:1px solid ${v.tagBorder};color:${v.nameColor}">${v.id}</div>
</div>`)}
${anodes.map((a) => html`
<div key=${"agent:" + a.a} onMouseEnter=${() => setState({ ha: a.a })} onMouseLeave=${() => setState({ ha: null })} style="position:absolute;transform:translate(-50%,-50%);cursor:default;opacity:${a.op};transition:opacity .25s;left:${a.left};top:${a.top}">
<div style="width:1.6cqw;height:1.6cqw;min-width:11px;min-height:11px;border-radius:50%;background:${a.fill};border:2px solid ${a.ring};box-shadow:0 0 0 2px var(--bg)"></div>
<div style="position:absolute;top:calc(100% + 6px);left:50%;transform:translateX(-50%);font-family:var(--mono);font-size:clamp(9px,1.05cqw,12px);white-space:nowrap;color:${a.color}">${a.a}</div>
</div>`)}
</div>
<div style="position:absolute;transform:translate(-50%,-50%);pointer-events:none;left:${P(cx, cy).left};top:${P(cx, cy).top}"><span style="display:inline-block;padding-bottom:5px;border-bottom:2px solid ${DEFAULT_AC};font-family:var(--zl,var(--head));font-size:clamp(10px,1.1cqw,13px);font-weight:var(--zlw,500);letter-spacing:var(--zlls,.18em);text-transform:uppercase;color:var(--fg)">Agents</span></div>
${zoneLabels.map((z) => html`<div style="position:absolute;pointer-events:none;opacity:${z.op};transition:opacity .25s;${z.at}"><span style="display:inline-block;white-space:nowrap;padding-bottom:6px;border-bottom:2px solid ${z.c};font-family:var(--zl,var(--head));font-size:var(--zlsz,16px);font-weight:var(--zlw,700);letter-spacing:var(--zlls,.02em);text-transform:var(--zlup,none);color:var(--fg)">${z.label}</span>${z.def && html`<span style="position:absolute;top:calc(100% + 16px);${z.right ? "right" : "left"}:0;width:420px;text-align:${z.right ? "right" : "left"};text-wrap:pretty">
<span style="display:block;font-family:var(--head);font-size:24px;font-weight:500;letter-spacing:-.02em;line-height:1.2;color:var(--fg)">${z.def.lead}<span style="color:${z.c}">${z.def.key}</span>${z.def.tail || ""}.</span>
<span style="display:block;margin-top:10px;font-size:17px;font-weight:300;line-height:1.4;letter-spacing:-.005em;color:var(--fg)">${z.def.how}</span></span>`}</div>`)}
</div>
<div style="border-left:1px solid var(--ln);padding:40px 36px;display:flex;flex-direction:column;min-width:0">
${hvInfo && !s.keep && html`
<div style="${LABEL};font-size:16px;letter-spacing:.16em;line-height:1;color:${hvInfo.typeColor}">${hvInfo.typeTxt}</div>
<h2 style="margin:12px 0 0;font-family:var(--head);font-size:40px;font-weight:var(--hw,500);letter-spacing:var(--hls,-.03em);line-height:1.05;overflow-wrap:anywhere">${hvInfo.id}</h2>
${hvInfo.failed
  ? html`<div style="font-size:16px;line-height:1.5;margin-top:24px;color:var(--rd)">${hvInfo.error}</div>`
  : html`
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px 20px;margin-top:36px">
${hvInfo.kpis.map((x) => html`<div><div style=${LABEL}>${x.k}</div><div style="${BIG};margin-top:10px;white-space:nowrap;color:${x.warn ? "var(--rd)" : "var(--fg)"}">${x.n}</div></div>`)}
</div>
<div style="${LABEL};margin-top:40px">Activity in the last ${hvInfo.days.length} days</div>
${hvInfo.days.some((n) => n)
  ? html`<div style="display:flex;align-items:flex-end;gap:2px;height:44px;margin-top:14px;border-bottom:1px solid var(--ln)">
${hvInfo.days.map((n) => html`<div style="flex:1;height:${n ? Math.max(3, (n / hvInfo.peak) * 44) : 0}px;background:${hvInfo.typeColor}"></div>`)}
</div>`
  : html`<div style="font-size:16px;color:var(--mt);margin-top:14px">No changes</div>`}
<div style="display:grid;grid-template-columns:max-content minmax(0,1fr);gap:14px 24px;align-items:baseline;margin-top:40px;font-size:16px">
${hvInfo.facts.map((f) => html`<div style=${LABEL}>${f.k}</div><div style="color:${f.color};overflow-wrap:anywhere">${f.v}</div>`)}
</div>`}`}
${haInfo && html`
<div style="${LABEL};font-size:16px;letter-spacing:.16em;line-height:1;color:var(--ac)">Agent</div>
<h2 style="margin:12px 0 0;font-family:var(--head);font-size:40px;font-weight:var(--hw,500);letter-spacing:var(--hls,-.03em);line-height:1.05;overflow-wrap:anywhere">${haInfo.a}</h2>
<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px 20px;margin-top:36px">
${haInfo.kpis.map((x) => html`<div><div style=${LABEL}>${x.k}</div><div style="${BIG};margin-top:10px;white-space:nowrap;color:${x.n ? "var(--fg)" : "var(--mt)"}">${x.n}</div></div>`)}
</div>
<div style="${LABEL};margin-top:40px">Activity in the last ${haInfo.adays.length} days</div>
${haInfo.achanges
  ? html`<div style="display:flex;align-items:flex-end;gap:2px;height:44px;margin-top:14px;border-bottom:1px solid var(--ln)">
${haInfo.adays.map((d) => html`<div style="flex:1;height:100%;display:flex;flex-direction:column-reverse">${["episodic", "semantic", "skill"].map((t) => (d[t] ? html`<div style="height:${(d[t] / haInfo.apeak) * 100}%;min-height:3px;background:${FAM[t][0]}"></div>` : null))}</div>`)}
</div>`
  : html`<div style="font-size:16px;color:var(--mt);margin-top:14px">No changes</div>`}
<div style="${LABEL};margin-top:40px">Reachable vaults</div>
<div style="margin-top:12px;border-top:1px solid var(--ln)">
${haInfo.reads.map((v) => html`<div class="hv-ac" onClick=${v.open} style="display:grid;grid-template-columns:auto max-content minmax(0,1fr);gap:12px;align-items:baseline;padding:12px 0;border-bottom:1px solid var(--ln);cursor:pointer;font-size:16px"><span style="width:8px;height:8px;border-radius:50%;background:${v.c};align-self:center"></span><span style="white-space:nowrap">${v.id}</span><span style="color:var(--mt);font-size:14px;text-align:right;line-height:1.4">${v.pub ? "public" : v.others.length ? html`shared with ${v.others.map((a, i) => html`${i ? ", " : ""}<span style="white-space:nowrap">${a}</span>`)}` : "only this agent"}</span></div>`)}
</div>`}
${noHover && html`
<div title=${looked} style="display:flex;justify-content:space-between;gap:20px">
${stats.map((x) => html`<div><div style="${big};white-space:nowrap">${overview ? x.n : "–"}</div><div style="font-size:14px;color:var(--mt);margin-top:6px">${x.k}</div></div>`)}
</div>
${overview && !home.length && html`<div style="font-size:17px;line-height:1.5;margin-top:28px;color:var(--mt);overflow-wrap:anywhere">No vaults in ${overview.registry.local || "a project .ctxvault above " + overview.registry.cwd} or ${overview.registry.global}.</div>`}
${problems.length > 0 && html`
<div style=${heading}>Needs attention</div>
<div style="margin-top:12px;border-top:1px solid var(--ln)">
${problems.map((v) => html`<div onMouseEnter=${() => setState({ hv: v.id, keep: true })} onMouseLeave=${() => setState({ hv: null, keep: false })} title=${v.error} style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;padding:13px 0;border-bottom:1px solid var(--ln);font-size:15px;cursor:default"><span style="overflow-wrap:anywhere">${v.id}</span><span style="color:var(--rd);font-size:14px">${v.problem}</span></div>`)}
</div>`}
${hasActivity && home.length > 0 && html`
<div style=${heading}>Activity<span style=${headingNote}>last ${DAYS} days</span></div>
<div style="display:flex;align-items:baseline;gap:10px;margin-top:16px"><span style=${big}>${CV.num(changes)}</span><span style="font-size:14px;color:var(--mt)">${changes === 1 ? "change" : "changes"}</span></div>
<div style="display:flex;align-items:flex-end;gap:3px;height:150px;margin-top:18px;border-bottom:1px solid var(--ln)">
${days.map((d, i) => html`<div title=${dayLabel(i) + " · " + dayTotal(d) + (dayTotal(d) === 1 ? " change" : " changes")} style="flex:1;height:100%;display:flex;flex-direction:column-reverse">
${["episodic", "semantic", "skill"].map((t) => (d[t] ? html`<div style="height:${(d[t] / peak) * 100}%;min-height:2px;background:${FAM[t][0]}"></div>` : null))}
</div>`)}
</div>
<div style="display:flex;justify-content:space-between;margin-top:8px;font-family:var(--mono);font-size:11px;color:var(--mt)"><span>${dayLabel(0)}</span><span>today</span></div>
${idle.length > 0 && html`
<div style=${heading}>Idle<span style=${headingNote}>no change in ${DAYS} days</span></div>
<div style="margin-top:12px;border-top:1px solid var(--ln)">
${idle.map((v) => html`<div class="hv-ac" onClick=${v.open} onMouseEnter=${() => setState({ hv: v.id, keep: true })} onMouseLeave=${() => setState({ hv: null, keep: false })} style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;padding:13px 0;border-bottom:1px solid var(--ln);font-size:15px;cursor:pointer"><span>${v.id}</span><span style="color:var(--mt);font-size:14px">${v.last ? CV.ago(v.last) + " ago" : "never changed"}</span></div>`)}
</div>`}`}`}
</div>
</div>`;
}

// --- episodic: statements over time -------------------------------------------

function useEpisodic(payload, group) {
  const base = useMemo(() => {
    const all = CV.statements(payload.episodes || []);
    const byId = new Map(all.map((x) => [x.id, x]));
    return { all, byId, t0: CV.earliest(all) };
  }, [payload]);
  const groups = useMemo(() => CV.groupBy(base.all, group), [base, group]);
  const keys = useMemo(() => CV.metaKeys(base.all), [base]);
  return { ...base, groups, keys };
}

// Two views of one vault, chosen from the tabs under the header. "Now" is the
// memory today: what it holds as true, as a table, and beside it what needs a
// look (recent changes, disputes, what is coming). "Over time" is the memory
// as it stood on one day, what differs from today, and how long each
// statement was true.
//
// Three levels of type, each with one job: 12px tracked capitals name things
// (sections, columns), 16px is what is read, 14px grey is the data around it,
// set in its own column. Red is only for disputes, the vault's colour only for
// what is active or selected.
const SMALL = "font-size:14px;color:var(--mt)";
const DATA = "font-size:14px;color:var(--mt);font-variant-numeric:tabular-nums;white-space:nowrap";
const TEXT = "font-size:16px;line-height:1.5;color:var(--fg)";
const HEAD = "display:flex;align-items:center;gap:16px;height:44px;box-sizing:border-box;border-bottom:1px solid var(--fg)";
const TITLE = (c = "var(--fg)") => `${LABEL};color:${c}`;
const BTN = "font:inherit;font-size:14px;color:var(--fg);background:none;border:0;padding:0;cursor:pointer";
const PICK = "font:inherit;font-size:14px;color:var(--fg);background:transparent;border:0;border-bottom:1px solid var(--ln);padding:2px 0;cursor:pointer;outline:0";
const STEP = "font:inherit;font-size:18px;line-height:1;width:36px;height:36px;color:var(--fg);background:transparent;border:1px solid var(--ln);border-radius:6px;cursor:pointer";
const RAIL_W = "clamp(380px, 36vw, 560px)";
const TAB = (on) => `${LABEL};font-size:13px;color:${on ? "var(--fg)" : "var(--mt)"};background:none;border:0;border-bottom:2px solid ${on ? "var(--ac)" : "transparent"};padding:0 0 14px;margin-bottom:-1px;cursor:pointer`;

// What happened, as a tag in its own column, named as the library names the
// operation (write, supersede, revise, invalidate). Each kind keeps one colour.
// The vault does not record why a statement was superseded, so the page does
// not say.
const CHANGE = {
  recorded: { label: "Recorded", c: "var(--ok)" },
  superseded: { label: "Superseded", c: "var(--se2)" },
  revised: { label: "Revised", c: "var(--ep2)" },
  closed: { label: "Closed", c: "var(--mt)" },
};
// Over time: the bars read against the chosen day, three ways only.
const BAR_LOOK = {
  held: { label: "true on the chosen day", bg: "var(--bar)", op: 1 },
  other: { label: "true at another time", bg: "color-mix(in oklab, var(--bar) 35%, var(--bg))", op: 1 },
  revised: { label: "revised: restated, same fact", bg: "repeating-linear-gradient(90deg, var(--bar) 0 5px, transparent 5px 9px)", op: 0.6 },
};
const DIFF = { new: "New since", gone: "No longer true", revised: "Revised since" };
const BINS = 80;

// The tabs and the search, set on the header's bottom rule: they steer the page.
function EpisodicBar({ s, C, count }) {
  return html`
${[["now", "Now"], ["time", "Over time"]].map(([m, l]) => html`<button onClick=${C.setMode(m)} style=${TAB(s.mode === m)}>${l}</button>`)}`;
}

// Search opens the content: it narrows everything below it, in both views
// (changes, disputes, the table, the strip, the bars), so it sits on top of
// them at reading size, says how much it kept, and answers to "/".
function SearchBox({ s, C, total, found }) {
  const box = useRef(null);
  useEffect(() => {
    const key = (e) => {
      if (e.key === "/" && document.activeElement !== box.current && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "")) { e.preventDefault(); box.current?.focus(); }
      else if (e.key === "Escape" && document.activeElement === box.current) { C.setState({ q: "" }); box.current.blur(); }
    };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, []);
  const on = !!s.q.trim();
  return html`
<div style="display:flex;align-items:center;gap:16px;height:60px;margin-bottom:40px;border-bottom:1px solid ${on ? "var(--ac)" : "var(--fg)"}">
<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke=${on ? "var(--fg)" : "var(--mt)"} stroke-width="1.6" style="flex:none"><circle cx="8.5" cy="8.5" r="6"/><path d="M13 13l5 5"/></svg>
<input ref=${box} placeholder=${"Search " + CV.num(total) + " statements: text, entities, metadata"} value=${s.q} onInput=${(e) => C.setState({ q: e.target.value })} style="flex:1;min-width:0;height:100%;font-size:20px;letter-spacing:-.01em" />
${on
  ? html`<span style=${DATA}>${found} of ${CV.num(total)}</span><button class="hv-ac" onClick=${() => C.setState({ q: "" })} style=${BTN}>Clear</button>`
  : null}
</div>`;
}

function GroupPick({ s, C, keys }) {
  return html`<label style="display:flex;align-items:baseline;gap:12px;margin-left:auto"><span style=${LABEL}>Group by</span>
<select value=${s.group} onChange=${(e) => C.setGroup(e.target.value)()} style=${PICK}>${keys.map((k) => html`<option value=${k} style="background:var(--sf);color:var(--fg)">${k}</option>`)}</select></label>`;
}

function Episodic({ s, C, payload }) {
  const setState = C.setState;
  const { all, byId, t0, groups: allGroups, keys } = useEpisodic(payload, s.group);
  CV.setRange(t0);
  const NOW = CV.R.now;
  const filtered = useMemo(() => new Set(CV.search(all, s.q)), [all, s.q]);
  const events = useMemo(() => CV.events(all, byId), [all, byId]);
  const next = useMemo(() => CV.successors(all), [all]);
  const timeMode = s.mode === "time";
  const at = timeMode ? (s.at ?? Math.max(CV.R.t0, NOW - 30 * CV.DAY)) : NOW;
  const atNow = Math.abs(at - NOW) < 60e3;
  const visibleGroups = allGroups.filter((g) => g.items.some((x) => filtered.has(x)));
  const dec = (x) => Object.assign({}, x, {
    st: CV.stateOf(x, at, at), disputed: CV.isDisputed(x, byId, at, at),
    vfTxt: CV.fmt(x.vf), vtTxt: x.vt ? CV.fmt(x.vt) : "open", tfTxt: CV.fmt(x.tf), ttTxt: x.tt ? CV.fmt(x.tt) : "now",
    click: C.select(x.id), selected: s.sel === x.id, confTxt: x.conf.toFixed(2), salTxt: x.sal.toFixed(2),
  });
  const ctx = { s, C, all, byId, events, next, filtered, visibleGroups, keys, at, atNow, NOW, dec };

  // the right column: the statement opened, else (in Now) what needs a look
  const panel = SidePanel({ s, setState, all, byId, next, dec, at, past: timeMode && !atNow });
  return html`
<div style="display:grid;grid-template-columns:minmax(0,1fr) ${RAIL_W};flex:1;min-height:0">
<div style="padding:24px 40px 48px;min-width:0;display:flex;flex-direction:column">
<${SearchBox} s=${s} C=${C} total=${all.length} found=${filtered.size} />
${timeMode ? OverTime(ctx) : html`${Attention(ctx)}${TrueNow(ctx)}`}
</div>
<div style="border-left:1px solid var(--ln);min-width:0"><div style="padding:36px 32px 48px;overflow:hidden auto;position:sticky;top:0;max-height:100vh;box-sizing:border-box">${panel}</div></div>
</div>`;
}

// ---- Now: what the memory holds as true today ------------------------------------

const currentOf = (all, NOW) => new Set(all.filter((x) => CV.stateOf(x, NOW, NOW) === "open"));

function TrueNow({ s, C, all, filtered, visibleGroups, keys, NOW }) {
  const current = currentOf(all, NOW);
  const shown = all.filter((x) => current.has(x) && filtered.has(x));
  const flat = s.group === "none";
  const groups = visibleGroups
    .map((g) => ({ name: g.name, items: g.items.filter((x) => current.has(x) && filtered.has(x)).sort((a, b) => b.vf - a.vf) }))
    .filter((g) => g.items.length).sort((a, b) => b.items.length - a.items.length);
  const limit = flat ? 60 : 5;
  const COLS = "display:grid;grid-template-columns:minmax(0,1fr) 120px 96px;gap:24px;align-items:baseline";
  const row = (x) => html`
<div class="hv-acs" onClick=${C.select(x.id)} style="${COLS};padding:12px 8px;border-bottom:1px solid var(--ln);cursor:pointer;background:${s.sel === x.id ? "var(--acs)" : "transparent"}">
<span style=${TEXT}>${x.text}</span><span style="${DATA};text-align:right">${CV.fmtShort(x.vf)}</span><span style="${DATA};text-align:right">${x.recalls}</span>
</div>`;
  return html`
<div style=${HEAD}><span style=${TITLE()}>True now</span>${GroupPick({ s, C, keys })}</div>
<div style="${COLS};padding:14px 8px 10px;border-bottom:1px solid var(--ln)"><span style=${LABEL}>Statement</span><span style="${LABEL};text-align:right">Since</span><span style="${LABEL};text-align:right">Recalled</span></div>
${!groups.length && html`<div style="${SMALL};padding:16px 8px">${s.q ? "Nothing true now matches the search." : "The memory holds nothing as true today."}</div>`}
${groups.map((g) => {
  const open = s.gsel === g.name, items = g.items.slice(0, open ? Infinity : limit);
  const more = g.items.length > limit;
  return html`
${!flat && html`<div style="display:flex;align-items:baseline;gap:12px;padding:28px 8px 10px;border-bottom:1px solid var(--ln)"><span style="font-size:16px;font-weight:500">${g.name}</span><span style=${DATA}>${g.items.length}</span></div>`}
${items.map(row)}
${more && html`<div style="padding:12px 8px"><button class="hv-ac" onClick=${C.selectGroup(g.name)} style=${BTN}>${open ? "Show fewer" : "Show all " + g.items.length}</button></div>`}`;
})}`;
}

// What needs a look, beside the table: changes, disputes, what is coming.
function Attention({ s, C, all, byId, events, filtered, NOW }) {
  const current = currentOf(all, NOW);
  const week = events.filter((e) => e.t > NOW - 7 * CV.DAY && filtered.has(e.s));
  // each list shows a few, then grows in place; past that, Over time has it all
  const allChanges = week.length ? week : events.filter((e) => filtered.has(e.s)).slice(0, 5);
  const changes = allChanges.slice(0, s.moreCh ? Infinity : 5);
  const allPairs = CV.disputePairs(all, current).filter(([a, b]) => filtered.has(a) || filtered.has(b));
  const pairs = allPairs.slice(0, s.moreDp ? Infinity : 3);
  // a list shows a few, then grows in place
  const grow = (total, key) => total <= (key === "moreCh" ? 5 : 3) ? null
    : html`<div style="padding:12px 8px"><button class="hv-ac" onClick=${() => C.setState({ [key]: !s[key] })} style=${BTN}>${s[key] ? "Show fewer" : "Show all " + total}</button></div>`;
  const allComing = all.filter((x) => CV.stateOf(x, NOW, NOW) === "future" && filtered.has(x)).sort((a, b) => a.vf - b.vf);
  const coming = allComing.slice(0, s.moreCo ? Infinity : 3);
  const section = (title, body, color, action, first) => html`
<div style="${HEAD};margin-top:${first ? 0 : 44}px"><span style=${TITLE(color)}>${title}</span>${action}</div>${body}`;
  const change = (e) => html`
<div class="hv-acs" onClick=${C.select(e.s.id)} style="display:grid;grid-template-columns:96px minmax(0,1fr) auto;gap:16px;align-items:baseline;padding:12px 8px;border-bottom:1px solid var(--ln);cursor:pointer;background:${s.sel === e.s.id ? "var(--acs)" : "transparent"}">
<span style="${LABEL};color:${CHANGE[e.kind].c}">${CHANGE[e.kind].label}</span>
<div style="min-width:0"><div style="${TEXT};color:${e.kind === "closed" ? "var(--mt)" : "var(--fg)"}">${e.s.text}</div>${e.was && html`<div style="${SMALL};margin-top:4px;text-decoration:line-through;text-decoration-color:var(--cl)">${e.was.text}</div>`}</div>
<span style=${DATA}>${CV.ago(e.t)}</span>
</div>`;
  const empty = (text) => html`<div style="${SMALL};padding:14px 8px">${text}</div>`;
  return html`
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:44px 56px;margin-bottom:56px;align-items:start">
<div>${section(week.length ? "Changes in the last 7 days" : "Latest changes",
    changes.length ? html`${changes.map(change)}${grow(allChanges.length, "moreCh")}` : empty("Nothing recorded yet."), undefined,
    null, true)}</div>
<div>${section("In dispute",
    pairs.length ? html`${pairs.map(([a, b], i) => html`<div style="border-left:2px solid var(--rd);margin-top:${i ? 16 : 0}px">${[a, b].map((x) => html`<div class="hv-acs" onClick=${C.select(x.id)} style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:baseline;padding:12px 8px 12px 14px;border-bottom:1px solid var(--ln);cursor:pointer;background:${s.sel === x.id ? "var(--acs)" : "transparent"}"><span style=${TEXT}>${x.text}</span><span style=${DATA}>${CV.fmtShort(x.tf)}</span></div>`)}</div>`)}${grow(allPairs.length, "moreDp")}` : empty("No statements contradict each other."), pairs.length ? "var(--rd)" : undefined, null, true)}
${coming.length > 0 && section("Coming up", html`${coming.map((x) => html`<div class="hv-acs" onClick=${C.select(x.id)} style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:baseline;padding:12px 8px;border-bottom:1px solid var(--ln);cursor:pointer;background:${s.sel === x.id ? "var(--acs)" : "transparent"}"><span style=${TEXT}>${x.text}</span><span style=${DATA}>${CV.fmtShort(x.vf)}</span></div>`)}${grow(allComing.length, "moreCo")}`, undefined, null, false)}</div>
</div>`;
}

// ---- Over time ------------------------------------------------------------------

function OverTime({ s, C, all, events, next, filtered, visibleGroups, keys, at, atNow, NOW }) {
  const span = NOW - CV.R.t0;
  const then = CV.heldAt(all, at), now = CV.heldAt(all, NOW);
  const heldN = all.filter((x) => then.has(x) && filtered.has(x)).length;

  // what differs between that day and today
  const diffs = { new: [], gone: [], revised: [] };
  for (const x of now) if (!then.has(x) && filtered.has(x)) diffs.new.push({ x, t: x.tf > at ? x.tf : x.vf });
  for (const x of then) if (!now.has(x) && filtered.has(x)) {
    const k = next.get(x.id)?.kind === "revised" ? "revised" : "gone";
    diffs[k].push({ x, t: x.tt ?? x.vt ?? NOW, by: next.get(x.id)?.s || null });
  }
  for (const k in diffs) diffs[k].sort((a, b) => b.t - a.t);
  const diffSet = s.diff ? new Set(diffs[s.diff].map((d) => d.x)) : null;

  // the activity strip: what the memory recorded (up) and closed (down)
  const bins = Array.from({ length: BINS }, () => ({ up: 0, down: 0 }));
  for (const e of events) {
    if (!filtered.has(e.s)) continue;
    const i = Math.min(BINS - 1, Math.floor(((e.t - CV.R.t0) / span) * BINS));
    if (i >= 0) e.kind === "closed" ? bins[i].down++ : bins[i].up++;
  }
  const peak = Math.max(1, ...bins.map((b) => Math.max(b.up, b.down)));
  const HALF = 34;
  // the arrows move one calendar day, landing at the day's end so that
  // everything recorded that day counts; past the last day is today
  const dayEnd = (t) => { const d = new Date(t); d.setHours(23, 59, 59, 999); return d.getTime(); };
  const stepDay = (t, n) => { const d = new Date(dayEnd(t)); d.setDate(d.getDate() + n); return d.getTime(); };
  const prevT = stepDay(at, -1) >= CV.R.t0 ? stepDay(at, -1) : undefined;
  const nextT = atNow ? undefined : stepDay(at, 1) >= NOW ? NOW : stepDay(at, 1);
  const drag = (e) => {
    e.preventDefault();
    const r = e.currentTarget.getBoundingClientRect();
    const move = (ev) => { const f = (ev.clientX - r.left) / r.width; C.setAt(f >= 0.995 ? NOW : CV.atFrac(f)); };
    const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up); };
    addEventListener("pointermove", move); addEventListener("pointerup", up); move(e);
  };
  const stop = (e) => e.stopPropagation();
  const atPct = CV.pct(at);
  const ticks = CV.ticks().filter((t) => t.f < 0.92);

  // the bars: how long each statement was true, read against the chosen day
  const someRows = 14;
  const groups = s.moreRows ? visibleGroups : visibleGroups.slice(0, someRows);
  const gap = span * 0.03;
  const lookOf = (x) => (next.get(x.id)?.kind === "revised" ? "revised" : then.has(x) ? "held" : "other");
  const rows = groups.map((g) => {
    const items = g.items.filter((x) => filtered.has(x)).sort((a, b) => a.vf - b.vf);
    const on = s.gsel === g.name, dense = items.length > 40;
    const lanes = [], maxLanes = s.group === "none" ? Infinity : dense ? 6 : 40, lane = new Map();
    for (const x of items) {
      let li = lanes.findIndex((l) => l <= x.vf);
      if (li < 0) { if (lanes.length < maxLanes) { li = lanes.length; lanes.push(0); } else li = lanes.indexOf(Math.min(...lanes)); }
      lanes[li] = (x.vt ?? NOW) + gap; lane.set(x, li);
    }
    const step = dense && s.group !== "none" ? 7 : 8;
    const bars = items.map((x) => {
      const L = BAR_LOOK[lookOf(x)];
      return { x, top: 16 + lane.get(x) * step, left: CV.pct(x.vf), width: ((CV.frac(x.vt ?? NOW) - CV.frac(x.vf)) * 100).toFixed(2) + "%",
        bg: s.sel === x.id ? "var(--ac)" : L.bg, op: diffSet && !diffSet.has(x) ? 0.15 : L.op };
    });
    const list = on ? items.filter((x) => then.has(x)).concat(items.filter((x) => !then.has(x))).slice(0, 40) : [];
    return { g, on, bars, list, rest: on ? items.length - list.length : 0, h: Math.max(58, 22 + lanes.length * step), held: items.filter((x) => then.has(x)).length, total: items.length };
  });
  const validTxt = (x) => CV.fmtShort(x.vf) + " → " + (x.vt ? CV.fmtShort(x.vt) : "now");
  const kpi = (label, n, k) => html`
<button onClick=${k && n ? C.setDiff(k) : null} style="font:inherit;text-align:left;background:none;border:0;padding:0 0 10px;color:var(--fg);cursor:${k && n ? "pointer" : "default"};border-bottom:2px solid ${k && s.diff === k ? "var(--ac)" : "transparent"};opacity:${k && !n ? 0.4 : 1}">
<div style=${LABEL}>${label}</div><div style="font-family:var(--head);font-size:28px;font-weight:500;letter-spacing:-.02em;margin-top:8px">${n}</div></button>`;
  const ROWCOLS = "display:grid;grid-template-columns:minmax(0,1fr) 120px;gap:24px;align-items:baseline";

  return html`
<div style="display:flex;align-items:flex-end;flex-wrap:wrap;gap:24px 56px">
<div style="display:flex;align-items:center;gap:14px">
<button class="hv-btn" title="previous day" disabled=${prevT == null} onClick=${() => C.setAt(prevT)} style="${STEP};opacity:${prevT == null ? 0.3 : 1}">‹</button>
<span style="font-family:var(--head);font-size:var(--hsz,32px);font-weight:500;letter-spacing:-.02em;min-width:210px;text-align:center">${atNow ? "Today" : CV.fmt(at)}</span>
<button class="hv-btn" title="next day" disabled=${nextT == null} onClick=${() => C.setAt(nextT)} style="${STEP};opacity:${nextT == null ? 0.3 : 1}">›</button>
</div>
<div style="display:flex;flex-wrap:wrap;gap:16px 48px;margin-left:auto">
${kpi("True then", heldN)}
${Object.entries(DIFF).map(([k, l]) => kpi(l, diffs[k].length, k))}
</div>
</div>
<div style="display:grid;grid-template-columns:200px minmax(0,1fr);margin-top:40px">
<div style="display:flex;flex-direction:column;justify-content:space-between;height:${2 * HALF}px;padding-right:20px;text-align:right"><span style=${LABEL}>Recorded</span><span style=${LABEL}>Closed</span></div>
<div onPointerDown=${drag} style="position:relative;height:${2 * HALF}px;cursor:crosshair;touch-action:none">
<div style="position:absolute;left:0;right:0;top:${HALF}px;height:1px;background:var(--ln)"></div>
${bins.map((b, i) => html`
${b.up > 0 && html`<div style="position:absolute;bottom:${HALF}px;left:${((i / BINS) * 100).toFixed(2)}%;width:calc(${(100 / BINS).toFixed(3)}% - 2px);height:${Math.max(2, (b.up / peak) * HALF)}px;background:var(--bar)"></div>`}
${b.down > 0 && html`<div style="position:absolute;top:${HALF + 1}px;left:${((i / BINS) * 100).toFixed(2)}%;width:calc(${(100 / BINS).toFixed(3)}% - 2px);height:${Math.max(2, (b.down / peak) * HALF)}px;background:var(--mt);opacity:.6"></div>`}`)}
</div>
<div></div>
<div onPointerDown=${drag} style="position:relative;height:32px;cursor:crosshair;touch-action:none;border-bottom:1px solid var(--fg)">
${ticks.map((t) => html`<span style="position:absolute;bottom:8px;${DATA};left:${(t.f * 100).toFixed(2)}%">${t.label}</span>`)}
<span style="position:absolute;bottom:8px;right:0;${DATA}">today</span>
<div style="position:absolute;bottom:-6px;width:12px;height:12px;margin-left:-6px;background:var(--ac);cursor:grab;z-index:3;left:${atPct}"></div>
</div>
</div>

${s.diff && html`
<div style="margin-top:36px">
<div style="${ROWCOLS};padding:0 8px 10px;border-bottom:1px solid var(--fg)"><span style=${LABEL}>${DIFF[s.diff]}</span><span style="${LABEL};text-align:right">${s.diff === "new" ? "Since" : "Until"}</span></div>
${diffs[s.diff].slice(0, s.diffAll ? 200 : 8).map((d) => html`<div class="hv-acs" onClick=${C.select(d.x.id)} style="${ROWCOLS};padding:12px 8px;border-bottom:1px solid var(--ln);cursor:pointer;background:${s.sel === d.x.id ? "var(--acs)" : "transparent"}"><div><div style=${TEXT}>${d.x.text}</div>${d.by && html`<div style="${SMALL};margin-top:4px">now: ${d.by.text}</div>`}</div><span style="${DATA};text-align:right">${CV.fmtShort(d.t)}</span></div>`)}
${diffs[s.diff].length > 8 && html`<div style="padding:12px 8px"><button class="hv-ac" onClick=${() => C.setState({ diffAll: !s.diffAll })} style=${BTN}>${s.diffAll ? "Show fewer" : "Show all " + diffs[s.diff].length}</button></div>`}
</div>`}
<div style="display:flex;margin-top:${s.diff ? 44 : 32}px;padding-bottom:12px;border-bottom:1px solid var(--ln)">${GroupPick({ s, C, keys })}</div>
<div style="position:relative;display:grid;grid-template-columns:200px minmax(0,1fr);align-content:start">
${rows.map((r) => html`
<div class="hv-ac" onClick=${C.selectGroup(r.g.name)} style="padding:14px 20px 0 0;cursor:pointer;min-height:${r.h}px;box-sizing:border-box;min-width:0"><div style="font-size:16px;font-weight:500;color:${r.on ? "var(--ac)" : "var(--fg)"};overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.g.name}</div><div style="${DATA};margin-top:4px">${atNow ? r.total : r.held + " of " + r.total}</div></div>
<div onPointerDown=${drag} style="position:relative;cursor:crosshair;touch-action:none;min-height:${r.h}px">
${r.bars.map((b) => html`<div class="hv-bar" onClick=${C.select(b.x.id)} onPointerDown=${stop} title=${b.x.text} style="position:absolute;height:4px;min-width:2px;cursor:pointer;background:${b.bg};opacity:${b.op};left:${b.left};width:${b.width};top:${b.top}px"></div>`)}
</div>
${r.on && html`
<div style="grid-column:2;padding:8px 0 28px">
<div style="${ROWCOLS};padding:0 8px 10px;border-bottom:1px solid var(--ln)"><span style=${LABEL}>Statement</span><span style="${LABEL};text-align:right">True</span></div>
${r.list.map((x) => html`<div class="hv-acs" onClick=${C.select(x.id)} style="${ROWCOLS};padding:12px 8px;border-bottom:1px solid var(--ln);cursor:pointer;background:${s.sel === x.id ? "var(--acs)" : "transparent"}"><span style="${TEXT};color:${then.has(x) ? "var(--fg)" : "var(--mt)"}">${x.text}</span><span style="${DATA};text-align:right">${validTxt(x)}</span></div>`)}
${r.rest > 0 && html`<div style="${SMALL};padding:12px 8px">${r.rest} more</div>`}
</div>`}`)}
<div style="position:absolute;top:0;bottom:0;left:200px;right:0;pointer-events:none"><div style="position:absolute;top:0;bottom:0;width:1px;background:var(--ac);left:${atPct}"></div></div>
</div>
<div style="display:flex;flex-wrap:wrap;gap:8px 28px;margin-top:24px;${SMALL}">
<span>${visibleGroups.length > someRows ? html`<button class="hv-ac" onClick=${() => C.setState({ moreRows: !s.moreRows })} style=${BTN}>${s.moreRows ? "Show fewer rows" : "Show all " + visibleGroups.length + " rows"}</button>` : ""}</span>
<span style="margin-left:auto;display:flex;flex-wrap:wrap;gap:8px 24px;align-items:center">
${Object.values(BAR_LOOK).map((L) => html`<span style="display:inline-flex;align-items:center;gap:10px"><span style="display:inline-block;width:24px;height:4px;background:${L.bg};opacity:${L.op}"></span>${L.label}</span>`)}
</span></div>`;
}

// One statement, in the order a reader asks about it: what it says, whether
// it holds, for how long (in the world and in memory), how it changed, how far
// to trust it, whether agents use it. A section shows only when it has
// something to say. Read against the day chosen in Over time, else today.
const STATUS = {
  open: { label: "True now", c: "var(--ok)" },
  then: { label: "True then", c: "var(--ok)" },
  disputed: { label: "In dispute", c: "var(--rd)" },
  closed: { label: "Closed", c: "var(--mt)" },
  superseded: { label: "Superseded", c: "var(--se2)" },
  revised: { label: "Revised", c: "var(--ep2)" },
  future: { label: "Not yet true", c: "var(--mt)" },
  unknown: { label: "Not yet known", c: "var(--mt)" },
};
// keys the library writes into metadata itself: the panel says them as history
const LIBRARY_META = new Set(["invalidation_reason", "revision_of"]);

// Word-level difference between two versions: what was dropped, what added.
function wordDiff(a, b) {
  const A = a.split(/(\s+)/), B = b.split(/(\s+)/);
  const L = Array.from({ length: A.length + 1 }, () => new Array(B.length + 1).fill(0));
  for (let i = A.length - 1; i >= 0; i--) for (let j = B.length - 1; j >= 0; j--)
    L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < A.length && j < B.length) {
    if (A[i] === B[j]) { out.push({ t: B[j], k: "same" }); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) out.push({ t: A[i++], k: "gone" });
    else out.push({ t: B[j++], k: "added" });
  }
  while (i < A.length) out.push({ t: A[i++], k: "gone" });
  while (j < B.length) out.push({ t: B[j++], k: "added" });
  return out;
}

// A word diff helps while most words survive; past that it is noise, and the
// old version reads better whole, struck through, under the new one.
function readableDiff(a, b) {
  const d = wordDiff(a, b), words = d.filter((p) => p.t.trim());
  const kept = words.filter((p) => p.k === "same").length;
  return kept / Math.max(1, words.length) >= 0.5 ? d : null;
}

const PANEL_HEAD = "display:flex;align-items:center;height:40px;border-bottom:1px solid var(--fg);margin-top:40px";
const KV = "display:grid;grid-template-columns:104px minmax(0,1fr);gap:14px 16px;align-items:baseline;margin-top:16px";
const meter = (v) => html`<span style="display:inline-flex;align-items:center;gap:12px"><span style="display:inline-block;width:120px;height:4px;background:var(--cl)"><span style="display:block;height:4px;width:${Math.round(Math.max(0, Math.min(1, v)) * 100)}%;background:var(--bar)"></span></span><span style=${DATA}>${v.toFixed(2)}</span></span>`;

function SidePanel({ s, setState, all, byId, next, dec, at, past }) {
  const raw = s.sel ? byId.get(s.sel) : null;
  if (!raw) return null;
  const x = dec(raw), NOW = CV.R.now;
  const after = next.get(raw.id);
  const date = (t) => CV.fmt(t);

  // whether it holds, in one word and one sentence
  const otherOpen = raw.disputes.map((id) => byId.get(id)).filter((o) => o && CV.stateOf(o, at, at) === "open");
  let st = x.st, sentence;
  if (x.st === "open") {
    st = x.disputed ? "disputed" : past ? "then" : "open";
    sentence = "True since " + date(raw.vf) + (x.disputed ? ", contradicted by " + otherOpen.length + (otherOpen.length === 1 ? " statement." : " statements.") : ".");
  } else if (x.st === "retracted" || x.st === "closed") {
    st = after ? after.kind : "closed";
    sentence = st === "revised" ? "Revised on " + date(raw.tt) + ": restated more precisely, the fact itself unchanged."
      : st === "superseded" ? "Superseded on " + date(raw.tt) + " by the statement that follows it."
      : (raw.tt ? "Closed on " : "Valid until ") + date(raw.vt ?? raw.tt) + ".";
  } else if (x.st === "future") sentence = "Recorded on " + date(raw.tf) + ", true from " + date(raw.vf) + ".";
  else sentence = "The memory learned this on " + date(raw.tf) + ".";
  if (past) sentence = "On " + date(at) + ": " + sentence.charAt(0).toLowerCase() + sentence.slice(1);

  // the two times, on one axis
  const t0 = Math.min(raw.vf, raw.tf, raw.occ ?? Infinity, past ? at : Infinity), t1 = NOW;   // the chosen day stays on the axis
  const pos = (t) => (((t - t0) / Math.max(1, t1 - t0)) * 100).toFixed(2) + "%";
  const lane = (from, to, dot) => html`
<div style="position:relative;height:12px">
<div style="position:absolute;top:4px;height:4px;background:var(--bar);left:${pos(from)};width:calc(${pos(to ?? t1)} - ${pos(from)});min-width:2px"></div>
<div style="position:absolute;top:2px;width:8px;height:8px;margin-left:-4px;border-radius:50%;background:var(--bar);left:${pos(from)}"></div>
${to != null && html`<div style="position:absolute;top:0;width:2px;height:12px;background:var(--bar);left:${pos(to)}"></div>`}
${dot != null && html`<div title=${"happened " + date(dot)} style="position:absolute;top:1px;width:10px;height:10px;margin-left:-5px;border-radius:50%;background:var(--bg);border:2px solid var(--bar);box-sizing:border-box;left:${pos(dot)}"></div>`}
${past && html`<div style="position:absolute;top:-4px;bottom:-4px;width:1px;background:var(--ac);left:${pos(at)}"></div>`}
</div>`;
  const span = (a, b) => CV.fmtShort(a) + " → " + (b == null ? "now" : CV.fmtShort(b));
  const lag = raw.tf - raw.vf, DAY = CV.DAY;
  const lagTxt = lag > DAY ? "The memory learned it " + Math.round(lag / DAY) + " d after it became true."
    : -lag > DAY ? "Recorded " + Math.round(-lag / DAY) + " d before it became true." : "";
  const ROW3 = "display:grid;grid-template-columns:72px minmax(0,1fr) 128px;gap:14px;align-items:center";

  // its versions, oldest first, each shown as the change from the one before
  const chain = CV.chainOf(raw, all, byId).map((c) => c.s);
  const versions = chain.map((v, i) => ({ v, kind: i ? (v.prev && v.prev.kind === "revised" ? "revised" : "superseded") : "first", diff: i ? readableDiff(chain[i - 1].text, v.text) : null, was: i ? chain[i - 1].text : null }));

  const disputes = raw.disputeLog.map((d) => ({ ...d, o: byId.get(d.with) })).filter((d) => d.o && d.t <= at);   // as noticed by the chosen day
  const atts = raw.attestations;
  const bySource = [...atts.reduce((m, a) => (a.source ? m.set(a.source, (m.get(a.source) || 0) + 1) : m), new Map())].sort((a, b) => b[1] - a[1]);
  const meta = Object.entries(raw.meta).filter(([k]) => !LIBRARY_META.has(k));

  return html`
<div style="${DATA};white-space:normal;overflow-wrap:anywhere;margin-bottom:18px">id ${raw.id}</div>
<div style="font-family:var(--head);font-size:24px;line-height:1.3;font-weight:500;letter-spacing:-.02em;text-wrap:pretty">${raw.text}</div>
${raw.entities.length > 0 && html`<div style="margin-top:12px;display:flex;flex-wrap:wrap;gap:4px 16px;font-size:14px"><span style="color:var(--mt)">about</span>${raw.entities.map((e) => html`<button class="hv-ac" onClick=${() => setState({ group: "entity", gsel: e, sel: null })} style=${BTN}>${e}</button>`)}</div>`}

<div style="margin-top:28px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap"><span style="${LABEL};color:${STATUS[st].c}">${STATUS[st].label}</span><span style=${TEXT}>${sentence}</span></div>

<div style=${PANEL_HEAD}><span style=${TITLE()}>Time</span></div>
<div style="display:flex;flex-direction:column;gap:14px;margin-top:18px">
<div style=${ROW3}><span style=${LABEL}>World</span>${lane(raw.vf, raw.vt, raw.occ != null && Math.abs(raw.occ - raw.vf) > 60e3 ? raw.occ : null)}<span style="${DATA};text-align:right">${span(raw.vf, raw.vt)}</span></div>
<div style=${ROW3}><span style=${LABEL}>Memory</span>${lane(raw.tf, raw.tt)}<span style="${DATA};text-align:right">${span(raw.tf, raw.tt)}</span></div>
</div>
${lagTxt && html`<div style="${SMALL};margin-top:12px">${lagTxt}</div>`}

${disputes.length > 0 && html`
<div style=${PANEL_HEAD}><span style=${TITLE(otherOpen.length ? "var(--rd)" : "var(--fg)")}>Contradicted by</span></div>
${disputes.map((d) => html`<div class="hv-acs" onClick=${C_select(setState, d.o.id)} style="padding:12px 8px 12px 14px;border-bottom:1px solid var(--ln);border-left:2px solid ${otherOpen.includes(d.o) ? "var(--rd)" : "var(--ln)"};cursor:pointer">
<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:baseline"><span style=${TEXT}>${d.o.text}</span><span style=${DATA}>${otherOpen.includes(d.o) ? "since " + CV.fmtShort(d.t) : "resolved"}</span></div>
${d.note && html`<div style="${SMALL};margin-top:4px">${d.note}</div>`}</div>`)}`}

${versions.length > 1 && html`
<div style=${PANEL_HEAD}><span style=${TITLE()}>Versions</span></div>
${versions.map(({ v, kind, diff, was }) => html`<div class="hv-acs" onClick=${C_select(setState, v.id)} style="display:grid;grid-template-columns:96px minmax(0,1fr) auto;gap:14px;align-items:baseline;padding:12px 8px;border-bottom:1px solid var(--ln);cursor:pointer;background:${v.id === raw.id ? "var(--acs)" : "transparent"}">
<span style="${LABEL};color:${kind === "first" ? "var(--mt)" : CHANGE[kind].c}">${kind === "first" ? "First" : CHANGE[kind].label}</span>
<span style=${TEXT}>${!diff && was ? html`${v.text}<span style="display:block;${SMALL};margin-top:4px;text-decoration:line-through;text-decoration-color:var(--cl)">${was}</span>` : diff ? diff.map((p) => p.k === "same" ? p.t : p.k === "gone" ? html`<span style="color:var(--mt);text-decoration:line-through">${p.t}</span>` : html`<span style="background:color-mix(in oklab, ${CHANGE[kind].c} 24%, transparent)">${p.t}</span>`) : v.text}</span>
<span style=${DATA}>${CV.fmtShort(v.tf)}</span></div>`)}`}

<div style=${PANEL_HEAD}><span style=${TITLE()}>Trust</span></div>
<div style=${KV}>
<span style=${LABEL}>Source</span><span style=${TEXT}>${raw.source}</span>
<span style=${LABEL}>Confirmed</span>${atts.length
  ? html`<div><div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px"><span style=${TEXT}>${atts.length} ${atts.length === 1 ? "time" : "times"}</span><span style=${DATA}>last ${CV.fmtShort(atts[atts.length - 1].t)}</span></div>
${bySource.length > 0 && html`<div style="${SMALL};margin-top:4px">by ${bySource.map(([k, n]) => k + (n > 1 ? " ×" + n : "")).join(", ")}</div>`}</div>`
  : html`<span style="${TEXT};color:var(--mt)">never</span>`}
<span style=${LABEL} title="How sure the writer was. Recall can leave out statements below a threshold.">Confidence</span>${meter(raw.conf)}
</div>

<div style=${PANEL_HEAD}><span style=${TITLE()}>Use</span></div>
<div style=${KV}>
<span style=${LABEL}>Recalled</span><span style="${TEXT};color:${raw.recalls ? "var(--fg)" : "var(--mt)"}">${raw.recalls ? raw.recalls + (raw.recalls === 1 ? " time" : " times") + (raw.lastRecall ? ", last " + CV.ago(raw.lastRecall) + " ago" : "") : "never"}</span>
<span style=${LABEL} title="How much it matters. Recall ranks by it.">Salience</span>${meter(raw.sal)}
</div>

${meta.length > 0 && html`
<div style=${PANEL_HEAD}><span style=${TITLE()}>Metadata</span></div>
<div style=${KV}>${meta.map(([k, v]) => html`<span style="${LABEL};text-transform:none;letter-spacing:0;font-size:14px">${k}</span><span style="${TEXT};overflow-wrap:anywhere">${v}</span>`)}</div>`}

`;
}
const C_select = (setState, id) => () => setState({ sel: id });

// --- semantic: documents, and recall by meaning --------------------------------

// A document's index can drift from its file: edited since, or deleted. The
// agent keeps getting the old chunks either way, so the page says so.
const SYNC = {
  in_sync: { txt: "In sync", color: "var(--fg)" },
  changed: { txt: "Changed since indexing", color: "var(--rd)" },
  missing: { txt: "Source file missing", color: "var(--rd)" },
};

function docFacts(d, content) {
  const st = SYNC[d.state];
  const out = [];
  if (st) out.push(["State", html`<span style="color:${st.color}">${st.txt}</span>`]);
  if (d.indexed_at) out.push(["Indexed", CV.fmtStamp(CV.ts(d.indexed_at))]);
  if (d.modified_at) out.push(["Modified", CV.fmtStamp(CV.ts(d.modified_at))]);
  out.push(["Chunks", String(d.chunks_count)], ["Type", d.filetype || "—"]);
  for (const [k, v] of Object.entries(d.metadata || {})) out.push([k, v == null ? "—" : String(v)]);
  // the library's own caveat on the reconstructed text, when it has one
  if (content && content.warning) out.push(["Note", html`<span style="color:var(--mt)">${content.warning}</span>`]);
  return out;
}

// One chunk as the agent receives it, whole: what the chunker carried over
// from the chunk before is part of it.
function Chunk({ c, focus }) {
  return html`
<div id=${"chunk-" + c.index} style="display:grid;grid-template-columns:96px minmax(0,1fr);gap:0 20px;padding:24px 0;border-top:1px solid var(--ln);scroll-margin-top:24px">
<div style="border-left:2px solid ${focus ? "var(--ac)" : "transparent"};padding-left:10px;margin-left:-12px">
<div style="${LABEL};color:${focus ? "var(--ac)" : "var(--mt)"}">#${c.index + 1}</div>
<div style="font-size:13px;color:var(--mt);margin-top:6px">${c.words} words</div>
</div>
<div style=${READ_BODY}>${c.text}</div>
</div>`;
}

function Semantic({ s, C, vault, payload }) {
  const setState = C.setState;
  const docs = payload.documents || [];
  const current = docs[s.doc] || null;
  // doc_id -> the document with its chunks | {error}; a snapshot carries them all
  const [contents, setContents] = useState(() => payload.contents || {});
  const [results, setResults] = useState(null);    // null: not asked yet
  const queryBlocked = !source.live;
  const qq = s.qq;
  const hasQuery = !!qq.trim();

  useEffect(() => {
    if (!current || contents[current.doc_id]) return;
    let gone = false;
    source.document(payload.name, current.doc_id)
      .then((c) => !gone && setContents((m) => ({ ...m, [current.doc_id]: c })))
      .catch((e) => !gone && setContents((m) => ({ ...m, [current.doc_id]: { error: String(e.message || e) } })));
    return () => { gone = true; };
  }, [payload.name, current && current.doc_id]);

  useEffect(() => {
    if (!hasQuery || queryBlocked) { setResults(null); return; }
    let gone = false;
    const id = setTimeout(() => {
      source.search(payload.name, qq.trim())
        // the score as the library returns it, the same number `ctxvault query`
        // prints: a similarity in [0, 1] on a cosine collection, else the raw
        // distance of a collection made by an earlier version (lower is closer)
        .then((r) => !gone && setResults(r.results.map((m) => ({ docId: m.doc_id, doc: CV.basename(m.source), chunk: m.chunk_index, text: m.text,
          sim: m.similarity, scoreTxt: m.similarity != null ? m.similarity.toFixed(2) : m.score.toFixed(3) }))))
        .catch(() => !gone && setResults([]));
    }, 250);
    return () => { gone = true; clearTimeout(id); };
  }, [payload.name, qq]);

  const content = current ? contents[current.doc_id] : null;
  // a search hit opens its document at the chunk it matched
  useEffect(() => {
    if (s.focus == null || !content || !content.chunks) return;
    const el = document.getElementById("chunk-" + s.focus);
    if (el) el.scrollIntoView({ block: "start" });
  }, [s.focus, content]);

  const openHit = (r) => () => {
    const i = docs.findIndex((d) => d.doc_id === r.docId);
    if (i >= 0) setState({ doc: i, qq: "", focus: r.chunk });
  };
  const showDoc = !hasQuery && !!current;
  const noResults = hasQuery && results != null && !results.length;

  return html`
<div style="display:grid;grid-template-columns:320px minmax(0,1fr);flex:1">
<div style=${LIST_COL}>
${docs.map((d, i) => html`<div class="hv-ac" onClick=${() => setState({ doc: i, qq: "", focus: null })} style=${ITEM(i === s.doc && !hasQuery)}><div style=${ITEM_NAME}>${CV.basename(d.source)}</div>${d.indexed_at && html`<div style=${ITEM_SUB}>${CV.fmt(CV.ts(d.indexed_at))}</div>`}</div>`)}
${(payload.unindexed || []).length > 0 && html`<div style="${LABEL};margin-top:28px;padding-bottom:8px;border-bottom:1px solid var(--ln);color:var(--rd)">Not indexed</div>
${payload.unindexed.map((f) => html`<div title=${f} style="padding:10px 0;font-size:14px;color:var(--mt);overflow-wrap:anywhere">${CV.basename(f)}</div>`)}`}
</div>
<div style=${READ_COL}>
<input placeholder=${queryBlocked ? "Search by meaning needs a live server" : "Search by meaning, as the agent would"} value=${qq} onInput=${(e) => setState({ qq: e.target.value })} disabled=${queryBlocked} style="width:100%;padding:10px 0;border-bottom:1px solid ${queryBlocked ? "var(--ln)" : "var(--fg)"};font-size:16px;opacity:${queryBlocked ? 0.6 : 1}" />
${hasQuery && html`<div style="margin-top:20px;display:flex;flex-direction:column">
${results && results.length > 0 && html`<div style="${LABEL};padding-bottom:8px">${results[0].sim != null ? "Similarity" : "Distance, lower is closer: reindex the vault for similarities"}</div>`}
${(results || []).map((r) => html`<div class="hv-acs" onClick=${openHit(r)} style="display:grid;grid-template-columns:64px 1fr;gap:16px;padding:16px 0;border-top:1px solid var(--ln);cursor:pointer"><div style="font-size:14px;color:var(--ac);font-variant-numeric:tabular-nums">${r.scoreTxt}${r.sim != null && html`<div style="height:3px;background:var(--ln);margin-top:6px"><div style="height:3px;background:var(--ac);width:${(r.sim * 100).toFixed(0)}%"></div></div>`}</div><div><div style="font-size:16px;line-height:1.6">${r.text}</div><div style="font-size:14px;color:var(--mt);margin-top:6px">${r.doc} · chunk #${r.chunk + 1}</div></div></div>`)}
${noResults && html`<div style="font-size:16px;color:var(--mt);padding:12px 0">Nothing close enough</div>`}</div>`}
${showDoc && html`<h2 style="${READ_TITLE};margin-top:32px">${CV.basename(current.source)}</h2>
<div style="display:flex;flex-wrap:wrap;gap:16px 40px;margin-top:20px">${docFacts(current, content).map(([k, v]) => html`<div style="min-width:0"><div style=${LABEL}>${k}</div><div style="font-size:16px;margin-top:6px;overflow-wrap:anywhere">${v}</div></div>`)}</div>
<div style="margin-top:28px">
${!content ? html`<div style="font-size:16px;color:var(--mt);padding:24px 0;border-top:1px solid var(--ln)">…</div>`
  : content.error ? html`<div style="font-size:16px;color:var(--rd);padding:24px 0;border-top:1px solid var(--ln)">${content.error}</div>`
  : (content.chunks || []).map((c) => html`<${Chunk} key=${c.index} c=${c} focus=${s.focus === c.index} />`)}
</div>`}
</div></div>`;
}

// --- the list | content body shared by the semantic and skill pages ---
// Same scale as the header: 12px tracked labels, 16px for what is read.
const LIST_COL = "border-right:1px solid var(--ln);padding:28px 24px 32px 40px";
const ITEM = (on) => `padding:12px 0;cursor:pointer;color:${on ? "var(--ac)" : "var(--fg)"}`;
const ITEM_NAME = "font-size:16px;font-weight:500;overflow-wrap:anywhere";
const ITEM_SUB = "font-size:14px;line-height:1.45;color:var(--mt);margin-top:4px";
const READ_COL = "padding:32px 40px 48px;width:100%;max-width:840px;margin:0 auto;box-sizing:border-box";
const READ_TITLE = "margin:0;font-family:var(--head);font-size:28px;font-weight:var(--hw,500);letter-spacing:-.02em;line-height:1.2;overflow-wrap:anywhere";
const READ_BODY = "font-size:16px;line-height:1.7;text-wrap:pretty;white-space:pre-wrap";

// --- skill: skills -----------------------------------------------------------

// What the library knows about a skill: its file, when it was last written,
// its size and length, and whatever frontmatter fields the author added
// beyond name and description (the skill's metadata).
function skillFacts(k) {
  const words = (k.instructions || "").trim().split(/\s+/).filter(Boolean).length;
  const out = [["File", k.source || CV.basename(k.path)]];
  if (k.last_modified) out.push(["Modified", CV.fmtStamp(CV.ts(k.last_modified))]);
  out.push(["Length", words + (words === 1 ? " word" : " words")], ["Size", CV.bytes(k.size_bytes || 0)]);
  for (const [key, v] of Object.entries(k.metadata || {})) out.push([key, v == null ? "—" : Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v)]);
  return out;
}

// A skill is markdown, and it is shown read: headings, lists, code, as its
// author laid it out. "Raw" is the file itself, what the agent receives.
function Skill({ s, C, payload }) {
  const skills = payload.skills || [];
  const skill = skills[s.doc] || null;
  const raw = !!s.raw;
  const way = (on, txt) => html`<button class="hv-ac" onClick=${() => C.setState({ raw: on })} style="${BTN};color:${raw === on ? "var(--fg)" : "var(--mt)"}">${txt}</button>`;
  return html`
<div style="display:grid;grid-template-columns:320px minmax(0,1fr);flex:1">
<div style=${LIST_COL}>
${skills.map((k, i) => html`<div class="hv-ac" onClick=${() => C.setState({ doc: i })} style=${ITEM(i === s.doc)}><div style=${ITEM_NAME}>${k.skill_name}</div>${k.description && html`<div style=${ITEM_SUB}>${k.description}</div>`}</div>`)}
</div>
${skill && html`<div style=${READ_COL}><h2 style=${READ_TITLE}>${skill.skill_name}</h2>${skill.description && html`<div style="font-size:16px;color:var(--mt);margin-top:8px">${skill.description}</div>`}
<div style="display:flex;flex-wrap:wrap;gap:16px 40px;margin-top:24px">${skillFacts(skill).map(([k, v]) => html`<div style="min-width:0"><div style=${LABEL}>${k}</div><div style="font-size:16px;margin-top:6px;overflow-wrap:anywhere">${v}</div></div>`)}</div>
<div style="display:flex;justify-content:flex-end;gap:16px;margin-top:24px;padding-top:12px;border-top:1px solid var(--ln)">${way(false, "Rendered")}${way(true, "Raw")}</div>
<div style="${READ_BODY};${raw ? "" : "white-space:normal"};margin-top:12px">${raw ? skill.instructions : MD.render(h, skill.instructions)}</div></div>`}
</div>`;
}

render(html`<${App} />`, document.getElementById("app"));
