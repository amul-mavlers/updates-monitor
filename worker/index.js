// Cloudflare Worker: starts the "Feed alerts to Google Chat" GitHub workflow on a cron.
// GitHub's own `schedule:` trigger is best-effort and often runs hours late; Cloudflare cron
// triggers fire on time, and a workflow_dispatch call starts the same workflow immediately.
//
// If dispatching fails (token revoked or expired), nobody would notice: the bot just goes quiet.
// So the Worker also posts to the alerts Chat space, at most once an hour while it keeps failing,
// and reminds the team before the token expires. Both are stateless: they only fire on the first
// 5-minute tick of an hour (failure) or of 04:00 UTC (reminder).

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
    throw new Error(`dispatch failed: HTTP ${res.status}${hint} ${(await res.text()).slice(0, 300)}`);
  }
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
          await dispatch(env);
        } catch (err) {
          console.error(err.message);
          failure = err;
        }
        await notify(event, env, failure);
        if (failure) throw failure; // marks the invocation as failed in the dashboard
      })(),
    );
  },

  // Opening the Worker's URL only reports its settings. It does not trigger anything.
  async fetch(_request, env) {
    const ok = Boolean(env.GH_TOKEN && env.REPO && env.WORKFLOW);
    const left = daysLeft(env, Date.now());
    return new Response(
      `feed-alerts-trigger\nrepo: ${env.REPO}\nworkflow: ${env.WORKFLOW}\nref: ${env.REF || "main"}\ntoken set: ${Boolean(env.GH_TOKEN)}\n` +
        `failure alerts to Chat: ${Boolean(env.GCHAT_WEBHOOK_ALERTS || env.GCHAT_WEBHOOK_URL)}\n` +
        `token expiry: ${left === null ? "not set (add TOKEN_EXPIRES in wrangler.jsonc)" : `${left} days left`}\n${ok ? "ready" : "MISSING SETTINGS"}\n`,
      { status: ok ? 200 : 500, headers: { "content-type": "text/plain" } },
    );
  },
};

export { dispatch, notify, daysLeft };
