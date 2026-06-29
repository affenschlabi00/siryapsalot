"""A local web GUI for the chatbot: open a browser, chat, download binaries.

Pure stdlib (http.server) — no extra dependencies. `siryapsalot serve` starts it. The page lets
you pick the persona (Lil Yapper / Yapzilla), the LLM provider (OpenAI / Anthropic / Ollama) and
— per provider — which model it uses, chat to build .exe files, and hit an Update button to pull
the newest code from the public repo (and switch branches). Choosing a provider refreshes the
model list to that provider's models (e.g. pick Ollama → its local models; pick OpenAI → gpt-*).
A 🧪 Eval button benchmarks the *selected* model: it runs the agent repair loop over the
oracle-verified task suite in a background thread and streams a live pass/fail scoreboard, so you
can see how good a given model is at turning intent into a correct binary.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer


class ChatService:
    """The testable core: a message in, a reply + (optional) downloadable binary out."""

    def __init__(self, bot=None, build_dir: str = "build", mode=None, model=None,
                 backend_name=None):
        if bot is None:
            from .chatbot import Chatbot, ChatbotGenerator
            bot = Chatbot(ChatbotGenerator(mode=mode, model=model, backend_name=backend_name),
                          out_dir=build_dir)
        self.bot = bot
        self.build_dir = build_dir
        self._eval_lock = threading.Lock()
        self._eval: dict = {"running": False, "done": 0, "total": 0, "results": [],
                            "backend": None, "model": None, "summary": None, "error": None}

    def message(self, text: str, mode=None, model=None, backend=None) -> dict:
        if backend and backend != getattr(self.bot.backend, "name", None):
            try:
                self.bot.set_backend(backend)
            except Exception:
                pass                                  # keep the working backend if the switch fails
        if mode:
            self.bot.switch(mode)
        if model:
            self.bot.set_model(model)
        res = self.bot.send(text)
        download = (os.path.basename(res["path"])
                    if res.get("success") and res.get("path") else None)
        persona = self.bot.mode.name if self.bot.mode else "Sir Yaps-a-Lot"
        return {"reply": res["reply"], "success": res["success"], "persona": persona,
                "download": download, "iterations": res.get("iterations")}

    def _backend_info(self) -> dict:
        """The current provider, its model, and the models it offers (for the model picker)."""
        b = self.bot.backend
        try:
            models = self.bot.models()
        except Exception:
            models = []
        return {"backend": getattr(b, "name", "?"), "model": getattr(b, "model", "?"),
                "models": models}

    def set_backend(self, name: str) -> dict:
        """Switch the LLM provider and report its models, so the model dropdown can refresh."""
        try:
            self.bot.set_backend(name)
            return {"ok": True, **self._backend_info()}
        except Exception as e:
            return {"ok": False, "error": str(e), **self._backend_info()}

    def info(self) -> dict:
        from . import llm, modes, updater
        bi = self._backend_info()
        backends = llm.available_backends()
        if bi["backend"] not in backends and bi["backend"] != "?":
            backends = [bi["backend"]] + backends      # always show the one in use
        return {
            **bi,
            "backends": backends,
            "modes": [{"id": m.id, "name": m.name} for m in modes.MODES.values()],
            "mode": self.bot.mode.id if self.bot.mode else None,
            **updater.status(),
        }

    def update(self, branch=None) -> dict:
        from . import updater
        return updater.update(branch)

    # --- model eval: benchmark a provider/model on the oracle-verified task suite ---------
    def eval_tasks(self) -> list[dict]:
        """The benchmark suite (name + intent), so the UI can preview what will be tested."""
        from .eval import TASKS
        return [{"name": t["name"], "intent": t["intent"]} for t in TASKS]

    def _select_tasks(self, names=None):
        from .eval import TASKS
        if not names:
            return list(TASKS)
        wanted = set(names)
        return [t for t in TASKS if t["name"] in wanted]

    def start_eval(self, max_iters: int = 3, backend=None, model=None,
                   generator=None, task_names=None) -> dict:
        """Kick off a benchmark of the chosen provider/model in a background thread.

        Drives the agent repair loop (agent.solve) over each task and scores it against the
        task's oracle — an objective "how good is this model at building binaries" number.
        Returns immediately; poll eval_status() for live progress. Pass `generator` to test
        without a live model (e.g. agent.LibraryGenerator -> reference solutions)."""
        with self._eval_lock:
            if self._eval.get("running"):
                return {"started": False, "busy": True, **self._snapshot_locked()}
            tasks = self._select_tasks(task_names)
            if not tasks:
                return {"started": False, "error": "no matching tasks"}
            if generator is None:
                try:
                    from .agent import LLMGenerator
                    from .llm import make_backend
                    b = make_backend(prefer=backend) if backend else self.bot.backend
                    if model:
                        b.set_model(model)
                    generator = LLMGenerator(backend=b)
                    bname, mname = getattr(b, "name", "?"), getattr(b, "model", "?")
                except Exception as e:
                    return {"started": False, "error": str(e)}
            else:
                bname = getattr(generator, "name", backend or "reference")
                mname = getattr(generator, "model", model or "reference")
            self._eval = {"running": True, "done": 0, "total": len(tasks), "results": [],
                          "backend": bname, "model": mname, "max_iters": max_iters,
                          "summary": None, "error": None}
        t = threading.Thread(target=self._run_eval, args=(generator, tasks, max_iters),
                             daemon=True)
        t.start()
        with self._eval_lock:
            return {"started": True, **self._snapshot_locked()}

    def _run_eval(self, generator, tasks, max_iters):
        from .agent import solve
        for task in tasks:
            try:
                res = solve(task, generator, max_iters=max_iters, out_dir=self.build_dir)
                entry = self._summarize_solve(res, task)
            except Exception as e:                       # a generator/build blew up on this task
                entry = {"task": task["name"], "intent": task["intent"], "passed": False,
                         "iterations": max_iters, "cases": None, "stage": "exception",
                         "error": str(e)}
            with self._eval_lock:
                self._eval["results"].append(entry)
                self._eval["done"] += 1
        with self._eval_lock:
            results = self._eval["results"]
            passed = sum(1 for r in results if r["passed"])
            total = len(results)
            self._eval["summary"] = {"passed": passed, "total": total,
                                     "score": round(passed / total, 3) if total else 0.0}
            self._eval["running"] = False

    @staticmethod
    def _summarize_solve(res: dict, task: dict) -> dict:
        traj = res.get("trajectory") or []
        last = traj[-1] if traj else {}
        cases = None
        for tc in last.get("tool_calls", []):
            if tc.get("tool") == "diff_behavior":
                cases = [tc.get("pass_count"), tc.get("total")]
        stage = None
        if not res.get("success") and last.get("tool_calls"):
            stage = last["tool_calls"][-1].get("tool")
        return {"task": task["name"], "intent": task["intent"],
                "passed": bool(res.get("success")), "iterations": res.get("iterations"),
                "cases": cases, "stage": stage}

    def _snapshot_locked(self) -> dict:
        e = self._eval
        return {"running": e["running"], "done": e["done"], "total": e["total"],
                "results": list(e["results"]), "backend": e["backend"], "model": e["model"],
                "summary": e["summary"], "error": e.get("error")}

    def eval_status(self) -> dict:
        with self._eval_lock:
            return self._snapshot_locked()


INDEX_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Sir Yaps-a-Lot — build binaries by chatting</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 :root{--bg:#0d1117;--panel:#161b22;--me:#1f6feb;--bot:#21262d;--txt:#e6edf3;--mut:#8b949e}
 *{box-sizing:border-box} body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;
   background:var(--bg);color:var(--txt);height:100vh;display:flex;flex-direction:column}
 header{padding:12px 18px;background:var(--panel);border-bottom:1px solid #30363d;
   display:flex;align-items:center;gap:10px;flex-wrap:wrap}
 header b{font-size:17px} .grow{flex:1}
 select,button.bar{background:#0d1117;color:var(--txt);border:1px solid #30363d;
   border-radius:8px;padding:7px 9px;font-size:13px}
 button.bar{cursor:pointer} button.bar:hover{border-color:var(--me)}
 #log{flex:1;overflow:auto;padding:20px;display:flex;flex-direction:column;gap:14px}
 .msg{max-width:820px;padding:12px 14px;border-radius:12px;white-space:pre-wrap;
   word-wrap:break-word;line-height:1.45}
 .me{align-self:flex-end;background:var(--me);color:#fff;border-bottom-right-radius:3px}
 .bot{align-self:flex-start;background:var(--bot);border-bottom-left-radius:3px;
   font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
 .sys{align-self:center;color:var(--mut);font-size:12px}
 .dl{display:inline-block;margin-top:10px;padding:8px 14px;background:#238636;color:#fff;
   border-radius:8px;text-decoration:none;font-family:system-ui}
 form{display:flex;gap:10px;padding:16px 20px;background:var(--panel);border-top:1px solid #30363d}
 #in{flex:1;padding:12px 14px;border-radius:10px;border:1px solid #30363d;background:#0d1117;
   color:var(--txt);font-size:15px} #send{padding:12px 22px;border:0;border-radius:10px;
   background:var(--me);color:#fff;font-size:15px;cursor:pointer} #send:disabled{opacity:.5}
</style></head><body>
<header>
 <b>Sir Yaps-a-Lot</b>
 <select id="mode" title="who you're chatting with"></select>
 <select id="backend" title="LLM provider"></select>
 <select id="model" title="LLM model"></select>
 <button class="bar" id="evalbtn" title="benchmark the selected model on the task suite">🧪 Eval</button>
 <span class="grow"></span>
 <select id="branch" title="git branch"></select>
 <button class="bar" id="upd" title="pull the newest version from git">⟳ Update</button>
 <span id="ver" style="color:var(--mut);font-size:12px"></span>
</header>
<div id="log"><div class="msg bot">Hi! Tell me what program you want and I'll build it.
Try: "make me a tic-tac-toe game", "primes under 50", or (as Yapzilla) "a window with a button that beeps".</div></div>
<form id="f"><input id="in" autocomplete="off" placeholder="make me a..."><button id="send">Build</button></form>
<script>
const log=document.getElementById('log'),inp=document.getElementById('in'),f=document.getElementById('f'),
      send=document.getElementById('send'),modeSel=document.getElementById('mode'),
      backendSel=document.getElementById('backend'),
      modelSel=document.getElementById('model'),branchSel=document.getElementById('branch'),
      upd=document.getElementById('upd'),ver=document.getElementById('ver'),
      evalbtn=document.getElementById('evalbtn');
function fill(sel,items,cur){sel.innerHTML='';items.forEach(it=>{const o=document.createElement('option');
  o.value=it.value;o.textContent=it.label;if(it.value===cur)o.selected=true;sel.appendChild(o);});}
function add(cls,txt,dl){const d=document.createElement('div');d.className='msg '+cls;d.textContent=txt;
  if(dl){const a=document.createElement('a');a.className='dl';a.href='/download/'+dl;a.textContent='⬇ download '+dl;
  a.setAttribute('download','');d.appendChild(document.createElement('br'));d.appendChild(a);}
  log.appendChild(d);log.scrollTop=log.scrollHeight;}
async function loadInfo(){const j=await (await fetch('/api/info')).json();
  fill(modeSel,j.modes.map(m=>({value:m.id,label:m.name})),j.mode);
  fill(backendSel,(j.backends||[j.backend]).map(b=>({value:b,label:b})),j.backend);
  fill(modelSel,(j.models||[]).map(m=>({value:m,label:m})),j.model);
  if(j.available){fill(branchSel,(j.branches||[]).map(b=>({value:b,label:'🌿 '+b})),j.branch);
    ver.textContent=(j.backend||'')+' · '+(j.model||'')+' · @'+(j.commit||'?');}
  else{branchSel.style.display='none';upd.title='updates need a git checkout (pip install -e .)';
    ver.textContent=(j.backend||'')+' · '+(j.model||'');}}
backendSel.onchange=async()=>{const prev=modelSel.innerHTML;modelSel.innerHTML='<option>…</option>';
  try{const j=await (await fetch('/api/backend',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({backend:backendSel.value})})).json();
    if(j.ok===false){add('sys','⚠️ could not switch to '+backendSel.value+': '+(j.error||''));modelSel.innerHTML=prev;return;}
    fill(modelSel,(j.models||[]).map(m=>({value:m,label:m})),j.model);
    ver.textContent=(j.backend||'')+' · '+(j.model||'');}
  catch(err){add('sys','backend switch error: '+err);modelSel.innerHTML=prev;}};
f.onsubmit=async e=>{e.preventDefault();const m=inp.value.trim();if(!m)return;
  add('me',m);inp.value='';send.disabled=true;
  const t=document.createElement('div');t.className='msg bot';t.textContent='building…';log.appendChild(t);
  try{const r=await fetch('/api/build',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:m,mode:modeSel.value,model:modelSel.value,backend:backendSel.value})});
    const j=await r.json();t.remove();add('bot',(j.persona?j.persona+': ':'')+j.reply,j.download);}
  catch(err){t.remove();add('bot','Error: '+err);}
  send.disabled=false;inp.focus();};
evalbtn.onclick=async()=>{evalbtn.disabled=true;
  const card=document.createElement('div');card.className='msg bot';log.appendChild(card);
  card.textContent='🧪 starting eval…';log.scrollTop=log.scrollHeight;
  function render(s){const head='🧪 Eval — '+(s.backend||'?')+' / '+(s.model||'?');
    const rows=(s.results||[]).map(r=>{const mark=r.passed?'✅':'❌';
      const cas=r.cases?(' '+r.cases[0]+'/'+r.cases[1]+' cases'):'';
      const it=(r.iterations!=null)?(' · '+r.iterations+' iter'):'';
      const why=(!r.passed&&r.stage)?(' · failed@'+r.stage):'';
      return '  '+mark+' '+(r.task||'').padEnd(11)+it+cas+why;});
    let foot='';
    if(s.running)foot='  …running ('+s.done+'/'+s.total+')';
    else if(s.summary)foot='Score: '+s.summary.passed+'/'+s.summary.total+
      ' tasks ('+Math.round(s.summary.score*100)+'%)';
    card.textContent=[head].concat(rows).concat(foot?[foot]:[]).join('\n');
    log.scrollTop=log.scrollHeight;}
  let start;
  try{start=await (await fetch('/api/eval',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({backend:backendSel.value,model:modelSel.value,max_iters:3})})).json();}
  catch(err){card.textContent='eval error: '+err;evalbtn.disabled=false;return;}
  if(start.started===false){card.textContent='⚠️ '+(start.busy?'an eval is already running':
      ('could not start eval: '+(start.error||'')));evalbtn.disabled=false;return;}
  async function poll(){let s;
    try{s=await (await fetch('/api/eval/status')).json();}
    catch(err){evalbtn.disabled=false;return;}
    render(s);if(s.running)setTimeout(poll,1500);else evalbtn.disabled=false;}
  poll();};
upd.onclick=async()=>{upd.disabled=true;add('sys','updating…');
  try{const j=await (await fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({branch:branchSel.value})})).json();
    add('sys',(j.ok?'✅ ':'⚠️ ')+'['+(j.branch||'?')+' @'+(j.commit||'?')+'] '+(j.message||'')+(j.note?'  — '+j.note:''));
    loadInfo();}catch(err){add('sys','update error: '+err);}upd.disabled=false;};
loadInfo();
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

        def _json(self, obj, code=200):
            self._send(code, "application/json", json.dumps(obj).encode())

        def _body(self):
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n)) if n else {}

        def do_GET(self):
            if self.path in ("/", "/index.html") or self.path.startswith("/?"):
                self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode())
            elif self.path == "/api/info":
                try:
                    self._json(service.info())
                except Exception as e:
                    self._json({"backend": "?", "model": "?", "models": [], "modes": [],
                                "available": False, "error": str(e)})
            elif self.path == "/api/eval/status":
                self._json(service.eval_status())
            elif self.path == "/api/eval/tasks":
                self._json({"tasks": service.eval_tasks()})
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
            try:
                body = self._body()
            except Exception:
                self._json({"error": "bad request"}, 400)
                return
            if self.path == "/api/build":
                try:
                    out = service.message(body["message"], mode=body.get("mode"),
                                          model=body.get("model"), backend=body.get("backend"))
                except Exception as e:
                    out = {"reply": f"Sorry, that failed: {e}", "success": False, "download": None}
                self._json(out)
            elif self.path == "/api/backend":
                try:
                    self._json(service.set_backend(body.get("backend")))
                except Exception as e:
                    self._json({"ok": False, "error": str(e)})
            elif self.path == "/api/eval":
                try:
                    self._json(service.start_eval(max_iters=int(body.get("max_iters", 3)),
                                                  backend=body.get("backend"),
                                                  model=body.get("model"),
                                                  task_names=body.get("tasks")))
                except Exception as e:
                    self._json({"started": False, "error": str(e)})
            elif self.path == "/api/update":
                try:
                    self._json(service.update(body.get("branch")))
                except Exception as e:
                    self._json({"ok": False, "message": str(e)})
            else:
                self._send(404, "text/plain", b"not found")

    return Handler


def serve(port: int = 8765, host: str = "127.0.0.1", bot=None, mode=None,
          model=None, backend_name=None):
    service = ChatService(bot=bot, mode=mode, model=model, backend_name=backend_name)
    httpd = HTTPServer((host, port), make_handler(service))
    print(f"siryapsalot chat UI → http://{host}:{port}   (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye!")
