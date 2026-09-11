/** Runtime checks keep API failures from becoming successful-looking research results. */
export type RunStatus = "RECEIVED" | "BRIEF_NORMALIZED";
export interface ResearchRequest {
  idea: string;
  max_llm_cost_usd: string;
  max_wall_time_s: number;
  max_experiments: number;
}
export interface RunReceipt {
  run_id: string;
  status: "RECEIVED";
}
export interface ResearchRun extends ResearchRequest {
  run_id: string;
  status: RunStatus;
  brief: string | null;
  events: { status: RunStatus; created_at: string }[];
  created_at: string;
  mode: "local";
}
export interface Submission {
  payload: ResearchRequest;
  key: string;
}
type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
const endpoint = "http://127.0.0.1:8001/api/v1/research-runs";

/** Errors describe recovery without rendering raw server bodies or internal traces. */
export class ResearchError extends Error {
  /** Carry recovery intent independently from server error text. */
  constructor(
    message: string,
    public readonly retryable: boolean,
  ) {
    super(message);
    this.name = "ResearchError";
  }
}

/** Stable serialized input lets an uncertain POST retry preserve its original identity. */
export function prepareSubmission(
  payload: ResearchRequest,
  previous: Submission | null,
  createKey: () => string = () => crypto.randomUUID(),
): Submission {
  if (previous && JSON.stringify(previous.payload) === JSON.stringify(payload))
    return previous;
  return { payload: { ...payload }, key: createKey() };
}

/** Object narrowing avoids trusting compile-time types at the HTTP boundary. */
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Only lifecycle states implemented by this console are accepted. */
function status(value: unknown): value is RunStatus {
  return value === "RECEIVED" || value === "BRIEF_NORMALIZED";
}

/** Validate identifiers before using them in a route or displaying a receipt. */
function runId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      value,
    )
  );
}

/** Every request is bounded; retrying a failed read must never submit another run. */
async function request(
  url: string,
  init: RequestInit,
  fetcher: Fetcher,
  expectedStatus = 200,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetcher(url, {
      ...init,
      signal: AbortSignal.timeout(10000),
      cache: "no-store",
    });
  } catch {
    throw new ResearchError(
      "The local API did not respond. Check that it is running, then retry.",
      true,
    );
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      403: "The API denied this request. Use the local console with local mode enabled.",
      404: "This run is no longer available. Local runs are cleared when the API restarts.",
      409: "This request key already belongs to different input. Change the idea to start a new request.",
      413: "This idea exceeds the request size limit. Shorten the text, then submit again.",
      422: "The API rejected these inputs. Review the idea and research limits.",
      429: "The API is busy. Wait a moment, then retry.",
    };
    throw new ResearchError(
      messages[response.status] ??
        "The API could not complete this request. Try again.",
      response.status >= 500 || response.status === 429,
    );
  }
  if (response.status !== expectedStatus) {
    throw new ResearchError(
      "The API returned an unexpected response status.",
      true,
    );
  }
  try {
    return await response.json();
  } catch {
    throw new ResearchError("The API returned an unreadable response.", true);
  }
}

/** Idempotency survives transport failure, so a retry cannot silently duplicate a run. */
export async function createRun(
  submission: Submission,
  fetcher: Fetcher = fetch,
): Promise<RunReceipt> {
  const value = await request(
    endpoint,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": submission.key,
      },
      body: JSON.stringify(submission.payload),
    },
    fetcher,
    202,
  );
  if (!record(value) || !runId(value.run_id) || value.status !== "RECEIVED") {
    throw new ResearchError("The API returned an invalid run receipt.", true);
  }
  return { run_id: value.run_id, status: value.status };
}

/** Reject partial or cross-run responses instead of inventing progress. */
export async function readRun(
  id: string,
  fetcher: Fetcher = fetch,
): Promise<ResearchRun> {
  if (!runId(id))
    throw new ResearchError("This run identifier is invalid.", false);
  const value = await request(`${endpoint}/${id}`, { method: "GET" }, fetcher);
  if (
    !record(value) ||
    value.run_id !== id ||
    !status(value.status) ||
    value.mode !== "local" ||
    typeof value.idea !== "string" ||
    !(value.brief === null || typeof value.brief === "string") ||
    typeof value.created_at !== "string" ||
    !Number.isFinite(Date.parse(value.created_at)) ||
    typeof value.max_llm_cost_usd !== "string" ||
    !Number.isFinite(Number(value.max_llm_cost_usd)) ||
    typeof value.max_wall_time_s !== "number" ||
    typeof value.max_experiments !== "number" ||
    !Array.isArray(value.events) ||
    !value.events.every(
      (event: unknown) =>
        record(event) &&
        status(event.status) &&
        typeof event.created_at === "string" &&
        Number.isFinite(Date.parse(event.created_at)),
    )
  ) {
    throw new ResearchError(
      "The API returned an invalid run state. Refresh the run to retry.",
      true,
    );
  }
  if (
    value.events.length !== (value.status === "RECEIVED" ? 1 : 2) ||
    value.events[0]?.status !== "RECEIVED" ||
    (value.status === "RECEIVED" && value.brief !== null) ||
    (value.status === "BRIEF_NORMALIZED" &&
      (typeof value.brief !== "string" ||
        value.brief.trim().length < 3 ||
        value.events[1]?.status !== "BRIEF_NORMALIZED"))
  ) {
    throw new ResearchError(
      "The API returned an inconsistent research timeline.",
      true,
    );
  }
  return value as unknown as ResearchRun;
}
