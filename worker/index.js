// Cloudflare Worker: starts the "Feed alerts to Google Chat" GitHub workflow on a cron.
// GitHub's own `schedule:` trigger is best-effort and often runs hours late; Cloudflare cron
// triggers fire on time, and a workflow_dispatch call starts the same workflow immediately.
//
// If dispatching fails (token revoked or expired), nobody would notice: the bot just goes quiet.
// So the Worker also posts to the alerts Chat space, at most once an hour while it keeps failing,
// and reminds the team before the token expires. Both are stateless: they only fire on the first
// 5-minute tick of an hour (failure) or of 04:00 UTC (reminder).

import { renderLanding } from "./landing.js";

async function dispatch(env) {
  const url = `https://api.github.com/repos/${env.REPO}/actions/workflows/${env.WORKFLOW}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${String(env.GH_TOKEN).trim()}`, // trim: pasted secrets often carry a trailing newline
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "feed-alerts-trigger",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: env.REF || "main" }),
  });
  if (res.status !== 204) {
    // GitHub's error body is safe to log: it never echoes the token.
    const hint = res.status === 401 ? " (token invalid, expired or revoked: create a new one and re-save the GH_TOKEN secret)"
      : res.status === 403 || res.status === 404 ? " (token needs Actions: Read and write on this repo)" : "";
    const err = new Error(`dispatch failed: HTTP ${res.status}${hint} ${(await res.text()).slice(0, 300)}`);
    err.status = res.status;
    throw err;
  }
}

// A GitHub 5xx or a network blip should not raise an alarm: try once more after a short pause.
// Auth and permission errors (401/403/404) are real problems and are reported straight away.
async function dispatchWithRetry(env, pauseMs = 2000) {
  try {
    await dispatch(env);
  } catch (err) {
    const transient = err.status === undefined || err.status >= 500;
    if (!transient) throw err;
    await new Promise((resolve) => setTimeout(resolve, pauseMs));
    await dispatch(env);
  }
}

// Names (never values) of required settings that are not set.
function missingSettings(env) {
  return ["GH_TOKEN", "REPO", "WORKFLOW"].filter((name) => !String(env[name] || "").trim());
}

async function chat(env, text) {
  const url = env.GCHAT_WEBHOOK_ALERTS || env.GCHAT_WEBHOOK_URL;
  if (!url) return false; // no webhook configured: the Cloudflare log is the only place left
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    return res.ok;
  } catch {
    return false; // never log the error text: it can contain the webhook URL
  }
}

// Days until the token expires (negative when expired), or null when no valid date is set.
function daysLeft(env, now) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(env.TOKEN_EXPIRES || "").trim());
  if (!m) return null;
  const end = Date.UTC(+m[1], +m[2] - 1, +m[3], 23, 59, 59);
  return Math.floor((end - now) / 86400000);
}

async function notify(event, env, failure) {
  const when = new Date(event.scheduledTime ?? Date.now());
  const firstTickOfHour = when.getUTCMinutes() < 5;
  if (failure && firstTickOfHour) {
    await chat(env, `⚠️ *Feed bot timer* · cannot start the workflow, so no feeds are being checked.\n${failure.message.slice(0, 300)}`);
  }
  const left = daysLeft(env, when.getTime());
  if (left !== null && left <= 14 && when.getUTCHours() === 4 && firstTickOfHour) {
    await chat(env, left < 0
      ? "⚠️ *Feed bot timer* · the GitHub token has expired. Create a new one and save it as the GH_TOKEN secret."
      : `⏰ *Feed bot timer* · the GitHub token expires in ${left} day${left === 1 ? "" : "s"}. Create a new one and save it as the GH_TOKEN secret.`);
  }
}

