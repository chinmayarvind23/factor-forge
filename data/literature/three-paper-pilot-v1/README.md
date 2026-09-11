# Three-paper retrieval development pilot

This frozen development corpus contains three original summaries of published equity-factor research, nine manually targeted queries, and 27 explicit binary judgments. It is too small and deliberately targeted to estimate production search quality or the 15-paper release benchmark. Full papers and extracted passages are not distributed here.

The documents cover Jegadeesh and Titman (1993), Novy-Marx's June 2012 manuscript preceding the 2013 publication, and Sloan (1996). The retained identifier `nm2013` comes from candidate tracking; its source version is explicitly the 2012 manuscript. Each `source_sha256` identifies the reviewed PDF, while the document and corpus identities bind the original summary actually indexed.

The summaries and query judgments were reviewed before running retrieval. Their canonical identities use sorted, compact UTF-8 JSON without a trailing newline:

| Input | SHA-256 |
| --- | --- |
| Corpus | `c880063eda90a0b3663a9e612aa0cfd97a816f1d84764106670ea463d58e531f` |
| Judgments | `3f4450282559d2dd9decbaf1c9a217644eae7252a393a453d7dda6b43e8188e1` |

The evaluation uses the fixed BM25 baseline at `k=3`. Recall@3 and MRR@3 are macro averages over the six answerable queries. The three queries with no relevant document have separate false-positive and abstention rates: any returned positive-score result counts as a false positive for that query. No relevance threshold is tuned. A partition with no applicable queries reports `null`, never perfect recall. Per-query ranks and denominators remain available in the report.

All pairs inside this corpus are judged. Papers outside it are unjudged, and expanding the corpus requires a new version and additional judgments. Do not rewrite this version after observing results.

These original summaries, queries, and judgments may be copied and redistributed for research and demonstrations with attribution to this repository. This permission does not cover the linked papers or imply an open license for their PDFs.

Run from a clean installed checkout:

```console
uv run python -m factorforge.evaluation.cli --corpus data/literature/three-paper-pilot-v1/corpus.json --qrels data/literature/three-paper-pilot-v1/qrels.json --output artifacts/local/retrieval-pilot-v1 --k 3
```

The command prints the report and a content-addressed record pointer. The record preserves exact input files, configuration, report, installed source snapshots, Python and package versions, and evaluation timing. Source snapshots are provenance, not executable attestation against concurrent local file changes. Use a frozen checkout for evidence collection. The command accepts local JSON files of at most 16 MiB each; schema and corpus limits also apply.
