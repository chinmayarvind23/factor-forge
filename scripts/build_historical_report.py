"""Render the measured historical study as a portable, dependency-free evidence page."""

import argparse
import html
import json
from pathlib import Path
from typing import Any

SCOPE = (
    "Retrospective fixed eight-stock universe; exploratory experiments, "
    "not published-factor reproduction"
)


def build(source: Path, output: Path) -> None:
    """Read saved results without changing metrics and escape data at the HTML boundary."""
    report: dict[str, Any] = json.loads(source.read_text(encoding="utf-8-sig"))
    experiments = report["experiments"]
    if not isinstance(experiments, list) or len(experiments) != report["total"]:
        raise ValueError("Experiment inventory does not match reported total")
    # Prevent report strings from closing the non-executable JSON script element.
    data = json.dumps(report, allow_nan=False).replace("<", "\\u003c")
    cards = [
        (f"{report['completed']} / {report['total']}", "Experiments completed"),
        (f"{report['source_rows']:,}", "Historical source rows"),
        (str(report["source_count"]), "Stocks in fixed universe"),
        (f"{report['runtime_seconds']:.2f}s", "Measured study runtime"),
    ]
    card_html = "".join(
        f'<div class="card"><strong>{html.escape(value)}</strong><span>{label}</span></div>'
        for value, label in cards
    )
    page = TEMPLATE.replace("__CARDS__", card_html)
    page = page.replace("__PERIOD__", html.escape(f"{report['start_date']} — {report['end_date']}"))
    page = page.replace("__SCOPE__", html.escape(SCOPE))
    page = page.replace("__DATA__", data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>FactorForge · Historical research evidence</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#0a101b;
color:#e9eef7}*{box-sizing:border-box}body{margin:0}
main{max-width:1240px;margin:auto;padding:40px 28px}
a{color:#79e4c2}header{display:flex;justify-content:space-between;gap:24px;align-items:center}
.brand{font-size:20px;font-weight:750;letter-spacing:-.6px}.tag,.eyebrow{font-size:11px;
letter-spacing:2px;text-transform:uppercase;color:#80d6bc}.tag{border:1px solid #31443f;
padding:8px 12px;border-radius:30px}h1{font-size:clamp(34px,5vw,62px);letter-spacing:-2px;
line-height:1.05;max-width:850px;margin:20px 0}p{line-height:1.6;color:#aab9cc}
.hero{padding:54px 0 22px}
.scope{border-left:3px solid #68d9b5;padding:10px 16px;background:#101e27;max-width:960px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0 36px}
.card,.panel{background:#111c2b;border:1px solid #26364a;border-radius:13px;padding:23px}
.card strong{display:block;font-size:31px;letter-spacing:-1px}.card span{display:block;
font-size:12px;color:#9cacbf;margin-top:8px}.panel{margin:20px 0}.panel-head{display:flex;
justify-content:space-between;align-items:center;gap:18px}h2{font-size:21px;margin:0 0 8px}
select{background:#0b1422;color:#e9eef7;border:1px solid #40536c;border-radius:7px;padding:10px}
label{font-size:13px;color:#b8c7d8}.chart{width:100%;overflow-x:auto}svg{width:100%;min-width:1000px;
height:auto}svg text{font-family:inherit;fill:#adbed1;font-size:12px}.table-wrap{overflow:auto}
table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th,td{text-align:right;
padding:13px 12px;border-bottom:1px solid #26364a}th{color:#92a8bf;font-size:11px;
text-transform:uppercase;
letter-spacing:.6px}th:first-child,td:first-child{text-align:left}td:first-child{color:#e4edf8}
.small{font-size:12px}.hash{overflow-wrap:anywhere;font-family:ui-monospace,monospace;color:#8da8c1}
footer{border-top:1px solid #273548;padding:20px 0;color:#92a6bd;font-size:12px}
@media(max-width:700px){main{padding:24px 16px}.cards{grid-template-columns:repeat(2,1fr)}
.card{padding:17px}.card strong{font-size:25px}.panel{padding:16px}.panel-head{align-items:start;
flex-direction:column}.hero{padding-top:36px}.tag{font-size:9px}}
</style></head><body><main>
<header><div class="brand">FactorForge<span style="color:#70dfbd"> /</span></div>
<span class="tag">Measured research evidence</span></header>
<section class="hero"><div class="eyebrow">Historical strategy laboratory</div>
<h1>From market history<br>to replayable experiments.</h1>
<p>__PERIOD__ · Daily equity data · Transaction-cost sensitivity · Statistical diagnostics</p>
<p class="scope">__SCOPE__</p></section>
<section class="cards" aria-label="Study measurements">__CARDS__</section>
<section class="panel"><div class="panel-head"><div><h2>Signal comparison</h2>
<p class="small">Annualized Sharpe ratios from saved experiment results. Select a cost
assumption.</p>
</div>
<label>Trading cost <select id="cost" aria-label="Trading cost in basis points"
></select></label></div>
<div id="chart" class="chart"></div></section>
<section class="panel"><h2>Experiment ledger</h2>
<p class="small">All experiments at the selected cost, including their recorded
execution status.</p>
<div class="table-wrap"><table><thead><tr><th>Signal</th><th>Cost (bps)</th><th>Status</th>
<th>Returns</th><th>Total return</th><th>Sharpe</th><th>Max drawdown</th><th>HAC t-stat</th>
<th>Folds</th></tr></thead><tbody id="rows"></tbody></table></div></section>
<section class="panel"><h2>Evidence and interpretation</h2>
<p>This study evaluates price-based signals on a fixed universe of eight surviving stocks.
Retrospective adjusted prices do not establish point-in-time data availability or historical
index membership. Experiment completion measures execution; it is separate from economic
performance, autonomous literature research, and replication of published factors.</p>
<p id="scope" class="small"></p><p id="spans" class="small"></p>
<p class="small">Dataset identity</p><p id="hash" class="hash"></p></section>
<footer>FactorForge · Results rendered directly from a saved study report · Research demonstration
</footer>
</main><script type="application/json" id="report">__DATA__</script>
<script>
// Use textContent for report fields so external strings never become executable markup.
const report=JSON.parse(document.getElementById('report').textContent);
const select=document.getElementById('cost');
const costs=[...new Set(report.experiments.map(row=>row.cost_bps))]
.sort((a,b)=>Number(a)-Number(b));
for(const cost of costs){const option=document.createElement('option');option.value=cost;
option.textContent=cost+' bps';select.append(option);}
document.getElementById('scope').textContent='Recorded scope: '+report.scope;
document.getElementById('spans').textContent='Recorded study spans: '+report.span_count;
document.getElementById('hash').textContent=report.dataset_sha256;
const num=(v,d=2)=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toFixed(d);
const pct=v=>v===null||v===undefined?'—':num(Number(v)*100)+'%';
// SVG elements are built with namespace-aware DOM calls; no report HTML is interpolated.
function node(tag,attrs,text){const item=document.createElementNS('http://www.w3.org/2000/svg',tag);
for(const [key,value] of Object.entries(attrs))item.setAttribute(key,String(value));
if(text!==undefined)item.textContent=text;return item;}
// Keep the chart and ledger on the same selected subset without filtering outcomes by return.
function render(){const rows=report.experiments.filter(row=>String(row.cost_bps)===select.value);
const body=document.getElementById('rows');body.replaceChildren();
for(const row of rows){const tr=document.createElement('tr');const folds=Array.isArray(row.folds)?
row.folds.length:row.folds;for(const value of [row.signal,row.cost_bps,row.status,row.n,
pct(row.total_return),num(row.annualized_sharpe),pct(row.max_drawdown),num(row.hac_t),folds]){
const td=document.createElement('td');td.textContent=value??'—';tr.append(td);}body.append(tr);}
const height=Math.max(150,rows.length*33+50);const svg=node('svg',{viewBox:`0 0 1100 ${height}`,
role:'img','aria-label':'Annualized Sharpe ratio by signal at the selected trading cost'});
const extent=Math.max(1,...rows.map(row=>Math.abs(Number(row.annualized_sharpe)||0)));
const center=650,scale=350/extent;
svg.append(node('line',{x1:center,y1:15,x2:center,y2:height-25,stroke:'#4a6078'}));
rows.forEach((row,index)=>{const y=index*33+30;svg.append(node('text',{x:8,y:y+5},row.signal));
if(row.annualized_sharpe!==null&&row.annualized_sharpe!==undefined&&
Number.isFinite(Number(row.annualized_sharpe))){const value=Number(row.annualized_sharpe);
const width=Math.abs(value)*scale;svg.append(node('rect',{x:value<0?center-width:center,y:y-10,
width:Math.max(width,1),height:19,rx:3,fill:value<0?'#809bc4':'#70dfbd'}));
svg.append(node('text',{x:1025,y:y+5},num(value)));}});
document.getElementById('chart').replaceChildren(svg);}
select.addEventListener('change',render);render();
</script></body></html>"""


def main() -> None:
    """Require explicit input and output locations to keep evidence publication reviewable."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.input, args.output)


if __name__ == "__main__":
    main()
