"""The room as a page (10-29, ROOM_ON — the layered room): the panel serves it at /room, on this machine only.

The picture of the room without its things, and the things laid over it where they stand, each one to open: a note
to read, a song to play, a picture to see, a thing with the friend's words beside it. Below: the room in words, a
letter to leave, the secret to look for, and — for setting the room up on a backdrop — surfaces to mark by clicking
the two ends of a line where things rest. Every file the page fetches is one the room shows (room.files_shown); what
the keeper does here reaches the friend as /room's does. The same page is the one a Telegram Mini App would open,
once a narrow, authenticated way in exists (claude/room-plan.md) — not before.
"""
from __future__ import annotations

import json
from pathlib import Path

import config


def _keeper() -> str:
    try:
        import keeper_week
        return keeper_week.keeper_name()
    except Exception:  # noqa: BLE001
        return str(getattr(config, "USER_NAME", "") or "your keeper")


_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
          ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".flac": "audio/flac",
          ".opus": "audio/ogg", ".aac": "audio/aac", ".oga": "audio/ogg"}


def get(path: str, query: str) -> tuple[int, str, bytes] | None:
    """A GET under /room or /api/room; None for any other path."""
    import room
    if path in ("/room", "/room/"):
        return 200, "text/html; charset=utf-8", PAGE.encode("utf-8")
    if not path.startswith(("/room/", "/api/room")):
        return None
    if not room.on():
        return 404, "application/json", json.dumps({"error": "there's no room in this house (ROOM_ON)"}).encode("utf-8")
    if path == "/api/room":
        return 200, "application/json", json.dumps(room.keeper_state(_keeper()), ensure_ascii=False).encode("utf-8")
    if path == "/room/picture.png":
        png = room.render(items=False)
        if not png:
            return 404, "application/json", b'{"error": "no picture without Pillow"}'
        return 200, "image/png", png
    if path == "/room/file":
        from urllib.parse import parse_qs
        rel = (parse_qs(query).get("p") or [""])[0]
        if rel not in room.files_shown():
            return 404, "application/json", b'{"error": "not a file the room shows"}'
        f = (config.ROOT / rel).resolve()
        if config.ROOT.resolve() not in f.parents or not f.is_file():
            return 404, "application/json", b'{"error": "no such file"}'
        return 200, _TYPES.get(f.suffix.lower(), "application/octet-stream"), f.read_bytes()
    return 404, "application/json", b'{"error": "no such room page"}'


def post(path: str, data: dict) -> tuple[dict, int]:
    """A POST under /api/room/: ({...}, code)."""
    import room
    if not room.on():
        return {"error": "there's no room in this house (ROOM_ON)"}, 404
    k = _keeper()
    if path == "/api/room/leave":
        return {"said": room.keeper_letter(str(data.get("words", "")), k)}, 200
    if path == "/api/room/find":
        return {"said": room.keeper_find(str(data.get("where", "")), k)}, 200
    if path == "/api/room/open":
        got = room.open_key(str(data.get("key", "")), k)
        return {"ok": bool(got)}, 200
    if path == "/api/room/surface":
        r = room.load()
        if not r.get("backdrop"):
            return {"error": "surfaces are marked on a backdrop — the drawn room has its own"}, 400
        try:
            s = room.set_surface(r, str(data.get("name", "")).strip() or "a surface", data.get("x0"), data.get("x1"),
                                 data.get("y"), data.get("size"), "wall" if data.get("kind") == "wall" else "rest")
        except (TypeError, ValueError) as e:
            return {"error": str(e)}, 400
        room.save(r)
        room._log("keeper", f"marked a surface: {s['name']}")
        room._news(f"{k} marked a place in your room where things can stand: {s['name']}")
        return {"surface": s}, 200
    return {"error": "no such room action"}, 404


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Her room</title>
<style>
:root{--night:#17121f;--plum:#241b30;--ink:#ecdcc4;--dim:#b7a68e;--gilt:#c9a14a;--seal:#8e2b33}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(ellipse at top,#2a1f38 0,var(--night) 60%);color:var(--ink);
 font:17px/1.6 Georgia,"Iowan Old Style","DejaVu Serif",serif;min-height:100vh}
