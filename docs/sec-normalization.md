# SEC company-concept normalization

`factorforge.data.sec_normalizer` converts an archived SEC company-concept JSON response
into normalized fundamental facts. The source CIK, taxonomy, tag, unit and requested filing
window must match the saved request. Values parse directly to Decimal; instant and duration
contexts retain their period boundaries. Original and amended filing accessions remain
separate observations.

The [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
describes company-concept responses grouped by unit. Acquisition must follow the
[developer guidance](https://www.sec.gov/about/developer-resources). This command operates
on archived bytes and makes no network calls.

## Prepare the request

Archive the raw response, reviewed CIK-to-security mapping and availability evidence in
the artifact store. Construct `SecNormalizationRequest` with:

- `source`: the raw JSON ArtifactRef; at most 2 MiB.
- `cik`, `taxonomy`, `tag`, `unit` and `period_kind`: the exact requested source context.
- `security_id` and `security_mapping`: the reviewed permanent security mapping and its evidence.
- `retrieved_at`: the recorded source capture time.
- `filed_from` and `filed_through`: the inclusive, frozen filing-date window.
- `availability`: accession, reviewed `available_at` timestamp and supporting evidence reference.

Supported taxonomies are `us-gaap` and `ifrs-full`; units are `USD`, `shares` and `pure`
(normalized as `dimensionless`). A CIK identifies a filing entity; ingestion must establish
its relationship to the intended security. The request references are limited to 128 unique
objects and 64 MiB combined, including timing and mapping evidence.

Availability timestamps must precede capture and cannot precede the corresponding filed
date. The command never turns a date into a guessed timestamp. If any scoped accession
lacks reviewed timing, the entire conversion is held and emits no normalized source.
The result lists unresolved accessions and preserves the full selected-row denominator.
An empty window is also explicit. Referenced evidence is hash-checked, but its semantic
interpretation remains the ingestor's responsibility.

## Run offline

Save the request as JSON after archiving its referenced inputs:

```powershell
uv run python -m factorforge.data.sec_normalizer --request sec-request.json --artifacts artifacts/sec --output sec-result.json
```

The output path must be new. The result references the request, transformation/validation
source snapshot, interpreter/package versions and normalized bytes. An identical request
and code version reproduce the result. Conflicting same-filing facts, duplicate JSON keys,
unsupported contexts, invalid numeric values and modified evidence fail validation.

Output is a `MonthlySourceBundle` facts component with empty membership. Ingestion must
join reviewed historical membership and the other execution sources into the complete
[observed dataset](monthly-admission.md). Duration facts remain available to future fiscal
selection policies; the current monthly signal assembler admits instant observations.

## Verification scope

Sixteen authored SEC-format tests cover revisions, point-in-time selection, exact fractional
values, partial/missing timing, duration contexts, filing windows, corrupt evidence and
receipt consistency. Ready and held CLI cases replay identically from disk, with 13 and 11
reachable objects verified respectively. These are controlled integration checks.

The attempted live SEC Assets request returned HTTP 403. Its response was retained;
successful live SEC ingestion and historical-factor results remain unverified.
