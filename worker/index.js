// Cloudflare Worker: starts the "Feed alerts to Google Chat" GitHub workflow on a cron.
// GitHub's own `schedule:` trigger is best-effort and often runs hours late; Cloudflare cron
// triggers fire on time, and a workflow_dispatch call starts the same workflow immediately.

async function dispatch(env) {
  const url = `https://api.github.com/repos/${env.REPO}/actions/workflows/${env.WORKFLOW}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "feed-alerts-trigger",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: env.REF || "main" }),
  });
  if (res.status !== 204) {
    // GitHub's error body is safe to log: it never echoes the token.
    throw new Error(`dispatch failed: HTTP ${res.status} ${(await res.text()).slice(0, 300)}`);
  }
}

export default {
  // Runs on the cron in wrangler.jsonc.
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(
      dispatch(env).catch((err) => {
        console.error(err.message);
        throw err; // marks the invocation as failed in the dashboard
      }),
    );
  },

  // Opening the Worker's URL only reports its settings. It does not trigger anything.
  async fetch(_request, env) {
    const ok = Boolean(env.GH_TOKEN && env.REPO && env.WORKFLOW);
    return new Response(
      `feed-alerts-trigger\nrepo: ${env.REPO}\nworkflow: ${env.WORKFLOW}\nref: ${env.REF || "main"}\ntoken set: ${Boolean(env.GH_TOKEN)}\n${ok ? "ready" : "MISSING SETTINGS"}\n`,
      { status: ok ? 200 : 500, headers: { "content-type": "text/plain" } },
    );
  },
};

export { dispatch };