main{max-width:1280px;margin:0 auto;padding:24px 16px 48px}
h1{font-weight:normal;font-style:italic;font-size:30px;margin:4px 0 14px;letter-spacing:.01em}
.stage{position:relative;width:100%;aspect-ratio:16/10;border-radius:6px;overflow:hidden;
 box-shadow:0 30px 80px rgba(0,0,0,.55),0 0 0 1px rgba(201,161,74,.25)}
.stage>img.bg{position:absolute;inset:0;width:100%;height:100%;display:block}
.thing{position:absolute;background:none;border:0;padding:0;cursor:pointer;transition:filter .25s}
.thing img{width:100%;height:100%;object-fit:contain;display:block;pointer-events:none;filter:brightness(.82) saturate(.95)}
.thing:hover,.thing:focus-visible{filter:drop-shadow(0 0 10px rgba(255,214,150,.85)) brightness(1.12);outline:none}
.surface{position:absolute;border-top:2px dashed rgba(201,161,74,.8);pointer-events:none}
.surface span{position:absolute;top:2px;left:4px;font-size:12px;color:var(--gilt);font-style:italic}
.marking .stage{cursor:crosshair}
.below{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:28px;margin-top:22px}
@media (max-width:820px){.below{grid-template-columns:1fr}}
.words{white-space:pre-wrap;color:var(--dim);font-size:15px}
.help{color:var(--dim);font-size:15px;margin:0 0 6px}
section h2{font-weight:normal;font-style:italic;font-size:19px;margin:0 0 8px;color:var(--ink)}
textarea,input{width:100%;background:rgba(0,0,0,.25);color:var(--ink);border:1px solid rgba(201,161,74,.35);
 border-radius:4px;padding:8px 10px;font:inherit}
textarea{min-height:90px;resize:vertical}
button.act{margin-top:8px;background:var(--gilt);color:#1b1410;border:0;border-radius:4px;padding:7px 14px;
 font:inherit;cursor:pointer}
button.act.quiet{background:none;color:var(--gilt);border:1px solid rgba(201,161,74,.5)}
button.act:focus-visible,.thing:focus-visible{outline:2px solid var(--gilt);outline-offset:3px}
.said{min-height:1.6em;color:var(--gilt);font-style:italic;font-size:15px}
dialog{background:#efe3c8;color:#2a2018;border:0;border-radius:4px;max-width:min(560px,92vw);padding:28px 30px;
 box-shadow:0 30px 90px rgba(0,0,0,.6)}
