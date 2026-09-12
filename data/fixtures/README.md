# Tiny market fixture

`tiny-market-v1.json` contains original fictional securities and manually chosen values for deterministic data-contract tests. It covers six dates from 29 April through 6 May 2024. The fixture is fictional rather than observed equity data.

Stable security identifiers survive ticker changes. `SEC-A` changes from `OLD` to `NEW` and splits two-for-one at 13:30 UTC on 2 May. All closes are unadjusted decimal strings in USD per contemporaneous share. Its cash dividend is 1.00 USD per post-split share, with entitlement immediately before 13:30 UTC on 3 May and payment at 12:00 UTC on 6 May. Cash is not automatically reinvested. A pre-split share becomes two shares, so `1 * 104.00 == 2 * 52.00`; the price change across the split is not a loss. The dividend price/receivable identity is `2 * 52.00 == 2 * 51.00 + 2 * 1.00` for an unchanged two-share holding.

`SEC-B` leaves the universe on 2 May with a known 24.00 USD per-share cash payout later that day. `SEC-C` leaves on 3 May with an explicitly unknown terminal outcome. It has no terminal price or payout to infer. Missing data remain `null`; a full holding-period accounting request that includes that exit must fail with an unavailable-outcome result. Neither security receives invented post-exit price rows.

Security-history intervals are half-open: `effective_from <= t < effective_to`, with a null end meaning no known interval end. Records also carry information-availability times. Symbol mappings for B and C remain valid identifiers after their exits; an open symbol interval is not a listing or trading permission. Membership events are the authority for formation-time universe selection; consumers must not use a later security-history snapshot to infer earlier membership.

Facts use the `FundamentalFact` fields and membership uses `MembershipEvent`. All facts are instant annual assets, so no duration-period start is required. A source ID identifies a fictional filing document. `SEC-A`'s 2023 assets become available exactly at 20:00 UTC on 1 May; its restatement is unavailable until 12:00 UTC on 6 May. `SEC-B`'s filing is delayed until 2 May. Retain both original and amended records and select by the formation-time contract.

These timestamps define a test market. They do not model exchange settlement, real regulatory deadlines or a real feed's latency. Formation-time information must still precede trading under the application's strict time-order rule. Consumers must supply any additional inputs required by their execution contract.

The original fictional content in this JSON and this README may be copied, modified and redistributed for any purpose. This fixture-only permission does not change the repository code license or grant rights in third-party papers or provider data. No external dataset was copied into these files.
