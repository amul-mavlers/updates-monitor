// Run with: node worker/test.mjs
import assert from "node:assert/strict";
import worker, { dispatch, daysLeft, missingSettings, cleanCatalog } from "./index.js";

// no real waiting in the retry pause
globalThis.setTimeout = (fn) => { fn(); return 0; };

const env = { GH_TOKEN: "tok", REPO: "o/r", WORKFLOW: "w.yml", REF: "main" };
const calls = [];
let githubStatus = 204;
globalThis.fetch = async (url, init) => {
  calls.push({ url, init });
  if (String(url).startsWith("https://api.github.com")) {
    return new Response(githubStatus === 204 ? null : '{"message":"Bad credentials"}', { status: githubStatus });
  }
  return new Response("ok", { status: 200 }); // Chat webhook
};
const chatCalls = () => calls.filter((c) => !String(c.url).startsWith("https://api.github.com"));
const at = (iso) => ({ scheduledTime: Date.parse(iso) });

// dispatch: URL, headers, body, token trimming
await dispatch(env);
assert.equal(calls[0].url, "https://api.github.com/repos/o/r/actions/workflows/w.yml/dispatches");
assert.equal(calls[0].init.method, "POST");
assert.equal(calls[0].init.headers.Authorization, "Bearer tok");
assert.equal(JSON.parse(calls[0].init.body).ref, "main");
await dispatch({ ...env, GH_TOKEN: "  tok\n" });
assert.equal(calls.at(-1).init.headers.Authorization, "Bearer tok");

