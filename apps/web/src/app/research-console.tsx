"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  createRun,
  prepareSubmission,
  type ResearchRun,
  readRun,
  type Submission,
} from "../lib/research";

/** Browser-only state exposes the real local lifecycle without implying a backtest ran. */
export default function ResearchConsole() {
  const [idea, setIdea] = useState("");
  const [cost, setCost] = useState("5.00");
  const [duration, setDuration] = useState("3600");
  const [experiments, setExperiments] = useState("12");
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const previous = useRef<Submission | null>(null);
  const submitting = useRef(false);

  // Sequential reads and cleanup avoid overlapping polls or stale updates after a new run.
  useEffect(() => {
    if (!runId || refresh === 0) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    /** Stop at the implemented local stage or a bounded, recoverable read failure. */
    async function poll() {
      try {
        const next = await readRun(runId as string);
        if (!active) return;
        setRun(next);
        setError("");
        attempts += 1;
        if (next.status !== "BRIEF_NORMALIZED" && attempts < 30)
          timer = setTimeout(poll, 700);
        else if (next.status !== "BRIEF_NORMALIZED")
          setError(
            "Normalization is taking longer than expected. Refresh this run to check again.",
          );
      } catch (failure) {
        if (active)
          setError(
            failure instanceof Error
              ? failure.message
              : "Unable to read this run.",
          );
      }
    }
    void poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [runId, refresh]);

  /** Preserve same-key retries, but give changed inputs a fresh identity. */
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    if (idea.trim().length < 3) {
      setError("Write an investment idea with at least 3 characters.");
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError("");
    setRunId(null);
    setRun(null);
    try {
      const submission = prepareSubmission(
        {
          idea: idea.trim(),
          max_llm_cost_usd: Number(cost).toFixed(2),
          max_wall_time_s: Number(duration),
          max_experiments: Number(experiments),
        },
        previous.current,
      );
      previous.current = submission;
      const receipt = await createRun(submission);
      previous.current = null;
      setRun(null);
      setRunId(receipt.run_id);
      setRefresh((value) => value + 1);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Unable to create this run.",
      );
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const complete = run?.status === "BRIEF_NORMALIZED";
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="FactorForge home">
          <span className="brand-mark">
            F<span>ƒ</span>
          </span>
          <span>
            FactorForge<small>RESEARCH WORKSPACE</small>
          </span>
        </a>
        <div className="workspace-label">
          WORKSPACE <span>01</span>
        </div>
        <div className="nav-item">
          <span>◈</span> Research console <span className="nav-dot" />
        </div>
        <div className="sidebar-note">
          <span className="eyebrow">THE RESEARCH LOOP</span>
          <p>
            Start with a question.
            <br />
            Make the assumptions visible.
            <br />
            Follow the evidence.
          </p>
          <div className="loop-line">
            <span /> <span /> <span /> <span />
          </div>
        </div>
        <div className="local-card">
          <span className="local-dot" />
          <strong>Local workspace</strong>
          <p>
            In-memory runs. Restarting the API clears this session’s records.
          </p>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span>{" "}
            <strong>Research console</strong>
          </span>
          <span className="stage-tag">EARLY RESEARCH PREVIEW</span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">FROM AN IDEA TO A RESEARCH BRIEF</p>
              <h1>
                Every factor starts
                <br />
                with a good question.
              </h1>
              <p className="intro">
                Capture an investment idea, set its boundaries, and inspect
                <br className="desktop-break" /> the first step of a
                reproducible research process.
              </p>
            </div>
            <div className="folio">
              RESEARCH
              <br />
              <strong>01 / 02</strong>
              <span>Idea → Brief</span>
            </div>
          </div>
          <div className="notice">
            <span className="notice-icon">i</span>
            <p>
              <strong>A small, visible first step.</strong> This local preview
              normalizes your idea into a brief. Literature retrieval, model
              calls and backtests are not running yet.
            </p>
          </div>
          <div className="work-grid">
            <section className="panel compose">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">01 / DEFINE</span>
                  <h2>Your research idea</h2>
                </div>
                <span className="panel-symbol">↗</span>
              </div>
              <form onSubmit={submit}>
                <label htmlFor="idea">
                  What would you like to investigate?
                </label>
                <textarea
                  id="idea"
                  value={idea}
                  onChange={(event) => setIdea(event.target.value)}
                  required
                  minLength={3}
                  maxLength={4000}
                  placeholder="Does medium-term momentum persist after controlling for sector exposure?"
                  disabled={busy}
                />
                <div className="input-footer">
                  <span>A question, a signal, or an assumption to test.</span>
                  <span>{idea.length} / 4,000</span>
                </div>
                <button
                  className="example"
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    setIdea(
                      "Test whether medium-term momentum persists after controlling for sector exposure.",
                    )
                  }
                >
                  ↳ Try a momentum research idea
                </button>
                <div className="limits-title">
                  <h3>Research limits</h3>
                  <span>Saved with your brief</span>
                </div>
                <div className="limits">
                  <div>
                    <label htmlFor="cost">LLM cost cap</label>
                    <div className="number-wrap">
                      <span>$</span>
                      <input
                        id="cost"
                        type="number"
                        min="0.01"
                        max="100"
                        step="0.01"
                        required
                        value={cost}
                        onChange={(event) => setCost(event.target.value)}
                        disabled={busy}
                      />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="duration">
                      Time limit <small>(seconds)</small>
                    </label>
                    <input
                      id="duration"
                      type="number"
                      min="1"
                      max="86400"
                      step="1"
                      required
                      value={duration}
                      onChange={(event) => setDuration(event.target.value)}
                      disabled={busy}
                    />
                  </div>
                  <div>
                    <label htmlFor="experiments">Experiment cap</label>
                    <input
                      id="experiments"
                      type="number"
                      min="1"
                      max="100"
                      step="1"
                      required
                      value={experiments}
                      onChange={(event) => setExperiments(event.target.value)}
                      disabled={busy}
                    />
                  </div>
                </div>
                <p className="limit-note">
                  Limits are recorded for future research stages. This step
                  makes no model calls and incurs no LLM cost.
                </p>
                <button type="submit" className="primary" disabled={busy}>
                  <span>
                    {busy ? "Creating your brief…" : "Create research brief"}
                  </span>
                  <span aria-hidden="true">→</span>
                </button>
                <p className="submit-note">
                  Retrying an interrupted request preserves its request key.
                </p>
              </form>
            </section>
            <section
              className="panel progress"
              aria-live="polite"
              aria-busy={busy}
            >
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">02 / INSPECT</span>
                  <h2>Run activity</h2>
                </div>
                <span className={`state-badge ${runId ? "active" : ""}`}>
                  {complete
                    ? "Brief ready"
                    : runId
                      ? "Received"
                      : "Awaiting idea"}
                </span>
              </div>
              {error && (
                <div className="error" role="alert">
                  <strong>Something needs attention</strong>
                  <p>{error}</p>
                  {runId && (
                    <button
                      type="button"
                      onClick={() => {
                        setError("");
                        setRefresh((value) => value + 1);
                      }}
                    >
                      Refresh this run ↻
                    </button>
                  )}
                </div>
              )}
              {!runId ? (
                <div className="empty">
                  <div className="empty-art">
                    <span />
                    <span />
                    <span />
                    <i>⌁</i>
                  </div>
                  <h3>A clear record from the start.</h3>
                  <p>
                    Your run ID, state transitions and normalized brief will
                    appear here after submission.
                  </p>
                  <div className="empty-flow">
                    <span>Idea received</span>
                    <b>→</b>
                    <span>Brief normalized</span>
                  </div>
                </div>
              ) : (
                <div className="run-details">
                  <div className="run-id">
                    <span>RUN ID</span>
                    <code>{runId}</code>
                  </div>
                  <ol className="timeline">
                    <li className="done">
                      <span className="timeline-dot">✓</span>
                      <div>
                        <h3>Idea received</h3>
                        <p>A stable run ID has been assigned.</p>
                        <time>
                          {run?.events[0]?.created_at
                            ? new Date(
                                run.events[0].created_at,
                              ).toLocaleTimeString()
                            : "Accepted by the local API"}
                        </time>
                      </div>
                    </li>
                    <li className={complete ? "done" : "pending"}>
                      <span className="timeline-dot">
                        {complete ? "✓" : "2"}
                      </span>
                      <div>
                        <h3>Brief normalized</h3>
                        <p>
                          {complete
                            ? "Whitespace normalized; your original meaning retained."
                            : "Waiting for the deterministic normalization step."}
                        </p>
                        {complete && run.events[1] && (
                          <time>
                            {new Date(
                              run.events[1].created_at,
                            ).toLocaleTimeString()}
                          </time>
                        )}
                      </div>
                    </li>
                  </ol>
                  {complete && (
                    <div className="brief">
                      <span className="eyebrow">NORMALIZED BRIEF</span>
                      <p>{run.brief}</p>
                      <span className="brief-tag">
                        Deterministic · No LLM call
                      </span>
                    </div>
                  )}
                  <p className="run-footnote">
                    This is a research brief, not a strategy result. No factor
                    performance has been measured.
                  </p>
                </div>
              )}
              <div className="panel-footer">
                <span className="local-dot" /> Local mode{" "}
                <span>Deterministic first step</span>
              </div>
            </section>
          </div>
          <footer className="page-footer">
            <span>FactorForge / Research with reproducible evidence</span>
            <span>Research only. No live trading.</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
