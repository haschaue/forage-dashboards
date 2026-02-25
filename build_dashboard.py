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
<div class="header">
  <h1>Forage Kitchen LLC &mdash; Period P&amp;L Dashboard</h1>
  <p>Same Store Sales 2025 vs 2024 &bull; By Restaurant &bull; Net Sales &bull; Labor % &bull; COGS % &bull; Occupancy % &bull; EBITDA %</p>
</div>
<div class="controls">
  <div class="ctrl-group"><label>Period Filter (KPIs)</label>
    <select id="periodSelect"><option value="0">All Periods (YTD)</option>
    <option value="12">P12</option><option value="11">P11</option><option value="10">P10</option>
    <option value="9">P9</option><option value="8">P8</option><option value="7">P7</option>
    <option value="6">P6</option><option value="5">P5</option><option value="4">P4</option>
    <option value="3">P3</option><option value="2">P2</option><option value="1">P1</option></select>
  </div>
</div>
<div class="main">
  <div id="kpiRow" class="kpi-row"></div>
  <div class="charts-grid">
    <div class="chart-card full"><h3>Same Store Net Sales &mdash; 2025 vs 2024</h3><canvas id="sssChart" height="70"></canvas></div>
    <div class="chart-card"><h3>Labor % by Period (Same Store)</h3><canvas id="laborChart" height="110"></canvas></div>
    <div class="chart-card"><h3>COGS % by Period (Same Store)</h3><canvas id="cogsChart" height="110"></canvas></div>
    <div class="chart-card"><h3>Occupancy % by Period (Same Store)</h3><canvas id="occChart" height="110"></canvas></div>
    <div class="chart-card"><h3>EBITDA % by Period (Same Store)</h3><canvas id="ebitdaChart" height="110"></canvas></div>
  </div>
  <div class="section-title">Same Store Sales by Period</div>
  <p class="note">Stores included: 8001-8006 all periods &bull; 8007 from P7 &bull; 8008 from P11 &bull; 8009 excluded (no 2024 history)</p>
  <div class="table-card"><table id="sssTable"></table></div>
  <div class="section-title">Same Store Sales by Restaurant</div>
  <p class="note">Each store compared over its eligible same-store periods only</p>
  <div class="table-card"><table id="sssByStoreTable"></table></div>
  <div class="section-title">Store Detail</div>
  <div class="store-tabs" id="storeTabs"></div>
  <div class="table-card"><table id="storeTable"></table></div>
  <div class="section-title">Net Sales by Store &mdash; 2025</div>
  <div class="table-card"><table id="netSalesTable"></table></div>
</div>
<script>
const DATA = ''' + data_json + ''';

const STORE_NAMES = {"8001":"State St","8002":"Hilldale","8003":"Monona","8004":"Middleton","8005":"Champaign","8006":"Whitefish Bay","8007":"Sun Prairie","8008":"Pewaukee","8009":"MKE Public Market","8010":"Brookfield"};
const SSS_CONFIG = {"8001":[1,2,3,4,5,6,7,8,9,10,11,12],"8002":[1,2,3,4,5,6,7,8,9,10,11,12],"8003":[1,2,3,4,5,6,7,8,9,10,11,12],"8004":[1,2,3,4,5,6,7,8,9,10,11,12],"8005":[1,2,3,4,5,6,7,8,9,10,11,12],"8006":[1,2,3,4,5,6,7,8,9,10,11,12],"8007":[7,8,9,10,11,12],"8008":[11,12]};
const STORE_IDS = ["8001","8002","8003","8004","8005","8006","8007","8008","8009"];
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

