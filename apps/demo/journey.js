/* Replay retained evidence without simulating inference, latency, or an agent correction. */
const $ = (id) => document.getElementById(id);
const names = ["Investment idea", "Source selection", "Model extraction", "Strategy", "Backtest attempt", "Research decision", "Reference comparison"];
let data, stage = 0;
// Render evidence as text so retained source content cannot inject markup.
function text(tag, value, cls) {
  const node = document.createElement(tag); node.textContent = value;
  if (cls) node.className = cls; return node;
}
// Keep each finding in a consistent labeled card.
function card(title, value, cls = "") {
  const node = document.createElement("section"); node.className = "card " + cls;
  node.append(text("h3", title), text("p", value)); return node;
}
// Each step reads the saved result; navigation never dispatches research.
function show() {
  $("steps").replaceChildren();
  names.forEach((name, i) => { const b = document.createElement("button"); b.append(text("small", String(i + 1).padStart(2, "0")), text("span", name)); b.setAttribute("aria-current", i === stage ? "step" : "false"); b.onclick = () => { stage = i; show(); }; $("steps").append(b); });
  $("stage-label").textContent = `Step ${stage + 1} of ${names.length}`;
  $("content").replaceChildren(); $("back").disabled = stage === 0;
  $("next").disabled = stage === 6; $("next").textContent = stage === 6 ? "Walkthrough complete" : `${names[stage + 1]} →`;
  const grid = document.createElement("div"); grid.className = "cards"; $("content").append(grid);
  const captions = ["Replay one captured request; no new model call is started.", "Selection uses the run's reviewed source catalog, not a live web search.", "The recorded model response is shown unchanged.", "A valid strategy contract can still contain an incorrect interpretation.", "The deterministic gate stops the attempt before committing any fills.", "Retain the outcome and its lineage; do not promote the candidate.", "Separate authored reference, shown for comparison—not an automatic correction."];
  $("caption").textContent = captions[stage];
  if (stage === 0) {
    $("title").textContent = "Start with a research question.";
    $("intro").textContent = "This walkthrough follows one actual retained local-model run from September 11, 2026.";
    const form = card("Recorded investment idea", "", "full");
    const label = text("label", "Research idea"); label.htmlFor = "idea";
    const input = document.createElement("input"); input.id = "idea"; input.placeholder = "Open the recorded research question";
    $("next").disabled = true;
    input.oninput = () => { $("next").disabled = input.value !== data.idea; };
    const load = text("button", "Use recorded idea"); load.onclick = () => { input.value = data.idea; $("next").disabled = false; };
    form.append(label, input, load); grid.append(form);
    grid.append(card("Execution budget", `${data.budget.max_experiments} experiment · ${data.budget.max_wall_time_s / 60} minute ceiling`), card("Example data", "An authored two-security integration fixture. This is a software workflow demonstration."));
  } else if (stage === 1) {
    $("title").textContent = "Retrieve a source with explicit rules.";
    $("intro").textContent = data.document.title + " · reviewed catalog · source page 1";
    const source = card("Selected source passage", "", "full");
    source.append(text("p", data.document.text.split("\n\n")[1], "source")); grid.append(source);
    grid.append(card("What the source specifies", "Long the high-score bucket. Short the low-score bucket."), card("Source identity", data.document.source_sha256, "detail"));
  } else if (stage === 2) {
    $("title").textContent = "Inspect what the model extracted.";
    $("intro").textContent = `${data.provider.model} · ${data.provider.prompt_tokens} input tokens · ${data.provider.output_tokens} output tokens · recorded inference`;
    const fields = {formula: data.observation.formula, direction: data.observation.long_short_direction, weighting: data.observation.weighting, holding_months: data.observation.holding_months, source_pages: data.observation.source_pages};
    const extracted = card("Recorded structured output", ""); extracted.append(text("pre", JSON.stringify(fields, null, 2), "code")); grid.append(extracted);
    grid.append(card("Compare with the source", "The source says long high scores. The model extracted long low scores. That response stays in the record.", "amber"));
  } else if (stage === 3) {
    $("title").textContent = "Compile an executable strategy.";
    $("intro").textContent = "Typed source choices are combined with the reviewed data, calendar and execution policy.";
    grid.append(card("Signal", data.strategy.formula, "green"), card("Recorded direction", data.strategy.direction));
    grid.append(card("Timing", "Form at month-end close; trade at the next session open."), card("Trading costs", `${data.strategy.costs.commission_bps} bps commission + ${data.strategy.costs.slippage_bps} bps slippage`));
    grid.append(card("Execution requirement", "A short position needs a known, active borrowing grant before any order can be committed.", "full"));
  } else if (stage === 4) {
    $("title").textContent = "The execution guard stops the attempt.";
    $("intro").textContent = "The proposed short position has no valid borrowing grant in the admitted source.";
    const trades = card("Trades committed", "", "green"); trades.append(text("div", String(data.execution.fills), "big")); grid.append(trades);
    const capital = card("Initial capital preserved", "", "green"); capital.append(text("div", `$${Number(data.execution.initial_cash).toLocaleString("en-US", {minimumFractionDigits:2})}`, "big")); grid.append(capital);
    grid.append(card("Recorded execution outcome", data.execution.reason, "full amber"));
    grid.append(card("Why this matters", "An executable model proposal does not bypass the account's trading permissions.", "full"));
  } else if (stage === 5) {
    $("title").textContent = "Explain the outcome. Keep the evidence.";
    $("intro").textContent = "The run ends with an execution-stopped report and inspectable artifacts.";
    grid.append(card("Decision", "Stop this candidate. No full-sample performance or factor promotion is claimed.", "full green"));
    grid.append(card("Retained lineage", `${data.evidence.verified_objects} reachable artifacts verified before building this replay.`));
    grid.append(card("What can be reviewed", "Selected source, model response, compiled strategy, attempted backtest and the exact stop reason."));
    grid.append(card("Backtest artifact SHA-256", data.evidence.monthly.sha256, "full detail"));
  } else {
    $("title").textContent = "Compare with the authored reference.";
    $("intro").textContent = data.reference.scope;
    grid.append(card("Recorded agent candidate", "Long low / short high → stopped before any trades.", "amber"));
    grid.append(card("Source-aligned reference", `Long high / short low → ${data.reference.fills} fills; $${Number(data.reference.initial_cash).toLocaleString("en-US")} → $${Number(data.reference.terminal_nav).toLocaleString("en-US",{minimumFractionDigits:2})}.`, "green"));
    grid.append(card("What this demo establishes", "The source, model proposal, execution constraints and final evidence can be inspected as one research journey. Reference figures describe synthetic accounting, not investment performance.", "full"));
  }
}
$("back").onclick = () => { if (stage) { stage--; show(); } };
$("next").onclick = () => { if (stage < 6) { stage++; show(); } };
fetch("journey.json").then(async response => {
  if (!response.ok) throw new Error("Evidence unavailable");
  data = await response.json();
  if (data.schema_version !== "research-journey-v1") throw new Error("Unknown replay format");
  $("scope").textContent = data.scope;
  $("integrity").textContent = "Source artifacts verified at build";
  $("run").textContent = `RUN ${data.run_id.slice(0, 8)}`; show();
}).catch(() => { $("scope").textContent = "Unable to load the retained research journey."; $("next").disabled = true; });