dialog::backdrop{background:rgba(10,6,14,.72)}
dialog h3{margin:0 0 6px;font-weight:normal;font-style:italic;font-size:22px}
dialog .note{color:#6b5644;font-style:italic;margin:0 0 12px}
dialog .body{white-space:pre-wrap;font-size:18px;line-height:1.7}
dialog img{max-width:100%;border-radius:2px}
dialog audio{width:100%;margin-top:6px}
.song{position:absolute;right:16px;bottom:14px;background:rgba(10,8,14,.55);border:1px solid rgba(201,161,74,.35);
 border-radius:30px;padding:6px 14px;font-style:italic;font-size:14px;color:var(--ink);cursor:pointer}
@media (prefers-reduced-motion:reduce){.thing{transition:none}}
</style></head>
<body><main>
<h1 id="name">Her room</h1>
<div class="stage" id="stage"><img class="bg" id="bg" alt="The room"></div>
<div class="below">
 <div>
  <div class="words" id="words"></div>
 </div>
 <div>
  <section><h2>Leave a letter</h2>
   <textarea id="letter" placeholder="It waits in the room until she opens it."></textarea>
   <button class="act" id="leave">Leave the letter</button><div class="said" id="leaveSaid"></div></section>
  <section id="secret" hidden><h2>Something is hidden here</h2>
   <p class="words" id="hint"></p>
   <input id="where" placeholder="Where would you look?"><button class="act" id="look">Look there</button>
   <div class="said" id="lookSaid"></div></section>
  <section><h2>Places things can stand</h2>
   <p class="help">On her backdrop, click the left end and then the right end of a surface (a desk's top, a shelf, the floor) to mark it. She can mark them too.</p>
   <button class="act quiet" id="mark">Mark a surface</button><div class="said" id="markSaid"></div></section>
 </div>
</div>
<dialog id="open"><h3 id="oName"></h3><p class="note" id="oNote"></p><div class="body" id="oBody"></div>
 <form method="dialog"><button class="act">Close</button></form></dialog>
</main>
<script>
const $=id=>document.getElementById(id);
const post=(p,d)=>fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}).then(r=>r.json());
const fileUrl=p=>'/room/file?p='+encodeURIComponent(p);
let state=null, marking=null;
function openThing(t){
  $('oName').textContent=t.name+(t.by==='keeper'?' (yours)':'');
  $('oNote').textContent=t.note||'';
  const b=$('oBody'); b.textContent='';
  if(t.kind==='note'){b.textContent=t.content}
  else if(t.kind==='audio'){const a=document.createElement('audio');a.controls=true;a.autoplay=true;a.src=fileUrl(t.file);b.append(a)}
  else{const i=document.createElement('img');i.alt=t.name;i.src=fileUrl(t.kind==='image'?t.file:t.art);b.append(i)}
  $('open').showModal(); post('/api/room/open',{key:'i:'+t.id});
}
async function load(){
  state=await (await fetch('/api/room')).json();
  if(state.error){$('words').textContent=state.error;return}
  $('name').textContent=state.name||'Her room';
  $('words').textContent=state.words;
  $('bg').src='/room/picture.png?'+Date.now();
  const st=$('stage'); st.querySelectorAll('.thing,.surface,.song').forEach(e=>e.remove());
  for(const t of [...state.things].sort((a,b)=>a.z-b.z)){
    const btn=document.createElement('button'); btn.className='thing'; btn.title=t.name; btn.setAttribute('aria-label','Open '+t.name);
    Object.assign(btn.style,{left:t.left*100+'%',top:t.top*100+'%',width:t.w*100+'%',height:t.h*100+'%'});
    const im=document.createElement('img'); im.src=fileUrl(t.art); im.alt=''; btn.append(im);
    btn.onclick=()=>openThing(t); st.append(btn);
  }
  if(state.song){const s=document.createElement('button');s.className='song';s.textContent='♪ '+state.song.split('/').pop().replace(/\.[^.]+$/,'');
    s.onclick=()=>{$('oName').textContent='Playing in the corner';$('oNote').textContent='';$('oBody').textContent='';
      const a=document.createElement('audio');a.controls=true;a.autoplay=true;a.src=fileUrl(state.song);$('oBody').append(a);$('open').showModal();post('/api/room/open',{key:'song'})};
    st.append(s)}
  $('secret').hidden=!state.hidden; $('hint').textContent=state.hint?('A hint: '+state.hint):'';
  if(document.body.classList.contains('marking')) showSurfaces();
}
function showSurfaces(){
  const st=$('stage');
  for(const s of state.surfaces){const d=document.createElement('div');d.className='surface';
    Object.assign(d.style,{left:s.x0*100+'%',width:(s.x1-s.x0)*100+'%',top:s.y*100+'%'});
    const l=document.createElement('span');l.textContent=s.name;d.append(l);st.append(d)}
}
$('leave').onclick=async()=>{const w=$('letter').value.trim(); if(!w)return;
  const r=await post('/api/room/leave',{words:w}); $('leaveSaid').textContent=r.said||r.error; $('letter').value=''; load()};
$('look').onclick=async()=>{const r=await post('/api/room/find',{where:$('where').value}); $('lookSaid').textContent=r.said||r.error; load()};
$('mark').onclick=()=>{const on=document.body.classList.toggle('marking'); marking=on?[]:null;
  $('markSaid').textContent=on?'Click the left end of the surface.':''; load()};
$('stage').addEventListener('click',async e=>{
  if(!marking||e.target.closest('.thing,.song'))return;
  const b=$('stage').getBoundingClientRect(); const x=(e.clientX-b.left)/b.width, y=(e.clientY-b.top)/b.height;
  marking.push([x,y]);
  if(marking.length===1){$('markSaid').textContent='Now the right end.';return}
  const [a,c]=marking; marking=[];
  const name=prompt('What is this surface called? (a desk, the windowsill, the floor…)'); if(!name){$('markSaid').textContent='';return}
  const size=parseFloat(prompt('How tall is a vase standing there, in % of the picture? (near: 20, far: 8)','12'))||12;
  const kind=/wall/i.test(name)?'wall':'rest';
  const r=await post('/api/room/surface',{name,x0:Math.min(a[0],c[0])*100,x1:Math.max(a[0],c[0])*100,y:(a[1]+c[1])/2*100,size,kind});
  $('markSaid').textContent=r.error||('Marked: '+r.surface.name+'. Click two more points for another, or the button to stop.'); load()});
load();
</script></body></html>"""