export default {
  // Runs on the cron in wrangler.jsonc.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(
      (async () => {
        let failure = null;
        try {
          const missing = missingSettings(env);
          if (missing.length) throw new Error(`missing settings: ${missing.join(", ")}`);
          await dispatchWithRetry(env);
        } catch (err) {
          console.error(err.message);
          failure = err;
        }
        await notify(event, env, failure);
        await pruneHistory(event, env);
        if (failure) throw failure; // marks the invocation as failed in the dashboard
      })(),
    );
  },

  // Public URLs:
  //   /        landing page: what each Chat space receives (data from catalog.json, written by the bot)
  //   /health  "ok" or "not configured", nothing else
  // Neither shows the repo, the token state, webhook names or the expiry date, and neither triggers anything.
  // Details about the Worker itself are in its logs.
  async fetch(request, env) {
    const common = {
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex",
      "referrer-policy": "no-referrer",
      "x-frame-options": "DENY",
    };
    const { pathname } = new URL(request.url);
    // The bot posts the messages it sends to Chat here, to be saved in D1. Needs the shared INGEST_TOKEN.
    if (pathname === "/api/events") return ingest(request, env, common);
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed\n", {
        status: 405,
        headers: { ...common, "content-type": "text/plain; charset=utf-8", allow: "GET, HEAD" },
      });
    }

    if (pathname === "/health") {
      const ok = missingSettings(env).length === 0;
      return new Response(ok ? "feed-alerts-trigger: ok\n" : "feed-alerts-trigger: not configured\n", {
        status: ok ? 200 : 503,
        headers: {
          ...common,
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "no-store",
          "content-security-policy": "default-src 'none'",
        },
      });
    }

    if (pathname === "/" || pathname === "/index.html") {
      const nonce = makeNonce();
      const [catalog, history] = await Promise.all([loadCatalog(env), loadHistory(env)]);
      const html = renderLanding({ ...catalog, history }, nonce);
      return new Response(html, {
        headers: {
          ...common,
          "content-type": "text/html; charset=utf-8",
          "cache-control": "public, max-age=300",
          // Only our own inline script and stylesheet (by nonce) may run; nothing can be loaded from anywhere else.
          "content-security-policy":
            `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`,
        },
      });
    }

    return new Response("not found\n", { status: 404, headers: { ...common, "content-type": "text/plain; charset=utf-8" } });
  },
};

function makeNonce() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

const CATEGORIES = ["incidents", "maintenance", "security", "news", "system"];
const SPACES = ["News", "Downtime", "WordPress & PHP"];
const str = (v, max) => (typeof v === "string" ? v.slice(0, max) : "");

// Keep only the fields the page uses, with sane types and sizes, whatever the file contains.
function cleanCatalog(raw) {
  const cards = (Array.isArray(raw?.cards) ? raw.cards : []).slice(0, 200).flatMap((c) =>
    c && CATEGORIES.includes(c.cat)
      ? [{
          cat: c.cat,
          source: str(c.source, 80),
          kind: str(c.kind, 120),
          spaces: (Array.isArray(c.spaces) ? c.spaces : []).filter((s) => SPACES.includes(s)),
          text: str(c.text, 2000),
          live: c.live === true,
          note: str(c.note, 300),
        }]
      : [],
  );
  const routing = (Array.isArray(raw?.routing) ? raw.routing : []).slice(0, 60).map((r) => ({
    source: str(r?.source, 80),
    how: str(r?.how, 60),
    space: str(r?.space, 60),
    extra: str(r?.extra, 120),
  }));
  return { cards, routing, updated: str(raw?.updated, 40) };
}

// The bot writes catalog.json to the repository. If it cannot be read, the page still loads, with a notice.
async function loadCatalog(env) {
  const empty = { cards: [], routing: [], updated: "" };
  if (!env.CATALOG_URL) return empty;
  try {
    const res = await fetch(env.CATALOG_URL, { cf: { cacheTtl: 300, cacheEverything: true } });
    if (!res.ok) return empty;
    const text = await res.text();
    return text.length > 500000 ? empty : cleanCatalog(JSON.parse(text));
  } catch {
    return empty;
  }
}

// ---- Message history in D1 (binding DB, table posted_messages: see migrations/) ----
const MAX_BODY = 262144;
const MAX_EVENTS = 100;
const RETENTION_DAYS = 90;
const isHttp = (v) => typeof v === "string" && /^https?:\/\//.test(v);

async function sha256(text) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
}

