import json, os

folder = r'C:\Users\ascha\OneDrive\Desktop\forage-data'
with open(os.path.join(folder, 'dashboard_data.json')) as f:
    data = json.load(f)

data_json = json.dumps(data, separators=(',',':'))

html = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Forage Kitchen - Period P&amp;L Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  :root {
    --bg:#0f1117;--card:#1a1d27;--card-hover:#22252f;--border:#2a2d3a;
    --text:#e4e4e7;--text-muted:#8b8d97;
    --green:#22c55e;--green-bg:rgba(34,197,94,.12);
    --red:#ef4444;--red-bg:rgba(239,68,68,.12);
    --accent:#6366f1;
  }
  *{margin:0;padding:0;box-sizing:border-box;}
  body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}
  .header{background:linear-gradient(135deg,#1e1b4b,#312e81);padding:24px 32px;border-bottom:1px solid var(--border);}
  .header h1{font-size:24px;font-weight:700;letter-spacing:-.5px;}
  .header p{color:var(--text-muted);font-size:13px;margin-top:4px;}
  .controls{display:flex;gap:16px;padding:16px 32px;background:var(--card);border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:flex-end;}
  .ctrl-group{display:flex;flex-direction:column;gap:4px;}
  .ctrl-group label{font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.8px;font-weight:700;}
  .ctrl-group select{background:#2a2d3a;color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 14px;font-size:13px;cursor:pointer;outline:none;}
  .ctrl-group select:hover{border-color:var(--accent);}
  .main{padding:24px 32px;max-width:1600px;margin:0 auto;}
  .kpi-row{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:28px;}
  .kpi-row.six{grid-template-columns:repeat(6,1fr);}
  .kpi-card.featured{border:1.5px solid var(--green);background:linear-gradient(180deg, rgba(34,197,94,.06), var(--card));}
  .kpi-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 18px;}
  .kpi-card:hover{border-color:var(--accent);}
  .kpi-card .label{font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.7px;font-weight:700;margin-bottom:6px;}
  .kpi-card .value{font-size:24px;font-weight:700;}
  .kpi-card .sub{font-size:11px;margin-top:5px;color:var(--text-muted);}
  .kpi-card .change{font-size:11px;margin-top:4px;padding:2px 8px;border-radius:4px;display:inline-block;font-weight:600;}
  .up{color:var(--green);}.up-bg{background:var(--green-bg);}
  .down{color:var(--red);}.down-bg{background:var(--red-bg);}
  .charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:28px;}
  .chart-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;}
  .chart-card.full{grid-column:1/-1;}
  .chart-card h3{font-size:13px;font-weight:600;margin-bottom:14px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;}
  .table-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;margin-bottom:24px;overflow-x:auto;}
  .table-card h3{font-size:13px;font-weight:600;margin-bottom:14px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;}
  table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap;}
  thead th{background:#22252f;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;font-size:10px;font-weight:700;padding:10px 10px;text-align:right;border-bottom:2px solid var(--border);position:sticky;top:0;}
  thead th:first-child{text-align:left;min-width:140px;}
  tbody td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums;}
  tbody td:first-child{text-align:left;font-weight:600;color:var(--text);}
  tbody tr:hover{background:var(--card-hover);}
  .pos{color:var(--green);}.neg{color:var(--red);}.na-val{color:#555;font-style:italic;}
  .total-row td{font-weight:700!important;border-top:2px solid var(--accent)!important;padding-top:10px;}
  .section-title{font-size:16px;font-weight:700;margin:32px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--border);}
  .store-tabs{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap;}
  .store-tab{padding:7px 14px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;background:#2a2d3a;border:1px solid var(--border);color:var(--text-muted);transition:all .15s;}
  .store-tab:hover{border-color:var(--accent);color:var(--text);}
  .store-tab.active{background:var(--accent);border-color:var(--accent);color:#fff;}
  .note{font-size:11px;color:var(--text-muted);margin:4px 0 12px;font-style:italic;}
  .spacer-row td{height:6px;border:none!important;padding:0!important;}
  @media(max-width:1100px){.kpi-row{grid-template-columns:repeat(3,1fr);}}
  @media(max-width:900px){.charts-grid{grid-template-columns:1fr;}.main{padding:16px;}.kpi-row{grid-template-columns:repeat(2,1fr);}}
</style>
</head>
<body>
<script src="nav.js"></script>
<div class="header">
  <h1>Forage Kitchen LLC &mdash; Period P&amp;L Dashboard</h1>
  <p>FY2026 YTD vs FY2025 &bull; 2-Yr Stacked Same Store Sales (Core Six) &bull; Net Sales &bull; Labor % &bull; COGS % &bull; Occupancy % &bull; EBITDA %</p>
</div>
<div class="controls">
  <div class="ctrl-group"><label>Period Filter (Stack KPIs)</label>
    <select id="periodSelect"><option value="0">YTD (P1-P7)</option>
    <option value="7">P7</option><option value="6">P6</option><option value="5">P5</option><option value="4">P4</option>
    <option value="3">P3</option><option value="2">P2</option><option value="1">P1</option></select>
  </div>
</div>
<div class="main">
  <div class="section-title">FY2026 YTD (P1-P7) vs FY2025 YTD (P1-P7) &mdash; All Stores</div>
  <p class="note">Periods 1-5, 2026 compared to Periods 1-5, 2025</p>
  <div id="ytd26KpiRow" class="kpi-row six"></div>
  <div class="table-card"><table id="ytd26Table"></table></div>
  <div class="charts-grid" style="margin-top:32px">
    <div class="chart-card full"><h3>Net Sales by Period &mdash; All Stores &bull; 2026 P1-P7</h3><canvas id="sssChart" height="70"></canvas></div>
    <div class="chart-card"><h3>Labor % by Period (Same Store)</h3><canvas id="laborChart" height="110"></canvas></div>
    <div class="chart-card"><h3>COGS % by Period (Same Store)</h3><canvas id="cogsChart" height="110"></canvas></div>
    <div class="chart-card"><h3>Occupancy % by Period (Same Store)</h3><canvas id="occChart" height="110"></canvas></div>
    <div class="chart-card"><h3>EBITDA % by Period (Same Store)</h3><canvas id="ebitdaChart" height="110"></canvas></div>
  </div>
  <div class="section-title">Same Store Sales &mdash; 2-Yr Stack (Core Six: 8001-8006)</div>
  <p class="note">Two-year stacked comp: 2026 vs 2024 over comparable periods &bull; only core-six stores have 2024 history</p>
  <div id="kpiRow" class="kpi-row"></div>
  <div class="section-title">2-Yr Stack by Period</div>
  <p class="note">Core-six totals each period &bull; 2-Yr Stack % = (2026 / 2024) - 1 &bull; only computed where 2026 data exists</p>
  <div class="table-card"><table id="sssTable"></table></div>
  <div class="section-title">2-Yr Stack by Restaurant</div>
  <p class="note">YTD P1-P7: 2024 / 2025 / 2026 comparable periods only</p>
  <div class="table-card"><table id="sssByStoreTable"></table></div>
  <div class="section-title">Store Detail &mdash; Trailing 12 Periods</div>
  <p class="note">Columns ordered oldest (left) to most recent (right) &bull; 2025 periods labeled '25 &bull; 2026 periods labeled '26 (green) &bull; PY = same 12 periods one year earlier</p>
  <div class="store-tabs" id="storeTabs"></div>
  <div class="table-card"><table id="storeTable"></table></div>
  <div class="section-title">Net Sales by Store &mdash; 2026</div>
  <div class="table-card"><table id="netSalesTable"></table></div>
</div>
<script>
const DATA = ''' + data_json + ''';

const STORE_NAMES = {"8001":"State St","8002":"Hilldale","8003":"Monona","8004":"Middleton","8005":"Champaign","8006":"Whitefish Bay","8007":"Sun Prairie","8008":"Pewaukee","8009":"MKE Public Market","8010":"Brookfield"};
const SSS_CONFIG = {"8001":[1,2,3,4,5,6,7,8,9,10,11,12],"8002":[1,2,3,4,5,6,7,8,9,10,11,12],"8003":[1,2,3,4,5,6,7,8,9,10,11,12],"8004":[1,2,3,4,5,6,7,8,9,10,11,12],"8005":[1,2,3,4,5,6,7,8,9,10,11,12],"8006":[1,2,3,4,5,6,7,8,9,10,11,12],"8007":[7,8,9,10,11,12],"8008":[11,12]};
const STORE_IDS = ["8001","8002","8003","8004","8005","8006","8007","8008","8009","8010"];
const CORE_SIX = ["8001","8002","8003","8004","8005","8006"];
const PERIODS = [1,2,3,4,5,6,7,8,9,10,11,12];

let charts = {};
let activeStore = "8001";

function gv(key,metric,p){if(!DATA[key]||!DATA[key][metric])return 0;return DATA[key][metric][String(p)]||0;}
function fmt(v){return "$"+Math.round(v).toLocaleString();}
function fmtPct(v){return v===null||isNaN(v)?"-":(v*100).toFixed(1)+"%";}
function fmtChg(v){return v===null||isNaN(v)||!isFinite(v)?"-":(v>=0?"+":"")+(v*100).toFixed(1)+"%";}

function sssP(metric,p){
  let t25=0,t24=0;
  for(const [s,vp] of Object.entries(SSS_CONFIG)){
    if(vp.includes(p)){t25+=gv(s+"_2025",metric,p);t24+=gv(s+"_2024",metric,p);}
  }
  return {v25:t25,v24:t24};
}
function stackP(metric,p){
  let v24=0,v25=0,v26=0;
  for(var i=0;i<CORE_SIX.length;i++){
    var s=CORE_SIX[i];
    v24+=gv(s+"_2024",metric,p);
    v25+=gv(s+"_2025",metric,p);
    v26+=gv(s+"_2026",metric,p);
  }
  return {v24:v24,v25:v25,v26:v26};
}

const FY26_PERIODS = [1,2,3,4,5,6,7];
function consol26(metric,p){
  if(!FY26_PERIODS.includes(p)) return null;
  var t=0;
  for(var i=0;i<STORE_IDS.length;i++){t+=gv(STORE_IDS[i]+"_2026",metric,p);}
  return t||null;
}
function allStores(metric,p,yr){
  var t=0;
  for(var i=0;i<STORE_IDS.length;i++){t+=gv(STORE_IDS[i]+"_"+yr,metric,p);}
  return t;
}

function renderKPIs(){
  const el=document.getElementById("kpiRow");
  const pf=parseInt(document.getElementById("periodSelect").value);
  const ps=pf===0?FY26_PERIODS:[pf];
  let ns24=0,ns25=0,ns26=0,eb26=0;
  for(const p of ps){
    const r=stackP("Net Sales",p);ns24+=r.v24;ns25+=r.v25;ns26+=r.v26;
    const e=stackP("EBITDA",p);eb26+=e.v26;
  }
  const stack=ns24?(ns26-ns24)/ns24:0;
  const yoy26=ns25?(ns26-ns25)/ns25:0;
  const yoy25=ns24?(ns25-ns24)/ns24:0;
  const eb26pct=ns26?eb26/ns26:0;
  const pl=pf===0?"YTD P1-P"+FY26_PERIODS[FY26_PERIODS.length-1]:"P"+pf;
  el.innerHTML=
    '<div class="kpi-card"><div class="label">2-Yr Stack Net Sales '+pl+'</div><div class="value">'+fmtChg(stack)+'</div>'+
    '<div class="change '+(stack>=0?"up up-bg":"down down-bg")+'">2026 vs 2024</div>'+
    '<div class="sub">2026: '+fmt(ns26)+' &middot; 2024: '+fmt(ns24)+'</div></div>'+
    '<div class="kpi-card"><div class="label">26 vs 25 Growth</div><div class="value">'+fmtChg(yoy26)+'</div>'+
    '<div class="change '+(yoy26>=0?"up up-bg":"down down-bg")+'">'+fmt(ns26-ns25)+' $</div>'+
    '<div class="sub">2025: '+fmt(ns25)+'</div></div>'+
    '<div class="kpi-card"><div class="label">25 vs 24 Growth</div><div class="value">'+fmtChg(yoy25)+'</div>'+
    '<div class="change '+(yoy25>=0?"up up-bg":"down down-bg")+'">'+fmt(ns25-ns24)+' $</div>'+
    '<div class="sub">prior-yr leg</div></div>'+
    '<div class="kpi-card"><div class="label">2026 EBITDA % '+pl+'</div><div class="value">'+fmtPct(eb26pct)+'</div>'+
    '<div class="change '+(eb26>=0?"up up-bg":"down down-bg")+'">EBITDA $: '+fmt(eb26)+'</div>'+
    '<div class="sub">Core six only</div></div>'+
    '<div class="kpi-card"><div class="label">Avg Annual (Stack)</div><div class="value">'+fmtChg(Math.pow(1+stack,0.5)-1)+'</div>'+
    '<div class="change up up-bg">2-yr CAGR</div>'+
    '<div class="sub">geometric avg of 25v24 &amp; 26v25</div></div>';
}

function renderSSSChart(){
  const ctx=document.getElementById("sssChart").getContext("2d");
  if(charts.sss)charts.sss.destroy();
  charts.sss=new Chart(ctx,{type:"bar",data:{
    labels:PERIODS.map(function(p){return "P"+p;}),
    datasets:[
      {label:"2026",data:PERIODS.map(function(p){return consol26("Net Sales",p);}),backgroundColor:"#22c55e",borderRadius:4,barPercentage:.4},
      {label:"2025",data:PERIODS.map(function(p){return allStores("Net Sales",p,2025);}),backgroundColor:"#6366f1",borderRadius:4,barPercentage:.4},
      {label:"2024",data:PERIODS.map(function(p){return allStores("Net Sales",p,2024);}),backgroundColor:"rgba(99,102,241,.25)",borderRadius:4,barPercentage:.4}
    ]},options:{responsive:true,interaction:{mode:"index",intersect:false},
    plugins:{legend:{labels:{color:"#8b8d97",font:{size:11}}},tooltip:{callbacks:{label:function(c){return c.dataset.label+": $"+Math.round(c.raw).toLocaleString();}}}},
    scales:{x:{ticks:{color:"#8b8d97"},grid:{color:"#1a1d27"}},y:{ticks:{color:"#8b8d97",callback:function(v){return "$"+(v/1000).toFixed(0)+"k";}},grid:{color:"#2a2d3a"}}}}});
}

function renderPctChart(id,metric){
  const ctx=document.getElementById(id).getContext("2d");
  if(charts[id])charts[id].destroy();
  const d26=PERIODS.map(function(p){var ns=consol26("Net Sales",p),mv=consol26(metric,p);return ns?(mv/ns*100):null;});
  const d25=PERIODS.map(function(p){var n=sssP("Net Sales",p),m=sssP(metric,p);return n.v25?(m.v25/n.v25*100):0;});
  const d24=PERIODS.map(function(p){var n=sssP("Net Sales",p),m=sssP(metric,p);return n.v24?(m.v24/n.v24*100):0;});
  charts[id]=new Chart(ctx,{type:"line",data:{labels:PERIODS.map(function(p){return "P"+p;}),datasets:[
    {label:"2026",data:d26,borderColor:"#22c55e",backgroundColor:"transparent",tension:.3,pointRadius:6,pointBackgroundColor:"#22c55e",spanGaps:false},
    {label:"2025",data:d25,borderColor:"#6366f1",backgroundColor:"rgba(99,102,241,.08)",fill:true,tension:.3,pointRadius:4,pointBackgroundColor:"#6366f1"},
    {label:"2024",data:d24,borderColor:"#8b8d97",backgroundColor:"transparent",borderDash:[5,5],tension:.3,pointRadius:3}
  ]},options:{responsive:true,interaction:{mode:"index",intersect:false},
  plugins:{legend:{labels:{color:"#8b8d97",font:{size:11}}},tooltip:{callbacks:{label:function(c){return c.dataset.label+": "+c.raw.toFixed(1)+"%";}}}},
  scales:{x:{ticks:{color:"#8b8d97"},grid:{color:"#1a1d27"}},y:{ticks:{color:"#8b8d97",callback:function(v){return v.toFixed(0)+"%";}},grid:{color:"#2a2d3a"}}}}});
}

function renderSSSTable(){
  var t=document.getElementById("sssTable");
  var h='<thead><tr><th>Period</th><th>2024 Net Sales</th><th>2025 Net Sales</th><th>2026 Net Sales</th><th>25v24 %</th><th>26v25 %</th><th>2-Yr Stack %</th><th>Stack $ (26-24)</th></tr></thead><tbody>';
  var t24=0,t25=0,t26=0;
  for(var i=0;i<PERIODS.length;i++){
    var p=PERIODS[i];
    var r=stackP("Net Sales",p);
    t24+=r.v24;t25+=r.v25;t26+=r.v26;
    var has26=r.v26>0;
    var c25v24=r.v24?(r.v25-r.v24)/r.v24:0;
    var c26v25=r.v25?(r.v26-r.v25)/r.v25:0;
    var cstack=r.v24?(r.v26-r.v24)/r.v24:0;
    var dstack=r.v26-r.v24;
    h+='<tr><td>P'+p+'</td>'+
      '<td>'+fmt(r.v24)+'</td>'+
      '<td>'+fmt(r.v25)+'</td>'+
      '<td style="color:#22c55e;font-weight:600">'+(has26?fmt(r.v26):'<span class="na-val">-</span>')+'</td>'+
      '<td class="'+(c25v24>=0?"pos":"neg")+'">'+fmtChg(c25v24)+'</td>'+
      '<td class="'+(c26v25>=0?"pos":"neg")+'">'+(has26?fmtChg(c26v25):'<span class="na-val">-</span>')+'</td>'+
      '<td class="'+(cstack>=0?"pos":"neg")+'" style="font-weight:600">'+(has26?fmtChg(cstack):'<span class="na-val">-</span>')+'</td>'+
      '<td class="'+(dstack>=0?"pos":"neg")+'">'+(has26?fmt(dstack):'<span class="na-val">-</span>')+'</td></tr>';
  }
  var tc25v24=t24?(t25-t24)/t24:0;
  var tc26v25=t25?(t26-t25)/t25:0;
  var tcstack=t24?(t26-t24)/t24:0;
  h+='<tr class="total-row"><td>Total</td>'+
    '<td>'+fmt(t24)+'</td><td>'+fmt(t25)+'</td>'+
    '<td style="color:#22c55e">'+fmt(t26)+'</td>'+
    '<td class="'+(tc25v24>=0?"pos":"neg")+'">'+fmtChg(tc25v24)+'</td>'+
    '<td class="'+(tc26v25>=0?"pos":"neg")+'">'+fmtChg(tc26v25)+'</td>'+
    '<td class="'+(tcstack>=0?"pos":"neg")+'">'+fmtChg(tcstack)+'</td>'+
    '<td class="'+((t26-t24)>=0?"pos":"neg")+'">'+fmt(t26-t24)+'</td></tr></tbody>';
  t.innerHTML=h;
}

function renderSSSByStore(){
  var t=document.getElementById("sssByStoreTable");
  var ytdLabel="YTD P1-P"+FY26_PERIODS[FY26_PERIODS.length-1];
  var h='<thead><tr><th>Store</th><th>Periods</th><th>2024 Net Sales</th><th>2025 Net Sales</th><th>2026 Net Sales</th><th>25v24 %</th><th>26v25 %</th><th>2-Yr Stack %</th><th>Stack $</th></tr></thead><tbody>';
  var g24=0,g25=0,g26=0;
  for(var i=0;i<CORE_SIX.length;i++){
    var sid=CORE_SIX[i];
    var s24=0,s25=0,s26=0;
    for(var j=0;j<FY26_PERIODS.length;j++){
      var p=FY26_PERIODS[j];
      s24+=gv(sid+"_2024","Net Sales",p);
      s25+=gv(sid+"_2025","Net Sales",p);
      s26+=gv(sid+"_2026","Net Sales",p);
    }
    g24+=s24;g25+=s25;g26+=s26;
    var c25v24=s24?(s25-s24)/s24:0;
    var c26v25=s25?(s26-s25)/s25:0;
    var cstack=s24?(s26-s24)/s24:0;
    h+='<tr><td>'+sid+' - '+STORE_NAMES[sid]+'</td><td>'+ytdLabel+'</td>'+
      '<td>'+fmt(s24)+'</td><td>'+fmt(s25)+'</td>'+
      '<td style="color:#22c55e;font-weight:600">'+fmt(s26)+'</td>'+
      '<td class="'+(c25v24>=0?"pos":"neg")+'">'+fmtChg(c25v24)+'</td>'+
      '<td class="'+(c26v25>=0?"pos":"neg")+'">'+fmtChg(c26v25)+'</td>'+
      '<td class="'+(cstack>=0?"pos":"neg")+'" style="font-weight:600">'+fmtChg(cstack)+'</td>'+
      '<td class="'+((s26-s24)>=0?"pos":"neg")+'">'+fmt(s26-s24)+'</td></tr>';
  }
  var gc25v24=g24?(g25-g24)/g24:0;
  var gc26v25=g25?(g26-g25)/g25:0;
  var gcstack=g24?(g26-g24)/g24:0;
  h+='<tr class="total-row"><td>Core Six Total</td><td>'+ytdLabel+'</td>'+
    '<td>'+fmt(g24)+'</td><td>'+fmt(g25)+'</td>'+
    '<td style="color:#22c55e">'+fmt(g26)+'</td>'+
    '<td class="'+(gc25v24>=0?"pos":"neg")+'">'+fmtChg(gc25v24)+'</td>'+
    '<td class="'+(gc26v25>=0?"pos":"neg")+'">'+fmtChg(gc26v25)+'</td>'+
    '<td class="'+(gcstack>=0?"pos":"neg")+'">'+fmtChg(gcstack)+'</td>'+
    '<td class="'+((g26-g24)>=0?"pos":"neg")+'">'+fmt(g26-g24)+'</td></tr></tbody>';
  t.innerHTML=h;
}

function renderStoreTabs(){
  var el=document.getElementById("storeTabs");
  var html="";
  for(var i=0;i<STORE_IDS.length;i++){
    var id=STORE_IDS[i];
    html+='<div class="store-tab '+(id===activeStore?"active":"")+'" onclick="selectStore(\\\''+id+'\\\')">';
    html+=id+" - "+STORE_NAMES[id]+"</div>";
  }
  el.innerHTML=html;
}
function selectStore(id){activeStore=id;renderStoreTabs();renderStoreTable();}

function renderStoreTable(){
  var t=document.getElementById("storeTable");
  var id=activeStore,nm=STORE_NAMES[id];

  // Build trailing-12 sequence (oldest -> newest), ending at the most recent reported 2026 period
  var lastP=FY26_PERIODS[FY26_PERIODS.length-1];
  var ttm=[]; // {p, yr}
  for(var pp=lastP+1; pp<=12; pp++) ttm.push({p:pp, yr:2025});
  for(var pp=1; pp<=lastP; pp++) ttm.push({p:pp, yr:2026});
  // Prior-year comparable: same calendar periods shifted back 1 year
  var ttmPY=ttm.map(function(x){return {p:x.p, yr:x.yr-1};});
  var nCols=ttm.length;

  var h='<thead><tr><th>'+id+' - '+nm+' &mdash; Trailing 12</th>';
  for(var i=0;i<nCols;i++){
    var yrTag=String(ttm[i].yr).slice(-2);
    var hl=(ttm[i].yr===2026)?' style="color:#22c55e"':'';
    h+='<th'+hl+'>P'+ttm[i].p+" '"+yrTag+'</th>';
  }
  h+='<th>TTM</th></tr></thead><tbody>';

  // TTM Net Sales
  var totTTM=0,totPY=0;
  h+='<tr style="color:#22c55e"><td><strong>TTM Net Sales</strong></td>';
  for(var i=0;i<nCols;i++){
    var v=gv(id+"_"+ttm[i].yr,"Net Sales",ttm[i].p);
    totTTM+=v;
    h+='<td>'+(v?fmt(v):'<span class="na-val">-</span>')+'</td>';
  }
  h+='<td><strong>'+fmt(totTTM)+'</strong></td></tr>';

  // PY TTM Net Sales (same periods, 1 year back)
  h+='<tr><td><strong>PY TTM Net Sales</strong></td>';
  for(var i=0;i<nCols;i++){
    var v=gv(id+"_"+ttmPY[i].yr,"Net Sales",ttmPY[i].p);
    totPY+=v;
    h+='<td>'+(v?fmt(v):'<span class="na-val">-</span>')+'</td>';
  }
  h+='<td><strong>'+fmt(totPY)+'</strong></td></tr>';

  // YoY % Change (period-by-period)
  h+='<tr><td>YoY %</td>';
  for(var i=0;i<nCols;i++){
    var cv=gv(id+"_"+ttm[i].yr,"Net Sales",ttm[i].p);
    var pv=gv(id+"_"+ttmPY[i].yr,"Net Sales",ttmPY[i].p);
    if(!cv||!pv){h+='<td class="na-val">-</td>';continue;}
    var c=(cv-pv)/pv;
    h+='<td class="'+(c>=0?"pos":"neg")+'">'+fmtChg(c)+'</td>';
  }
  var totYoY=totPY?(totTTM-totPY)/totPY:0;
  h+='<td class="'+(totYoY>=0?"pos":"neg")+'"><strong>'+(totPY?fmtChg(totYoY):'-')+'</strong></td></tr>';

  h+='<tr class="spacer-row"><td colspan="'+(nCols+2)+'"></td></tr>';

  // COGS / Labor / Occupancy % (trailing 12)
  var metricList=[["COGS","COGS %"],["Labor","Labor %"],["Occupancy","Occupancy %"]];
  for(var m=0;m<metricList.length;m++){
    var tm=0,tns=0;
    h+='<tr><td>'+metricList[m][1]+'</td>';
    for(var i=0;i<nCols;i++){
      var ns=gv(id+"_"+ttm[i].yr,"Net Sales",ttm[i].p);
      var mv=gv(id+"_"+ttm[i].yr,metricList[m][0],ttm[i].p);
      tm+=mv;tns+=ns;
      h+='<td>'+(ns?fmtPct(mv/ns):'<span class="na-val">-</span>')+'</td>';
    }
    h+='<td><strong>'+(tns?fmtPct(tm/tns):"-")+'</strong></td></tr>';
  }

  // EBITDA % (trailing 12)
  var tebd=0,tens=0;
  h+='<tr><td>EBITDA %</td>';
  for(var i=0;i<nCols;i++){
    var ns=gv(id+"_"+ttm[i].yr,"Net Sales",ttm[i].p);
    var ev=gv(id+"_"+ttm[i].yr,"EBITDA",ttm[i].p);
    tebd+=ev;tens+=ns;
    var pv=ns?ev/ns:null;
    h+='<td class="'+(pv!==null?(pv>=0?"pos":"neg"):"")+'">'+(pv!==null?fmtPct(pv):'<span class="na-val">-</span>')+'</td>';
  }
  h+='<td class="'+(tebd>=0?"pos":"neg")+'"><strong>'+(tens?fmtPct(tebd/tens):"-")+'</strong></td></tr>';

  // EBITDA $ (trailing 12)
  var tebd2=0;
  h+='<tr><td>EBITDA $</td>';
  for(var i=0;i<nCols;i++){
    var ns=gv(id+"_"+ttm[i].yr,"Net Sales",ttm[i].p);
    var ev=gv(id+"_"+ttm[i].yr,"EBITDA",ttm[i].p);
    tebd2+=ev;
    h+='<td class="'+(ns?(ev>=0?"pos":"neg"):"")+'">'+(ns?fmt(ev):'<span class="na-val">-</span>')+'</td>';
  }
  h+='<td class="'+(tebd2>=0?"pos":"neg")+'"><strong>'+fmt(tebd2)+'</strong></td></tr></tbody>';
  t.innerHTML=h;
}

function renderNetSalesTable(){
  var t=document.getElementById("netSalesTable");
  var h='<thead><tr><th>Store</th>';
  for(var i=0;i<PERIODS.length;i++)h+='<th>P'+PERIODS[i]+'</th>';
  h+='<th>YTD</th></tr></thead><tbody>';
  var gt=[];for(var i=0;i<12;i++)gt.push(0);
  var grand=0;
  for(var s=0;s<STORE_IDS.length;s++){
    var id=STORE_IDS[s],rt=0;
    h+='<tr><td>'+id+' - '+STORE_NAMES[id]+'</td>';
    for(var i=0;i<12;i++){var v=gv(id+"_2026","Net Sales",PERIODS[i]);rt+=v;gt[i]+=v;h+='<td>'+(v?fmt(v):'<span class="na-val">-</span>')+'</td>';}
    grand+=rt;h+='<td><strong>'+fmt(rt)+'</strong></td></tr>';
  }
  h+='<tr class="total-row"><td>All Stores</td>';
  for(var i=0;i<12;i++)h+='<td>'+(gt[i]?fmt(gt[i]):'<span class="na-val">-</span>')+'</td>';
  h+='<td><strong>'+fmt(grand)+'</strong></td></tr></tbody>';
  t.innerHTML=h;
}

function renderYtd26KPIs(){
  var el=document.getElementById("ytd26KpiRow");
  var ns26=0,ns25=0,cg26=0,cg25=0,lb26=0,lb25=0,oc26=0,oc25=0,eb26=0,eb25=0;
  // SSS = stores with non-zero Net Sales in both years across the YTD periods
  var sssNs26=0,sssNs25=0,sssCount=0,sssStores=[];
  for(var i=0;i<STORE_IDS.length;i++){
    var id=STORE_IDS[i];
    var sNs26=0,sNs25=0;
    for(var p=0;p<FY26_PERIODS.length;p++){
      var pp=FY26_PERIODS[p];
      ns26+=gv(id+"_2026","Net Sales",pp);ns25+=gv(id+"_2025","Net Sales",pp);
      cg26+=gv(id+"_2026","COGS",pp);cg25+=gv(id+"_2025","COGS",pp);
      lb26+=gv(id+"_2026","Labor",pp);lb25+=gv(id+"_2025","Labor",pp);
      oc26+=gv(id+"_2026","Occupancy",pp);oc25+=gv(id+"_2025","Occupancy",pp);
      eb26+=gv(id+"_2026","EBITDA",pp);eb25+=gv(id+"_2025","EBITDA",pp);
      sNs26+=gv(id+"_2026","Net Sales",pp);sNs25+=gv(id+"_2025","Net Sales",pp);
    }
    if(sNs26>0 && sNs25>0){sssNs26+=sNs26;sssNs25+=sNs25;sssCount++;sssStores.push(id);}
  }
  var sssPct=sssNs25?(sssNs26-sssNs25)/sssNs25:0;
  var sc=ns25?(ns26-ns25)/ns25:0;
  var lp26=ns26?lb26/ns26:0,lp25=ns25?lb25/ns25:0;
  var cp26=ns26?cg26/ns26:0,cp25=ns25?cg25/ns25:0;
  var op26=ns26?oc26/ns26:0,op25=ns25?oc25/ns25:0;
  var ep26=ns26?eb26/ns26:0,ep25=ns25?eb25/ns25:0;
  var lastP=FY26_PERIODS[FY26_PERIODS.length-1];
  el.innerHTML=
    '<div class="kpi-card featured"><div class="label">YTD Same Store Sales</div><div class="value '+(sssPct>=0?"up":"down")+'">'+fmtChg(sssPct)+'</div>'+
    '<div class="change '+(sssPct>=0?"up up-bg":"down down-bg")+'">P1-P'+lastP+' &middot; '+sssCount+' stores</div>'+
    '<div class="sub">26: '+fmt(sssNs26)+' &middot; 25: '+fmt(sssNs25)+'</div></div>'+
    '<div class="kpi-card"><div class="label">YTD 2026 Net Sales</div><div class="value">'+fmt(ns26)+'</div>'+
    '<div class="change '+(sc>=0?"up up-bg":"down down-bg")+'">'+fmtChg(sc)+' vs YTD 2025</div>'+
    '<div class="sub">YTD 2025: '+fmt(ns25)+'</div></div>'+
    '<div class="kpi-card"><div class="label">YTD Labor %</div><div class="value">'+fmtPct(lp26)+'</div>'+
    '<div class="change '+(lp26<=lp25?"up up-bg":"down down-bg")+'">'+(lp26<=lp25?"Improved":"Higher")+' vs '+fmtPct(lp25)+'</div></div>'+
    '<div class="kpi-card"><div class="label">YTD COGS %</div><div class="value">'+fmtPct(cp26)+'</div>'+
    '<div class="change '+(cp26<=cp25?"up up-bg":"down down-bg")+'">'+(cp26<=cp25?"Improved":"Higher")+' vs '+fmtPct(cp25)+'</div></div>'+
    '<div class="kpi-card"><div class="label">YTD Occupancy %</div><div class="value">'+fmtPct(op26)+'</div>'+
    '<div class="change '+(op26<=op25?"up up-bg":"down down-bg")+'">'+(op26<=op25?"Improved":"Higher")+' vs '+fmtPct(op25)+'</div></div>'+
    '<div class="kpi-card"><div class="label">YTD EBITDA %</div><div class="value">'+fmtPct(ep26)+'</div>'+
    '<div class="change '+(ep26>=ep25?"up up-bg":"down down-bg")+'">'+fmtChg(ep26-ep25)+' pts vs YTD 2025</div>'+
    '<div class="sub">EBITDA $: '+fmt(eb26)+'</div></div>';
}

function renderYtd26Table(){
  var t=document.getElementById("ytd26Table");
  var h='<thead><tr><th>Store</th><th>Net Sales 2026</th><th>Net Sales 2025</th><th>% Chg</th><th>Labor %</th><th>COGS %</th><th>Occup %</th><th>EBITDA %</th><th>EBITDA $</th></tr></thead><tbody>';
  var tns26=0,tns25=0,tcg=0,tlb=0,toc=0,teb=0;
  for(var i=0;i<STORE_IDS.length;i++){
    var id=STORE_IDS[i];
    var sns26=0,sns25=0,scg=0,slb=0,soc=0,seb=0;
    for(var p=0;p<FY26_PERIODS.length;p++){
      var pp=FY26_PERIODS[p];
      sns26+=gv(id+"_2026","Net Sales",pp);sns25+=gv(id+"_2025","Net Sales",pp);
      scg+=gv(id+"_2026","COGS",pp);slb+=gv(id+"_2026","Labor",pp);
      soc+=gv(id+"_2026","Occupancy",pp);seb+=gv(id+"_2026","EBITDA",pp);
    }
    tns26+=sns26;tns25+=sns25;tcg+=scg;tlb+=slb;toc+=soc;teb+=seb;
    var pc=sns25?(sns26-sns25)/sns25:0;
    h+='<tr><td>'+id+' - '+STORE_NAMES[id]+'</td>'+
      '<td>'+(sns26?fmt(sns26):'<span class="na-val">-</span>')+'</td>'+
      '<td>'+(sns25?fmt(sns25):'<span class="na-val">-</span>')+'</td>'+
      '<td class="'+(pc>=0?"pos":"neg")+'">'+(sns25&&sns26?fmtChg(pc):'<span class="na-val">N/A</span>')+'</td>'+
      '<td>'+(sns26?fmtPct(slb/sns26):"-")+'</td>'+
      '<td>'+(sns26?fmtPct(scg/sns26):"-")+'</td>'+
      '<td>'+(sns26?fmtPct(soc/sns26):"-")+'</td>'+
      '<td class="'+(seb>=0?"pos":"neg")+'">'+(sns26?fmtPct(seb/sns26):"-")+'</td>'+
      '<td class="'+(seb>=0?"pos":"neg")+'">'+fmt(seb)+'</td></tr>';
  }
  var tpc=tns25?(tns26-tns25)/tns25:0;
  h+='<tr class="total-row"><td>All Stores</td>'+
    '<td>'+fmt(tns26)+'</td><td>'+fmt(tns25)+'</td>'+
    '<td class="'+(tpc>=0?"pos":"neg")+'">'+fmtChg(tpc)+'</td>'+
    '<td>'+fmtPct(tns26?tlb/tns26:0)+'</td><td>'+fmtPct(tns26?tcg/tns26:0)+'</td>'+
    '<td>'+fmtPct(tns26?toc/tns26:0)+'</td>'+
    '<td class="'+(teb>=0?"pos":"neg")+'">'+fmtPct(tns26?teb/tns26:0)+'</td>'+
    '<td class="'+(teb>=0?"pos":"neg")+'">'+fmt(teb)+'</td></tr></tbody>';
  t.innerHTML=h;
}

function renderAll(){
  renderKPIs();renderSSSChart();
  renderPctChart("laborChart","Labor");renderPctChart("cogsChart","COGS");
  renderPctChart("occChart","Occupancy");renderPctChart("ebitdaChart","EBITDA");
  renderSSSTable();renderSSSByStore();renderStoreTabs();renderStoreTable();renderNetSalesTable();
  renderYtd26KPIs();renderYtd26Table();
}
document.getElementById("periodSelect").addEventListener("change",renderKPIs);
renderAll();
</script>
</body>
</html>'''

output_path = os.path.join(folder, 'dashboard.html')
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'Dashboard written to {output_path}')
print(f'File size: {os.path.getsize(output_path):,} bytes')
