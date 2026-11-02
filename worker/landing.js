// Landing page for the Worker's public URL. Generated from the design in the repo history; edit freely.
// Shows what each Chat space receives, using data from catalog.json (written by the bot).
// No external resources: the page is served with a strict Content-Security-Policy.
export const TEMPLATE = String.raw`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>Feed Alerts</title>
<style>
/* Layout: a calm catalogue. Header, a sticky filter bar, then one section per message family; each message is a Chat-style card. */
:root{
  --bg:#f3f5f7;--card:#ffffff;--ink:#16202a;--mute:#566574;--line:#d9e0e6;--chip:#e7ecf0;
  --inc:#c42b38;--maint:#a8650f;--sec:#6a44bd;--news:#1d6aae;--sys:#46586a;--wp:#0b7f82;
  --font:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;--mono:ui-monospace,'SF Mono','Cascadia Mono',Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0d1319;--card:#151e27;--ink:#e6edf3;--mute:#93a3b3;--line:#25313d;--chip:#1e2a35;
  --inc:#ff7b86;--maint:#e8a84f;--sec:#b49bff;--news:#6fb3ef;--sys:#9db0c2;--wp:#4fd0d2;color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0d1319;--card:#151e27;--ink:#e6edf3;--mute:#93a3b3;--line:#25313d;--chip:#1e2a35;
  --inc:#ff7b86;--maint:#e8a84f;--sec:#b49bff;--news:#6fb3ef;--sys:#9db0c2;--wp:#4fd0d2;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font-family:var(--font);font-size:15px;line-height:1.55;
  padding-block:0 56px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.wrap{max-width:1180px;margin:0 auto}
header{padding-block:36px 20px}
h1{font-size:clamp(28px,4.4vw,40px);line-height:1.1;font-weight:700;letter-spacing:-.02em;margin:0 0 10px;text-wrap:balance}
.lede{max-width:64ch;color:var(--mute);margin:0 0 20px}
.stats{display:flex;flex-wrap:wrap;gap:10px 28px;font-family:var(--mono);font-size:12px;color:var(--mute)}
.stats b{display:block;font-family:var(--font);font-size:26px;font-weight:700;color:var(--ink);letter-spacing:-.02em}
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);padding-block:12px;border-bottom:1px solid var(--line)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{font:inherit;font-size:13.5px;font-weight:500;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:6px 13px;border-radius:99px;cursor:pointer;display:inline-flex;gap:8px;align-items:center}
.chip i{font-style:normal;font-family:var(--mono);font-size:11px;color:var(--mute)}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.chip[aria-pressed="true"] i{color:var(--bg);opacity:.7}
.chip:focus-visible,a:focus-visible{outline:2px solid var(--news);outline-offset:2px}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:10px;font-size:12.5px;color:var(--mute)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:-1px}
section{padding-top:34px}
section[hidden]{display:none}
.sh{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;margin-bottom:14px}
h2{font-size:20px;font-weight:700;letter-spacing:-.01em;margin:0}
.sd{color:var(--mute);font-size:14px;max-width:70ch}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,340px),1fr));gap:16px;align-items:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px 14px;min-width:0}
.top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.tag{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:5px;border:1px solid var(--line);color:var(--mute)}
.tag.live{color:var(--ink);border-color:var(--ink)}
.spaces{display:flex;gap:6px;flex-wrap:wrap}
.sp{font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:99px;background:var(--chip);color:var(--ink);white-space:nowrap}
.msg{display:flex;gap:10px}
.av{flex:none;width:30px;height:30px;border-radius:50%;background:var(--ink);color:var(--bg);display:grid;place-items:center;font-size:11px;font-weight:700;letter-spacing:.02em}
.body{min-width:0;font-size:14.5px;overflow-wrap:anywhere}
.who{font-size:12px;color:var(--mute);margin-bottom:3px}
.who b{color:var(--ink)}
.body a{color:var(--news)}
.at{background:color-mix(in srgb,var(--news) 18%,transparent);color:var(--news);border-radius:4px;padding:0 4px;font-weight:600}
.note{margin:12px 0 0;padding-top:10px;border-top:1px dashed var(--line);font-size:12.5px;color:var(--mute)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);font-weight:500}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:14px}
.panel{margin-top:26px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.panel h2{display:flex;align-items:center;gap:10px}
.panel p{margin:8px 0 0;color:var(--mute);max-width:75ch}
.meta{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:14px;font-size:13px}
.meta span{color:var(--mute)}
.meta b{color:var(--ink);font-weight:600}
.meta code{font-family:var(--mono);font-size:12px;background:var(--chip);padding:2px 7px;border-radius:5px;color:var(--ink)}
.chip .dot{margin:0}
.foot{margin-top:40px;color:var(--mute);font-size:13px}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Feed Alerts</h1>
  <p class="lede">What each Google Chat space receives from the bot. Pick a space to see its messages. Cards marked <b>Live</b> come from today's feeds; <b>Example</b> cards show messages that only appear during an outage, a maintenance window or a problem with the bot itself.</p>
  <div class="stats" id="stats"></div>
</header>
<div class="bar">
  <div class="chips" id="chips" role="group" aria-label="Choose a Chat space"></div>
</div>
<div id="panel"></div>
<main id="out"></main>
<section id="routing">
  <div class="sh"><h2>Where each source goes</h2><span class="sd">Twelve sources, checked every 5 minutes.</span></div>
  <div class="tw"><table><thead><tr><th>Source</th><th>Read as</th><th>Posts to</th><th>Also</th></tr></thead><tbody id="rt"></tbody></table></div>
</section>
<p class="foot" id="foot"></p>
</div>
<script nonce="__NONCE__">
const DATA=__DATA__;
const FAMILIES=[
 {id:'incidents',name:'Incidents',color:'--inc',desc:'Outages on GitHub, Cloudflare, Shopify and Google Workspace. Every update to one incident lands in the same Chat thread, with severity, affected parts and time to resolve.'},
 {id:'maintenance',name:'Maintenance',color:'--maint',desc:'Planned work. Cloudflare lists every datacenter, so only nearby ones are posted.'},
 {id:'security',name:'Security and urgent',color:'--sec',desc:'News that mentions a CVE, a security release or a critical flaw. It goes to Downtime, and WordPress and PHP items are also kept in their own space.'},
 {id:'news',name:'News and releases',color:'--news',desc:'Release notes and posts from WordPress, PHP, Shopify, WooCommerce, Laravel and Node.js.'},
 {id:'system',name:'Bot health',color:'--sys',desc:'Messages the bot and its timer send about themselves, so a silent failure does not go unnoticed.'}
];
const esc=s=>s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function render(text){
  const keep=[];
  const hold=html=>{keep.push(html);return '\u0000'+(keep.length-1)+'\u0000'};
  let t=text.replace(/<users\/all>/g,()=>hold('<span class="at">@all</span>'));
  t=t.replace(/<(https?:\/\/[^|>]+)\|([^>]+)>/g,(m,u,l)=>hold('<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(l)+'</a>'));
  t=t.replace(/https?:\/\/[^\s\u0000]+/g,u=>hold('<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(u)+'</a>'));
  let h=esc(t).replace(/(^|[\s(])\*([^*\n]+)\*/g,'$1<strong>$2</strong>').replace(/\n/g,'<br>');
  return h.replace(/\u0000(\d+)\u0000/g,(m,i)=>keep[+i]);
}
const spColor=n=>n==='Downtime'?'--inc':n==='News'?'--news':'--wp';
function card(c){
  const sp=c.spaces.map(n=>'<span class="sp"><span class="dot" style="background:var('+spColor(n)+')"></span>'+esc(n)+'</span>').join('');
  return '<article class="card"><div class="top"><span class="tag'+(c.live?' live':'')+'">'+(c.live?'Live':'Example')+'</span><span class="spaces">'+sp+'</span></div>'+
   '<div class="msg"><div class="av" aria-hidden="true">FB</div><div class="body"><div class="who"><b>Feed bot</b> · '+esc(c.source)+'</div>'+render(c.text)+'</div></div>'+
   (c.note?'<p class="note">'+esc(c.note)+'</p>':'')+'</article>';
}
const SPACES=[
 {id:'wp-php',name:'WordPress & PHP',color:'--wp',
  desc:'Everything from WordPress News, PHP News and PHP Releases. Items about security are also copied to Downtime, so they are not missed during an outage.',
  sources:'WordPress News, PHP News, PHP Releases'},
 {id:'news',name:'News',color:'--news',
  desc:'The default space. Release notes and posts from Shopify, WooCommerce, Laravel and Node.js, plus Cloudflare maintenance in nearby regions.',
  sources:'Shopify Changelog, WooCommerce Dev, Laravel News, Node.js Blog, Cloudflare maintenance'},
 {id:'downtime',name:'Downtime',color:'--inc',
  desc:'Outages from GitHub, Cloudflare, Shopify and Google Workspace, security news, and the bot\'s own health messages.',
  sources:'GitHub, Cloudflare, Shopify and Google Workspace status, Patchstack, security items from every feed'}
];
const DEFAULT_SPACE='wp-php';
let current=(location.hash||'').slice(1);
if(current!=='all'&&!SPACES.some(x=>x.id===current))current=DEFAULT_SPACE;
const inSpace=(c,sp)=>sp.id==='all'||c.spaces.indexOf(sp.name)>-1;
function draw(){
  const all={id:'all',name:'All spaces'};
  document.getElementById('chips').innerHTML=SPACES.concat([all]).map(x=>{
    const n=x.id==='all'?DATA.cards.length:DATA.cards.filter(c=>inSpace(c,x)).length;
    return '<button class="chip" data-f="'+x.id+'" aria-pressed="'+(x.id===current)+'">'+(x.color?'<span class="dot" style="background:var('+x.color+')"></span>':'')+esc(x.name)+'<i>'+n+'</i></button>';
  }).join('');
  const sp=SPACES.find(x=>x.id===current)||all;
  const cards=DATA.cards.filter(c=>inSpace(c,sp));
  document.getElementById('panel').innerHTML=sp.id==='all'
   ?'<div class="panel"><h2>All spaces</h2><p>Every message the bot can post, across the three spaces. Each card shows where it goes.</p></div>'
   :'<div class="panel"><h2><span class="dot" style="background:var('+sp.color+');width:12px;height:12px;margin:0"></span>'+esc(sp.name)+' space</h2><p>'+esc(sp.desc)+'</p>'+
    '<div class="meta"><span>Sources <b>'+esc(sp.sources)+'</b></span><span>Messages shown <b>'+cards.length+'</b></span></div></div>';
  document.getElementById('out').innerHTML=FAMILIES.map(f=>{
    const items=cards.filter(c=>c.cat===f.id);
    if(!items.length)return '';
    return '<section><div class="sh"><h2 style="color:var('+f.color+')">'+f.name+'</h2><span class="sd">'+esc(f.desc)+'</span></div><div class="grid">'+items.map(card).join('')+'</div></section>';
  }).join('')||'<section><p class="sd">'+(DATA.cards.length?'No messages in this space yet.':'Samples are loading from the latest run. Try again in a few minutes.')+'</p></section>';
}
const kinds=new Set(DATA.cards.map(c=>c.kind.replace(/Resolved after .*?(?= ·|$)/,'Resolved')));
document.getElementById('stats').innerHTML=
 '<div><b>'+DATA.routing.length+'</b>sources</div><div><b>3</b>Chat spaces</div><div><b>'+kinds.size+'</b>kinds of message</div><div><b>'+DATA.cards.filter(c=>c.live).length+'</b>live right now</div>';
document.getElementById('routing').hidden=!DATA.routing.length;
document.getElementById('rt').innerHTML=DATA.routing.map(r=>'<tr><td><b>'+esc(r.source)+'</b></td><td>'+esc(r.how)+'</td><td>'+esc(r.space)+'</td><td>'+esc(r.extra||'—')+'</td></tr>').join('');
const when=DATA.updated?new Date(DATA.updated).toLocaleString('en-GB',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}):'';
document.getElementById('foot').textContent=(DATA.cards.length
  ?'Live cards come from the latest check of the real feeds'+(when?'; the newest item shown is from '+when+' IST':'')+'. Times inside messages are shown in IST, as the bot posts them.'
  :'The live samples are temporarily unavailable. They return after the next check.');
document.getElementById('chips').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;current=b.dataset.f;try{history.replaceState(null,'','#'+current)}catch(_){}draw()});
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
  return TEMPLATE.replace("__NONCE__", nonce).replace("__DATA__", () => scriptJson(data));
}
