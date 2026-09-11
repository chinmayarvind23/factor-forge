# Session calendar contract

`SessionCalendar` stores ordered, unique same-day UTC opens and closes, an explicit coverage
interval and the availability time of the entire versioned schedule. The calendar is an input
artifact. Its canonical hash, byte length and ID must match the `TimingSpec` reference.

`plan_formations` requires full declared coverage of every requested calendar month. It selects
the last supplied session in each month, or only June for annual formation. A requested month
without sessions fails. A later trade open is selected by counting supplied sessions, not by
adding weekdays. Missing future sessions fail rather than being extrapolated.

The request bounds an inclusive formation-date window. A planned trade can occur afterward;
the executor must separately enforce its sample and budget. Every formation must occur at or
after the calendar version's availability time. This prevents using a later calendar revision
to choose historical formation dates. UTC normalization also prevents repeated local hours
from reversing the order of formation and trade.

Coverage and availability are source assertions, not independently verified exchange facts.
This version assumes the supplied schedule was known in full at its recorded publication time.
Unexpected cancellations, changed session times and overnight sessions need a separately
versioned calendar policy; a retrospective list of actual dates cannot silently be treated as
an advance schedule. Calendar validation does not establish that source rows or prices were
available for a strategy decision.
