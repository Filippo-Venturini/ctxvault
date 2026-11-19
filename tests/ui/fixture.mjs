// A snapshot the memory viewer can open cold: one episodic vault, three
// statements, fixed timestamps. The page reads a snapshot exactly as it reads
// the live server, so the tests drive the real app over this instead of a
// browser and a running vault.
//
// The three statements are chosen so the time cursor has something to hide:
// the oven only becomes known after the cursor's default day.

export const GENERATED_AT = "2026-03-20T09:00:00Z";

const episode = (over) => ({
  entities: [],
  source: "owner",
  confidence: 0.9,
  salience: 0.5,
  occurred_at: null,
  valid_to: null,
  invalidated_at: null,
  superseded_by: null,
  revised_by: null,
  reopened_at: null,
  reopen_reason: null,
  recall_count: 0,
  last_recalled_at: null,
  confirmed_count: 0,
  last_confirmed_at: null,
  disputed_with: [],
  metadata: {},
  attestations: [],
  disputes: [],
  closures: [],
  ...over,
});

const episodes = [
  // true before the cursor's day, and confirmed twice with metadata: the
  // disclosure test opens this one first.
  episode({
    id: "croissants-at-seven",
    content: "Butter croissants come out at seven",
    entities: ["croissant"],
    valid_from: "2026-02-01T06:00:00+00:00",
    recorded_at: "2026-02-01T06:00:00+00:00",
    confirmed_count: 1,
    last_confirmed_at: "2026-03-01T09:00:00+00:00",
    metadata: { topic: "opening" },
    attestations: [
      { at: "2026-02-02T09:00:00+00:00", source: "staff", metadata: { run_id: "seed-1", model: "gpt-5" } },
      { at: "2026-03-01T09:00:00+00:00", source: "owner", metadata: { run_id: "seed-2" } },
    ],
  }),
  // recorded after the cursor's day: the time cursor must not know it yet.
  episode({
    id: "second-oven",
    content: "A second oven arrives on the dock",
    valid_from: "2026-03-19T08:00:00+00:00",
    recorded_at: "2026-03-19T08:00:00+00:00",
    confirmed_count: 1,
    last_confirmed_at: "2026-03-19T09:00:00+00:00",
    attestations: [
      { at: "2026-03-19T09:00:00+00:00", source: "dock", metadata: { run_id: "seed-4", model: "gpt-5" } },
    ],
  }),
  // closed in March, reopened a week later: both events come from closures.
  episode({
    id: "rye-five-euros",
    content: "Rye loaf costs five euros",
    valid_from: "2026-01-05T00:00:00+00:00",
    valid_to: "2026-03-05T00:00:00+00:00",
    recorded_at: "2026-01-05T00:00:00+00:00",
    invalidated_at: "2026-03-05T00:00:00+00:00",
    metadata: { invalidation_reason: "price change" },
    closures: [
      {
        closed_at: "2026-03-05T00:00:00+00:00",
        valid_to: "2026-03-05T00:00:00+00:00",
        superseded_by: null,
        revised_by: null,
        reason: "price change",
        reopened_at: "2026-03-12T00:00:00+00:00",
        reopen_reason: "supplier price restored",
        metadata: { run_id: "close-1" },
        reopen_metadata: { run_id: "reopen-1" },
      },
    ],
  }),
];

const activity = Array.from({ length: 30 }, (_, i) => (i === 13 ? 3 : 0));

export function snapshot() {
  // a fresh object every call: the page owns what it reads
  return JSON.parse(JSON.stringify({
    generated_at: GENERATED_AT,
    today: GENERATED_AT,
    activity_days: 30,
    registry: { local: null, global: "D:\\vaults" },
    home: "D:\\vaults",
    vaults: [
      {
        name: "bakery-facts",
        type: "episodic",
        scope: "local",
        path: "D:\\vaults\\bakery-facts",
        restricted: false,
        allowed_agents: [],
        embedding_model: null,
        embedding_default: false,
        disk_bytes: 40960,
        counts: { total: 3, open: 2, closed: 1, holding: 2, disputes: 0, entities: 3 },
        last_activity: "2026-03-19T08:00:00+00:00",
        activity,
        payload: {
          name: "bakery-facts",
          type: "episodic",
          episodes,
          entities: [],
          stats: { total: 3, open: 2, closed: 1, holding: 2, disputes: 0 },
        },
      },
    ],
  }));
}
