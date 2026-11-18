// The memory viewer's three behaviours that until now only reading the code
// could check: a section opened for one statement does not stay open for the
// next, the time cursor does not show what the vault had not recorded yet,
// and closes and reopens come from `closures`.
//
// Each test opens the page with a hash the viewer already supports, then acts
// on it the way a reader does: clicks a row, clicks a control, reads the panel.

import assert from "node:assert/strict";
import test from "node:test";

import { snapshot, GENERATED_AT } from "./fixture.mjs";
import { openViewer, settle, byText, bar, click, text } from "./helpers.mjs";

const VAULT = "bakery-facts";
const CURSOR = Date.parse(GENERATED_AT) - 30 * 86_400_000;   // the page's default day in "Over time"

function panel(window, id) {
  const first = [...window.document.querySelectorAll("div")].find((d) => text(d).startsWith("id " + id));
  assert.ok(first, `the panel for ${id} is not open`);
  return first.parentElement;
}

test("a section opened for one statement is closed for the next", async () => {
  const window = await openViewer({ hash: `#v=${VAULT}&ep=croissants-at-seven`, snapshot: snapshot() });

  const opened = panel(window, "croissants-at-seven");
  assert.match(text(opened), /2 times/, "confirmations start collapsed, as a count");
  assert.doesNotMatch(text(opened), /seed-1/, "metadata is hidden until asked for");

  await click(window, byText(window, "2 times"));
  await click(window, byText(window, "run_id, model"));
  assert.match(text(panel(window, "croissants-at-seven")), /seed-1/, "the nested row opens as well");

  // the next statement: one click in the table, no reload
  await click(window, byText(window, "A second oven arrives on the dock"));
  const next = panel(window, "second-oven");
  assert.match(text(next), /1 time/);
  assert.doesNotMatch(text(next), /seed-1/, "the section opened above must not carry over");
  assert.doesNotMatch(text(next), /seed-4/, "and the next statement starts collapsed too");

  await click(window, byText(window, "1 time"));
  await click(window, byText(window, "run_id, model"));
  assert.match(text(panel(window, "second-oven")), /seed-4/, "the section still opens when asked");
});

test("the time cursor does not know what was recorded after it", async () => {
  const window = await openViewer({ hash: `#v=${VAULT}&m=t&at=${CURSOR}`, snapshot: snapshot() });
  await settle(window);

  await click(window, bar(window, "A second oven arrives on the dock"));
  const late = panel(window, "second-oven");
  assert.match(text(late), /Not yet known/, "recorded after the chosen day");

  await click(window, bar(window, "Rye loaf costs five euros"));
  const earlier = panel(window, "rye-five-euros");
  assert.match(text(earlier), /True then/, "true on the chosen day");
  assert.match(text(earlier), /On \d{1,2} \w{3}/, "the panel reads against that day, not today");
});

test("closes and reopens are rendered from closures", async () => {
  const window = await openViewer({ hash: `#v=${VAULT}&ep=rye-five-euros`, snapshot: snapshot() });
  const panelText = text(panel(window, "rye-five-euros"));

  assert.match(panelText, /Rye loaf costs five euros/);
  assert.match(panelText, /Closed/);
  assert.match(panelText, /price change/);
  assert.match(panelText, /Reopened/);
  assert.match(panelText, /supplier price restored/);
});
