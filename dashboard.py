#!/usr/bin/env python3
"""
Web dashboard for the MNQ reversal bot.

    python dashboard.py

Opens at http://localhost:8765
Reads the latest log file in logs/ and refreshes every 5 s.
No extra dependencies beyond the standard library.
"""
import glob
import json
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = int(os.getenv("DASH_PORT", "8765"))
_ROOT = Path(__file__).resolve().parent


# ─────────────────────────────────────────────────────────────
# Log parsing  (same logic as monitor.py)
# ─────────────────────────────────────────────────────────────

def _latest_log() -> str | None:
    files = sorted(glob.glob(str(_ROOT / "logs" / "bot_*.log")))
    return files[-1] if files else None


def _parse_log(path: str) -> dict:
    bars: list[dict] = []
    trades: list[dict] = []
    errors: list[str] = []
    reconnects = 0

    bar_re     = re.compile(
        r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] "
        r"O=([\d.]+) H=([\d.]+) L=([\d.]+) C=([\d.]+) V=(\d+)"
        r".*trades=(\d+)\/(\d+) pnl=\$([\d.+-]+)"
    )
    meta_re    = re.compile(r"Signal: (\w+)\s+mode=(\S+)\s+grade=(\S+)\s+qty=(\d+)")
    signal_re  = re.compile(r"SIGNAL (\w+) @ ([\d.]+)\s+stop=([\d.]+)\s+tgt=([\d.]+)")
    bracket_re = re.compile(r"Bracket placed: entry=(\d+) stop=(\S+)")
    tp_re      = re.compile(r"TP hit: target=([\d.]+)")
    rec_re     = re.compile(r"Trade recorded: pnl=([\d.+-]+)")
    error_re   = re.compile(r"\[ERROR\]")

    meta: dict = {}
    open_trade: dict | None = None

    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            ts = line[:19]

            m = bar_re.search(line)
            if m:
                bars.append({"ts": m[1], "o": m[2], "h": m[3], "l": m[4],
                              "c": m[5], "v": m[6], "trades": m[7], "max": m[8], "pnl": m[9]})
                continue

            m = meta_re.search(line)
            if m:
                meta = {"mode": m.group(2), "grade": m.group(3), "qty": m.group(4)}
                continue

            m = signal_re.search(line)
            if m:
                if open_trade and open_trade["outcome"] == "OPEN":
                    open_trade["outcome"] = "SL?"
                open_trade = {
                    "num": len(trades) + 1,
                    "ts": ts,
                    "dir": m.group(1),
                    "entry": float(m.group(2)),
                    "stop": float(m.group(3)),
                    "target": float(m.group(4)),
                    "mode": meta.get("mode", "?"),
                    "grade": meta.get("grade", "?"),
                    "qty": int(meta.get("qty", 1)),
                    "outcome": "OPEN",
                    "exit_px": None,
                    "pnl": None,
                    "entry_id": None,
                    "stop_id": None,
                }
                trades.append(open_trade)
                meta = {}
                continue

            m = bracket_re.search(line)
            if m and open_trade:
                open_trade["entry_id"] = m.group(1)
                open_trade["stop_id"]  = m.group(2).rstrip(")")
                continue

            m = tp_re.search(line)
            if m and open_trade:
                open_trade["outcome"] = "TP ✓"
                open_trade["exit_px"] = float(m.group(1))
                continue

            m = rec_re.search(line)
            if m and open_trade:
                pnl = float(m.group(1))
                if pnl > 0:
                    open_trade["pnl"] = pnl
                    if open_trade["outcome"] == "OPEN":
                        open_trade["outcome"] = "TP ✓"
                continue

            if error_re.search(line):
                errors.append(line.strip()[-120:])

            if "LiveFeed reconnecting" in line:
                reconnects += 1

    return {
        "bars": bars,
        "trades": trades,
        "errors": errors[-5:],
        "reconnects": reconnects,
        "log_file": os.path.basename(path),
    }


