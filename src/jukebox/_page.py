PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jukebox</title>
<style>
:root{color-scheme:light dark;--b:#8884;--a:#2a7}
body{font:16px/1.4 system-ui,sans-serif;margin:0 auto;max-width:46rem;padding:1rem}
h1{font-size:1.3rem;margin:.2rem 0 1rem} h2{font-size:1rem;margin:1.4rem 0 .5rem;text-transform:uppercase;letter-spacing:.05em;opacity:.7}
section{border:1px solid var(--b);border-radius:.6rem;padding:.8rem;margin-bottom:1rem}
button,input,select{font:inherit;padding:.45rem .7rem;border:1px solid var(--b);border-radius:.4rem;background:Canvas;color:CanvasText}
button{cursor:pointer} button.primary{background:var(--a);color:#fff;border-color:var(--a)} button.danger{color:#c33}
.row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin:.3rem 0}
.row>input,.row>select{flex:1;min-width:8rem} label{display:block;font-size:.85rem;opacity:.7;margin-top:.5rem}
#nowrow{display:flex;gap:.8rem;align-items:center} #nowrow>div{flex:1;min-width:0}
#cover{width:6rem;height:6rem;object-fit:cover;border-radius:.4rem;flex:none;background:var(--b)}
#now{font-size:1.1rem} #err{color:#c33;min-height:1.2em} .muted{opacity:.65}
#last{padding:.6rem;border-radius:.4rem;background:#2a72;margin-bottom:.6rem}
table{width:100%;border-collapse:collapse} td{padding:.4rem .3rem;border-top:1px solid var(--b);vertical-align:top;word-break:break-all}
td.act{white-space:nowrap;text-align:right} input[type=range]{padding:0;flex:2}
details>summary{cursor:pointer;font-size:1rem;text-transform:uppercase;letter-spacing:.05em;opacity:.8;padding:.2rem 0}
details[open]>summary{margin-bottom:.6rem}
</style></head><body>
<h1>Jukebox</h1>

<section>
  <div id="nowrow"><img id="cover" alt="" hidden referrerpolicy="no-referrer">
    <div><div id="now">&nbsp;</div><div id="err"></div></div></div>
  <div class="row">
    <button data-act="prev">&#9198;</button><button data-act="play_pause" class="primary">&#9199;</button>
    <button data-act="next">&#9197;</button><button data-act="stop">&#9209;</button>
    <input type="range" id="vol" min="0" max="80" value="0"><span id="volv"></span>
  </div>
</section>

<section>
  <h2 style="margin-top:0">Assign a card</h2>
  <div id="last" class="muted">Put a card on the reader and its ID shows up here.</div>
  <label>Card ID</label><input id="f-id" autocomplete="off" style="width:100%;box-sizing:border-box">
  <label>Name (optional)</label><input id="f-name" autocomplete="off" style="width:100%;box-sizing:border-box">
  <label>What should it do?</label>
  <div class="row"><select id="f-type">
    <option value="spotify">Play from Spotify (paste a link)</option>
    <option value="folder">Play a local folder</option>
    <option value="stream">Play a web radio / stream</option>
    <option value="action">Run an action</option></select></div>
  <div class="row"><input id="f-spotify" placeholder="https://open.spotify.com/playlist/... or spotify:playlist:...">
    <input id="f-stream" placeholder="https://... (address of the stream)" hidden>
    <input id="f-folder" list="folders" placeholder="folder under the music root" hidden>
    <select id="f-action" hidden></select><input id="f-arg" type="number" placeholder="value" hidden style="max-width:7rem;flex:none"></div>
  <datalist id="folders"></datalist>
  <div class="row"><button id="save" class="primary">Save card</button><button id="clear">Clear</button><span id="msg"></span></div>
</section>

<section>
  <details id="cardsbox">
    <summary>Cards <span id="count" class="muted"></span></summary>
    <input id="filter" placeholder="Search" style="width:100%;box-sizing:border-box;margin-bottom:.5rem">
    <table id="cards"></table>
  </details>
</section>

<section>
  <div class="row"><button id="shutdown" class="danger">Shut down the jukebox</button><span id="sysmsg" class="muted"></span></div>
</section>

<script>
const $ = id => document.getElementById(id);
const post = (u, b, m = "POST") => fetch(u, {method: m, headers: {"Content-Type": "application/json"}, body: JSON.stringify(b || {})})
  .then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.status); return j; });
