"""Flask web console: password-protected view + control dashboard.

A single process serves this app and runs the trading loop in a background
thread (see BotController). Deploy with exactly one worker.
"""
from __future__ import annotations

import functools
import hmac
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from flask import (Flask, Response, jsonify, redirect, render_template_string,
                   request, session, url_for)

from ..config import load_config
from ..exchange import Exchange, ExchangeError
from ..storage.db import Database
from .controller import BotController

LOG_FILE = os.getenv("LOG_FILE", "logs/bot.log")

# Curated, user-editable settings exposed in the console.
SETTINGS_SCHEMA = [
    {"key": "grid.count", "label": "Grid levels", "type": "int",
     "min": 2, "max": 50},
    {"key": "grid.spacing_mode", "label": "Spacing", "type": "enum",
     "options": ["arithmetic", "geometric", "atr"]},
    {"key": "grid.range_min_width_pct", "label": "Min range width %",
     "type": "float", "min": 0.5, "max": 50},
    {"key": "grid.range_recalc_interval_sec", "label": "Range recalc (sec)",
     "type": "int", "min": 60, "max": 86400},
    {"key": "order.size_mode", "label": "Order size mode", "type": "enum",
     "options": ["fixed_usdt", "fixed_sol", "portfolio_percent"]},
    {"key": "order.fixed_usdt", "label": "Order size (USDT)", "type": "float",
     "min": 1, "max": 100000},
    {"key": "risk.profile", "label": "Risk profile", "type": "enum",
     "options": ["low", "medium", "high"]},
    {"key": "risk.auto_resume_after_sec", "label": "Auto-resume after (sec, 0=off)",
     "type": "int", "min": 0, "max": 86400},
    {"key": "accumulation.profit_conversion_mode", "label": "Profit conversion",
     "type": "enum", "options": ["none", "partial_to_SOL", "full_to_SOL"]},
    {"key": "accumulation.profit_conversion_percent", "label": "Conversion %",
     "type": "float", "min": 0, "max": 100},
    {"key": "accumulation.sell_reduction_factor", "label": "Uptrend sell factor",
     "type": "float", "min": 0, "max": 1},
]


