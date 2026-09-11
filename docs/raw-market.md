# Raw market input contracts

The `raw-market-source-v1` bundle declares a bounded original-fixture market: up to eight
permanent security IDs, raw USD opening/closing observations, separate corporate actions,
explicit complete action/exit coverage and finite short-loan grants. It contains observations
and permissions supplied by trusted ingestion; it contains no target weights or fills.

`MarketQuote` extends the existing raw-price ledger contract with an open/close phase.
`ledger_mark()` preserves all quote fields when passing a revalidated observation into the
ledger. Decimal prices use strings in JSON. Duplicate quote instants or source IDs,
uncovered securities, invalid amounts and events outside source coverage fail validation.
Availability clocks are retained even when they are late; the executor must reject using
a quote before it became available.

Short membership alone grants no loan. `BorrowGrant` names a security, exact maximum shares,
availability time and a nonempty closed validity interval. The first original profile permits
only explicitly zero annual borrow cost. Quantity, expiry and availability must be checked
at every required holding observation. This schema is not a broker margin model.

An empty action inventory is meaningful only with the explicit complete coverage assertions.
Nonempty actions and unknown terminal proceeds remain represented as source data. The first
planned strategy executor rejects those unsupported events; this loader does not silently
drop them or manufacture proceeds.

The separate `interval-returns-v1` bundle identifies benchmark and risk-free series by exact
start/end clocks, availability and cumulative decimal return. It admits at most 1,022 rows,
enough for two series over a 512-session sample. Duplicate identities/intervals fail. A
missing interval stays missing until execution checks the complete calendar; no zero rate
is inferred from an absent row.

`load_market` and `load_intervals` verify each artifact's exact size and SHA-256 before
interpretation. They require JSON media type, cap each source at 8 MiB, reject duplicate
members and nonfinite extensions, and preflight row counts and depth 16 before typed
validation. Market limits are 8,192 quotes and 2,048 entries each for actions and loans.
The full strategy admission must also enforce its union, total input-byte and operation
budgets. No manifest permission or execution authority follows from successful parsing.

Strict JSON parsing permits date strings while strict Python input requires typed dates;
the distinction follows [Pydantic's JSON contract](https://github.com/pydantic/pydantic/blob/main/docs/concepts/json.md).
The loader retains JSON mode for the nested date and decimal contracts after structural
preflight, avoiding whole-model coercion.
