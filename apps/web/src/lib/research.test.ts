import { expect, test } from "bun:test";
import {
  createRun,
  prepareSubmission,
  ResearchError,
  type ResearchRequest,
  type ResearchRun,
  readRun,
} from "./research";

const payload: ResearchRequest = {
  idea: "Test medium-term momentum",
  max_llm_cost_usd: "5.00",
  max_wall_time_s: 3600,
  max_experiments: 12,
};
const id = "9a6dfbb2-2fe0-4fa3-91ae-02e2874090c0";

/** Network uncertainty must preserve both request identity and exact payload. */
test("retry reuses its idempotency key and changed input gets a new key", () => {
  const first = prepareSubmission(payload, null, () => "first");
  expect(prepareSubmission({ ...payload }, first, () => "wrong")).toBe(first);
  expect(
    prepareSubmission({ ...payload, max_experiments: 2 }, first, () => "second")
      .key,
  ).toBe("second");
});

/** Verify the write contract at the boundary where duplication can occur. */
test("creation sends the required key and accepts the receipt", async () => {
  const result = await createRun(
    { payload, key: "unique" },
    async (url, init) => {
      expect(url).toEndWith("/api/v1/research-runs");
      expect(init?.method).toBe("POST");
      expect(init?.headers).toEqual({
        "Content-Type": "application/json",
        "Idempotency-Key": "unique",
      });
      expect(JSON.parse(String(init?.body))).toEqual(payload);
      return Response.json({ run_id: id, status: "RECEIVED" }, { status: 202 });
    },
  );
  expect(result.run_id).toBe(id);
});

/** Failure recovery is explicit and never exposes raw server error content. */
test("validation errors are actionable and not retryable", async () => {
  try {
    await createRun(
      { payload, key: "unique" },
      async () => new Response("internal secret", { status: 422 }),
    );
  } catch (error) {
    expect(error).toBeInstanceOf(ResearchError);
    expect((error as ResearchError).retryable).toBe(false);
    expect((error as Error).message).not.toContain("internal secret");
    return;
  }
  throw new Error("Expected a rejected request");
});

/** Fetch failures are uncertain writes and must offer same-key retry. */
test("network failure is retryable", async () => {
  await expect(
    createRun({ payload, key: "unique" }, async () => {
      throw new Error("offline");
    }),
  ).rejects.toMatchObject({ retryable: true });
});

/** Data from a different run cannot replace the requested run's timeline. */
test("reject malformed receipts and mismatched run states", async () => {
  await expect(
    createRun({ payload, key: "unique" }, async () =>
      Response.json({ run_id: "bad", status: "RECEIVED" }, { status: 202 }),
    ),
  ).rejects.toThrow("invalid run receipt");
  await expect(
    readRun(id, async () => Response.json({ run_id: "other" })),
  ).rejects.toThrow("invalid run state");
});

/** A valid local stage can stop polling without manufacturing benchmark evidence. */
test("reads the normalized brief and ordered events", async () => {
  const run: ResearchRun = {
    ...payload,
    run_id: id,
    status: "BRIEF_NORMALIZED",
    brief: payload.idea,
    mode: "local",
    storage: "memory",
    created_at: "2026-09-11T12:00:00Z",
    events: [
      { status: "RECEIVED", created_at: "2026-09-11T12:00:00Z" },
      { status: "BRIEF_NORMALIZED", created_at: "2026-09-11T12:00:01Z" },
    ],
  };
  expect(await readRun(id, async () => Response.json(run))).toEqual(run);
  expect(
    (
      await readRun(id, async () =>
        Response.json({ ...run, storage: "postgres" }),
      )
    ).storage,
  ).toBe("postgres");
  await expect(
    readRun(id, async () => Response.json({ ...run, storage: "unknown" })),
  ).rejects.toThrow("invalid run state");
  await expect(
    readRun(id, async () => Response.json({ ...run, brief: null })),
  ).rejects.toThrow("inconsistent research timeline");
});

/** A successful HTTP status still has to match the asynchronous creation contract. */
test("rejects a receipt served with an unexpected HTTP status", async () => {
  await expect(
    createRun({ payload, key: "unique" }, async () =>
      Response.json({ run_id: id, status: "RECEIVED" }),
    ),
  ).rejects.toThrow("unexpected response status");
});

/** A missing run cannot establish whether storage was ephemeral or access was denied. */
test("missing runs describe only the unavailable workspace record", async () => {
  await expect(
    readRun(id, async () => new Response(null, { status: 404 })),
  ).rejects.toThrow("unavailable in the current workspace");
});
