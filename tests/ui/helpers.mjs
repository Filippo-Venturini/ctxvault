// The viewer is three plain scripts over vendored Preact: no build step, so
// there is nothing to bundle and nothing to stub. This loads the real
// index.html and runs the real data.js / markdown.js / app.js in a jsdom
// window, with a snapshot set before the app starts.
//
// The scripts are evaluated from their files rather than fetched: jsdom's
// resource loader would race the assertions, and what the tests care about is
// the code that ships, not the way the browser fetches it.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.resolve(here, "../../src/ctxvault/ui/static");

const ORDER = [
  "vendor/preact.umd.js",
  "vendor/preact-hooks.umd.js",
  "vendor/htm.umd.js",
  "data.js",
  "markdown.js",
  "app.js",
];

const read = (file) => fs.readFileSync(path.join(staticDir, file), "utf8");

export async function openViewer({ hash = "", snapshot }) {
  const dom = new JSDOM(fs.readFileSync(path.join(staticDir, "index.html"), "utf8"), {
    // an http origin, not file://: the viewer keeps its state in the hash and
    // history.replaceState refuses to run on a file URL
    url: "http://localhost/ui/" + hash,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });

  const { window } = dom;
  // the app picks its source at load: a snapshot here means no fetch at all
  window.CTXVAULT_SNAPSHOT = snapshot;
  // one script, not six: the viewer's top-level `const`s must see each other,
  // exactly as they do when the browser runs consecutive <script> tags
  window.eval(ORDER.map(read).join("\n;\n"));

  await until(window, () => window.document.querySelector("#app .cv"));
  // the vault's payload arrives on a promise: wait until the page stops saying
  // it is reading, so a caller can look for rows and panels
  await until(window, () => !window.document.body.textContent.includes("reading the vault"));
  return window;
}

// Preact renders synchronously but its effects resolve on the microtask queue
// and its hooks schedule on animation frames; one frame plus a turn is enough.
export async function settle(window) {
  await new Promise((resolve) => window.requestAnimationFrame(resolve));
  await new Promise((resolve) => window.setTimeout(resolve, 0));
}

export async function until(window, predicate, timeout = 2000) {
  const started = Date.now();
  while (!predicate()) {
    if (Date.now() - started > timeout) throw new Error("the viewer did not reach the expected state");
    await settle(window);
  }
}

export const text = (node) => (node.textContent || "").replace(/\s+/g, " ").trim();

export function button(window, label) {
  return [...window.document.querySelectorAll("button")].find((b) => text(b) === label) || null;
}

// Buttons first: a wrapper div often carries the same text as the control
// inside it, and clicking the wrapper would do nothing.
export function byText(window, label) {
  const pick = (selector) => [...window.document.querySelectorAll(selector)].find((n) => text(n) === label) || null;
  return pick("button") || pick("span") || pick("div");
}

export function bar(window, label) {
  return [...window.document.querySelectorAll(".hv-bar")].find((b) => b.getAttribute("title") === label) || null;
}

export async function click(window, node) {
  if (!node) throw new Error("nothing to click");
  node.click();
  await settle(window);
  await settle(window);
}