function renderKPIs(){
  const el=document.getElementById("kpiRow");
  const pf=parseInt(document.getElementById("periodSelect").value);
  const ps=pf===0?PERIODS:[pf];
  let ns25=0,ns24=0,cg25=0,cg24=0,lb25=0,lb24=0,oc25=0,oc24=0,eb25=0,eb24=0;
  for(const p of ps){
    const a=sssP("Net Sales",p);ns25+=a.v25;ns24+=a.v24;
    const b=sssP("COGS",p);cg25+=b.v25;cg24+=b.v24;
    const c=sssP("Labor",p);lb25+=c.v25;lb24+=c.v24;
    const d=sssP("Occupancy",p);oc25+=d.v25;oc24+=d.v24;
    const e=sssP("EBITDA",p);eb25+=e.v25;eb24+=e.v24;
  }
  const sc=ns24?(ns25-ns24)/ns24:0;
  const lp25=ns25?lb25/ns25:0,lp24=ns24?lb24/ns24:0;
  const cp25=ns25?cg25/ns25:0,cp24=ns24?cg24/ns24:0;
  const op25=ns25?oc25/ns25:0,op24=ns24?oc24/ns24:0;
  const ep25=ns25?eb25/ns25:0,ep24=ns24?eb24/ns24:0;
  const pl=pf===0?"YTD":"P"+pf;
  el.innerHTML=
    '<div class="kpi-card"><div class="label">Net Sales '+pl+'</div><div class="value">'+fmt(ns25)+'</div>'+
    '<div class="change '+(sc>=0?"up up-bg":"down down-bg")+'">'+fmtChg(sc)+' vs 2024</div>'+
    '<div class="sub">2024: '+fmt(ns24)+'</div></div>'+
    '<div class="kpi-card"><div class="label">Labor % '+pl+'</div><div class="value">'+fmtPct(lp25)+'</div>'+
    '<div class="change '+(lp25<=lp24?"up up-bg":"down down-bg")+'">'+(lp25<=lp24?"Improved":"Higher")+' vs '+fmtPct(lp24)+'</div></div>'+
    '<div class="kpi-card"><div class="label">COGS % '+pl+'</div><div class="value">'+fmtPct(cp25)+'</div>'+
    '<div class="change '+(cp25<=cp24?"up up-bg":"down down-bg")+'">'+(cp25<=cp24?"Improved":"Higher")+' vs '+fmtPct(cp24)+'</div></div>'+
    '<div class="kpi-card"><div class="label">Occupancy % '+pl+'</div><div class="value">'+fmtPct(op25)+'</div>'+
    '<div class="change '+(op25<=op24?"up up-bg":"down down-bg")+'">'+(op25<=op24?"Improved":"Higher")+' vs '+fmtPct(op24)+'</div></div>'+
    '<div class="kpi-card"><div class="label">EBITDA % '+pl+'</div><div class="value">'+fmtPct(ep25)+'</div>'+
    '<div class="change '+(ep25>=ep24?"up up-bg":"down down-bg")+'">'+fmtChg(ep25-ep24)+' pts vs 2024</div>'+
    '<div class="sub">EBITDA $: '+fmt(eb25)+'</div></div>';
}

function renderSSSChart(){
  const ctx=document.getElementById("sssChart").getContext("2d");
  if(charts.sss)charts.sss.destroy();
  charts.sss=new Chart(ctx,{type:"bar",data:{
    labels:PERIODS.map(function(p){return "P"+p;}),
    datasets:[
      {label:"2025",data:PERIODS.map(function(p){return sssP("Net Sales",p).v25;}),backgroundColor:"#6366f1",borderRadius:4,barPercentage:.4},
      {label:"2024",data:PERIODS.map(function(p){return sssP("Net Sales",p).v24;}),backgroundColor:"rgba(99,102,241,.25)",borderRadius:4,barPercentage:.4}
    ]},options:{responsive:true,interaction:{mode:"index",intersect:false},
    plugins:{legend:{labels:{color:"#8b8d97",font:{size:11}}},tooltip:{callbacks:{label:function(c){return c.dataset.label+": $"+Math.round(c.raw).toLocaleString();}}}},
    scales:{x:{ticks:{color:"#8b8d97"},grid:{color:"#1a1d27"}},y:{ticks:{color:"#8b8d97",callback:function(v){return "$"+(v/1000).toFixed(0)+"k";}},grid:{color:"#2a2d3a"}}}}});
}