def _coerce_setting(spec: dict, val) -> tuple[bool, object]:
    try:
        if spec["type"] == "int":
            v = int(val)
        elif spec["type"] == "float":
            v = float(val)
        elif spec["type"] == "enum":
            v = str(val)
            return (v in spec["options"], v)
        else:
            return False, None
    except (TypeError, ValueError):
        return False, None
    if "min" in spec and v < spec["min"]:
        return False, v
    if "max" in spec and v > spec["max"]:
        return False, v
    return True, v


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

    console = cfg.console
    # Read-only DB connection for the dashboard (separate from the bot loop's).
    read_db = Database(cfg.env.db_path)
    # Dedicated read-only market-data client for charts so we never touch the
    # trading loop's ccxt client concurrently. Created lazily on first use.
    chart_ex: dict[str, object] = {"ex": None}
    chart_lock = threading.Lock()

    def _chart_exchange() -> Exchange:
        with chart_lock:
            if chart_ex["ex"] is None:
                ex = Exchange(cfg, trading_enabled=False)
                ex.load_markets()
                chart_ex["ex"] = ex
            return chart_ex["ex"]  # type: ignore[return-value]

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

    # ---- chart data ----------------------------------------
    @app.route("/api/tokens")
    @require_auth
    def api_tokens():
        return jsonify({
            "tokens": console["chart_tokens"],
            "timeframes": console["chart_timeframes"],
            "default_token": console["default_token"],
            "default_timeframe": console["default_timeframe"],
            "traded": cfg.symbol,
        })

    @app.route("/api/candles")
    @require_auth
    def api_candles():
        symbol = request.args.get("symbol", console["default_token"])
        timeframe = request.args.get("timeframe", console["default_timeframe"])
        if symbol not in console["chart_tokens"]:
            return jsonify({"error": "symbol not allowed"}), 400
        if timeframe not in console["chart_timeframes"]:
            return jsonify({"error": "timeframe not allowed"}), 400
        limit = int(console.get("chart_candles", 300))
        try:
            rows = _chart_exchange().fetch_ohlcv_symbol(symbol, timeframe, limit)
        except ExchangeError as exc:
            return jsonify({"error": str(exc)}), 502
        except Exception as exc:  # network/exchange hiccups shouldn't 500 the UI
            return jsonify({"error": f"market data unavailable: {exc}"}), 502
        candles = [
            {"time": int(r[0] // 1000), "open": r[1], "high": r[2],
             "low": r[3], "close": r[4]}
            for r in rows
        ]
        return jsonify({"symbol": symbol, "timeframe": timeframe,
                        "candles": candles})

    @app.route("/api/fills")
    @require_auth
    def api_fills():
        # Entry/exit markers only exist for the traded symbol.
        rows = list(read_db.fills())
        fills = [
            {"time": int(row["ts"]), "side": row["side"], "price": row["price"],
             "amount": row["amount"], "realized_pnl": row["realized_pnl"]}
            for row in rows
        ]
        return jsonify({"symbol": cfg.symbol, "fills": fills})

    @app.route("/api/history")
    @require_auth
    def api_history():
        rows = read_db.equity_history(2000)
        return jsonify({"points": [
            {"time": int(r["ts"]), "net_sol": r["net_sol"],
             "total_value": r["total_value_usdt"], "price": r["price"]}
            for r in rows
        ]})

    @app.route("/api/stats")
    @require_auth
    def api_stats():
        fills = list(read_db.fills())
        sells = [f for f in fills if f["side"] == "sell"]
        total_fees = sum(f["fee"] for f in fills)
        realized = [f["realized_pnl"] for f in sells]
        wins = [p for p in realized if p > 0]
        round_trips = len(sells)
        started = float(read_db.get_meta("started_ts", time.time()) or time.time())
        days = max((time.time() - started) / 86400.0, 1e-6)
        snap = controller.status()
        m = snap.get("metrics", {}) if isinstance(snap, dict) else {}
        net_sol = float(m.get("net_sol_accumulated", 0.0) or 0.0)
        return jsonify({
            "fills": len(fills),
            "round_trips": round_trips,
            "total_fees_usdt": round(total_fees, 4),
            "total_realized_usdt": round(sum(realized), 4),
            "win_rate_pct": round(100 * len(wins) / round_trips, 1) if round_trips else 0.0,
            "avg_profit_usdt": round(sum(realized) / round_trips, 4) if round_trips else 0.0,
            "sol_per_day": round(net_sol / days, 6),
            "days_running": round(days, 2),
        })

    @app.route("/api/settings", methods=["GET", "POST"])
    @require_auth
    def api_settings():
        if request.method == "GET":
            raw = controller.bot.cfg.raw
            out = []
            for spec in SETTINGS_SCHEMA:
                sec, _, fld = spec["key"].partition(".")
                out.append({**spec, "value": (raw.get(sec, {}) or {}).get(fld)})
            return jsonify({"settings": out})
        # POST: validate and apply.
        payload = request.get_json(silent=True) or {}
        overrides, errors = {}, []
        by_key = {s["key"]: s for s in SETTINGS_SCHEMA}
        for key, val in payload.items():
            spec = by_key.get(key)
            if spec is None:
                errors.append(f"unknown setting {key}")
                continue
            ok, coerced = _coerce_setting(spec, val)
            if not ok:
                errors.append(f"invalid value for {key}: {val}")
            else:
                overrides[key] = coerced
        if errors:
            return jsonify({"error": "; ".join(errors)}), 400
        if overrides:
            controller.apply_settings(overrides)
        return jsonify({"ok": True, "applied": overrides})

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
 .toolbar{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
 select{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;
  padding:7px 10px;font-weight:600}
 .tf{display:flex;gap:4px}
 .tf button{padding:6px 10px;background:#21262d}
 .tf button.active{background:#1f6feb}
 #gridtoggle.active{background:#1f6feb}
 #chart{width:100%;height:360px;background:#161b22;border:1px solid #30363d;
  border-radius:10px}
 .legend{font-size:12px;color:#8b949e;margin:6px 0}
 .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin:0 4px 0 10px}
 .buy{background:#3fb950}.sell{background:#f85149}
 .note{color:#8b949e;font-size:12px}
 .tag{padding:2px 7px;border-radius:6px;font-size:11px;font-weight:600}
 .tag.resting{background:#30363d;color:#c9d1d9}
 .tag.entry{background:#1f6f33;color:#fff}
 .tag.exit{background:#8e1519;color:#fff}
 .settings{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:10px;margin-bottom:8px}
 .setting{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px}
 .setting label{display:block;font-size:12px;color:#8b949e;margin-bottom:4px}
 .setting input,.setting select{width:100%;background:#0d1117;color:#c9d1d9;
  border:1px solid #30363d;border-radius:6px;padding:6px 8px;box-sizing:border-box}
 .setting .key{font-size:10px;color:#6e7681;margin-top:4px}
</style>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
</head><body>
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

 <div class="section">Chart</div>
 <div class="toolbar">
  <select id="token"></select>
  <div class="tf" id="tf"></div>
  <button id="gridtoggle" class="active" onclick="toggleGrid()">Grid orders: on</button>
  <span class="legend"><span class="dot buy"></span>entry (buy)
   <span class="dot sell"></span>exit (sell)
   &nbsp;|&nbsp; dashed lines = open grid orders</span>
 </div>
 <div id="chart"></div>
 <div class="legend" id="chartnote"></div>

 <div class="section">Performance</div>
 <div class="grid" id="statcards">
  <div class="card"><div class="label">SOL / day</div><div class="val" id="st_solday">-</div></div>
  <div class="card"><div class="label">Round-trips</div><div class="val" id="st_rt">-</div></div>
  <div class="card"><div class="label">Win rate</div><div class="val" id="st_win">-</div></div>
  <div class="card"><div class="label">Avg profit / trade</div><div class="val" id="st_avg">-</div></div>
  <div class="card"><div class="label">Total realized</div><div class="val" id="st_real">-</div></div>
  <div class="card"><div class="label">Total fees</div><div class="val" id="st_fees">-</div></div>
 </div>
 <div class="legend">NET SOL accumulated (green) &amp; total value in USDT (blue) over time</div>
 <div id="eqchart" style="height:240px"></div>

 <div class="section">Settings <span class="note">— applied live at the next cycle</span></div>
 <div id="settings" class="settings"></div>
 <div class="btns">
  <button class="green" id="savebtn" onclick="saveSettings()">Save settings</button>
  <span class="note" id="settingsmsg"></span>
 </div>

 <div class="section">Grid position</div>
 <div class="legend" id="position">-</div>
 <div class="legend" id="target">-</div>

 <div class="section">Grid ladder (<span id="oo_count">0</span> resting orders)
  <span class="note">— each rung: buy low, sell one step up</span></div>
 <table><thead><tr><th>Rung</th><th>Buy @</th><th>Sell @</th>
  <th>Target %</th><th>Amount (SOL)</th><th>Distance</th><th>Resting now</th>
  </tr></thead><tbody id="orders"></tbody></table>

 <div class="section">Filled trades (<span id="fl_count">0</span>)
  <span class="note">— executed entries &amp; exits</span></div>
 <table><thead><tr><th>Time</th><th>Type</th><th>Price</th>
  <th>Amount (SOL)</th><th>Realized PnL</th>
  </tr></thead><tbody id="trades"></tbody></table>

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
  // grid position summary
  const held=m.grid_sol||0, avg=m.grid_avg_cost||0, up=m.unrealized_pnl_usdt||0;
  document.getElementById('position').innerHTML = held>0
   ? `Holding <b>${fmt(held,4)} SOL</b> bought at avg <b>${fmt(avg,4)}</b> · `+
     `unrealized <span class="${cls(up)}">${up>=0?'+':''}${fmt(up,4)} USDT</span> · `+
     `${(s.open_orders||[]).filter(o=>o.side==='sell').length} sell order(s) staged to exit`
   : 'No grid SOL held yet — all capital is in resting buy orders / reserve.';

  // per-rung profit target
  document.getElementById('target').innerHTML = s.step_pct
   ? `Per-rung target: <b>${fmt(s.step_pct,2)}%</b> gross `+
     `(≈ <b>${fmt(s.net_step_pct,2)}%</b> net of fees) per buy→sell round-trip.`
   : '';

  const px=m.price||0;
  const oo=s.open_orders||[];
  document.getElementById('oo_count').textContent=oo.length;
  // Build a paired ladder from the grid levels: each rung = buy(lower)+sell(upper).
  const levels=(s.grid_levels||[]).slice().sort((a,b)=>a-b);
  const near=(price,side)=>oo.find(o=>o.side===side&&Math.abs(o.price-price)<1e-3);
  let rows='';
  for(let i=0;i<levels.length-1;i++){
   const lo=levels[i], hi=levels[i+1];
   const tgt=(hi-lo)/lo*100;
   const b=near(lo,'buy'), sl=near(hi,'sell');
   if(!b&&!sl) continue;
   const amt=(b&&b.amount)||(sl&&sl.amount)||0;
   const dist=px?((lo-px)/px*100):0;
   const badges=(b?'<span class="tag entry">BUY</span> ':'')+
                (sl?'<span class="tag exit">SELL</span>':'')||'<span class="note">—</span>';
   rows+=`<tr><td>${i}</td><td>${fmt(lo,4)}</td><td>${fmt(hi,4)}</td>`+
    `<td class="pos">+${fmt(tgt,2)}%</td><td>${fmt(amt,4)}</td>`+
    `<td class="${cls(dist)}">${dist>=0?'+':''}${fmt(dist,2)}%</td>`+
    `<td>${badges}</td></tr>`;
  }
  document.getElementById('orders').innerHTML=rows||
   '<tr><td colspan="7" class="note">No resting grid orders.</td></tr>';
  latestOrders=oo; latestRange=s.active_range||null;
  drawGrid();
  document.getElementById('updated').textContent=new Date().toLocaleTimeString();
 }catch(e){/* transient */}
 try{
  const f=await (await fetch('/api/fills')).json();
  const fills=(f.fills||[]).slice().reverse();
  document.getElementById('fl_count').textContent=fills.length;
  document.getElementById('trades').innerHTML=fills.slice(0,25).map(x=>{
   const buy=x.side==='buy';
   const t=new Date(x.time*1000).toLocaleString();
   const pnl=x.realized_pnl||0;
   const pnlc=buy?'':('<span class="'+cls(pnl)+'">'+(pnl>=0?'+':'')+fmt(pnl,4)+'</span>');
   return `<tr><td class="note">${t}</td>`+
    `<td><span class="tag ${buy?'entry':'exit'}">${buy?'ENTRY (buy)':'EXIT (sell)'}</span></td>`+
    `<td>${fmt(x.price,4)}</td><td>${fmt(x.amount,4)}</td>`+
    `<td>${buy?'<span class="note">—</span>':pnlc}</td></tr>`;
  }).join('');
 }catch(e){}
 try{
  const l=await (await fetch('/api/logs')).json();
  const pre=document.getElementById('logs');
  pre.textContent=(l.lines||[]).join('');
  pre.scrollTop=pre.scrollHeight;
 }catch(e){}
}
refresh();setInterval(refresh,5000);

// ---------- chart ----------
let chart, series, tradedSymbol=null;
let curToken=null, curTf=null;
let gridLines=[], showGrid=true, latestOrders=[], latestRange=null;

function toggleGrid(){
 showGrid=!showGrid;
 const b=document.getElementById('gridtoggle');
 b.textContent='Grid orders: '+(showGrid?'on':'off');
 b.classList.toggle('active',showGrid);
 drawGrid();
}

function drawGrid(){
 if(!series)return;
 gridLines.forEach(l=>{try{series.removePriceLine(l);}catch(e){}});
 gridLines=[];
 // Grid orders only exist for the traded token.
 if(!showGrid||curToken!==tradedSymbol)return;
 (latestOrders||[]).forEach(o=>{
  const buy=o.side==='buy';
  gridLines.push(series.createPriceLine({
   price:Number(o.price),
   color:buy?'#3fb950':'#f85149',
   lineWidth:1,
   lineStyle:LightweightCharts.LineStyle.Dashed,
   axisLabelVisible:true,
   title:(buy?'BUY ':'SELL ')+Number(o.amount).toFixed(3),
  }));
 });
 // Active range bounds as faint solid lines.
 if(latestRange&&latestRange.length===2){
  [['range lo',latestRange[0]],['range hi',latestRange[1]]].forEach(([t,p])=>{
   gridLines.push(series.createPriceLine({
    price:Number(p),color:'#8b949e',lineWidth:1,
    lineStyle:LightweightCharts.LineStyle.Dotted,axisLabelVisible:false,title:t,
   }));
  });
 }
}

function initChart(){
 const el=document.getElementById('chart');
 chart=LightweightCharts.createChart(el,{
  layout:{background:{color:'#161b22'},textColor:'#c9d1d9'},
  grid:{vertLines:{color:'#21262d'},horzLines:{color:'#21262d'}},
  // Put the price axis (and therefore the BUY/SELL price-line labels) on the LEFT.
  leftPriceScale:{borderColor:'#30363d',visible:true},
  rightPriceScale:{visible:false},
  timeScale:{borderColor:'#30363d',timeVisible:true,secondsVisible:false},
  crosshair:{mode:0},autoSize:true,
 });
 series=chart.addCandlestickSeries({
  priceScaleId:'left',
  upColor:'#3fb950',downColor:'#f85149',borderVisible:false,
  wickUpColor:'#3fb950',wickDownColor:'#f85149',
 });
 window.addEventListener('resize',()=>chart.timeScale().fitContent());
}

function snap(t,candles){ // snap a fill time to its candle bucket time
 let best=candles.length?candles[0].time:t;
 for(const c of candles){ if(c.time<=t) best=c.time; else break; }
 return best;
}

async function loadMarkers(candles){
 if(curToken!==tradedSymbol){series.setMarkers([]);
  document.getElementById('chartnote').textContent=
   'Entry/exit markers show only for the traded token ('+tradedSymbol+').';
  return;}
 document.getElementById('chartnote').textContent='';
 try{
  const f=await (await fetch('/api/fills')).json();
  const min=candles.length?candles[0].time:0;
  const mk=(f.fills||[]).filter(x=>x.time>=min).map(x=>({
   time:snap(x.time,candles),
   position:x.side==='buy'?'belowBar':'aboveBar',
   color:x.side==='buy'?'#3fb950':'#f85149',
   shape:x.side==='buy'?'arrowUp':'arrowDown',
   text:(x.side==='buy'?'B ':'S ')+Number(x.price).toFixed(2),
  }));
  mk.sort((a,b)=>a.time-b.time);
  series.setMarkers(mk);
 }catch(e){series.setMarkers([]);}
}

async function loadChart(){
 if(!curToken||!curTf)return;
 try{
  const url='/api/candles?symbol='+encodeURIComponent(curToken)+'&timeframe='+curTf;
  const d=await (await fetch(url)).json();
  if(d.error){document.getElementById('chartnote').textContent='Chart: '+d.error;return;}
  const candles=d.candles||[];
  series.setData(candles);
  chart.timeScale().fitContent();
  await loadMarkers(candles);
  drawGrid();
 }catch(e){document.getElementById('chartnote').textContent='Chart unavailable.';}
}

async function initTokens(){
 const t=await (await fetch('/api/tokens')).json();
 tradedSymbol=t.traded;
 curToken=t.default_token; curTf=t.default_timeframe;
 const sel=document.getElementById('token');
 sel.innerHTML=t.tokens.map(x=>`<option value="${x}" ${x===curToken?'selected':''}>`+
  `${x}${x===tradedSymbol?' (trading)':''}</option>`).join('');
 sel.onchange=()=>{curToken=sel.value;loadChart();};
 const tf=document.getElementById('tf');
 tf.innerHTML=t.timeframes.map(x=>`<button data-tf="${x}" `+
  `class="${x===curTf?'active':''}">${x}</button>`).join('');
 tf.querySelectorAll('button').forEach(b=>b.onclick=()=>{
  curTf=b.dataset.tf;
  tf.querySelectorAll('button').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  loadChart();
 });
 initChart();
 loadChart();
 setInterval(loadChart,30000);
}
// ---------- stats ----------
async function loadStats(){
 try{
  const s=await (await fetch('/api/stats')).json();
  document.getElementById('st_solday').textContent=(s.sol_per_day>=0?'+':'')+fmt(s.sol_per_day,6);
  document.getElementById('st_solday').className='val '+cls(s.sol_per_day);
  document.getElementById('st_rt').textContent=s.round_trips;
  document.getElementById('st_win').textContent=fmt(s.win_rate_pct,1)+'%';
  document.getElementById('st_avg').textContent=(s.avg_profit_usdt>=0?'+':'')+fmt(s.avg_profit_usdt,4);
  document.getElementById('st_avg').className='val '+cls(s.avg_profit_usdt);
  document.getElementById('st_real').textContent=(s.total_realized_usdt>=0?'+':'')+fmt(s.total_realized_usdt,4);
  document.getElementById('st_real').className='val '+cls(s.total_realized_usdt);
  document.getElementById('st_fees').textContent=fmt(s.total_fees_usdt,4);
 }catch(e){}
}

// ---------- equity curve ----------
let eqChart,eqNetSeries,eqValSeries;
function initEqChart(){
 eqChart=LightweightCharts.createChart(document.getElementById('eqchart'),{
  layout:{background:{color:'#161b22'},textColor:'#c9d1d9'},
  grid:{vertLines:{color:'#21262d'},horzLines:{color:'#21262d'}},
  rightPriceScale:{borderColor:'#30363d'},
  leftPriceScale:{borderColor:'#30363d',visible:true},
  timeScale:{borderColor:'#30363d',timeVisible:true,secondsVisible:false},
  autoSize:true,
 });
 eqNetSeries=eqChart.addLineSeries({color:'#3fb950',lineWidth:2,priceScaleId:'right',
  title:'NET SOL'});
 eqValSeries=eqChart.addLineSeries({color:'#58a6ff',lineWidth:1,priceScaleId:'left',
  title:'Value (USDT)'});
}
async function loadEquity(){
 try{
  const h=await (await fetch('/api/history')).json();
  const pts=h.points||[];
  if(!pts.length)return;
  eqNetSeries.setData(pts.map(p=>({time:p.time,value:p.net_sol})));
  eqValSeries.setData(pts.map(p=>({time:p.time,value:p.total_value})));
  eqChart.timeScale().fitContent();
 }catch(e){}
}

// ---------- settings ----------
async function loadSettings(){
 const r=await (await fetch('/api/settings')).json();
 const el=document.getElementById('settings');
 el.innerHTML=(r.settings||[]).map(s=>{
  let inp;
  if(s.type==='enum'){
   inp=`<select data-key="${s.key}">`+s.options.map(o=>
    `<option value="${o}" ${o===s.value?'selected':''}>${o}</option>`).join('')+'</select>';
  }else{
   const step=s.type==='int'?'1':'any';
   inp=`<input data-key="${s.key}" type="number" step="${step}" `+
    `value="${s.value??''}" min="${s.min??''}" max="${s.max??''}">`;
  }
  return `<div class="setting"><label>${s.label}</label>${inp}`+
   `<div class="key">${s.key}</div></div>`;
 }).join('');
}
async function saveSettings(){
 const inputs=document.querySelectorAll('#settings [data-key]');
 const payload={};
 inputs.forEach(i=>{payload[i.dataset.key]=i.value;});
 const msg=document.getElementById('settingsmsg');
 msg.textContent='saving…';
 try{
  const r=await fetch('/api/settings',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const j=await r.json();
  if(!r.ok){msg.textContent='error: '+(j.error||r.status);return;}
  msg.textContent='applied — takes effect next cycle';
  setTimeout(()=>{msg.textContent='';},5000);
 }catch(e){msg.textContent='error: '+e.message;}
}

initTokens();
initEqChart();
loadStats();loadEquity();loadSettings();
setInterval(loadStats,15000);
setInterval(loadEquity,60000);
</script></body></html>
"""