// Compare secrets without leaking where they differ: hash both, then compare every byte.
async function sameSecret(a, b) {
  const [x, y] = await Promise.all([sha256(a), sha256(b)]);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

// Keep only well-formed events with sane sizes; anything else is dropped, never stored.
function cleanEvents(raw, now = Date.now()) {
  if (!Array.isArray(raw)) return [];
  return raw.slice(0, MAX_EVENTS).flatMap((e) => {
    if (!e || typeof e.key !== "string" || !e.key || !CATEGORIES.includes(e.category)) return [];
    const t = Date.parse(e.posted_at);
    if (Number.isNaN(t) || t > now + 86400000) return [];
    return [{
      key: e.key.slice(0, 300),
      posted_at: new Date(t).toISOString(),
      source: str(e.source, 80),
      kind: str(e.kind, 120),
      category: e.category,
      title: str(e.title, 300),
      spaces: (Array.isArray(e.spaces) ? e.spaces : []).filter((s) => SPACES.includes(s)).join(","),
      text: str(e.text, 2000),
      link: isHttp(e.link) ? e.link.slice(0, 500) : "",
    }];
  });
}

async function ingest(request, env, common) {
  const reply = (obj, status, extra = {}) =>
    new Response(JSON.stringify(obj), {
      status,
      headers: { ...common, "content-type": "application/json", "cache-control": "no-store", ...extra },
    });
  if (request.method !== "POST") return reply({ error: "method not allowed" }, 405, { allow: "POST" });
  if (!env.INGEST_TOKEN || !env.DB) return reply({ error: "not configured" }, 503);
  if (!(await sameSecret(request.headers.get("authorization") || "", `Bearer ${env.INGEST_TOKEN}`))) {
    return reply({ error: "unauthorized" }, 401);
  }
  let body;
  try {
    const text = await request.text();
    if (text.length > MAX_BODY) return reply({ error: "too large" }, 413);
    body = JSON.parse(text);
  } catch {
    return reply({ error: "bad request" }, 400);
  }
  const events = cleanEvents(body?.events);
  if (!events.length) return reply({ stored: 0, received: 0 }, 200);
  try {
    // INSERT OR IGNORE on the unique item_key: a batch sent twice (a lost reply) never duplicates rows.
    const insert = env.DB.prepare(
      "INSERT OR IGNORE INTO posted_messages (item_key, posted_at, source, kind, category, title, spaces, text, link) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    );
    const results = await env.DB.batch(
      events.map((e) => insert.bind(e.key, e.posted_at, e.source, e.kind, e.category, e.title, e.spaces, e.text, e.link)),
    );
    const stored = results.reduce((n, r) => n + (r?.meta?.changes ?? 0), 0);
    return reply({ stored, received: events.length }, 200);
  } catch (err) {
    console.error(`ingest failed: ${err.message}`);
    return reply({ error: "storage error" }, 503); // the bot keeps these events and sends them again
  }
}

// The latest posted messages, for the landing page. Any problem (no database, missing table) gives an empty list.
async function loadHistory(env, limit = 60) {
  if (!env.DB) return [];
  try {
    const { results } = await env.DB
      .prepare("SELECT posted_at, source, kind, category, title, spaces, link FROM posted_messages ORDER BY posted_at DESC, id DESC LIMIT ?")
      .bind(limit)
      .all();
    return (results || []).map((r) => ({
      posted_at: str(r.posted_at, 30),
      source: str(r.source, 80),
      kind: str(r.kind, 120),
      category: CATEGORIES.includes(r.category) ? r.category : "news",
      title: str(r.title, 300),
      spaces: str(r.spaces, 100).split(",").filter((s) => SPACES.includes(s)),
      link: isHttp(r.link) ? str(r.link, 500) : "",
    }));
  } catch (err) {
    console.error(`history read failed: ${err.message}`);
    return [];
  }
}

// Once a day (first tick after 03:00 UTC) drop history older than RETENTION_DAYS.
async function pruneHistory(event, env) {
  const when = new Date(event.scheduledTime ?? Date.now());
  if (!env.DB || when.getUTCHours() !== 3 || when.getUTCMinutes() >= 5) return;
  try {
    const cutoff = new Date(when.getTime() - RETENTION_DAYS * 86400000).toISOString();
    await env.DB.prepare("DELETE FROM posted_messages WHERE posted_at < ?").bind(cutoff).run();
  } catch (err) {
    console.error(`history prune failed: ${err.message}`);
  }
}

export {
  dispatch, dispatchWithRetry, notify, daysLeft, missingSettings, cleanCatalog, loadCatalog,
  cleanEvents, loadHistory, pruneHistory, sameSecret,
};
