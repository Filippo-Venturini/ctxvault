// Markdown, read. A skill is a markdown file, and the skill page shows it
// the way its author wrote it to be read: headings, lists, code, tables,
// links. The subset is what skills use; what the parser does not know stays
// visible as text, never dropped.
//
// Vault content is written by agents and a snapshot is published, so this
// never builds HTML from it. It builds Preact nodes through `h`: text is
// text, a link is a link only to http(s) or mailto, and an image is shown as
// a link to its source rather than loaded. Chunks of a semantic vault do not
// come here: a chunk is a fragment, shown as the agent receives it.

const MD = (() => {
  const CODE_FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace";
  const CODE = `font-family:${CODE_FONT};font-size:14px;background:var(--sf);border:1px solid var(--ln);border-radius:4px;padding:1px 5px`;
  const PRE = `font-family:${CODE_FONT};font-size:14px;line-height:1.55;background:var(--sf);border:1px solid var(--ln);border-radius:6px;padding:14px 16px;margin:16px 0;overflow-x:auto;white-space:pre`;
  const H = ["", "font-size:24px;margin:32px 0 12px", "font-size:21px;margin:28px 0 10px", "font-size:18px;margin:24px 0 8px",
    "font-size:16px;margin:20px 0 6px", "font-size:16px;margin:20px 0 6px;color:var(--mt)", "font-size:16px;margin:20px 0 6px;color:var(--mt)"];
  const HEAD = "font-family:var(--head);font-weight:500;letter-spacing:-.02em;line-height:1.25;text-wrap:pretty";
  const P = "margin:0 0 14px";
  const LIST = "margin:0 0 14px;padding-left:26px";
  const LI = "margin:4px 0";
  const QUOTE = "margin:0 0 14px;padding-left:16px;border-left:2px solid var(--ln);color:var(--mt)";
  const HR = "border:0;border-top:1px solid var(--ln);margin:24px 0";
  const TABLE = "border-collapse:collapse;margin:0 0 16px;font-size:15px;display:block;overflow-x:auto;max-width:100%";
  const TH = "text-align:left;font-weight:500;padding:6px 14px 6px 0;border-bottom:1px solid var(--fg);white-space:nowrap";
  const TD = "padding:6px 14px 6px 0;border-bottom:1px solid var(--ln);vertical-align:top";
  const LINK = "color:var(--ac);text-decoration:underline;text-underline-offset:3px";

  const FENCE = /^\s{0,3}(`{3,}|~{3,})\s*(\S*)/;
  const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
  const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
  const QUOTED = /^\s{0,3}>\s?(.*)$/;
  const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
  const ROW = /^\s*\|.*\|\s*$/;
  const DIVIDER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

  const safeUrl = (url) => /^(https?:|mailto:|#)/i.test(url.trim()) ? url.trim() : null;

  // --- inline: code spans, emphasis, links, escapes --------------------------

  const INLINE = new RegExp([
    "\\\\([\\\\`*_~\\[\\]()#>|!-])",                  // 1 escape
    "(`+)([\\s\\S]*?[^`])\\2(?!`)",                    // 2 fence, 3 code
    "(\\*\\*|__)(?=\\S)([\\s\\S]*?\\S)\\4",            // 4, 5 strong
    "(\\*|_)(?=\\S)([\\s\\S]*?\\S)\\6",                // 6, 7 emphasis
    "~~(?=\\S)([\\s\\S]*?\\S)~~",                      // 8 strike
    "(!?)\\[([^\\]]*)\\]\\(((?:[^()\\s]|\\([^()\\s]*\\))+)(?:\\s+\"[^\"]*\")?\\)",  // 9 image?, 10 text, 11 url (one level of parentheses)
    "<((?:https?:|mailto:)[^>\\s]+)>",                 // 12 autolink
  ].join("|"));

  function inline(h, text) {
    const out = [];
    let rest = text;
    while (rest) {
      const m = INLINE.exec(rest);
      if (!m) { out.push(rest); break; }
      const before = rest.slice(0, m.index);
      // "_" and "__" mark emphasis only at a word edge: snake_case stays as it is
      const underscore = (m[4] === "__" || m[6] === "_") && /\w$/.test(before);
      if (underscore) { out.push(before + m[0][0]); rest = rest.slice(m.index + 1); continue; }
      if (before) out.push(before);
      if (m[1] != null) out.push(m[1]);
      else if (m[3] != null) out.push(h("code", { style: CODE }, m[3].replace(/^ (.*) $/, "$1")));
      else if (m[5] != null) out.push(h("strong", { style: "font-weight:600" }, inline(h, m[5])));
      else if (m[7] != null) out.push(h("em", null, inline(h, m[7])));
      else if (m[8] != null) out.push(h("s", null, inline(h, m[8])));
      else if (m[10] != null) out.push(link(h, m[9] ? (m[10] || m[11]) : inline(h, m[10]), m[11]));
      else if (m[12] != null) out.push(link(h, m[12], m[12]));
      rest = rest.slice(m.index + m[0].length);
    }
    return out;
  }

  function link(h, children, url) {
    const href = safeUrl(url);
    if (!href) return h("span", null, children);
    return h("a", { href, target: "_blank", rel: "noreferrer noopener", style: LINK }, children);
  }

  // --- blocks ----------------------------------------------------------------

  function blocks(h, lines) {
    const out = [];
    let i = 0;
    const para = [];
    const flush = () => {
      if (!para.length) return;
      out.push(h("p", { style: P }, lines_(h, para.splice(0))));
    };
    while (i < lines.length) {
      const line = lines[i];
      let m;
      if (!line.trim()) { flush(); i++; continue; }
      if ((m = FENCE.exec(line))) {
        flush();
        const close = new RegExp("^\\s{0,3}" + m[1][0] + "{" + m[1].length + ",}\\s*$");
        let j = i + 1;
        while (j < lines.length && !close.test(lines[j])) j++;
        out.push(h("pre", { style: PRE }, h("code", null, lines.slice(i + 1, j).join("\n"))));
        i = j + 1;
        continue;
      }
      if ((m = HEADING.exec(line))) {
        flush();
        const level = m[1].length;
        out.push(h("h" + level, { style: HEAD + ";" + H[level] }, inline(h, m[2])));
        i++;
        continue;
      }
      if (RULE.test(line)) { flush(); out.push(h("hr", { style: HR })); i++; continue; }
      if (QUOTED.test(line)) {
        flush();
        const inner = [];
        while (i < lines.length && (m = QUOTED.exec(lines[i]))) { inner.push(m[1]); i++; }
        out.push(h("blockquote", { style: QUOTE }, blocks(h, inner)));
        continue;
      }
      if (ITEM.test(line)) {
        flush();
        const [node, next] = list(h, lines, i);
        out.push(node);
        i = next;
        continue;
      }
      if (ROW.test(line) && i + 1 < lines.length && DIVIDER.test(lines[i + 1])) {
        flush();
        const head = cells(line);
        const rows = [];
        let j = i + 2;
        while (j < lines.length && lines[j].includes("|") && lines[j].trim()) { rows.push(cells(lines[j])); j++; }
        out.push(h("table", { style: TABLE },
          h("thead", null, h("tr", null, head.map((c, k) => h("th", { key: k, style: TH }, inline(h, c))))),
          h("tbody", null, rows.map((r, k) => h("tr", { key: k }, head.map((_, c) => h("td", { key: c, style: TD }, inline(h, r[c] || ""))))))));
        i = j;
        continue;
      }
      para.push(line);
      i++;
    }
    flush();
    return out;
  }

  // A paragraph's lines, soft breaks joined; two trailing spaces break the line.
  function lines_(h, ls) {
    const out = [];
    ls.forEach((l, k) => {
      if (k) out.push(/ {2,}$/.test(ls[k - 1]) ? h("br") : " ");
      out.push(...inline(h, l.replace(/\s+$/, "")));
    });
    return out;
  }

  const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").replace(/\\\|/g, "\u0000").split("|").map((c) => c.trim().replace(/\u0000/g, "|"));

  // Items start at the marker's indent; what is indented past it belongs to
  // the item, blank lines included when something indented follows. An item
  // of one paragraph stays on its line (a tight list); anything more is
  // laid out as blocks, nested lists among them.
  function list(h, lines, start) {
    const first = ITEM.exec(lines[start]);
    const indent = first[1].length;
    const ordered = /\d/.test(first[2]);
    const items = [];
    let i = start;
    while (i < lines.length) {
      const m = ITEM.exec(lines[i]);
      if (!m || m[1].length !== indent || /\d/.test(m[2]) !== ordered) break;
      const width = m[1].length + m[2].length + 1;
      const body = [m[3]];
      i++;
      while (i < lines.length) {
        const l = lines[i];
        if (!l.trim()) {
          const after = lines[i + 1];
          if (after != null && after.trim() && leading(after) > indent) { body.push(""); i++; continue; }
          break;
        }
        if (leading(l) <= indent) break;
        body.push(l.slice(Math.min(width, leading(l))));
        i++;
      }
      items.push(body);
      if (i < lines.length && !lines[i].trim() && i + 1 < lines.length && ITEM.test(lines[i + 1]) && leading(lines[i + 1]) === indent) i++;
    }
    const startAt = ordered ? parseInt(first[2], 10) : null;
    const nodes = items.map((body, k) => {
      const inner = blocks(h, body);
      const tight = inner.length === 1 && inner[0].type === "p";
      return h("li", { key: k, style: LI }, tight ? inner[0].props.children : inner);
    });
    const props = { style: LIST };
    if (startAt != null && startAt !== 1) props.start = startAt;
    return [h(ordered ? "ol" : "ul", props, nodes), i];
  }

  const leading = (l) => l.length - l.replace(/^\s+/, "").length;

  // The text as a list of nodes to put inside any element.
  const render = (h, text) => blocks(h, String(text || "").replace(/\r\n?/g, "\n").split("\n"));

  return { render };
})();
