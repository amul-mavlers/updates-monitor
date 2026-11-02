// Run with: node worker/test.mjs
import assert from "node:assert/strict";
import worker, { dispatch, notify, daysLeft } from "./index.js";

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

// status page: never prints the token, 500 when settings are missing
const page = await worker.fetch(new Request("https://x/"), alerts);
assert.equal(page.status, 200);
const text = await page.text();
assert.ok(!text.includes("tok\n") && !text.includes("chat.example"), "status page must not print secrets");
assert.equal((await worker.fetch(new Request("https://x/"), { REPO: "o/r" })).status, 500);

console.log("worker tests passed");