let cards = [], lastSeen = 0, total = null, loaded = {};
// The list, the folders and the actions are fetched only when they are needed: the page itself stays small and
// opens quickly on a poor Wi-Fi.
const once = (key, url, fn) => loaded[key] ? null : (loaded[key] = fetch(url).then(r => r.json()).then(fn).catch(() => { loaded[key] = null; }));
const ARG = {volume_set: ["value", "volume 0-100"], seek_forward: ["seconds", "seconds"], seek_back: ["seconds", "seconds"]};

document.querySelectorAll("[data-act]").forEach(b => b.onclick = () => post("/api/action", {name: b.dataset.act}).catch(e => $("err").textContent = e.message));
$("shutdown").onclick = async () => {
  if (!confirm("Shut the jukebox down? It has to be switched on again by hand.")) return;
  try { await post("/api/action", {name: "shutdown"}); $("sysmsg").textContent = "Shutting down. Wait a few seconds before you cut the power."; }
  catch (e) { $("sysmsg").textContent = e.message; }
};
let coverNow = "";
$("cover").onload = () => $("cover").hidden = false;
$("cover").onerror = () => $("cover").hidden = true;
$("vol").onchange = () => post("/api/action", {name: "volume_set", args: {value: +$("vol").value}});
$("vol").oninput = () => $("volv").textContent = $("vol").value;

function show() {
  const t = $("f-type").value;
  $("f-spotify").hidden = t !== "spotify"; $("f-folder").hidden = t !== "folder"; $("f-stream").hidden = t !== "stream";
  $("f-action").hidden = t !== "action";
  $("f-arg").hidden = !(t === "action" && ARG[$("f-action").value]);
  if (t === "folder") once("folders", "/api/folders", j => $("folders").replaceChildren(...j.map(n => new Option(n, n))));
  if (t === "action") once("actions", "/api/actions", j => { const v = $("f-action").value; $("f-action").replaceChildren(...j.map(n => new Option(n, n))); if (v) $("f-action").value = v; show(); });
  if (!$("f-arg").hidden) $("f-arg").placeholder = ARG[$("f-action").value][1];
}
$("f-type").onchange = $("f-action").onchange = show;

function clearForm() { for (const i of ["f-id","f-name","f-spotify","f-folder","f-stream","f-arg"]) $(i).value = ""; $("msg").textContent = ""; }
$("clear").onclick = clearForm;

$("save").onclick = async () => {
  const t = $("f-type").value, body = {name: $("f-name").value};
  if (t === "spotify") body.play = $("f-spotify").value;
  else if (t === "folder") body.play = "folder:" + $("f-folder").value;
  else if (t === "stream") body.play = "stream:" + $("f-stream").value;
  else { body.action = $("f-action").value; const a = ARG[body.action];
    if (a) { if ($("f-arg").value === "") { $("msg").textContent = "Value needed"; return; } body.args = {[a[0]]: +$("f-arg").value}; } }
  try { await post("/api/cards/" + encodeURIComponent($("f-id").value.trim()), body, "PUT");
    clearForm(); $("msg").textContent = "Saved"; if ($("cardsbox").open) loadCards(); else total = null;
  } catch (e) { $("msg").textContent = e.message; }
};

function edit(c) {
  $("f-id").value = c.id; $("f-name").value = c.name || ""; $("msg").textContent = "";
  if (c.action) { $("f-type").value = "action";
    if (!loaded.actions) $("f-action").replaceChildren(new Option(c.action, c.action));   // the full list follows in show()
    $("f-action").value = c.action; const a = ARG[c.action]; $("f-arg").value = a ? (c.args[a[0]] ?? "") : ""; }
  else if (c.play.startsWith("spotify:")) { $("f-type").value = "spotify"; $("f-spotify").value = c.play; }
  else if (c.play.startsWith("stream:")) { $("f-type").value = "stream"; $("f-stream").value = c.play.slice(7); }
  else { $("f-type").value = "folder"; $("f-folder").value = c.play.replace(/^(folder|file):/, ""); }
  show(); window.scrollTo({top: $("f-id").offsetTop - 80, behavior: "smooth"});
}

