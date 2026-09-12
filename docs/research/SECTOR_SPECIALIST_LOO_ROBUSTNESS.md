# Sector Specialist Leave-One-Out Robustness Audit

Status: historical diagnostic only. This result does not authorize runtime promotion and does not replace untouched forward evidence.

## Question

The broad sector/ticker specialist historical screen was not demonstrated overall, but Information Technology showed a small positive point-estimate hint at 3h and 5h. Before creating a narrower specialist from that observation, this audit asks whether the hint survives removal of each constituent in the frozen IT cohort: AAPL, AMD, MSFT and NVDA.

The audit re-runs the unchanged chronological specialist hierarchy after removing one IT symbol at a time. Proper-score comparisons remain sector-vs-global, use active specialist rows only, preserve the 80-observation / 8-session gate, and use paired session-block bootstrap. The historical window is already inspected, so this is a falsification/sensitivity diagnostic rather than a decisive holdout.

## Content-addressed 60d/5m result

The evidence run captured SPY plus all eight equity inputs with no symbol failures. Every captured yfinance frame contained 4,680 rows from 2026-06-17 09:30 ET through 2026-09-11 15:55 ET.

### 3h

Baseline IT sector-vs-global point estimates remained positive:

- Brier improvement: `+0.001503`
- log-loss improvement: `+0.003011`
- directional-accuracy delta: `+0.025`
- paired observations: `280` across `10` sessions
- Brier 95% session-bootstrap CI: `[-0.000280, +0.003404]`
- log-loss 95% session-bootstrap CI: `[-0.000562, +0.006838]`

All four leave-one-out variants retained positive Brier and log-loss point estimates. None became decision-grade evidence because the bootstrap lower bounds still crossed zero. The 3h hint therefore appears distributed across the current IT cohort rather than attributable to one constituent, but it remains statistically unconfirmed.

### 5h

Baseline IT sector-vs-global point estimates were also positive but unstable:

- Brier improvement: `+0.001311`
- log-loss improvement: `+0.002635`
- paired observations: `120` across `10` sessions
- Brier 95% session-bootstrap CI: `[-0.000293, +0.003578]`
- log-loss 95% session-bootstrap CI: `[-0.000602, +0.007203]`

The leave-one-out result is composition-sensitive:

| Omitted symbol | Brier improvement | Log-loss improvement | Point result |
| --- | ---: | ---: | --- |
| AAPL | +0.003157 | +0.006346 | positive |
| AMD | -0.001859 | -0.004024 | negative |
| MSFT | -0.001963 | -0.003903 | negative |
| NVDA | -0.000142 | -0.000335 | negative |

Only one of four omission variants remains positive at 5h. The 5h hint is therefore too dependent on the exact cohort composition to justify a narrower production-facing specialist hypothesis.

## Decision

- Do **not** promote the broad sector specialist.
- Do **not** build a 5h IT specialist from this historical hint.
- Treat the 3h IT result only as a weak, distributed screening clue because its bootstrap interval still includes zero.
- Do not tune ridge strength, gates, taxonomy or thresholds on this same 60d window to rescue the result.

## Next logical step

If specialist research continues, pre-register a new research identity before looking at new outcomes. The cleaner option is an industry-level hypothesis with a new symbol cohort and untouched evidence, rather than repeatedly tuning the same broad-sector calibration layer on the already-inspected window. Until then, the global Regular-hours path remains the safer incumbent.
