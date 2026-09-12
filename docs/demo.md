# Research journey demo

[Watch the 64-second recording](assets/research-journey.mp4) or
[open the interactive replay](https://chinmayarvind-factorforge.static.hf.space/journey.html).

![Research journey](assets/research-journey.gif)

The recording follows one actual retained local-model run through seven stages:

1. Enter its recorded research idea.
2. Inspect the selected source passage from the reviewed catalog.
3. Read the unchanged structured model extraction.
4. Inspect the compiled strategy, timing and costs.
5. See the borrowing gate stop the attempted backtest before any fills.
6. Read the outcome and inspect its artifact identity.
7. Compare with a separately authored, successful deterministic reference.

The model interpreted the direction differently from the source. The recording retains
that result and the execution stop. The reference is explicitly separate; it is not an
automatic correction by the agent. All inputs are authored integration fixtures.
This is an evidence replay, not new inference, live literature search or an investment
performance claim. Each screen keeps that scope visible.

The walkthrough export verified 48 objects reachable from the scheduler result. The
recorder checked all seven scenes, the expected guard and reference result, and browser
errors. Desktop/mobile screenshots and an MP4-decoded frame were inspected. Encoding
changes only the format; the video contains real browser navigation through the replay.
The [recording receipt](assets/research-journey-recording.json) retains hashes and scope.

## Open locally

From the repository root, serve the checked-in replay without running any evaluation:

```powershell
python -m http.server 8769 --bind 127.0.0.1 --directory apps/demo
```

Open http://127.0.0.1:8769/journey.html. The idea field accepts the recorded question;
use “Use recorded idea” to fill it. New research uses [the local operator](research-command.md).

## Record again

Install the web workspace dependencies and Playwright Chromium, then run from the root:

```powershell
$env:FACTORFORGE_DEMO_URL='http://127.0.0.1:8769/journey.html'
$env:FACTORFORGE_DEMO_RECORDING='C:/path/to/fresh-recording-directory'
node apps/web/scripts/record-journey.mjs
```

Add `--check` for a short, non-recording desktop/mobile verification. The recorder writes
seven screenshots, a WebM and `recording.json`. Keep the original WebM with its receipt.
Export to MP4 with H.264/yuv420p and GIF with a reduced palette using FFmpeg.

`apps/demo/journey.json` is the checked-in display projection. To rebuild it from an
existing retained original capture and an existing reference-demo artifact store:

```powershell
uv run python scripts/build_journey.py --run PATH_TO_CAPTURE --reference-demo dist/space --output apps/demo/journey.json
```

The exporter verifies artifact closure and matching strategy inputs before selecting
public display fields. It does not rerun or edit inference. The normal Space builder
copies the four journey assets alongside its dashboard assets.

## Earlier dashboard tour

The [45-second dashboard recording](assets/demo.mp4) and [GIF](assets/demo.gif) show four
saved execution scenarios, time-series validation and the historical study's cost controls.
Its recorder remains `apps/web/scripts/record-demo.ts`. Both recordings display saved
research evidence; neither establishes the autonomous release benchmark.