function render() {
  const q = $("filter").value.toLowerCase(), tb = $("cards"); tb.replaceChildren();
  const list = cards.filter(c => (c.id + " " + (c.name || "") + " " + (c.play || c.action)).toLowerCase().includes(q))
    .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
  $("count").textContent = `(${list.length}${list.length !== cards.length ? " of " + cards.length : ""})`;
  for (const c of list) {
    const tr = tb.insertRow(), a = tr.insertCell(), d = tr.insertCell(), x = tr.insertCell();
    a.textContent = c.name || "(no name)"; const id = document.createElement("div"); id.className = "muted"; id.textContent = c.id; a.append(id);
    d.textContent = c.play || ("action: " + c.action + (Object.keys(c.args || {}).length ? " " + JSON.stringify(c.args) : ""));
    x.className = "act";
    for (const [label, fn, cls] of [["Play", async function () { // feedback: shows when the box has received the request
          this.textContent = "…"; try { await post("/api/cards/" + encodeURIComponent(c.id) + "/play"); this.textContent = "✓"; $("err").textContent = ""; }
          catch (e) { this.textContent = "Play"; $("err").textContent = e.message; } setTimeout(() => this.textContent = "Play", 2000); }], ["Edit", () => edit(c)],
        ["Delete", async () => { if (confirm("Delete card " + (c.name || c.id) + "?")) { await post("/api/cards/" + encodeURIComponent(c.id), {}, "DELETE"); loadCards(); } }, "danger"]]) {
      const b = document.createElement("button"); b.textContent = label; if (cls) b.className = cls; b.onclick = () => fn.call(b); x.append(b, " ");
    }
  }
}
$("filter").oninput = render;
const loadCards = () => fetch("/api/cards").then(r => r.json()).then(j => { cards = j; total = j.length; render(); });
$("cardsbox").ontoggle = () => { if ($("cardsbox").open && total === null) loadCards(); };

// One request at a time, the next one only after the previous has finished (a slow link must not pile up
// requests), paused while the tab is hidden, slower after a failure.
let pollTimer = null;
async function poll() {
  clearTimeout(pollTimer); let delay = 1500;
  const ctl = new AbortController(), kill = setTimeout(() => ctl.abort(), 8000);
  try {
    const s = await (await fetch("/api/state", {signal: ctl.signal})).json();
    $("now").textContent = (s.playing ? "▶ " : "⏸ ") + (s.target ? (s.name || s.target) : "nothing playing");
    $("err").textContent = s.error || "";
    if ((s.cover || "") !== coverNow) {          // load the picture only when it changes
      coverNow = s.cover || "";
      if (coverNow) $("cover").src = coverNow; else { $("cover").hidden = true; $("cover").removeAttribute("src"); }
    }
    $("vol").max = s.max_volume; if (document.activeElement !== $("vol")) { $("vol").value = s.volume; $("volv").textContent = s.volume; }
    if (!$("cardsbox").open) { $("count").textContent = `(${s.cards})`; if (total !== s.cards) total = null; }
    else if (total !== null && s.cards !== total) loadCards();   // changed elsewhere (sync, other browser)
    if (s.last_card && s.last_card_time !== lastSeen) {
      const first = lastSeen === 0; lastSeen = s.last_card_time;
      const box = $("last"); box.className = ""; box.textContent = "Last card: " + s.last_card + (s.last_card_known ? " (known: " + (s.last_card_name || "no name") + ")" : " (not assigned yet)");
      if (!first && !s.last_card_known) { $("f-id").value = s.last_card; }
    }
  } catch (e) { $("err").textContent = "no connection"; delay = 5000; }
  clearTimeout(kill);
  if (!document.hidden) pollTimer = setTimeout(poll, delay);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });

poll(); show();
</script></body></html>
"""
