# Literature discovery

Search Crossref from an investment idea, retain the response, and replay the candidate
list offline. This command runs locally and needs no API key or model call.

```powershell
python -m factorforge.retrieval.discovery --query "equity momentum returns buying winners selling losers" --limit 10 --artifacts artifacts/discovery --output discovery.json
python -m factorforge.retrieval.discovery --replay discovery.json --artifacts artifacts/discovery --output discovery-replay.json
```

The first command makes one request to `https://api.crossref.org/works` using
`query.bibliographic`, `rows`, and `select=DOI,title`. Results retain provider rank,
title and DOI; duplicate DOIs collapse to their first occurrence. The receipt includes
the query, retrieval time, HTTP status, capture completeness and SHA-256 reference to
the response. Replay verifies the bytes and reconstructs the same candidates.

Requests have a 30-second total deadline and a one-MiB retained-response limit.
Redirects, automatic retries and environment proxy settings are disabled. HTTP errors,
transport errors, malformed responses and oversized responses produce retained terminal
receipts. A partial capture never produces paper candidates. The CLI creates its output
exclusively before making a request, preventing accidental overwrite and duplicate work
when the same output path already exists.

In the first live development query, Crossref returned ten candidates and ranked
*Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency*
second (DOI `10.1111/j.1540-6261.1993.tb04702.x`). This is one discovery observation;
retrieval relevance across a benchmark remains to be measured.

## Handoff to source selection

Discovery candidates are explicitly `metadata_only`. To use a candidate in the
[research command](research-command.md), acquire its permitted source text, retain
physical-page artifacts, create a reviewed `SourcePacket`, and bind it to a matching
`PaperDocument` in a `LiteratureCatalog`. The existing source selector ranks that
catalog and supplies extraction packets. Discovery does not fabricate page numbers,
infer reuse rights, download arbitrary result links, or automatically approve a source.
The [PDF admission command](source-ingestion.md) now builds that catalog from a
permitted local PDF and reviewed page selection. Download and identity/rights review
remain explicit local ingestion steps.

The existing HTTP client dependency avoids adding a provider SDK or service.
[Crossref's official REST documentation](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
describes the metadata endpoint and its access terms. Only DOI and title fields are
requested; abstracts and third-party full text are excluded from this discovery capture.
# Optional discovery cache

[Redis-assisted discovery](../tools/cache/README.md) reuses recent source-verified
successful metadata captures. It retains the original capture time and publishes an
explicit cache/provider delivery receipt. Raw source admission and research decisions
remain separate from metadata discovery.
