# Historical benchmark and risk-free inputs

`factorforge.data.french_normalizer` converts an archived daily Fama/French
three-factor ZIP into the engine's `IntervalSource` format. Market total return is
`(Mkt-RF + RF) / 100`; risk-free return is `RF / 100`. SMB and HML remain in the
archived source and do not become strategy outputs.

The [source definition](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html)
describes the market excess return and risk-free series. The
[data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)
documents source revisions, including the transition from CRSP FIZ to CIZ. Pin each
download: current historical values are a source vintage, not proof of what was
published on each historical trading day.

## Import

Archive the ZIP and acquisition receipt in the artifact store. Create a
`FrenchDailyRequest` with their references, the retrieval timestamp, and the exact
ordered UTC session-close timestamps from the strategy's declared calendar. Include
the pre-trade baseline close and every later close; 2–512 sessions are supported.

```powershell
uv run python -m factorforge.data.french_normalizer --request request.json --artifacts artifacts/reference --output normalized-result.json
```

The command runs offline and refuses to overwrite its output file. The result links
the request, trusted normalizer source, and normalized interval data. The linked
artifact closure is verified before returning. Attach these source and transformation
references to the observed dataset manifest when admitting a complete dataset.
Acquisition receipts and session clocks are operator assertions; hashes prove their
identity, not their authenticity or the correctness of exchange closing times.

Each source date after the baseline maps to one close-to-close interval. Source dates
and declared session dates must match exactly within the selected window. The importer
does not fill gaps, skip sessions, compound across missing days or infer a calendar.
Missing-value sentinels, duplicate dates, malformed numbers, unexpected archive members
and oversized expanded content are rejected. ZIP contents are read in memory, never
extracted into the filesystem.

Availability is the capture timestamp. Monthly execution permits these comparison
series only when available by `evaluated_at`; they never influence formation decisions.
This preserves the distinction between historical strategy inputs and ex-post reference
returns without backdating publication.

## Verified scope

A live public download contained 26,296 daily rows. A declared four-session January
2024 window produced six comparison rows; all 13 linked artifacts verified, and offline
replay produced identical output. Controlled tests also pass the normalized rows through
monthly execution and check its evaluation-time availability gate.

This is historical reference ingestion. Published-factor reproduction still requires
independently constructed portfolios, entitled security-level data, point-in-time
fundamentals and membership, and frozen comparison tolerances. No factor reproduction
count follows from importing the published return series.