function renderPctChart(id,metric){
  const ctx=document.getElementById(id).getContext("2d");
  if(charts[id])charts[id].destroy();
  const d25=PERIODS.map(function(p){var n=sssP("Net Sales",p),m=sssP(metric,p);return n.v25?(m.v25/n.v25*100):0;});
  const d24=PERIODS.map(function(p){var n=sssP("Net Sales",p),m=sssP(metric,p);return n.v24?(m.v24/n.v24*100):0;});
  charts[id]=new Chart(ctx,{type:"line",data:{labels:PERIODS.map(function(p){return "P"+p;}),datasets:[
    {label:"2025",data:d25,borderColor:"#6366f1",backgroundColor:"rgba(99,102,241,.08)",fill:true,tension:.3,pointRadius:4,pointBackgroundColor:"#6366f1"},
    {label:"2024",data:d24,borderColor:"#8b8d97",backgroundColor:"transparent",borderDash:[5,5],tension:.3,pointRadius:3}
  ]},options:{responsive:true,interaction:{mode:"index",intersect:false},
  plugins:{legend:{labels:{color:"#8b8d97",font:{size:11}}},tooltip:{callbacks:{label:function(c){return c.dataset.label+": "+c.raw.toFixed(1)+"%";}}}},
  scales:{x:{ticks:{color:"#8b8d97"},grid:{color:"#1a1d27"}},y:{ticks:{color:"#8b8d97",callback:function(v){return v.toFixed(0)+"%";}},grid:{color:"#2a2d3a"}}}}});
}

function renderSSSTable(){
  var t=document.getElementById("sssTable");
  var h='<thead><tr><th>Period</th><th>2025 Net Sales</th><th>2024 Net Sales</th><th>$ Change</th><th>% Change</th><th>Labor %</th><th>COGS %</th><th>Occup %</th><th>EBITDA %</th></tr></thead><tbody>';
  var tn25=0,tn24=0,tc=0,tl=0,to=0,te=0;
  for(var i=0;i<PERIODS.length;i++){
    var p=PERIODS[i];
    var ns=sssP("Net Sales",p),cg=sssP("COGS",p),lb=sssP("Labor",p),oc=sssP("Occupancy",p),eb=sssP("EBITDA",p);
    tn25+=ns.v25;tn24+=ns.v24;tc+=cg.v25;tl+=lb.v25;to+=oc.v25;te+=eb.v25;
    var dc=ns.v25-ns.v24,pc=ns.v24?(dc/ns.v24):0;
    h+='<tr><td>P'+p+'</td><td>'+fmt(ns.v25)+'</td><td>'+fmt(ns.v24)+'</td>'+
      '<td class="'+(dc>=0?"pos":"neg")+'">'+fmt(dc)+'</td><td class="'+(pc>=0?"pos":"neg")+'">'+fmtChg(pc)+'</td>'+
      '<td>'+fmtPct(ns.v25?lb.v25/ns.v25:0)+'</td><td>'+fmtPct(ns.v25?cg.v25/ns.v25:0)+'</td>'+
      '<td>'+fmtPct(ns.v25?oc.v25/ns.v25:0)+'</td><td class="'+(eb.v25>=0?"pos":"neg")+'">'+fmtPct(ns.v25?eb.v25/ns.v25:0)+'</td></tr>';
  }
  var tdc=tn25-tn24,tpc=tn24?(tdc/tn24):0;
  h+='<tr class="total-row"><td>Total</td><td>'+fmt(tn25)+'</td><td>'+fmt(tn24)+'</td>'+
    '<td class="'+(tdc>=0?"pos":"neg")+'">'+fmt(tdc)+'</td><td class="'+(tpc>=0?"pos":"neg")+'">'+fmtChg(tpc)+'</td>'+
    '<td>'+fmtPct(tn25?tl/tn25:0)+'</td><td>'+fmtPct(tn25?tc/tn25:0)+'</td>'+
    '<td>'+fmtPct(tn25?to/tn25:0)+'</td><td class="'+(te>=0?"pos":"neg")+'">'+fmtPct(tn25?te/tn25:0)+'</td></tr></tbody>';
  t.innerHTML=h;
}

