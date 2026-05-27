"""Flask web console: password-protected view + control dashboard.

A single process serves this app and runs the trading loop in a background
thread (see BotController). Deploy with exactly one worker.
"""
from __future__ import annotations

import functools
import hmac
import os
import secrets
from collections import deque
from pathlib import Path

from flask import (Flask, Response, jsonify, redirect, render_template_string,
                   request, session, url_for)

from ..config import load_config
from .controller import BotController

LOG_FILE = os.getenv("LOG_FILE", "logs/bot.log")


def _check_password(supplied: str) -> bool:
    expected = os.getenv("CONSOLE_PASSWORD", "")
    if not expected:
        return False
    return hmac.compare_digest(supplied or "", expected)


def _tail(path: str, n: int = 200) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return list(deque(fh, maxlen=n))


def require_auth(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("auth"):
            return view(*args, **kwargs)
        # API clients may pass a bearer token equal to the console password.
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and _check_password(auth[7:]):
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"error": "unauthorized"}), 401
        return redirect(url_for("login"))
    return wrapped


def create_app(project_root: Path | None = None) -> Flask:
    root = project_root or Path(__file__).resolve().parent.parent.parent
    cfg = load_config(root)
    mode = cfg.env.run_mode if cfg.env.run_mode in {"paper", "live"} else "paper"

    app = Flask(__name__)
    app.secret_key = os.getenv("CONSOLE_SECRET") or secrets.token_hex(32)

    controller = BotController(cfg, mode)
    controller.start()
    app.config["controller"] = controller

    # ---- auth ----------------------------------------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not os.getenv("CONSOLE_PASSWORD"):
            return ("CONSOLE_PASSWORD is not set; the console is disabled. "
                    "Set it in the environment to enable login."), 503
        error = ""
        if request.method == "POST":
            if _check_password(request.form.get("password", "")):
                session["auth"] = True
                return redirect(url_for("dashboard"))
            error = "Incorrect password."
        return render_template_string(LOGIN_HTML, error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---- views ---------------------------------------------
    @app.route("/")
    @require_auth
    def dashboard():
        return render_template_string(DASHBOARD_HTML, mode=mode)

    @app.route("/api/status")
    @require_auth
    def api_status():
        return jsonify(controller.status())

    @app.route("/api/logs")
    @require_auth
    def api_logs():
        return jsonify({"lines": _tail(LOG_FILE, 200)})

    @app.route("/api/action/<name>", methods=["POST"])
    @require_auth
    def api_action(name: str):
        actions = {
            "pause": controller.pause,
            "resume": controller.resume,
            "cancel-all": controller.cancel_all,
            "convert": controller.convert,
            "emergency-stop": controller.emergency_stop,
            "clear-kill": controller.clear_kill_switch,
        }
        fn = actions.get(name)
        if fn is None:
            return jsonify({"error": f"unknown action {name}"}), 400
        fn()
        return jsonify({"ok": True, "action": name})

    @app.route("/healthz")
    def healthz():
        return Response("ok", mimetype="text/plain")

    return app


LOGIN_HTML = """
<!doctype html><html><head><meta charset="utf-8"><title>SOL Grid Bot</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;
  display:flex;height:100vh;align-items:center;justify-content:center;margin:0}
 form{background:#161b22;padding:32px;border-radius:12px;border:1px solid #30363d;
  width:300px}
 h1{font-size:18px;margin:0 0 16px}
 input{width:100%;padding:10px;margin:8px 0;background:#0d1117;color:#c9d1d9;
  border:1px solid #30363d;border-radius:6px;box-sizing:border-box}
 button{width:100%;padding:10px;background:#238636;color:#fff;border:0;
  border-radius:6px;cursor:pointer;font-weight:600}
 .err{color:#f85149;font-size:13px;min-height:16px}
</style></head><body>
<form method="post">
 <h1>SOL Accumulation Grid Bot</h1>
 <div class="err">{{ error }}</div>
 <input type="password" name="password" placeholder="Console password" autofocus>
 <button type="submit">Sign in</button>
</form></body></html>
"""

DASHBOARD_HTML = """
<!doctype html><html><head><meta charset="utf-8"><title>SOL Grid Bot Console</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;margin:0;
  padding:16px}
 h1{font-size:18px;margin:0 0 4px}
 .sub{color:#8b949e;font-size:13px;margin-bottom:16px}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:12px;margin-bottom:16px}
 .card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px}
 .card .label{color:#8b949e;font-size:12px}
 .card .val{font-size:20px;font-weight:700;margin-top:4px}
 .pos{color:#3fb950}.neg{color:#f85149}
 .pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;
  font-weight:600}
 .ok{background:#1f6f33}.warn{background:#9e6a03}.bad{background:#8e1519}
 .btns{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}
 button{padding:9px 14px;border:0;border-radius:7px;cursor:pointer;font-weight:600;
  color:#fff;background:#30363d}
 button.green{background:#238636}button.amber{background:#9e6a03}
 button.red{background:#da3633}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #21262d}
 th{color:#8b949e;font-weight:600}
 pre{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:12px;
  max-height:280px;overflow:auto;font-size:12px;white-space:pre-wrap}
 .section{font-size:14px;margin:18px 0 8px;color:#8b949e}
 a{color:#58a6ff}
</style></head><body>
 <h1>SOL Accumulation Grid Bot <span id="mode" class="pill ok">{{ mode }}</span></h1>
 <div class="sub">Last update: <span id="updated">-</span> ·
  <a href="/logout">log out</a></div>

 <div class="btns">
  <button class="amber" onclick="act('pause')">Pause</button>
  <button class="green" onclick="act('resume')">Resume</button>
  <button onclick="act('convert')">Convert profit &rarr; SOL</button>
  <button onclick="act('cancel-all')">Cancel all orders</button>
  <button class="red" onclick="act('emergency-stop')">EMERGENCY STOP</button>
  <button onclick="act('clear-kill')">Clear kill switch</button>
 </div>

 <div class="grid">
  <div class="card"><div class="label">NET SOL ACCUMULATED</div>
   <div class="val" id="net">-</div></div>
  <div class="card"><div class="label">Current SOL</div>
   <div class="val" id="sol">-</div></div>
  <div class="card"><div class="label">Current USDT</div>
   <div class="val" id="usdt">-</div></div>
  <div class="card"><div class="label">Price</div>
   <div class="val" id="price">-</div></div>
  <div class="card"><div class="label">Realized PnL</div>
   <div class="val" id="rpnl">-</div></div>
  <div class="card"><div class="label">Total value (USDT)</div>
   <div class="val" id="tval">-</div></div>
  <div class="card"><div class="label">Regime</div>
   <div class="val" id="regime" style="font-size:15px">-</div></div>
  <div class="card"><div class="label">State</div>
   <div class="val"><span id="state" class="pill ok">-</span></div></div>
 </div>

 <div class="section">Open orders (<span id="oo_count">0</span>)</div>
 <table><thead><tr><th>Side</th><th>Price</th><th>Amount (SOL)</th><th>Level</th>
  </tr></thead><tbody id="orders"></tbody></table>

 <div class="section">Logs</div>
 <pre id="logs">loading…</pre>

<script>
async function act(name){
 if(name==='emergency-stop' && !confirm('Engage kill switch and halt trading?'))return;
 await fetch('/api/action/'+name,{method:'POST'});
 setTimeout(refresh,300);
}
function fmt(n,d=4){return (n==null||isNaN(n))?'-':Number(n).toFixed(d);}
function cls(n){return n>=0?'pos':'neg';}
async function refresh(){
 try{
  const s=await (await fetch('/api/status')).json();
  const m=s.metrics||{};
  document.getElementById('mode').textContent=(s.mode||'-').toUpperCase();
  const net=m.net_sol_accumulated;
  const netEl=document.getElementById('net');
  netEl.textContent=(net>=0?'+':'')+fmt(net,6);
  netEl.className='val '+cls(net);
  document.getElementById('sol').textContent=fmt(m.current_sol,6);
  document.getElementById('usdt').textContent=fmt(m.current_usdt,2);
  document.getElementById('price').textContent=fmt(m.price,4);
  const r=document.getElementById('rpnl');
  r.textContent=(m.realized_pnl_usdt>=0?'+':'')+fmt(m.realized_pnl_usdt,4);
  r.className='val '+cls(m.realized_pnl_usdt);
  document.getElementById('tval').textContent=fmt(m.total_value_usdt,2);
  document.getElementById('regime').textContent=(s.regime||'-')+
   (s.regime_detail?(' · '+s.regime_detail):'');
  const st=document.getElementById('state');
  st.textContent=(s.state||'-')+(s.halted?' (HALTED)':'');
  st.className='pill '+(s.halted?'bad':(s.paused?'warn':'ok'));
  const oo=s.open_orders||[];
  document.getElementById('oo_count').textContent=oo.length;
  document.getElementById('orders').innerHTML=oo.map(o=>
   `<tr><td>${o.side}</td><td>${fmt(o.price,4)}</td>`+
   `<td>${fmt(o.amount,4)}</td><td>${o.grid_level??'-'}</td></tr>`).join('');
  document.getElementById('updated').textContent=new Date().toLocaleTimeString();
 }catch(e){/* transient */}
 try{
  const l=await (await fetch('/api/logs')).json();
  const pre=document.getElementById('logs');
  pre.textContent=(l.lines||[]).join('');
  pre.scrollTop=pre.scrollHeight;
 }catch(e){}
}
refresh();setInterval(refresh,5000);
</script></body></html>
"""
