# Discovered paper to extraction catalog

The admission command binds a candidate from a saved discovery receipt to a permitted
local PDF, extracts selected physical pages, and creates the `LiteratureCatalog` used
by the existing research command. It retains the discovery response, PDF, parser version,
page output and catalog under one verifiable admission receipt.

Install Poppler, Python 3 and `prlimit` in Linux, or in your WSL distribution on Windows.
The command uses `pdftotext -layout -enc UTF-8`; it does not install tools automatically.

Prepare a request after reviewing the PDF identity and your permitted use:

```python
from pathlib import Path
from factorforge.data.artifacts import LocalArtifactStore
from factorforge.retrieval.ingestion import AdmissionRequest

store = LocalArtifactStore(Path("artifacts/discovery"))
discovery = store.put(Path("discovery.json").read_bytes(), media_type="application/json")
pdf = store.put(Path("paper.pdf").read_bytes(), media_type="application/pdf")
request = AdmissionRequest(
    discovery=discovery,
    pdf=pdf,
    doi="10.1111/j.1540-6261.1993.tb04702.x",
    paper_id="jt1993",
    selected_strategy="Six-month momentum ranking with six-month holding",
    pages=(4, 5, 6),
    identity_reviewed=True,
    rights="private_research_only",
)
with Path("admission-request.json").open("xb") as output:
    output.write(request.canonical_bytes())
```

The DOI must occur in your saved discovery result. The example page numbers apply to
the reviewed author-hosted version; review page numbers for your own PDF version.

```powershell
python -m factorforge.retrieval.ingestion --request admission-request.json --artifacts artifacts/discovery --output admission.json --wsl
```

Omit `--wsl` on Linux. To materialize the catalog for a research plan:

```python
from factorforge.retrieval.ingestion import SourceAdmission

admission = SourceAdmission.model_validate_json(Path("admission.json").read_bytes())
with Path("catalog.json").open("xb") as output:
    output.write(store.get(admission.catalog))
```

Use that catalog with the [research command](research-command.md). Retain the admission
receipt alongside the plan: the existing catalog includes page references and PDF hash,
while the admission receipt is the root containing the full PDF and discovery provenance.
Catalogs from multiple admissions can be combined through `LiteratureCatalog(entries=...)`;
its existing validator rejects duplicate paper identities.

## Boundaries and evidence

The parser receives verified PDF bytes through stdin, with no source-controlled command
arguments, URLs or shell evaluation. A fixed Python wrapper writes output inside Linux
temporary files so `prlimit` applies on both native Linux and WSL. Limits are 512 MiB
address space, 20 CPU seconds and one MiB per output file, plus wall-clock timeouts.
These are parser resource limits, not the experiment runner's Docker security sandbox.
Only trusted local operators should invoke ingestion with permitted PDFs.

Admission accepts PDFs up to eight MiB and up to 16 selected pages within a 32-page span.
It rejects missing pages and blank text layers; OCR and visual interpretation remain
separate review steps. Page text is preserved after removal of Poppler's form-feed page
separator. The catalog indexes at most 16,000 characters, while extraction receives all
selected page artifacts within the existing packet limit. Rights and PDF/DOI identity
are operator declarations, not conclusions inferred from metadata.

The live development check admitted the saved momentum PDF, reproduced physical pages
4–6 from the earlier paper study, verified ten reachable artifacts, and successfully
prepared the existing extraction prompt. It made no model call. The paper and its text
remain private; only implementation and original test data are committed.