function renderSSSByStore(){
  var t=document.getElementById("sssByStoreTable");
  var h='<thead><tr><th>Store</th><th>SSS Periods</th><th>2025 Net Sales</th><th>2024 Net Sales</th><th>$ Change</th><th>% Change</th><th>Labor %</th><th>COGS %</th><th>Occup %</th><th>EBITDA %</th></tr></thead><tbody>';
  var gn25=0,gn24=0,gc=0,gl=0,go=0,ge=0;
  var entries=Object.entries(SSS_CONFIG);
  for(var e=0;e<entries.length;e++){
    var sid=entries[e][0],vps=entries[e][1];
    var sn25=0,sn24=0,sc=0,sl=0,so=0,se=0;
    for(var j=0;j<vps.length;j++){
      var p=vps[j];
      sn25+=gv(sid+"_2025","Net Sales",p);sn24+=gv(sid+"_2024","Net Sales",p);
      sc+=gv(sid+"_2025","COGS",p);sl+=gv(sid+"_2025","Labor",p);
      so+=gv(sid+"_2025","Occupancy",p);se+=gv(sid+"_2025","EBITDA",p);
    }
    gn25+=sn25;gn24+=sn24;gc+=sc;gl+=sl;go+=so;ge+=se;
    var dc=sn25-sn24,pc=sn24?(dc/sn24):0;
    var pLabel=vps.length===12?"P1-P12":"P"+vps[0]+"-P"+vps[vps.length-1];
    h+='<tr><td>'+sid+' - '+STORE_NAMES[sid]+'</td><td>'+pLabel+'</td><td>'+fmt(sn25)+'</td><td>'+fmt(sn24)+'</td>'+
      '<td class="'+(dc>=0?"pos":"neg")+'">'+fmt(dc)+'</td><td class="'+(pc>=0?"pos":"neg")+'">'+fmtChg(pc)+'</td>'+
      '<td>'+fmtPct(sn25?sl/sn25:0)+'</td><td>'+fmtPct(sn25?sc/sn25:0)+'</td>'+
      '<td>'+fmtPct(sn25?so/sn25:0)+'</td><td class="'+(se>=0?"pos":"neg")+'">'+fmtPct(sn25?se/sn25:0)+'</td></tr>';
  }
  var gdc=gn25-gn24,gpc=gn24?(gdc/gn24):0;
  h+='<tr class="total-row"><td>All Same Stores</td><td></td><td>'+fmt(gn25)+'</td><td>'+fmt(gn24)+'</td>'+
    '<td class="'+(gdc>=0?"pos":"neg")+'">'+fmt(gdc)+'</td><td class="'+(gpc>=0?"pos":"neg")+'">'+fmtChg(gpc)+'</td>'+
    '<td>'+fmtPct(gn25?gl/gn25:0)+'</td><td>'+fmtPct(gn25?gc/gn25:0)+'</td>'+
    '<td>'+fmtPct(gn25?go/gn25:0)+'</td><td class="'+(ge>=0?"pos":"neg")+'">'+fmtPct(gn25?ge/gn25:0)+'</td></tr></tbody>';
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
  var id=activeStore,nm=STORE_NAMES[id],isSS=SSS_CONFIG.hasOwnProperty(id),vps=SSS_CONFIG[id]||[];
  var h='<thead><tr><th>'+id+' - '+nm+'</th>';
  for(var i=0;i<PERIODS.length;i++)h+='<th>P'+PERIODS[i]+'</th>';
  h+='<th>Total</th></tr></thead><tbody>';

  // Net Sales 2025
  var tot=0;
  h+='<tr><td><strong>Net Sales 2025</strong></td>';
  for(var i=0;i<PERIODS.length;i++){var v=gv(id+"_2025","Net Sales",PERIODS[i]);tot+=v;h+='<td>'+(v?fmt(v):'<span class="na-val">-</span>')+'</td>';}
  h+='<td><strong>'+fmt(tot)+'</strong></td></tr>';

  // Net Sales 2024
  if(isSS){
    var tot24=0;
    h+='<tr><td>Net Sales 2024</td>';
    for(var i=0;i<PERIODS.length;i++){var v=gv(id+"_2024","Net Sales",PERIODS[i]);tot24+=v;h+='<td>'+(v?fmt(v):'<span class="na-val">-</span>')+'</td>';}
    h+='<td><strong>'+fmt(tot24)+'</strong></td></tr>';
    h+='<tr><td>SSS % Change</td>';
    var st25=0,st24=0;
    for(var i=0;i<PERIODS.length;i++){
      var p=PERIODS[i];
      if(vps.includes(p)){var v25=gv(id+"_2025","Net Sales",p),v24=gv(id+"_2024","Net Sales",p);st25+=v25;st24+=v24;var c=v24?(v25-v24)/v24:0;h+='<td class="'+(c>=0?"pos":"neg")+'">'+fmtChg(c)+'</td>';}
      else h+='<td class="na-val">N/A</td>';
    }
    var tc=st24?(st25-st24)/st24:0;
    h+='<td class="'+(tc>=0?"pos":"neg")+'"><strong>'+fmtChg(tc)+'</strong></td></tr>';
  } else {
    h+='<tr><td>Net Sales 2024</td>';for(var i=0;i<12;i++)h+='<td class="na-val">N/A</td>';h+='<td class="na-val">N/A</td></tr>';
    h+='<tr><td>SSS % Change</td>';for(var i=0;i<12;i++)h+='<td class="na-val">N/A</td>';h+='<td class="na-val">N/A</td></tr>';
  }

  h+='<tr class="spacer-row"><td colspan="14"></td></tr>';

  // COGS %
  var tm,tns;
  var metricList=[["COGS","COGS %"],["Labor","Labor %"],["Occupancy","Occupancy %"]];
  for(var m=0;m<metricList.length;m++){
    tm=0;tns=0;
    h+='<tr><td>'+metricList[m][1]+'</td>';
    for(var i=0;i<PERIODS.length;i++){
      var ns=gv(id+"_2025","Net Sales",PERIODS[i]),mv=gv(id+"_2025",metricList[m][0],PERIODS[i]);tm+=mv;tns+=ns;
      h+='<td>'+(ns?fmtPct(mv/ns):'<span class="na-val">-</span>')+'</td>';
    }
    h+='<td><strong>'+(tns?fmtPct(tm/tns):"-")+'</strong></td></tr>';
  }

  // EBITDA %
  var tebd=0,tens=0;
  h+='<tr><td>EBITDA %</td>';
  for(var i=0;i<PERIODS.length;i++){
    var ns=gv(id+"_2025","Net Sales",PERIODS[i]),ev=gv(id+"_2025","EBITDA",PERIODS[i]);tebd+=ev;tens+=ns;
    var pv=ns?ev/ns:null;
    h+='<td class="'+(pv!==null?(pv>=0?"pos":"neg"):"")+'">'+(pv!==null?fmtPct(pv):'<span class="na-val">-</span>')+'</td>';
  }
  h+='<td class="'+(tebd>=0?"pos":"neg")+'"><strong>'+(tens?fmtPct(tebd/tens):"-")+'</strong></td></tr>';

  // EBITDA $
  var tebd2=0;
  h+='<tr><td>EBITDA $</td>';
  for(var i=0;i<PERIODS.length;i++){var ev=gv(id+"_2025","EBITDA",PERIODS[i]);tebd2+=ev;h+='<td class="'+(ev>=0?"pos":"neg")+'">'+fmt(ev)+'</td>';}
  h+='<td class="'+(tebd2>=0?"pos":"neg")+'"><strong>'+fmt(tebd2)+'</strong></td></tr></tbody>';
  t.innerHTML=h;
}

