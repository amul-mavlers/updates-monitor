// Run with: node worker/history.test.mjs
// Tests the D1 message history: the protected /api/events endpoint, reading it back, and retention.
import assert from "node:assert/strict";
import worker, { cleanEvents, loadHistory, pruneHistory, sameSecret } from "./index.js";

// A tiny stand-in for a D1 database: just enough SQL handling for the three statements the Worker uses.
function fakeDb({ fail = false } = {}) {
  const rows = [];
  let nextId = 1;
  function exec(sql, args) {
    if (fail) throw new Error("D1 unavailable");
    if (sql.startsWith("INSERT OR IGNORE")) {
      const [item_key, posted_at, source, kind, category, title, spaces, text, link] = args;
      if (rows.some((r) => r.item_key === item_key)) return { meta: { changes: 0 } };
      rows.push({ id: nextId++, item_key, posted_at, source, kind, category, title, spaces, text, link });
      return { meta: { changes: 1 } };
    }
    if (sql.startsWith("SELECT")) {
      const sorted = [...rows].sort((a, b) => b.posted_at.localeCompare(a.posted_at) || b.id - a.id);
      return { results: sorted.slice(0, args[0]) };
    }
    if (sql.startsWith("DELETE")) {
      const before = rows.length;
      for (let i = rows.length - 1; i >= 0; i--) if (rows[i].posted_at < args[0]) rows.splice(i, 1);
      return { meta: { changes: before - rows.length } };
    }
    throw new Error("unexpected SQL: " + sql);
  }
  const stmt = (sql, args) => ({ sql, args, bind: (...a) => stmt(sql, a), run: async () => exec(sql, args), all: async () => exec(sql, args) });
  return { rows, prepare: (sql) => stmt(sql, []), batch: async (list) => list.map((s) => exec(s.sql, s.args)) };
}