# ─────────────────────────────────────────────────────────────
# HTML  (also works as a standalone artifact via fetch fallback)
# ─────────────────────────────────────────────────────────────

_HTML = """<title>MNQ Bot Dashboard</title>
<meta name="claude:viewport-fit-sides" content="cover">

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">

<style>
/* Design tokens: dark terminal (single theme, deliberate) */
:root{
  --bg:#090b14;--surf:#0e1120;--surf-hi:#131629;
  --bdr:#191d33;--bdr-hi:#21274a;
  --fg:#d8ddf0;--muted:#4f5674;--dim:#252949;
  --green:#00d896;--green-bg:rgba(0,216,150,.08);
  --red:#ff3f5e;--red-bg:rgba(255,63,94,.08);
  --amber:#f5c842;--amber-bg:rgba(245,200,66,.08);
  --blue:#3b9cff;--blue-bg:rgba(59,156,255,.08);
  --purple:#9f8bff;--purple-bg:rgba(159,139,255,.08);
  --mono:'JetBrains Mono','Cascadia Code',monospace;
  --sans:'Inter',system-ui,sans-serif;
  color-scheme:dark;
}
*{box-sizing:border-box;min-width:0}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:13px;line-height:1.5;margin:0;
  padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));
  padding-block:0;}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:110;background:var(--bg);}

/* Top bar */
.topbar{position:sticky;top:env(safe-area-inset-top,0px);z-index:100;background:var(--bg);
  border-bottom:1px solid var(--bdr);display:flex;align-items:center;gap:12px;padding:11px 0;
  margin-left:calc(-1 * max(16px,env(safe-area-inset-left,0px)));
  margin-right:calc(-1 * max(16px,env(safe-area-inset-right,0px)));
  padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));}
.brand{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-weight:600;font-size:13px;letter-spacing:.06em;flex:1;}
.brand-dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 8px rgba(0,216,150,.5);flex-shrink:0;}
.badge{padding:2px 8px;border-radius:3px;font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;}
.badge-s{background:var(--amber-bg);color:var(--amber);border:1px solid rgba(245,200,66,.2);}
.badge-l{background:var(--green-bg);color:var(--green);border:1px solid rgba(0,216,150,.2);}
.hdr-meta{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--muted);}
.btn-open{cursor:pointer;padding:4px 11px;border-radius:4px;border:1px solid var(--bdr-hi);background:var(--surf);color:var(--muted);font:12px var(--sans);transition:color .15s,border-color .15s;white-space:nowrap;}
.btn-open:hover{color:var(--fg);border-color:var(--dim);}

/* Stats */
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--bdr);border:1px solid var(--bdr);border-radius:8px;overflow:hidden;margin-block:16px;}
@media(max-width:600px){.stats{grid-template-columns:repeat(3,1fr);}}
.stat{background:var(--surf);padding:13px 15px;display:flex;flex-direction:column;gap:3px;}
.stat-lbl{font-size:10px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);}
.stat-val{font:600 22px/1 var(--mono);color:var(--fg);font-variant-numeric:tabular-nums;}
.stat-val.g{color:var(--green);}.stat-val.r{color:var(--red);}.stat-val.a{color:var(--amber);}
.stat-sub{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums;}

/* Layout */
.wrap{padding-block:16px;display:flex;flex-direction:column;gap:14px;}
.two-col{display:grid;grid-template-columns:1fr 300px;gap:14px;}
@media(max-width:780px){.two-col{grid-template-columns:1fr;}}

/* Cards */
.card{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;overflow:hidden;}
.card-hdr{padding:9px 15px;border-bottom:1px solid var(--bdr);display:flex;align-items:center;justify-content:space-between;font-size:10px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);}
.chart-box{padding:12px 14px 8px;height:210px;position:relative;}
.chart-box canvas{max-width:100%;}

/* Mode breakdown */
.mode-list{padding:12px 15px;display:flex;flex-direction:column;gap:9px;}
.mode-row{display:flex;align-items:center;justify-content:space-between;font-size:12px;margin-bottom:3px;}
.mode-name{display:flex;align-items:center;gap:6px;font-weight:500;}
.mode-pip{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
.mode-cnt{font:11px var(--mono);color:var(--muted);}
.bar-track{height:3px;background:var(--bdr-hi);border-radius:2px;overflow:hidden;}
.bar-fill{height:100%;border-radius:2px;transition:width .4s ease;}
.grade-row{display:flex;gap:8px;padding:10px 15px 12px;border-top:1px solid var(--bdr);}
.grade-pill{flex:1;display:flex;flex-direction:column;align-items:center;gap:1px;padding:6px 4px;border-radius:4px;border:1px solid var(--bdr-hi);}
.grade-lbl{font:600 10px var(--mono);}
.grade-num{font:600 18px/1 var(--mono);font-variant-numeric:tabular-nums;}

/* Tables */
.tscroll{overflow-x:auto;}
table{width:100%;border-collapse:collapse;min-width:680px;font-size:12px;}
thead th{padding:7px 11px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--bdr);white-space:nowrap;}
th.r{text-align:right;}
tbody tr{border-bottom:1px solid var(--bdr);transition:background .1s;}
tbody tr:last-child{border-bottom:none;}
tbody tr:hover{background:var(--surf-hi);}
tbody tr.tp{border-left:3px solid var(--green);}
tbody tr.sl{border-left:3px solid var(--red);}
tbody tr.op{border-left:3px solid var(--amber);}
td{padding:7px 11px;white-space:nowrap;}
td.m{font-family:var(--mono);font-variant-numeric:tabular-nums;}
td.r{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;}
.g{color:var(--green);}.r{color:var(--red);}.a{color:var(--amber);}
.muted{color:var(--muted);}.dim{color:var(--dim);}
.pnl-est{color:var(--red);opacity:.65;}

/* Badges */
.mb{display:inline-block;padding:2px 6px;border-radius:3px;font:600 10px var(--mono);text-transform:uppercase;}
.mb-std{background:var(--purple-bg);color:var(--purple);}
.mb-agg{background:var(--blue-bg);color:var(--blue);}
.mb-ant{background:var(--green-bg);color:var(--green);}
.gb{display:inline-block;padding:2px 5px;border-radius:3px;font:600 11px var(--mono);}
.gb-ap{color:var(--amber);}.gb-b{color:var(--fg);}.gb-c{color:var(--muted);}
.ob{display:inline-block;padding:2px 7px;border-radius:3px;font:600 11px var(--mono);}
.ob-tp{background:var(--green-bg);color:var(--green);}
.ob-sl{background:var(--red-bg);color:var(--red);}
.ob-op{background:var(--amber-bg);color:var(--amber);}

/* Errors */
.err-list{padding:10px 15px;display:flex;flex-direction:column;gap:5px;}
.err-item{font:12px var(--mono);color:var(--red);opacity:.8;}

/* Drop overlay */
#drop-ov{position:fixed;inset:0;background:rgba(9,11,20,.88);display:flex;align-items:center;justify-content:center;z-index:200;font:600 20px var(--sans);letter-spacing:.04em;color:var(--muted);pointer-events:none;}
</style>

<header class="topbar">
  <div class="brand"><span class="brand-dot"></span>MNQ REVERSAL BOT</div>
  <div class="hdr-meta">
    <span id="src-badge" class="badge badge-s">SAMPLE DATA</span>
    <span id="hdr-ts"></span>
    <span id="hdr-recon"></span>
  </div>
  <label class="btn-open" for="file-in">Open .log file</label>
  <input type="file" id="file-in" accept=".log" hidden>
</header>

<div class="stats">
  <div class="stat" id="st-trades">
    <div class="stat-lbl">Trades Today</div>
    <div class="stat-val">0</div>
    <div class="stat-sub">0 TP &middot; 0 SL</div>
  </div>
  <div class="stat" id="st-wr">
    <div class="stat-lbl">Win Rate</div>
    <div class="stat-val">&mdash;</div>
    <div class="stat-sub">closed trades</div>
  </div>
  <div class="stat" id="st-gross">
    <div class="stat-lbl">TP Proceeds</div>
    <div class="stat-val g">$0</div>
    <div class="stat-sub">gross wins</div>
  </div>
  <div class="stat" id="st-net">
    <div class="stat-lbl">Net P&amp;L</div>
    <div class="stat-val">$0</div>
    <div class="stat-sub">incl. est. SL</div>
  </div>
  <div class="stat" id="st-streak">
    <div class="stat-lbl">Streak</div>
    <div class="stat-val">&mdash;</div>
    <div class="stat-sub">current</div>
  </div>
</div>

<div class="wrap">
  <div class="two-col">
    <div class="card">
      <div class="card-hdr">Equity Curve</div>
      <div class="chart-box"><canvas id="eq-chart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-hdr">Entry Mode Breakdown</div>
      <div id="mode-panel"></div>
    </div>
  </div>

  <div class="card">
    <div class="card-hdr">Trade Log <span id="trade-count" style="color:var(--dim)"></span></div>
    <div class="tscroll">
      <table>
        <thead><tr>
          <th>#</th><th>TIME</th><th>DIR</th><th>MODE</th><th>GR</th>
          <th class="r">QTY</th><th class="r">ENTRY</th><th class="r">STOP</th>
          <th class="r">TARGET</th><th class="r">EXIT</th><th>OUTCOME</th><th class="r">P&amp;L</th>
        </tr></thead>
        <tbody id="trade-body"></tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-hdr">Recent 5-Min Bars</div>
    <div class="tscroll">
      <table>
        <thead><tr>
          <th>TIME</th><th class="r">OPEN</th><th class="r">HIGH</th>
          <th class="r">LOW</th><th class="r">CLOSE</th><th class="r">VOLUME</th>
        </tr></thead>
        <tbody id="bars-body"></tbody>
      </table>
    </div>
  </div>

  <div class="card" id="err-card" hidden>
    <div class="card-hdr" style="color:var(--red)">Recent Errors</div>
    <div class="err-list" id="err-list"></div>
  </div>
</div>

<div id="drop-ov" hidden>Drop .log file to load</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
const SAMPLE={
  bars:[
    {ts:"2024-11-04 09:00",o:"20412.50",h:"20445.00",l:"20398.75",c:"20430.25",v:"1823",trades:"0",max:"6",pnl:"0.00"},
    {ts:"2024-11-04 09:05",o:"20430.25",h:"20467.50",l:"20418.00",c:"20461.75",v:"2104",trades:"0",max:"6",pnl:"0.00"},
    {ts:"2024-11-04 09:10",o:"20461.75",h:"20485.25",l:"20439.50",c:"20442.00",v:"1956",trades:"1",max:"6",pnl:"120.00"},
    {ts:"2024-11-04 09:15",o:"20442.00",h:"20453.50",l:"20398.25",c:"20414.75",v:"2341",trades:"2",max:"6",pnl:"360.00"},
    {ts:"2024-11-04 09:20",o:"20414.75",h:"20427.50",l:"20401.00",c:"20419.25",v:"1687",trades:"3",max:"6",pnl:"280.00"},
    {ts:"2024-11-04 09:25",o:"20419.25",h:"20480.75",l:"20412.50",c:"20476.00",v:"1983",trades:"4",max:"6",pnl:"520.00"},
  ],
  trades:[
    {num:1,ts:"2024-11-04T09:12:35",dir:"LONG",entry:20414.75,stop:20374.75,target:20474.75,mode:"aggressive",grade:"B",qty:1,outcome:"TP \u2713",exit_px:20474.75,pnl:120.0},
    {num:2,ts:"2024-11-04T09:47:12",dir:"SHORT",entry:20498.50,stop:20538.50,target:20438.50,mode:"anticipation",grade:"A+",qty:2,outcome:"TP \u2713",exit_px:20438.50,pnl:240.0},
    {num:3,ts:"2024-11-04T10:25:08",dir:"LONG",entry:20442.25,stop:20402.25,target:20502.25,mode:"aggressive",grade:"C",qty:1,outcome:"SL?",exit_px:null,pnl:null},
    {num:4,ts:"2024-11-04T11:08:44",dir:"SHORT",entry:20521.75,stop:20561.75,target:20461.75,mode:"standard",grade:"A+",qty:2,outcome:"TP \u2713",exit_px:20461.75,pnl:240.0},
    {num:5,ts:"2024-11-04T11:43:21",dir:"LONG",entry:20487.00,stop:20447.00,target:20547.00,mode:"standard",grade:"B",qty:1,outcome:"OPEN",exit_px:null,pnl:null},
  ],
  errors:[],reconnects:0,log_file:null,
};

function parseLog(text){
  const bars=[],trades=[],errors=[];let reconnects=0;
  const barRe=/\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2})\\] O=([\\d.]+) H=([\\d.]+) L=([\\d.]+) C=([\\d.]+) V=(\\d+).*trades=(\\d+)\\/(\\d+) pnl=\\$([\\d.+-]+)/;
  const metaRe=/Signal: (\\w+)\\s+mode=(\\S+)\\s+grade=(\\S+)\\s+qty=(\\d+)/;
  const sigRe=/SIGNAL (\\w+) @ ([\\d.]+)\\s+stop=([\\d.]+)\\s+tgt=([\\d.]+)/;
  const tpRe=/TP hit: target=([\\d.]+)/;
  const recRe=/Trade recorded: pnl=([\\d.+-]+)/;
  let meta={},open=null;
  for(const line of text.split('\\n')){
    let m;
    if((m=barRe.exec(line))){bars.push({ts:m[1],o:m[2],h:m[3],l:m[4],c:m[5],v:m[6],trades:m[7],max:m[8],pnl:m[9]});continue;}
    if((m=metaRe.exec(line))){meta={mode:m[2],grade:m[3],qty:m[4]};continue;}
    if((m=sigRe.exec(line))){
      if(open&&open.outcome==='OPEN')open.outcome='SL?';
      open={num:trades.length+1,ts:line.slice(0,19),dir:m[1],entry:+m[2],stop:+m[3],target:+m[4],
            mode:meta.mode||'?',grade:meta.grade||'?',qty:+(meta.qty||1),outcome:'OPEN',exit_px:null,pnl:null};
      trades.push(open);meta={};continue;
    }
    if((m=tpRe.exec(line))&&open){open.outcome='TP \u2713';open.exit_px=+m[1];continue;}
    if((m=recRe.exec(line))&&open){const p=+m[1];if(p>0){open.pnl=p;if(open.outcome==='OPEN')open.outcome='TP \u2713';}continue;}
    if(/\\[ERROR\\]/.test(line))errors.push(line.trim().slice(-120));
    if(/LiveFeed reconnecting/.test(line))reconnects++;
  }
  return{bars,trades,errors:errors.slice(-5),reconnects,log_file:null};
}

let eqChart=null;

function renderAll(d,src){
  rHdr(d,src);rStats(d);rChart(d);rModes(d);rTrades(d);rBars(d);rErrors(d);
}

function rHdr(d,src){
  const b=document.getElementById('src-badge');
  if(src==='sample'){b.className='badge badge-s';b.textContent='SAMPLE DATA';}
  else{b.className='badge badge-l';b.textContent=typeof src==='string'&&src!=='live'?src.slice(0,20):'LIVE';}
  document.getElementById('hdr-ts').textContent='Updated '+new Date().toLocaleTimeString();
  document.getElementById('hdr-recon').textContent=d.reconnects>0?d.reconnects+' reconnects':'';
}

function rStats(d){
  const T=d.trades,tp=T.filter(t=>t.outcome==='TP \u2713').length,sl=T.filter(t=>t.outcome==='SL?').length,op=T.filter(t=>t.outcome==='OPEN').length;
  const closed=tp+sl,wr=closed?Math.round(tp/closed*100):null;
  const gross=T.reduce((s,t)=>t.pnl!=null?s+t.pnl:s,0);
  const slEst=T.filter(t=>t.outcome==='SL?').reduce((s,t)=>s+Math.abs(t.entry-t.stop)*t.qty*2,0);
  const net=gross-slEst;
  const ca=T.filter(t=>t.outcome!=='OPEN');
  let streak=0;
  if(ca.length){const last=ca.at(-1).outcome;for(let i=ca.length-1;i>=0;i--){if(ca[i].outcome===last)streak++;else break;}if(last==='SL?')streak=-streak;}
  function set(id,val,cls,sub){const e=document.getElementById(id);e.querySelector('.stat-val').textContent=val;e.querySelector('.stat-val').className='stat-val '+(cls||'');e.querySelector('.stat-sub').textContent=sub;}
  set('st-trades',T.length,'',tp+' TP \\u00b7 '+sl+' SL'+(op?' \\u00b7 '+op+' open':''));
  set('st-wr',wr!=null?wr+'%':'\\u2014',wr!=null?(wr>=50?'g':'r'):'',closed?tp+'/'+closed+' closed':'no closed trades');
  set('st-gross','$'+gross.toFixed(0),'g','gross wins');
  set('st-net',(net>=0?'+':'')+'$'+net.toFixed(0),net>=0?'g':'r','incl. est. SL');
  set('st-streak',Math.abs(streak)||'\\u2014',streak>0?'g':streak<0?'r':'',streak>0?'win streak':streak<0?'loss streak':'\\u2014');
  document.getElementById('trade-count').textContent=T.length?T.length+' total':'';
}

function rChart(d){
  const canvas=document.getElementById('eq-chart');
  const ctx=canvas.getContext('2d');
  if(eqChart){eqChart.destroy();eqChart=null;}
  const lbl=['Start'],pts=[0],col=['#4f5674'];
  let running=0;
  for(const t of d.trades){
    lbl.push('T'+t.num);
    if(t.pnl!=null)running+=t.pnl;
    else if(t.outcome==='SL?')running-=Math.abs(t.entry-t.stop)*t.qty*2;
    pts.push(running);
    col.push(t.outcome==='TP \u2713'?'#00d896':t.outcome==='SL?'?'#ff3f5e':'#f5c842');
  }
  if(pts.length<=1){
    ctx.fillStyle='#4f5674';ctx.font='13px Inter,sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.fillText('No trades yet',(canvas.clientWidth||300)/2,(canvas.clientHeight||180)/2);return;
  }
  const last=pts[pts.length-1],lc=last>=0?'#00d896':'#ff3f5e';
  eqChart=new Chart(ctx,{type:'line',data:{labels:lbl,datasets:[{data:pts,borderColor:lc,borderWidth:2,
    backgroundColor(c){const{chart:{ctx:x,chartArea:a}}=c;if(!a)return'transparent';
      const g=x.createLinearGradient(0,a.top,0,a.bottom);
      if(last>=0){g.addColorStop(0,'rgba(0,216,150,.15)');g.addColorStop(1,'rgba(0,216,150,0)');}
      else{g.addColorStop(0,'rgba(255,63,94,.15)');g.addColorStop(1,'rgba(255,63,94,0)');}
      return g;},
    fill:true,tension:.35,pointBackgroundColor:col,pointBorderColor:'#0e1120',pointBorderWidth:2,pointRadius:5,pointHoverRadius:7}]},
    options:{responsive:true,maintainAspectRatio:false,animation:{duration:300},
      scales:{y:{grid:{color:'#191d33'},border:{color:'#191d33'},ticks:{color:'#4f5674',font:{family:"'JetBrains Mono',monospace",size:11},callback:v=>'$'+v.toLocaleString()}},
              x:{grid:{color:'#191d33'},border:{color:'#191d33'},ticks:{color:'#4f5674',font:{family:"'JetBrains Mono',monospace",size:11}}}},
      plugins:{legend:{display:false},tooltip:{backgroundColor:'#131629',borderColor:'#191d33',borderWidth:1,titleColor:'#d8ddf0',bodyColor:'#4f5674',padding:10,
        callbacks:{title:i=>{const t=d.trades[i[0].dataIndex-1];return t?'Trade T'+t.num+'  '+t.ts.slice(11,16):'Session start';},
          label:i=>{const t=d.trades[i.dataIndex-1];if(!t)return'Cumulative: $0';
            const L=['Cumulative: $'+i.raw.toLocaleString(),''+t.dir+'  '+t.mode.slice(0,4).toUpperCase()+'  ['+t.grade+']',t.outcome];
            if(t.pnl!=null)L.push('This trade: +$'+t.pnl);return L;}}}}}});
}

function rModes(d){
  const T=d.trades,n=T.length||1;
  const M={standard:{n:0,c:'#9f8bff',lbl:'Standard (3-bar)'},aggressive:{n:0,c:'#3b9cff',lbl:'Aggressive (2-bar)'},anticipation:{n:0,c:'#00d896',lbl:'Anticipation (hammer)'}};
  const G={'A+':0,'B':0,'C':0};
  for(const t of T){const k=(t.mode||'').toLowerCase();if(M[k])M[k].n++;else M.standard.n++;G[t.grade]=(G[t.grade]||0)+1;}
  let h='<div class="mode-list">';
  for(const[,m]of Object.entries(M)){const p=Math.round(m.n/n*100);
    h+=`<div><div class="mode-row"><div class="mode-name"><span class="mode-pip" style="background:${m.c}"></span>${m.lbl}</div><span class="mode-cnt">${m.n}</span></div><div class="bar-track"><div class="bar-fill" style="width:${m.n?Math.max(p,2):0}%;background:${m.c}"></div></div></div>`;}
  h+='</div><div class="grade-row">';
  for(const[g,clr]of[['A+','#f5c842'],['B','#d8ddf0'],['C','#4f5674']]){
    h+=`<div class="grade-pill"><span class="grade-lbl" style="color:${clr}">${g}</span><span class="grade-num" style="color:${clr}">${G[g]||0}</span></div>`;}
  h+='</div>';
  document.getElementById('mode-panel').innerHTML=h;
}

const mBadge=m=>{const k=(m||'').toLowerCase();return k==='anticipation'?'<span class="mb mb-ant">ANT</span>':k==='aggressive'?'<span class="mb mb-agg">AGGR</span>':'<span class="mb mb-std">STD</span>';};
const gBadge=g=>g==='A+'?'<span class="gb gb-ap">A+</span>':g==='B'?'<span class="gb gb-b">B</span>':'<span class="gb gb-c">C</span>';
const oBadge=o=>o==='TP \u2713'?'<span class="ob ob-tp">TP</span>':o==='SL?'?'<span class="ob ob-sl">SL</span>':'<span class="ob ob-op">OPEN</span>';
const pnlCell=t=>{if(t.pnl!=null)return`<td class="r ${t.pnl>=0?'g':'r'}">${t.pnl>=0?'+':''}$${t.pnl.toFixed(0)}</td>`;
  if(t.outcome==='SL?'){const l=Math.abs(t.entry-t.stop)*t.qty*2;return`<td class="r pnl-est">~-$${l.toFixed(0)}</td>`;}
  return'<td class="r dim">\\u2014</td>';};

function rTrades(d){
  const tb=document.getElementById('trade-body');
  if(!d.trades.length){tb.innerHTML='<tr><td colspan="12" style="text-align:center;color:var(--muted);padding:24px">No trades today</td></tr>';return;}
  tb.innerHTML=d.trades.slice(-20).map(t=>{
    const rc=t.outcome==='TP \u2713'?'tp':t.outcome==='SL?'?'sl':'op';
    const time=t.ts.length>=16?t.ts.slice(11,16):t.ts;
    const exit=t.exit_px!=null?t.exit_px.toFixed(2):'\\u2014';
    return`<tr class="${rc}"><td class="m muted">${t.num}</td><td class="m">${time}</td><td class="${t.dir==='LONG'?'g':'r'}" style="font-weight:600">${t.dir}</td><td>${mBadge(t.mode)}</td><td>${gBadge(t.grade)}</td><td class="r m">${t.qty}</td><td class="r m">${t.entry.toFixed(2)}</td><td class="r m r">${t.stop.toFixed(2)}</td><td class="r m g">${t.target.toFixed(2)}</td><td class="r m muted">${exit}</td><td>${oBadge(t.outcome)}</td>${pnlCell(t)}</tr>`;}).join('');
}

function rBars(d){
  const tb=document.getElementById('bars-body');
  if(!d.bars.length){tb.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px">No bars received yet</td></tr>';return;}
  tb.innerHTML=d.bars.slice(-6).map(b=>{
    const up=+b.c>=+b.o;
    return`<tr><td class="m muted">${b.ts}</td><td class="r m">${b.o}</td><td class="r m g">${b.h}</td><td class="r m r">${b.l}</td><td class="r m ${up?'g':'r'}">${b.c}</td><td class="r m muted">${b.v}</td></tr>`;}).join('');
}

function rErrors(d){
  const card=document.getElementById('err-card');
  if(!d.errors||!d.errors.length){card.hidden=true;return;}
  card.hidden=false;document.getElementById('err-list').innerHTML=d.errors.map(e=>`<div class="err-item">${e}</div>`).join('');
}

function loadFile(file){const r=new FileReader();r.onload=e=>{const p=parseLog(e.target.result);p.log_file=file.name;renderAll(p,file.name);};r.readAsText(file);}
document.addEventListener('dragover',e=>{e.preventDefault();document.getElementById('drop-ov').hidden=false;});
document.addEventListener('dragleave',e=>{if(!e.relatedTarget)document.getElementById('drop-ov').hidden=true;});
document.addEventListener('drop',e=>{e.preventDefault();document.getElementById('drop-ov').hidden=true;const f=e.dataTransfer.files[0];if(f)loadFile(f);});
document.getElementById('file-in').addEventListener('change',e=>{if(e.target.files[0])loadFile(e.target.files[0]);});

async function init(){
  try{
    const res=await fetch('/api/data',{signal:AbortSignal.timeout(1500)});
    if(!res.ok)throw new Error();
    const data=await res.json();
    renderAll(data,data.log_file||'live');
    setInterval(async()=>{try{const r=await fetch('/api/data',{signal:AbortSignal.timeout(1500)});if(r.ok)renderAll(await r.json(),'live');}catch{}},5000);
  }catch{renderAll(SAMPLE,'sample');}
}
init();
</script>"""


# ─────────────────────────────────────────────────────────────
# HTTP server
# ─────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            body = _HTML.encode()
            ct   = "text/html"
        elif path == "/api/data":
            lf = _latest_log()
            if lf:
                data = _parse_log(lf)
            else:
                data = {"bars": [], "trades": [], "errors": [], "reconnects": 0, "log_file": None}
            body = json.dumps(data).encode()
            ct   = "application/json"
        else:
            self._send(404, "text/plain", b"Not found"); return
        self._send(200, ct, body)

    def _send(self, code: int, ct: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ct + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_) -> None:  # silence access log
        pass


if __name__ == "__main__":
    srv = HTTPServer(("localhost", PORT), _Handler)
    print(f"Dashboard → http://localhost:{PORT}")
    print("Drag & drop a .log file on the page, or leave it running for live updates.")
    print("Ctrl+C to stop.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