function renderNetSalesTable(){
  var t=document.getElementById("netSalesTable");
  var h='<thead><tr><th>Store</th>';
  for(var i=0;i<PERIODS.length;i++)h+='<th>P'+PERIODS[i]+'</th>';
  h+='<th>Total</th></tr></thead><tbody>';
  var gt=[];for(var i=0;i<12;i++)gt.push(0);
  var grand=0;
  for(var s=0;s<STORE_IDS.length;s++){
    var id=STORE_IDS[s],rt=0;
    h+='<tr><td>'+id+' - '+STORE_NAMES[id]+'</td>';
    for(var i=0;i<12;i++){var v=gv(id+"_2025","Net Sales",PERIODS[i]);rt+=v;gt[i]+=v;h+='<td>'+(v?fmt(v):'<span class="na-val">-</span>')+'</td>';}
    grand+=rt;h+='<td><strong>'+fmt(rt)+'</strong></td></tr>';
  }
  h+='<tr class="total-row"><td>All Stores</td>';
  for(var i=0;i<12;i++)h+='<td>'+fmt(gt[i])+'</td>';
  h+='<td><strong>'+fmt(grand)+'</strong></td></tr></tbody>';
  t.innerHTML=h;
}

function renderAll(){
  renderKPIs();renderSSSChart();
  renderPctChart("laborChart","Labor");renderPctChart("cogsChart","COGS");
  renderPctChart("occChart","Occupancy");renderPctChart("ebitdaChart","EBITDA");
  renderSSSTable();renderSSSByStore();renderStoreTabs();renderStoreTable();renderNetSalesTable();
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
