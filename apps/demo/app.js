"use strict";
let selection = 0;

/** Use text nodes for every evidence value so recorded content cannot become HTML. */
function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

/** Display financial amounts without changing the exact values in downloadable evidence. */
function money(value) {
  return Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" });
}

/** Draw only recorded NAV observations; the curve performs no inferred backtest. */
function drawChart(observations) {
  const chart = document.querySelector("#chart");
  chart.replaceChildren();
  const values = observations.map((row) => Number(row.snapshot.nav_usd));
  if (!values.length) { chart.style.display = "none"; return; }
  chart.style.display = "block";
  const minimum = Math.min(...values), maximum = Math.max(...values);
  const range = Math.max(maximum - minimum, 1);
  const points = values.map((value, i) => `${35 + i * 630 / Math.max(values.length - 1, 1)},${160 - (value - minimum) * 130 / range}`);
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", points.join(" "));
  line.setAttribute("fill", "none"); line.setAttribute("stroke", "#267050"); line.setAttribute("stroke-width", "3");
  chart.append(line);
  for (const [value, y] of [[maximum, 20], [minimum, 190]]) {
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", "35"); label.setAttribute("y", String(y));
    label.setAttribute("fill", "#68766c"); label.setAttribute("font-size", "12");
    label.textContent = money(value); chart.append(label);
  }
}

/** Verify every displayed evidence record against its exact published content identity. */
async function readEvidence(ref) {
  const response = await fetch(`objects/sha256/${ref.sha256.slice(0, 2)}/${ref.sha256}`);
  if (!response.ok) throw new Error("Execution evidence is unavailable.");
  const bytes = await response.arrayBuffer();
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
  if (digest !== ref.sha256 || bytes.byteLength !== ref.size_bytes) throw new Error("Execution evidence did not match its recorded identity.");
  return JSON.parse(new TextDecoder().decode(bytes));
}

/** Keep execution and validation identities bound before rendering the selected case. */
async function selectCase(item) {
  const current = ++selection;
  document.querySelectorAll("#cases button").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.id === item.id)));
  const result = await readEvidence(item.root);
  const validation = item.validation ? await readEvidence(item.validation) : null;
  if (validation && validation.request.result.sha256 !== item.root.sha256) throw new Error("Validation evidence did not match this execution.");
  const digest = item.root.sha256;
  if (current !== selection) return;
  document.querySelector("#title").textContent = item.title;
  document.querySelector("#status").textContent = result.status === "completed" ? "Completed" : "Guard applied";
  const metrics = document.querySelector("#metrics"); metrics.replaceChildren();
  const validationPanel = document.querySelector("#validation-panel");
  validationPanel.hidden = !validation;
  if (validation) {
    document.querySelector("#validation-summary").textContent = `${validation.periods.length} executed return intervals feed ${validation.folds.length} contiguous test blocks. Each block retains walk-forward and purged partitions, an explicit embargo, and a HAC mean diagnostic. This assesses a fixed strategy; it does not fit parameters or establish investment performance.`;
    document.querySelector("#validation-download").href = `objects/sha256/${item.validation.sha256.slice(0, 2)}/${item.validation.sha256}`;
  }
  for (const [label, value] of [["Initial capital", money(result.request.initial_cash_usd)], ["Terminal NAV", result.performance ? money(result.performance.terminal_nav_usd) : "No trades"], ["Verified artifacts at build", String(item.objects)]]) {
    const card = element("div", "", "metric"); card.append(element("span", label), element("strong", value)); metrics.append(card);
  }
  drawChart(result.observations);
  document.querySelector("#chart-note").textContent = result.observations.length ? `${result.observations.length} recorded observations · All values in USD` : "The precision check stopped execution before placing any trades.";
  document.querySelector("#decision").textContent = item.id === "hybrid" ? "The hybrid combines two original hypotheses: 75% score and 25% quality. Both point-in-time signals contribute to each security’s score. The blend runs through the same borrowing, funding, transaction-cost and liquidation rules, and retains both parent strategies in its evidence." : result.status === "completed" ? "The declared strategy completed with point-in-time signals, recorded borrowing permission, commissions, slippage, and terminal liquidation. The next research step is evaluation on a substantive historical dataset." : `The engine preserved the exact funding contract and recorded ${result.failure_code}. The selected capital would require quantities outside the supported exact-share precision. No rounding or silent correction was applied.`;
  const fills = document.querySelector("#fills"); fills.replaceChildren();
  for (const fill of result.fills) {
    const row = element("tr", "");
    for (const value of [fill.security_id, fill.signed_quantity, fill.quote.price_usd, fill.executed_at]) row.append(element("td", String(value)));
    fills.append(row);
  }
  if (!result.fills.length) { const row = element("tr", ""); const cell = element("td", "No trades dispatched."); cell.colSpan = 4; row.append(cell); fills.append(row); }
  document.querySelector("#integrity").textContent = "Result SHA-256 and byte count verified in your browser. Linked artifact closure verified during the Python build.";
  document.querySelector("#download").href = `objects/sha256/${digest.slice(0, 2)}/${digest}`;
  document.querySelector("#raw").textContent = JSON.stringify(result, null, 2);
}

/** Surface missing evidence explicitly rather than replacing it with simulated success. */
function showError(error) {
  document.querySelector("#status").textContent = "";
  document.querySelector("#validation-panel").hidden = true;
  document.querySelector("#metrics").replaceChildren();
  document.querySelector("#chart").replaceChildren();
  document.querySelector("#fills").replaceChildren();
  document.querySelector("#raw").textContent = "";
  document.querySelector("#decision").textContent = "";
  document.querySelector("#download").removeAttribute("href");
  document.querySelector("#title").textContent = "Evidence could not be loaded";
  document.querySelector("#integrity").textContent = error.message;
}

/** Load the public allowlisted bundle; this static app never invokes a model or backend. */
async function initialize() {
  const response = await fetch("evidence.json");
  if (!response.ok) throw new Error("The evidence index is unavailable.");
  const manifest = await response.json();
  for (const item of manifest.cases) {
    const button = element("button", item.title); button.dataset.id = item.id;
    button.addEventListener("click", () => selectCase(item).catch(showError));
    document.querySelector("#cases").append(button);
  }
  await selectCase(manifest.cases[0]);
}

initialize().catch(showError);
