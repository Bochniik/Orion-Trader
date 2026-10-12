# JPM prospective research lockbox — candidate only

Status: `CANDIDATE_NOT_CERTIFIED`; verdict: `AWAITING_MORE_EVIDENCE`.
Scope: `SIMULATED_FORWARD` only; no LIVE_FORWARD mutation or production promotion.

Predeclared first XNYS lockbox session: **2026-10-19** (before session open).
Candidate final XNYS session: **2027-02-11**.
Calendar-defined development sessions: **20**, from **2026-09-21** through **2026-10-16**.
Calendar-defined lockbox sessions: **80**.
Candidate manifest SHA-256 (canonical JSON excluding the digest field):
`bfe24d3b87ba2ed538cb38915c5a4f8a716113ed5b85f7b6a7b2563049d94cec`.

Selection is based only on the predeclared date and XNYS exchange calendar,
not on issued-prediction counts, settled outcomes, or performance.
Development labels with target_time_utc >= 2026-10-19T13:30:00+00:00
are embargoed. The full manifest must be independently verified against
the digest before any lockbox use. Git commit anchoring this note alone
does **not** certify an untouched lockbox.

Optimistic same-session 5-minute-stride=1 upper bounds for 80 sessions:
3h **3,368**, 5h **1,482**. These are NOT observed samples. At stride=6,
the theoretical maxima fall to 628 and 312 respectively, so neither
horizon could reach 1,000 OOS samples. Replay stride and provider
availability must be checked before attempting validation.

SpecialistEvidenceGate (each 3h and 5h): at least 1,000 *settled*
out-of-sample predictions across 10 XNYS sessions; accuracy gain >= 0.02,
Brier reduction >= 0.01, coverage >= 0.30, no ECE deterioration;
paired incumbent/specialist comparison, session stability and
uncertainty reporting; independently untouched lockbox required.

No claims of validated provider responses, settled samples, calibrated
metrics, or passing the gate are made by this preregistration note.