const TOKEN = "ingest-secret-token";
const event = (n, extra = {}) => ({
  key: `WooCommerce Dev|item${n}`, posted_at: "2026-11-03T10:0" + n + ":00Z", source: "WooCommerce Dev", kind: "WooCommerce",
  category: "news", title: `Woo 11.${n}`, spaces: ["News"], text: "message", link: "https://developer.woocommerce.com/x", ...extra,
});
const post = (body, token = TOKEN, env) => worker.fetch(
  new Request("https://x/api/events", {
    method: "POST",
    headers: token === null ? {} : { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  }),
  env,
);

// --- authentication ---
let db = fakeDb();
let env = { DB: db, INGEST_TOKEN: TOKEN };
let res = await post({ events: [event(1)] }, null, env);
assert.equal(res.status, 401);
res = await post({ events: [event(1)] }, "wrong-token", env);
assert.equal(res.status, 401);
res = await post({ events: [event(1)] }, TOKEN.slice(0, -1), env);
assert.equal(res.status, 401, "a prefix of the token is not enough");
assert.equal(db.rows.length, 0, "nothing stored without the right token");
const text401 = await res.text();
assert.ok(!text401.includes(TOKEN), "the response never echoes the token");

assert.equal((await post({ events: [event(1)] }, TOKEN, { DB: db })).status, 503, "no INGEST_TOKEN configured");
assert.equal((await post({ events: [event(1)] }, TOKEN, { INGEST_TOKEN: TOKEN })).status, 503, "no database bound");
const get = await worker.fetch(new Request("https://x/api/events"), env);
assert.equal(get.status, 405);
assert.equal(get.headers.get("allow"), "POST");

// --- storing ---
res = await post({ events: [event(1), event(2)] }, TOKEN, env);
assert.equal(res.status, 200);
assert.deepEqual(await res.json(), { stored: 2, received: 2 });
assert.equal(res.headers.get("cache-control"), "no-store");
assert.equal(res.headers.get("x-content-type-options"), "nosniff");
assert.equal(db.rows.length, 2);
assert.equal(db.rows[0].spaces, "News");

res = await post({ events: [event(1), event(2)] }, TOKEN, env);
assert.deepEqual(await res.json(), { stored: 0, received: 2 }, "a resent batch does not duplicate rows");
assert.equal(db.rows.length, 2);

assert.deepEqual(await (await post({ events: [] }, TOKEN, env)).json(), { stored: 0, received: 0 });
assert.equal((await post("{not json", TOKEN, env)).status, 400);
assert.equal((await post("x".repeat(300000), TOKEN, env)).status, 413);

// --- validation ---
const future = new Date(Date.now() + 3 * 86400000).toISOString();
const cleaned = cleanEvents([
  event(1, { key: "" }),                       // no key
  event(2, { category: "evil" }),              // unknown category
  event(3, { posted_at: "not a date" }),
  event(4, { posted_at: future }),             // too far in the future
  null,
  "text",
  event(5, { title: "t".repeat(1000), text: "x".repeat(5000), spaces: ["News", "Nope", "Downtime"], link: "javascript:alert(1)" }),
  event(6, { posted_at: "2026-11-03T10:06:00+05:30" }),
]);
assert.equal(cleaned.length, 2);
assert.equal(cleaned[0].title.length, 300);
assert.equal(cleaned[0].text.length, 2000);
assert.equal(cleaned[0].spaces, "News,Downtime", "unknown spaces are dropped");
assert.equal(cleaned[0].link, "", "non-http links are dropped");
assert.equal(cleaned[1].posted_at, "2026-11-03T04:36:00.000Z", "times are normalised to UTC");
assert.equal(cleanEvents(Array.from({ length: 150 }, (_, i) => event(i % 9 + 1, { key: "k" + i }))).length, 100, "at most 100 events per request");
assert.deepEqual(cleanEvents("nope"), []);

// --- a failing database: reported as retryable, never leaks details ---
const broken = { DB: fakeDb({ fail: true }), INGEST_TOKEN: TOKEN };
res = await post({ events: [event(1)] }, TOKEN, broken);
assert.equal(res.status, 503);
const failText = await res.text();
assert.ok(!failText.includes("D1 unavailable") && !failText.includes(TOKEN));

// --- constant-time comparison helper ---
assert.equal(await sameSecret("abc", "abc"), true);
assert.equal(await sameSecret("abc", "abd"), false);
assert.equal(await sameSecret("abc", "abcd"), false);
assert.equal(await sameSecret("", "x"), false);

// --- reading history for the landing page ---
db = fakeDb();
env = { DB: db, INGEST_TOKEN: TOKEN };
await post({ events: [event(1), event(3), event(2, { category: "security", spaces: ["Downtime"], link: "" })] }, TOKEN, env);
const history = await loadHistory(env);
assert.deepEqual(history.map((h) => h.title), ["Woo 11.3", "Woo 11.2", "Woo 11.1"], "newest first");
assert.deepEqual(history[1].spaces, ["Downtime"]);
assert.equal(history[1].link, "");
assert.ok(!("text" in history[0]), "the full message text is not sent to the page");
assert.equal((await loadHistory(env, 2)).length, 2);
assert.deepEqual(await loadHistory({}), [], "no database: empty history");
assert.deepEqual(await loadHistory({ DB: fakeDb({ fail: true }) }), [], "database error: empty history");

// the landing page shows it, and survives a failing database
const home = await worker.fetch(new Request("https://x/"), env);
assert.equal(home.status, 200);
const html = await home.text();
assert.ok(html.includes("Woo 11.3"), "history reaches the page data");
assert.ok(!html.includes(TOKEN) && !html.includes("a41b7b98"), "no token or database id on the page");
const homeBroken = await worker.fetch(new Request("https://x/"), { ...broken, INGEST_TOKEN: TOKEN });
assert.equal(homeBroken.status, 200, "the page still loads when the database is down");

// --- retention: once a day, 90 days ---
const old = event(1, { key: "old", posted_at: "2026-06-01T00:00:00Z" });
const recent = event(2, { key: "recent", posted_at: "2026-10-30T00:00:00Z" });
db = fakeDb();
env = { DB: db, INGEST_TOKEN: TOKEN };
await post({ events: [old, recent] }, TOKEN, env);
await pruneHistory({ scheduledTime: Date.parse("2026-11-03T12:02:00Z") }, env);
assert.equal(db.rows.length, 2, "not pruned outside the 03:00 UTC window");
await pruneHistory({ scheduledTime: Date.parse("2026-11-03T03:02:00Z") }, env);
assert.deepEqual(db.rows.map((r) => r.item_key), ["recent"], "rows older than 90 days are removed");
await pruneHistory({ scheduledTime: Date.parse("2026-11-03T03:02:00Z") }, { DB: fakeDb({ fail: true }) }); // must not throw
await pruneHistory({ scheduledTime: Date.parse("2026-11-03T03:02:00Z") }, {});

console.log("history tests passed");