// failure gives an actionable hint
githubStatus = 401;
await assert.rejects(dispatch(env), /HTTP 401 \(token invalid/);
githubStatus = 404;
await assert.rejects(dispatch(env), /HTTP 404 \(token needs Actions/);

// scheduled(): failing dispatch is rethrown AND posted to Chat, but only on the first tick of an hour
const alerts = { ...env, GCHAT_WEBHOOK_ALERTS: "https://chat.example/alerts" };
async function runScheduled(e, event) {
  const pending = [];
  await worker.scheduled(event, e, { waitUntil: (p) => pending.push(p) });
  await Promise.all(pending);
}
githubStatus = 401;
calls.length = 0;
await assert.rejects(runScheduled(alerts, at("2026-10-26T10:02:00Z")), /HTTP 401/);
assert.equal(chatCalls().length, 1);
assert.match(JSON.parse(chatCalls()[0].init.body).text, /cannot start the workflow/);
calls.length = 0;
await assert.rejects(runScheduled(alerts, at("2026-10-26T10:32:00Z")), /HTTP 401/);
assert.equal(chatCalls().length, 0, "no repeat alert within the same hour");
calls.length = 0;
await assert.rejects(runScheduled(env, at("2026-10-26T11:01:00Z")), /HTTP 401/); // no webhook configured
assert.equal(chatCalls().length, 0);

// healthy runs stay silent
githubStatus = 204;
calls.length = 0;
await runScheduled(alerts, at("2026-10-26T12:02:00Z"));
assert.equal(chatCalls().length, 0);

// token expiry reminder: daily at 04:00 UTC, only inside the last 14 days
const soon = { ...alerts, TOKEN_EXPIRES: "2026-11-02" };
assert.equal(daysLeft(soon, Date.parse("2026-10-26T04:02:00Z")), 7);
assert.equal(daysLeft({ TOKEN_EXPIRES: "garbage" }, Date.now()), null);
calls.length = 0;
await runScheduled(soon, at("2026-10-26T04:02:00Z"));
assert.match(JSON.parse(chatCalls()[0].init.body).text, /expires in 7 days/);
calls.length = 0;
await runScheduled(soon, at("2026-10-26T05:02:00Z"));
assert.equal(chatCalls().length, 0, "reminder only at 04:00 UTC");
calls.length = 0;
await runScheduled({ ...alerts, TOKEN_EXPIRES: "2027-03-01" }, at("2026-10-26T04:02:00Z"));
assert.equal(chatCalls().length, 0, "too early to remind");
calls.length = 0;
await runScheduled({ ...alerts, TOKEN_EXPIRES: "2026-10-20" }, at("2026-10-26T04:02:00Z"));
assert.match(JSON.parse(chatCalls()[0].init.body).text, /has expired/);

// /health: only "ok / not configured", nothing about the repo, token or webhooks; safe headers
const page = await worker.fetch(new Request("https://x/health"), { ...soon, GH_TOKEN: "secret-token-value" });
assert.equal(page.status, 200);
const text = await page.text();
assert.equal(text, "feed-alerts-trigger: ok\n");
for (const leak of ["secret-token-value", "o/r", "w.yml", "chat.example", "2026-11-02", "days"]) {
  assert.ok(!text.includes(leak), `status page must not reveal ${leak}`);
}
assert.equal(page.headers.get("x-content-type-options"), "nosniff");
assert.equal(page.headers.get("cache-control"), "no-store");
assert.equal(page.headers.get("x-robots-tag"), "noindex");
assert.match(page.headers.get("content-security-policy"), /default-src 'none'/);
const bare = await worker.fetch(new Request("https://x/health"), { REPO: "o/r" });
assert.equal(bare.status, 503);
assert.equal(await bare.text(), "feed-alerts-trigger: not configured\n");
assert.equal((await worker.fetch(new Request("https://x/health", { method: "HEAD" }), alerts)).status, 200);
const post405 = await worker.fetch(new Request("https://x/health", { method: "POST" }), alerts);
assert.equal(post405.status, 405);
assert.equal(post405.headers.get("allow"), "GET, HEAD");

// missing settings are named (never their values) in the log and the alert
assert.deepEqual(missingSettings({ REPO: "o/r" }), ["GH_TOKEN", "WORKFLOW"]);
calls.length = 0;
await assert.rejects(runScheduled({ ...alerts, GH_TOKEN: "" }, at("2026-10-26T13:01:00Z")), /missing settings: GH_TOKEN/);
assert.equal(calls.filter((c) => String(c.url).startsWith("https://api.github.com")).length, 0);
assert.match(JSON.parse(chatCalls()[0].init.body).text, /missing settings: GH_TOKEN/);

// retry: a transient GitHub error is retried once and raises no alarm; real errors are not retried
const statuses = [502, 204];
globalThis.fetch = async (url, init) => {
  calls.push({ url, init });
  if (String(url).startsWith("https://api.github.com")) return new Response(null, { status: statuses.shift() ?? 204 });
  return new Response("ok", { status: 200 });
};
calls.length = 0;
await runScheduled(alerts, at("2026-10-26T14:01:00Z"));
assert.equal(calls.filter((c) => String(c.url).startsWith("https://api.github.com")).length, 2, "retried once");
assert.equal(chatCalls().length, 0, "a recovered blip raises no alarm");

statuses.push(502, 502);
calls.length = 0;
await assert.rejects(runScheduled(alerts, at("2026-10-26T15:01:00Z")), /HTTP 502/);
assert.equal(calls.filter((c) => String(c.url).startsWith("https://api.github.com")).length, 2, "gives up after one retry");
assert.equal(chatCalls().length, 1, "persistent failure is reported");

statuses.push(401);
calls.length = 0;
await assert.rejects(runScheduled(alerts, at("2026-10-26T16:01:00Z")), /HTTP 401/);
assert.equal(calls.filter((c) => String(c.url).startsWith("https://api.github.com")).length, 1, "401 is not retried");


// landing page: served at "/", strict CSP with a per-request nonce, data from catalog.json, nothing sensitive
const catalogUrl = "https://raw.example/catalog.json";
const goodCatalog = {
  updated: "2026-11-02T17:30:10Z",
  cards: [
    { cat: "news", source: "WooCommerce Dev", kind: "WooCommerce", spaces: ["News"], text: "hello *world*", live: true, note: "" },
    { cat: "evil", source: "x", kind: "x", spaces: ["News"], text: "dropped: unknown category", live: true, note: "" },
    { cat: "incidents", source: "GitHub", kind: "Resolved", spaces: ["Downtime", "NotASpace"], text: "</script><img src=x onerror=alert(1)>", live: false, note: "" },
  ],
  routing: [{ source: "GitHub Status", how: "Status page API", space: "Downtime", extra: "" }],
};
let catalogResponse = () => new Response(JSON.stringify(goodCatalog), { status: 200 });
globalThis.fetch = async (url, init) => {
  calls.push({ url, init });
  if (String(url) === catalogUrl) return catalogResponse();
  return new Response("ok", { status: 200 });
};
const site = { ...alerts, GH_TOKEN: "secret-token-value", CATALOG_URL: catalogUrl };
const home = await worker.fetch(new Request("https://x/"), site);
assert.equal(home.status, 200);
assert.match(home.headers.get("content-type"), /text\/html/);
const homeHtml = await home.text();
const csp = home.headers.get("content-security-policy");
const nonce = /script-src 'nonce-([^']+)'/.exec(csp)[1];
assert.ok(homeHtml.includes(`<script nonce="${nonce}">`), "script carries the CSP nonce");
assert.match(csp, /default-src 'none'/);
assert.match(csp, /frame-ancestors 'none'/);
assert.doesNotMatch(csp, /unsafe-eval|script-src[^;]*unsafe-inline/);
assert.equal(home.headers.get("x-frame-options"), "DENY");
assert.equal(home.headers.get("x-content-type-options"), "nosniff");
assert.ok(homeHtml.includes("WooCommerce Dev"), "catalog data is on the page");
assert.ok(!homeHtml.includes("dropped: unknown category"), "cards with an unknown category are dropped");
assert.ok(!homeHtml.includes("NotASpace"), "unknown spaces are dropped");
assert.equal((homeHtml.match(/<\/script>/g) || []).length, 1, "data cannot close the script early");
for (const leak of ["secret-token-value", "chat.example", "o/r", "w.yml", "GCHAT_WEBHOOK", "GH_TOKEN", "TOKEN_EXPIRES", "raw.example"]) {
  assert.ok(!homeHtml.includes(leak), `landing page must not reveal ${leak}`);
}
assert.ok(!/https?:\/\/[^"'\s]*(fonts|cdn|googleapis)/.test(homeHtml), "no external resources");
const nonce2 = /script-src 'nonce-([^']+)'/.exec((await worker.fetch(new Request("https://x/"), site)).headers.get("content-security-policy"))[1];
assert.notEqual(nonce, nonce2, "a new nonce per request");
assert.equal((await worker.fetch(new Request("https://x/index.html"), site)).status, 200);

// a failing or hostile catalog never breaks the page
for (const broken of [
  () => new Response("nope", { status: 500 }),
  () => new Response("{not json", { status: 200 }),
  () => new Response("x".repeat(600000), { status: 200 }),
  () => { throw new Error("network down"); },
]) {
  catalogResponse = broken;
  const fallback = await worker.fetch(new Request("https://x/"), site);
  assert.equal(fallback.status, 200, "page still loads when the catalog is unavailable");
  assert.ok((await fallback.text()).includes("const DATA={"), "page still has its data stub");
}
catalogResponse = () => new Response(JSON.stringify(goodCatalog), { status: 200 });
const noUrl = await worker.fetch(new Request("https://x/"), alerts);
assert.equal(noUrl.status, 200);

// other paths and methods
assert.equal((await worker.fetch(new Request("https://x/anything"), site)).status, 404);
assert.equal((await worker.fetch(new Request("https://x/", { method: "POST" }), site)).status, 405);
assert.equal((await worker.fetch(new Request("https://x/", { method: "HEAD" }), site)).status, 200);
const clean = cleanCatalog({ cards: "nope", routing: null });
assert.deepEqual(clean, { cards: [], routing: [], updated: "" });

console.log("worker tests passed");
