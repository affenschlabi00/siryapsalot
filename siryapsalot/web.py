"""A local web GUI for the chatbot: open a browser, chat, download binaries.

Pure stdlib (http.server) — no extra dependencies. `siryapsalot serve` starts it; the page POSTs
each message to /api/build, which runs the chatbot and returns the reply plus a download link to
the freshly built .exe.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer


class ChatService:
    """The testable core: a message in, a reply + (optional) downloadable binary out."""

    def __init__(self, bot=None, build_dir: str = "build", mode=None):
        if bot is None:
            from .chatbot import Chatbot, ChatbotGenerator
            bot = Chatbot(ChatbotGenerator(mode=mode), out_dir=build_dir)
        self.bot = bot
        self.build_dir = build_dir

    def message(self, text: str, mode=None) -> dict:
        if mode:
            self.bot.switch(mode)
        res = self.bot.send(text)
        download = (os.path.basename(res["path"])
                    if res.get("success") and res.get("path") else None)
        persona = self.bot.mode.name if self.bot.mode else "Sir Yaps-a-Lot"
        return {"reply": res["reply"], "success": res["success"], "persona": persona,
                "download": download, "iterations": res.get("iterations")}


INDEX_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Sir Yaps-a-Lot — build binaries by chatting</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 :root{--bg:#0d1117;--panel:#161b22;--me:#1f6feb;--bot:#21262d;--txt:#e6edf3;--mut:#8b949e}
 *{box-sizing:border-box} body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;
   background:var(--bg);color:var(--txt);height:100vh;display:flex;flex-direction:column}
 header{padding:14px 20px;background:var(--panel);border-bottom:1px solid #30363d}
 header b{font-size:17px} header span{color:var(--mut);font-size:13px;margin-left:8px}
 #log{flex:1;overflow:auto;padding:20px;display:flex;flex-direction:column;gap:14px}
 .msg{max-width:780px;padding:12px 14px;border-radius:12px;white-space:pre-wrap;
   word-wrap:break-word;line-height:1.45}
 .me{align-self:flex-end;background:var(--me);color:#fff;border-bottom-right-radius:3px}
 .bot{align-self:flex-start;background:var(--bot);border-bottom-left-radius:3px;
   font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
 .dl{display:inline-block;margin-top:10px;padding:8px 14px;background:#238636;color:#fff;
   border-radius:8px;text-decoration:none;font-family:system-ui}
 form{display:flex;gap:10px;padding:16px 20px;background:var(--panel);border-top:1px solid #30363d}
 #in{flex:1;padding:12px 14px;border-radius:10px;border:1px solid #30363d;background:#0d1117;
   color:var(--txt);font-size:15px} #send{padding:12px 22px;border:0;border-radius:10px;
   background:var(--me);color:#fff;font-size:15px;cursor:pointer} #send:disabled{opacity:.5}
 .hint{color:var(--mut);font-size:13px}
 header{display:flex;align-items:center;gap:12px}
 #mode{margin-left:auto;background:#0d1117;color:var(--txt);border:1px solid #30363d;
   border-radius:8px;padding:8px 10px;font-size:14px}
</style></head><body>
<header><b>Sir Yaps-a-Lot</b><span>pick who builds your .exe →</span>
 <select id="mode" title="who you're chatting with">
   <option value="classic">🙂 Lil Yapper — simple</option>
   <option value="deluxe">😈 Yapzilla — full GUI + sound</option>
 </select></header>
<div id="log"><div class="msg bot">Hi! Tell me what program you want and I'll build it.
Try: "make me a tic-tac-toe game", "a program that prints the primes under 50", or
"pop up a message box that says hello".</div></div>
<form id="f"><input id="in" autocomplete="off" placeholder="make me a..."><button id="send">Build</button></form>
<script>
const log=document.getElementById('log'),inp=document.getElementById('in'),
      f=document.getElementById('f'),send=document.getElementById('send');
function add(cls,txt,dl){const d=document.createElement('div');d.className='msg '+cls;d.textContent=txt;
  if(dl){const a=document.createElement('a');a.className='dl';a.href='/download/'+dl;a.textContent='⬇ download '+dl;
  a.setAttribute('download','');d.appendChild(document.createElement('br'));d.appendChild(a);}
  log.appendChild(d);log.scrollTop=log.scrollHeight;}
f.onsubmit=async e=>{e.preventDefault();const m=inp.value.trim();if(!m)return;
  add('me',m);inp.value='';send.disabled=true;
  const t=document.createElement('div');t.className='msg bot';t.textContent='building…';log.appendChild(t);
  const mode=document.getElementById('mode').value;
  try{const r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:m,mode:mode})});const j=await r.json();t.remove();
    add('bot',(j.persona?j.persona+': ':'')+j.reply,j.download);}catch(err){t.remove();add('bot','Error: '+err);}
  send.disabled=false;inp.focus();};
</script></body></html>"""


def make_handler(service: ChatService):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, ctype, data, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html") or self.path.startswith("/?"):
                self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode())
            elif self.path.startswith("/download/"):
                name = os.path.basename(urllib.parse.unquote(self.path[len("/download/"):]))
                fp = os.path.join(service.build_dir, name)
                if os.path.isfile(fp):
                    with open(fp, "rb") as fh:
                        data = fh.read()
                    self._send(200, "application/octet-stream", data,
                               {"Content-Disposition": f'attachment; filename="{name}"'})
                else:
                    self._send(404, "text/plain", b"not found")
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            if self.path != "/api/build":
                self._send(404, "text/plain", b"not found")
                return
            n = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(n))
                msg = body["message"]
            except Exception:
                self._send(400, "application/json", b'{"error":"bad request"}')
                return
            try:
                out = service.message(msg, mode=body.get("mode"))
            except Exception as e:  # never let one bad build kill the server
                out = {"reply": f"Sorry, that failed: {e}", "success": False, "download": None}
            self._send(200, "application/json", json.dumps(out).encode())

    return Handler


def serve(port: int = 8765, host: str = "127.0.0.1", bot=None, mode=None):
    service = ChatService(bot=bot, mode=mode)
    httpd = HTTPServer((host, port), make_handler(service))
    print(f"siryapsalot chat UI → http://{host}:{port}   (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye!")
