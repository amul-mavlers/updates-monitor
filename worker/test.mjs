// Run with: node worker/test.mjs
import assert from "node:assert/strict";
import worker, { dispatch } from "./index.js";

const env = { GH_TOKEN: "tok", REPO: "o/r", WORKFLOW: "w.yml", REF: "main" };
const calls = [];
globalThis.fetch = async (url, init) => {
  calls.push({ url, init });
  return new Response(calls.fail ? '{"message":"Not Found"}' : null, { status: calls.fail ? 404 : 204 });
};

await dispatch(env);
assert.equal(calls[0].url, "https://api.github.com/repos/o/r/actions/workflows/w.yml/dispatches");
assert.equal(calls[0].init.method, "POST");
assert.equal(calls[0].init.headers.Authorization, "Bearer tok");
assert.equal(JSON.parse(calls[0].init.body).ref, "main");

calls.fail = true;
await assert.rejects(dispatch(env), /HTTP 404/);

const pending = [];
await assert.rejects(
  (async () => {
    await worker.scheduled({}, env, { waitUntil: (p) => pending.push(p) });
    await Promise.all(pending);
  })(),
  /HTTP 404/,
);

const ok = await worker.fetch(new Request("https://x/"), env);
assert.equal(ok.status, 200);
assert.ok(!(await ok.text()).includes("tok\n"), "status page must not print the token");
assert.equal((await worker.fetch(new Request("https://x/"), { REPO: "o/r" })).status, 500);
console.log("worker tests passed");
