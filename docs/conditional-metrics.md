# Metrics for a complete conditional NAV path

`compute_performance` accepts initial pre-trade capital, a same-time inception NAV event,
an ordered inventory of session closes and every corresponding later NAV. Risk-free returns,
execution batches and annualization are separate explicit inputs. A missing declared close,
unknown NAV or unsupported external cash flow fails the complete-path calculation.

The first full interval divides its closing NAV by initial pre-trade capital. Later intervals
divide consecutive closes. The inception event contributes to total return and drawdown but
creates no additional daily observation. For example, an entry fee that changes 1,000 to 999,
followed by a first close of 984, gives a first interval return of `984/1000 - 1`.

Net mean is the arithmetic mean of interval returns. Each cumulative risk-free return must
match the exact start and end of one interval; a Friday-to-Monday interval needs its complete
matching rate. Excess return is net return minus that rate. Excess sample variance divides
the squared deviations by `n - 1`. Net Sharpe is `sqrt(A) * mean(excess) / sd(excess)`, with
annualization `A` declared as an integer from 1 through 366. Both its mean and standard
deviation use excess returns. This follows the historical differential-return ratio in
[Sharpe's 1994 definition](https://web.stanford.edu/~wfsharpe/art/sr/SR.htm); square-root scaling
is a reporting convention whose interpretation depends on serial dependence and compounding.

Missing, malformed, duplicate or endpoint-misaligned rates make only the dependent excess
metrics unavailable. Zero rates must be supplied explicitly. Fewer than two periods leaves
sample variance and Sharpe undefined; zero excess variance also leaves Sharpe undefined.
There is no ordinary t-statistic substituted for the planned HAC analysis.

Total return is final NAV divided by initial capital, minus one. Maximum drawdown uses the
running peak across initial capital, inception NAV and all supplied closes. It measures that
observed path, which may omit intraday losses. Terminal zero or negative NAV is retained and
drawdown can exceed one. No further interval may follow observed insolvency. Immediate
inception insolvency preserves total return and drawdown with zero daily observations.

Turnover is the sum of each executed batch's absolute notional divided by its own pre-trade
NAV. The entry counts; splits, dividends and acquisition settlement are not executions.
Buying 1,000 against NAV 1,000 and later selling 700 against NAV 700 gives turnover two.
The execution inventory must be complete, chronological and unique, with simultaneous
trades aggregated into one batch. An absent inventory means unavailable turnover; an explicit
empty inventory means zero. Invalid batches disable turnover while valid NAV metrics remain.

The implementation uses isolated 50-digit half-even Decimal arithmetic. Inputs have at most
50 coefficient digits, bounded exponents and magnitudes, and at most 10,000 periods or batches.
JSON decimals are strings. Rounded total return can equal minus one while a tiny positive
balance remains: exact terminal NAV determines the separate solvent/insolvent outcome.

Eight frozen fictional cases passed 176 numerical/count comparisons using an absolute
`1e-40` representation tolerance. That allowance applies to those engineering examples,
not all supported magnitudes or published-factor acceptance tolerances. The initial suite
passes 67 tests on Windows and Linux. Saved reports check structural and arithmetic
consistency of retained intervals and statuses. Authenticating the NAV path and recomputing
all aggregates requires replay against the inputs identified by the report's hashes.

These calculations do not establish calendar completeness, source rights, order feasibility,
sample-end liquidation or empirical strategy performance. The caller's declared session
inventory defines the sample; calendar and execution admission remain separate gates.
