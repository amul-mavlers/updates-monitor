// Landing page for the Worker's public URL: what each Chat space receives, using data from catalog.json
// (written by the bot). Everything is inline and the page is served with a strict Content-Security-Policy,
// so it loads nothing from other sites. Elements are built with the DOM (textContent), never innerHTML,
// so feed text cannot inject markup. Keep it that way, and keep apostrophes out of single-quoted strings.
export const TEMPLATE = String.raw`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<meta name="color-scheme" content="light dark">
<title>Feed Alerts</title>
<style nonce="__NONCE__">
:root{
  --bg:#f3f5f8;--card:#ffffff;--ink:#132029;--mute:#546472;--line:#d9e0e7;--chip:#e8edf2;--hover:#eef2f6;
  --shadow:0 1px 2px rgba(15,30,45,.06),0 6px 18px rgba(15,30,45,.05);
  --inc:#c42b38;--maint:#a8650f;--sec:#6a44bd;--news:#1d6aae;--sys:#46586a;--wp:#0b7f82;
  --bad:#c42b38;--warn:#bf5f00;--mon:#8a6d00;--ok:#1b7a4a;--neutral:#546472;
  --font:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0c1218;--card:#141d26;--ink:#e7eef4;--mute:#92a3b3;--line:#24303c;--chip:#1d2934;--hover:#1a2530;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 6px 18px rgba(0,0,0,.25);
  --inc:#ff7b86;--maint:#e8a84f;--sec:#b49bff;--news:#6fb3ef;--sys:#9db0c2;--wp:#4fd0d2;
  --bad:#ff7b86;--warn:#f0a050;--mon:#e3c34a;--ok:#5fd394;--neutral:#92a3b3;color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0c1218;--card:#141d26;--ink:#e7eef4;--mute:#92a3b3;--line:#24303c;--chip:#1d2934;--hover:#1a2530;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 6px 18px rgba(0,0,0,.25);
  --inc:#ff7b86;--maint:#e8a84f;--sec:#b49bff;--news:#6fb3ef;--sys:#9db0c2;--wp:#4fd0d2;
  --bad:#ff7b86;--warn:#f0a050;--mon:#e3c34a;--ok:#5fd394;--neutral:#92a3b3;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);font-size:15px;line-height:1.55;
  padding-block:0 64px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));
  -webkit-text-size-adjust:100%}
.wrap{max-width:1160px;margin:0 auto}
button,input{font:inherit;color:inherit}
a{color:var(--news)}
:focus-visible{outline:2px solid var(--news);outline-offset:2px;border-radius:6px}
.topbar{display:flex;justify-content:space-between;align-items:center;padding-block:16px 0}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;letter-spacing:-.01em}
.logo{width:22px;height:22px;border-radius:7px;background:conic-gradient(from 200deg,var(--wp),var(--news),var(--inc),var(--wp))}
.ghost{background:transparent;border:1px solid var(--line);border-radius:99px;padding:5px 13px;font-size:13px;cursor:pointer;color:var(--mute)}
.ghost:hover{background:var(--hover);color:var(--ink)}
header{padding-block:34px 8px}
h1{font-size:clamp(28px,4.6vw,42px);line-height:1.08;font-weight:750;letter-spacing:-.025em;margin:0 0 12px;text-wrap:balance}
.lede{max-width:62ch;color:var(--mute);margin:0 0 22px;font-size:16px}
.steps{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.steps li{display:flex;gap:12px;align-items:flex-start;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--card)}
.steps b{flex:none;width:24px;height:24px;border-radius:50%;background:var(--ink);color:var(--bg);display:grid;place-items:center;font-size:12px}
.steps span{font-size:13.5px;color:var(--mute)}
.steps strong{display:block;color:var(--ink);font-size:14.5px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:14px;margin-top:26px}
.tile{text-align:left;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 18px;cursor:pointer;box-shadow:var(--shadow);
  display:flex;flex-direction:column;gap:6px;transition:border-color .15s,transform .15s}
.tile:hover{border-color:var(--c)}
.tile[aria-pressed="true"]{border-color:var(--c);box-shadow:0 0 0 2px var(--c),var(--shadow)}
.tile .tn{display:flex;align-items:center;gap:9px;font-weight:700;font-size:17px}
.tile .tc{font-size:30px;font-weight:750;letter-spacing:-.02em;line-height:1}
.tile .tc small{font-size:13px;font-weight:500;color:var(--mute);margin-left:6px;letter-spacing:0}
.tile .td{font-size:13.5px;color:var(--mute)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--c);flex:none}
.s-wp{--c:var(--wp)}.s-news{--c:var(--news)}.s-down{--c:var(--inc)}
.f-inc{--c:var(--inc)}.f-maint{--c:var(--maint)}.f-sec{--c:var(--sec)}.f-news{--c:var(--news)}.f-sys{--c:var(--sys)}
.tools{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);margin-top:22px;padding-block:12px;border-bottom:1px solid var(--line);
  display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center}
.search{flex:1 1 220px;min-width:0;max-width:340px;background:var(--card);border:1px solid var(--line);border-radius:99px;padding:7px 14px}
.chips{display:flex;flex-wrap:wrap;gap:7px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:99px;padding:5px 12px;font-size:13px;font-weight:500;cursor:pointer;display:inline-flex;gap:7px;align-items:center}
.chip i{font-style:normal;font-family:var(--mono);font-size:11px;color:var(--mute)}
.chip:hover{background:var(--hover)}
.chip[aria-pressed="true"]{background:var(--ink);border-color:var(--ink);color:var(--bg)}
.chip[aria-pressed="true"] i{color:var(--bg);opacity:.7}
.toggle{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--mute);cursor:pointer;margin-left:auto}
section.fam{padding-top:32px}
.sh{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;margin-bottom:14px}
.sh h2{font-size:19px;font-weight:700;letter-spacing:-.01em;margin:0;color:var(--c)}
.sh p{margin:0;color:var(--mute);font-size:14px;max-width:72ch}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,340px),1fr));gap:16px;align-items:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;min-width:0;box-shadow:var(--shadow)}
.card.thread{grid-column:1/-1}
@media (min-width:760px){.card.thread{grid-column:span 2}}
.ch{display:flex;align-items:center;gap:10px}
.av{flex:none;width:34px;height:34px;border-radius:50%;background:color-mix(in srgb,var(--c) 16%,var(--card));border:1px solid color-mix(in srgb,var(--c) 40%,transparent);display:grid;place-items:center;font-size:16px}
.ct{min-width:0;flex:1}
.src{font-size:13px;font-weight:650;line-height:1.25}
.src small{display:block;font-weight:400;color:var(--mute);font-size:12px}
.pills{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.pill{--c:var(--neutral);font-size:11.5px;font-weight:650;padding:1px 8px;border-radius:99px;color:var(--c);
  background:color-mix(in srgb,var(--c) 13%,transparent);border:1px solid color-mix(in srgb,var(--c) 34%,transparent)}
.pill.bad{--c:var(--bad)}.pill.warn{--c:var(--warn)}.pill.mon{--c:var(--mon)}.pill.ok{--c:var(--ok)}.pill.maint{--c:var(--maint)}
.tag{font-family:var(--mono);font-size:10px;letter-spacing:.07em;text-transform:uppercase;padding:2px 7px;border-radius:5px;border:1px solid var(--line);color:var(--mute);white-space:nowrap}
.tag.live{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 50%,transparent)}
.copy{background:transparent;border:1px solid var(--line);border-radius:7px;font-size:11.5px;padding:2px 8px;color:var(--mute);cursor:pointer}
.copy:hover{background:var(--hover);color:var(--ink)}
.title{font-size:15.5px;font-weight:650;line-height:1.35;margin:12px 0 0;overflow-wrap:anywhere}
.meta{display:flex;flex-wrap:wrap;gap:3px 14px;margin-top:6px;font-size:12.5px;color:var(--mute)}
.meta span{font-family:var(--mono);font-size:12px}
.sum{margin:8px 0 0;font-size:14px;overflow-wrap:anywhere}
.more{display:inline-block;margin-top:10px;font-size:13px;font-weight:600;text-decoration:none;border:1px solid var(--line);border-radius:8px;padding:3px 10px}
.more:hover{background:var(--hover)}
.raw{margin:12px 0 0;font-size:14px;overflow-wrap:anywhere}
.at{background:color-mix(in srgb,var(--news) 18%,transparent);color:var(--news);border-radius:4px;padding:0 4px;font-weight:650}
.cf{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:12px;padding-top:10px;border-top:1px solid var(--line);font-size:12px;color:var(--mute)}
.sp{display:inline-flex;align-items:center;gap:6px;background:var(--chip);color:var(--ink);border-radius:99px;padding:2px 9px;font-size:11.5px;font-weight:600}
.sp .dot{width:8px;height:8px}
.note{flex:1 1 100%;margin:2px 0 0}
.tl{margin:14px 0 0;padding:0;list-style:none}
.tl li{position:relative;padding:0 0 16px 26px}
.tl li:last-child{padding-bottom:0}
.tl li::before{content:"";position:absolute;left:5px;top:16px;bottom:0;width:2px;background:var(--line)}
.tl li:last-child::before{display:none}
.tl li::after{content:"";position:absolute;left:0;top:5px;width:12px;height:12px;border-radius:50%;background:var(--c,var(--neutral));border:2px solid var(--card)}
.tl .pill{margin-right:6px}
.tl .t{font-family:var(--mono);font-size:12px;color:var(--mute)}
.tl p{margin:4px 0 0;font-size:14px;overflow-wrap:anywhere}
.tl li.bad{--c:var(--bad)}.tl li.warn{--c:var(--warn)}.tl li.mon{--c:var(--mon)}.tl li.ok{--c:var(--ok)}.tl li.maint{--c:var(--maint)}
.empty{padding:40px 0;color:var(--mute);text-align:center}
details.routing{margin-top:40px;background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}
details.routing summary{cursor:pointer;padding:14px 18px;font-weight:650;font-size:16px}
.tw{overflow-x:auto;padding:0 6px 8px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 12px;border-top:1px solid var(--line);vertical-align:top}
th{font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);font-weight:500;border-top:0}
.foot{margin:28px 0 0;color:var(--mute);font-size:13px}
.stats{margin:14px 0 0;color:var(--mute);font-size:13px;font-family:var(--mono)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div class="brand"><span class="logo" aria-hidden="true"></span>Feed Alerts</div>
    <button id="theme" class="ghost" type="button" aria-label="Switch between light and dark">Light / Dark</button>
  </div>
  <header>
    <h1>What lands in each Chat space</h1>
    <p class="lede">A bot watches status pages and release feeds and posts only what is new. Pick a space to see exactly what it receives. Cards marked Live are real recent items; Example cards show messages that only appear during an outage or a problem with the bot.</p>
    <ol class="steps">
      <li><b>1</b><span><strong>Timer</strong>Wakes the bot every 5 minutes.</span></li>
      <li><b>2</b><span><strong>Check</strong>Reads status pages and feeds, keeps only new items.</span></li>
      <li><b>3</b><span><strong>Post</strong>Sends each item to the right Chat space.</span></li>
    </ol>
    <p class="stats" id="stats"></p>
  </header>
  <noscript><p class="empty">This page needs JavaScript to show the messages.</p></noscript>
  <nav class="tiles" id="tiles" aria-label="Chat spaces"></nav>
  <div class="tools">
    <input class="search" id="q" type="search" placeholder="Search messages" aria-label="Search messages" autocomplete="off">
    <div class="chips" id="chips" role="group" aria-label="Filter by kind of message"></div>
    <label class="toggle"><input type="checkbox" id="live"> Live only</label>
  </div>
  <main id="out"></main>
  <details class="routing" id="routing">
    <summary>Where each source goes</summary>
    <div class="tw"><table><thead><tr><th>Source</th><th>Read as</th><th>Posts to</th><th>Also</th></tr></thead><tbody id="rt"></tbody></table></div>
  </details>
  <p class="foot" id="foot"></p>
</div>
<script nonce="__NONCE__">
const DATA = __DATA__;
const FAMILIES = [
  {id: "incidents", name: "Incidents", cls: "f-inc", desc: "Outages on GitHub, Cloudflare, Shopify and Google Workspace. Every update to one incident lands in the same Chat thread."},
  {id: "maintenance", name: "Maintenance", cls: "f-maint", desc: "Planned work. Cloudflare lists every datacenter, so only nearby ones are posted."},
  {id: "security", name: "Security and urgent", cls: "f-sec", desc: "News that mentions a CVE, a security release or a critical flaw. It goes to Downtime, and WordPress and PHP items are also kept in their own space."},
  {id: "news", name: "News and releases", cls: "f-news", desc: "Release notes and posts from WordPress, PHP, Shopify, WooCommerce, Laravel and Node.js."},
  {id: "system", name: "Bot health", cls: "f-sys", desc: "Messages the bot and its timer send about themselves, so a silent failure does not go unnoticed."}
];
const SPACES = [
  {id: "wp-php", name: "WordPress & PHP", cls: "s-wp", desc: "WordPress News, PHP News and PHP Releases. Security items are also copied to Downtime."},
  {id: "news", name: "News", cls: "s-news", desc: "The default space: Shopify, WooCommerce, Laravel and Node.js, plus nearby Cloudflare maintenance."},
  {id: "downtime", name: "Downtime", cls: "s-down", desc: "Outages, security news and the bot own health messages."}
];
const SPACE_CLASS = {"WordPress & PHP": "s-wp", "News": "s-news", "Downtime": "s-down"};
const state = {space: "wp-php", family: "all", q: "", live: false};

function $(id) { return document.getElementById(id); }
function h(tag, attrs, kids) {
  const e = document.createElement(tag);
  const a = attrs || {};
  for (const k in a) {
    const v = a[k];
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  (kids || []).forEach(function (c) {
    if (c === null || c === undefined || c === false) return;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return e;
}
function safeLink(href, label, cls) {
  if (!/^https?:\/\//.test(href)) return document.createTextNode(label);
  return h("a", {href: href, target: "_blank", rel: "noopener noreferrer", class: cls || false, text: label});
}
function inline(text) {
  const frag = document.createDocumentFragment();
  const re = /<users\/all>|<(https?:\/\/[^|>]+)\|([^>]+)>|(https?:\/\/[^\s<]+)|\*([^*\n]+)\*/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
    if (m[0] === "<users/all>") frag.appendChild(h("span", {class: "at", text: "@all"}));
    else if (m[1]) frag.appendChild(safeLink(m[1], m[2]));
    else if (m[3]) frag.appendChild(safeLink(m[3], m[3]));
    else frag.appendChild(h("strong", {text: m[4]}));
    last = re.lastIndex;
  }
  if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
  return frag;
}
function multiline(text) {
  const frag = document.createDocumentFragment();
  text.split("\n").forEach(function (line, i) {
    if (i) frag.appendChild(document.createElement("br"));
    frag.appendChild(inline(line));
  });
  return frag;
}
function statusClass(label) {
  const w = label.toLowerCase();
  if (w.indexOf("completed") > -1 || w.indexOf("resolved") === 0) return "ok";
  if (w.indexOf("investigating") === 0) return "bad";
  if (w.indexOf("identified") === 0) return "warn";
  if (w.indexOf("monitoring") === 0 || w.indexOf("verifying") === 0) return "mon";
  if (w.indexOf("scheduled") === 0 || w.indexOf("maintenance") === 0) return "maint";
  return "";
}
function impactClass(word) { return word === "critical" ? "bad" : word === "major" ? "warn" : "mon"; }
// Turns the bot's Chat text into parts. Returns null for free-form messages (the bot health ones).
function parse(text) {
  const lines = text.split("\n");
  let head = lines[0], mention = false;
  if (head.indexOf("<users/all> ") === 0) { mention = true; head = head.slice(12); }
  const hm = /^(\S+) \*(.+?)\* · (.+)$/.exec(head);
  const tm = lines[1] ? /^\*(.+)\*$/.exec(lines[1]) : null;
  if (!hm || !tm) return null;
  const parts = hm[3].split(" · ");
  const out = {emoji: hm[1], source: hm[2], status: parts[0], impact: "", title: tm[1], time: "", affected: "", summary: "", href: "", mention: mention};
  const sum = [];
  for (let i = 2; i < lines.length; i++) {
    const l = lines[i];
    const lm = /^<(https?:\/\/[^|>]+)\|[^>]+>$/.exec(l);
    if (l.indexOf("🕒 ") === 0) out.time = l.slice(3);
    else if (l.indexOf("Affected: ") === 0) out.affected = l.slice(10);
    else if (lm) out.href = lm[1];
    else sum.push(l);
  }
  out.summary = sum.join(" ");
  const im = /^(minor|major|critical) impact$/i.exec(parts[1] || "");
  if (im) out.impact = im[1].toLowerCase();
  return out;
}
function copyText(text, btn) {
  const done = function () { const old = btn.textContent; btn.textContent = "Copied"; setTimeout(function () { btn.textContent = old; }, 1200); };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () {});
}
function spacePills(c) {
  return c.spaces.map(function (n) { return h("span", {class: "sp " + (SPACE_CLASS[n] || "")}, [h("span", {class: "dot"}), n]); });
}
function pillsFor(p) {
  const out = [];
  if (p.status) out.push(h("span", {class: "pill " + statusClass(p.status), text: p.status}));
  if (p.impact) out.push(h("span", {class: "pill " + impactClass(p.impact), text: p.impact + " impact"}));
  if (p.mention) out.push(h("span", {class: "at", text: "@all"}));
  return out;
}
function famClass(c) {
  const f = FAMILIES.filter(function (x) { return x.id === c.cat; })[0];
  return f ? f.cls : "";
}
function card(c) {
  const p = parse(c.text);
  const copy = h("button", {type: "button", class: "copy", "aria-label": "Copy message text", text: "Copy", onclick: function (ev) { copyText(c.text, ev.currentTarget); }});
  const top = h("div", {class: "ch"}, [
    h("div", {class: "av", "aria-hidden": "true", text: p ? p.emoji : "💬"}),
    h("div", {class: "ct"}, [
      h("div", {class: "src"}, [p ? p.source : c.source, p ? null : h("small", {text: c.kind})]),
      p ? h("div", {class: "pills"}, pillsFor(p)) : null
    ]),
    h("span", {class: "tag" + (c.live ? " live" : ""), text: c.live ? "Live" : "Example"}),
    copy
  ]);
  const body = [];
  if (p) {
    body.push(h("h3", {class: "title", text: p.title}));
    const meta = [];
    if (p.time) meta.push(h("span", {text: p.time}));
    if (p.affected) meta.push(h("div", {text: "Affected: " + p.affected}));
    if (meta.length) body.push(h("div", {class: "meta"}, meta));
    if (p.summary) body.push(h("p", {class: "sum"}, [inline(p.summary)]));
    if (p.href) body.push(safeLink(p.href, "Read more", "more"));
  } else {
    body.push(h("p", {class: "raw"}, [multiline(c.text)]));
  }
  const foot = h("div", {class: "cf"}, [].concat(spacePills(c), c.note ? [h("p", {class: "note", text: c.note})] : []));
  return h("article", {class: "card " + famClass(c)}, [top].concat(body, [foot]));
}
// Example messages that belong to one incident or one maintenance window read as a single Chat thread.
function threadCard(items) {
  const first = items[0];
  const p0 = parse(first.text);
  const list = h("ol", {class: "tl"}, items.map(function (c) {
    const p = parse(c.text);
    if (!p) return h("li", {}, [multiline(c.text)]);
    const kids = [h("span", {class: "pill " + statusClass(p.status), text: p.status})];
    if (p.impact) kids.push(h("span", {class: "pill " + impactClass(p.impact), text: p.impact + " impact"}));
    if (p.mention) kids.push(h("span", {class: "at", text: "@all"}));
    if (p.time) kids.push(h("span", {class: "t", text: p.time}));
    const li = [h("div", {}, kids)];
    if (p.summary) li.push(h("p", {}, [inline(p.summary)]));
    return h("li", {class: statusClass(p.status)}, li);
  }));
  const title = p0 ? p0.title : first.source;
  return h("article", {class: "card thread " + famClass(first)}, [
    h("div", {class: "ch"}, [
      h("div", {class: "av", "aria-hidden": "true", text: "🧵"}),
      h("div", {class: "ct"}, [h("div", {class: "src"}, [first.source, h("small", {text: "One thread, " + items.length + " updates"})])]),
      h("span", {class: "tag", text: "Example"})
    ]),
    h("h3", {class: "title", text: title}),
    list,
    h("div", {class: "cf"}, [].concat(spacePills(first), first.note ? [h("p", {class: "note", text: first.note})] : []))
  ]);
}
function groupThreads(cards) {
  const buckets = {}, order = [];
  cards.forEach(function (c) {
    const key = !c.live && (c.cat === "incidents" || c.cat === "maintenance") ? c.source + "|" + c.cat + "|" + (c.text.split("\n")[1] || "") : null;
    if (key === null) { order.push({single: c}); return; }
    if (!buckets[key]) { buckets[key] = []; order.push({key: key}); }
    buckets[key].push(c);
  });
  return order.map(function (o) {
    if (o.single) return card(o.single);
    const items = buckets[o.key];
    return items.length > 1 ? threadCard(items) : card(items[0]);
  });
}
function inSpace(c, sp) { return sp.id === "all" || c.spaces.indexOf(sp.name) > -1; }
function currentSpace() {
  return SPACES.filter(function (x) { return x.id === state.space; })[0] || {id: "all", name: "All spaces"};
}
function matchesQuery(c) {
  if (!state.q) return true;
  return (c.text + " " + c.source + " " + c.kind).toLowerCase().indexOf(state.q) > -1;
}
function drawTiles() {
  const nav = $("tiles");
  nav.textContent = "";
  SPACES.forEach(function (sp) {
    const cards = DATA.cards.filter(function (c) { return inSpace(c, sp); });
    const sources = {};
    cards.forEach(function (c) { sources[c.source] = 1; });
    nav.appendChild(h("button", {type: "button", class: "tile " + sp.cls, "aria-pressed": String(state.space === sp.id), onclick: function () { pick(sp.id); }}, [
      h("span", {class: "tn"}, [h("span", {class: "dot"}), sp.name]),
      h("span", {class: "tc"}, [String(cards.length), h("small", {text: "messages from " + Object.keys(sources).length + " sources"})]),
      h("span", {class: "td", text: sp.desc})
    ]));
  });
}
function drawChips() {
  const sp = currentSpace();
  const base = DATA.cards.filter(function (c) { return inSpace(c, sp); });
  const box = $("chips");
  box.textContent = "";
  const all = [{id: "all", name: "Everything"}].concat(FAMILIES.filter(function (f) { return base.some(function (c) { return c.cat === f.id; }); }));
  all.forEach(function (f) {
    const n = f.id === "all" ? base.length : base.filter(function (c) { return c.cat === f.id; }).length;
    box.appendChild(h("button", {type: "button", class: "chip", "aria-pressed": String(state.family === f.id), onclick: function () { state.family = f.id; draw(); }}, [f.name, h("i", {text: String(n)})]));
  });
  const link = h("button", {type: "button", class: "chip", "aria-pressed": String(state.space === "all"), onclick: function () { pick("all"); }}, ["All spaces", h("i", {text: String(DATA.cards.length)})]);
  box.appendChild(link);
}
function drawList() {
  const sp = currentSpace();
  const out = $("out");
  out.textContent = "";
  if (!DATA.cards.length) {
    out.appendChild(h("p", {class: "empty", text: "The live samples are loading from the latest bot run. Try again in a few minutes."}));
    return;
  }
  const cards = DATA.cards.filter(function (c) {
    return inSpace(c, sp) && (state.family === "all" || c.cat === state.family) && (!state.live || c.live) && matchesQuery(c);
  });
  let shown = 0;
  FAMILIES.forEach(function (f) {
    const items = cards.filter(function (c) { return c.cat === f.id; });
    if (!items.length) return;
    shown += items.length;
    out.appendChild(h("section", {class: "fam " + f.cls}, [
      h("div", {class: "sh"}, [h("h2", {text: f.name}), h("p", {text: f.desc})]),
      h("div", {class: "grid"}, groupThreads(items))
    ]));
  });
  if (!shown) out.appendChild(h("p", {class: "empty", text: "No messages match. Clear the search or the filters."}));
}
function draw() { drawTiles(); drawChips(); drawList(); }
function pick(id) {
  state.space = id;
  state.family = "all";
  try { history.replaceState(null, "", "#" + id); } catch (e) {}
  draw();
}
function readHash() {
  const id = (location.hash || "").slice(1);
  state.space = id === "all" || SPACES.some(function (x) { return x.id === id; }) ? id : "wp-php";
}
function drawStatic() {
  const live = DATA.cards.filter(function (c) { return c.live; }).length;
  $("stats").textContent = DATA.routing.length + " sources  ·  3 Chat spaces  ·  " + live + " live items shown";
  const rt = $("rt");
  rt.textContent = "";
  DATA.routing.forEach(function (r) {
    rt.appendChild(h("tr", {}, [
      h("td", {}, [h("strong", {text: r.source})]),
      h("td", {text: r.how}),
      h("td", {}, [h("span", {class: "sp " + (SPACE_CLASS[r.space] || "")}, [h("span", {class: "dot"}), r.space])]),
      h("td", {text: r.extra || "-"})
    ]));
  });
  $("routing").hidden = !DATA.routing.length;
  let when = "";
  if (DATA.updated) {
    try { when = new Date(DATA.updated).toLocaleString("en-GB", {timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit"}); } catch (e) {}
  }
  $("foot").textContent = DATA.cards.length
    ? "Live cards come from the latest check of the real feeds" + (when ? "; the newest item shown is from " + when + " IST" : "") + ". Times inside messages are shown in IST, as the bot posts them."
    : "The live samples are temporarily unavailable. They return after the next check.";
}
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) {}
  if (saved === "light" || saved === "dark") document.documentElement.setAttribute("data-theme", saved);
  $("theme").addEventListener("click", function () {
    const root = document.documentElement;
    const prefersDark = !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const dark = root.getAttribute("data-theme") === "dark" || (!root.getAttribute("data-theme") && prefersDark);
    const next = dark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
  });
}
readHash();
initTheme();
drawStatic();
$("q").addEventListener("input", function (ev) { state.q = ev.target.value.trim().toLowerCase(); drawList(); });
$("live").addEventListener("change", function (ev) { state.live = ev.target.checked; drawList(); });
window.addEventListener("hashchange", function () { readHash(); state.family = "all"; draw(); });
draw();
</script>
</body>
</html>
`;

// JSON for a <script>: escape characters that could end the script or break the string.
// Written with character codes so the source contains no backslashes to get mangled.
function scriptJson(data) {
  const bs = String.fromCharCode(92); // backslash
  return JSON.stringify(data)
    .split("<").join(bs + "u003c")
    .split(String.fromCharCode(0x2028)).join(bs + "u2028")
    .split(String.fromCharCode(0x2029)).join(bs + "u2029");
}

export function renderLanding(data, nonce) {
  return TEMPLATE.split("__NONCE__").join(nonce).replace("__DATA__", () => scriptJson(data));
}
