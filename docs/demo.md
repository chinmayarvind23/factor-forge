# Recorded demo

[Open the hosted dashboard](https://huggingface.co/spaces/chinmayarvind/factorforge)
or [watch the video](assets/demo.mp4).

![Evidence walkthrough](assets/demo.gif)

The recording walks through four saved scenarios built from original repository
fixtures: a monthly experiment, a weighted two-signal hybrid, a twelve-return
validation path, and an execution guard. The validation view shows three contiguous
test blocks. The browser verifies the downloaded records before rendering results.
The free hosted dashboard displays saved evidence; run new research locally using
[the research command](research-command.md).

## Re-record

Install the web workspace dependencies and Playwright Chromium. From `apps/web`,
compile the recorder for Node so Playwright's video process runs in its supported
runtime. Set an absolute, fresh output directory outside the repository:

```powershell
bun install --frozen-lockfile
bun x playwright install chromium
bun build scripts/record-demo.ts --target node --packages external --outfile node_modules/.cache/factorforge-record-demo.mjs
$env:FACTORFORGE_DEMO_URL='https://chinmayarvind-factorforge.static.hf.space'
$env:FACTORFORGE_DEMO_RECORDING='C:/path/to/fresh-recording-directory'
node node_modules/.cache/factorforge-record-demo.mjs
```

The script checks each scene's status and accounting result, captures an overview,
and records browser errors. A successful run writes `recording.json` and a WebM
video. Keep that original and receipt together. Export the video to MP4 and GIF
with FFmpeg for the README; those exports change encoding and size only.

The current walkthrough demonstrates the saved execution paths. Published-factor
benchmark results and trained-policy comparisons need their own completed studies
before they can appear in a release demo.
