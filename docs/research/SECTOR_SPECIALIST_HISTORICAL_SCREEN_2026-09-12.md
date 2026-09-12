# Sector Specialist Historical Screen — 2026-09-12

Status: completed historical screening; research-only; not a decisive holdout.

## Scope

This screen evaluates the frozen `orion-specialist-universe-v1` hierarchy on 60 days of 5-minute historical data for AAPL, MSFT, NVDA, AMD, AMZN, TSLA, META and GOOGL. V3 point-in-time walk-forward probabilities are first converted through the existing chronological V3.1 held-out calibration path. The specialist hierarchy is then fit strictly from completed prior sessions. The 30m, 1h, 3h and 5h horizons remain independent.

The result cannot authorize runtime promotion. It is allowed to reject a weak design, but positive findings require untouched forward evidence.

Workflow run: `34687711342`

Artifact: `sector-specialist-historical-screen-34687711342`

Artifact SHA-256: `c6285c5ccb9ede7c7fdaca1635b6522249cd73c729be276a090af64a0c21c539`

All eight requested equity symbols completed successfully; no symbol failures were recorded.

## Overall hierarchy result

Positive improvement means the child layer reduced the loss relative to its direct parent.

| Horizon | Comparison | Active pairs | Sessions | Brier improvement | Log-loss improvement | Bootstrap P(Brier > 0) | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 30m | global -> sector | 960 | 10 | -0.000178 | -0.000359 | 0.0275 | not demonstrated |
| 30m | sector -> ticker | 960 | 10 | -0.000704 | -0.001409 | 0.0225 | not demonstrated |
| 1h | global -> sector | 880 | 10 | -0.000322 | -0.000647 | 0.1030 | not demonstrated |
| 1h | sector -> ticker | 880 | 10 | -0.000861 | -0.001738 | 0.1420 | not demonstrated |
| 3h | global -> sector | 560 | 10 | +0.000388 | +0.000756 | 0.6275 | not demonstrated |
| 3h | sector -> ticker | 560 | 10 | -0.004906 | -0.010090 | 0.0615 | not demonstrated |
| 5h | global -> sector | 240 | 10 | -0.000287 | -0.000626 | 0.4420 | not demonstrated |
| 5h | sector -> ticker | 240 | 10 | -0.007062 | -0.014650 | 0.0790 | not demonstrated |

The 30m ticker layer is particularly unfavorable: both proper scores degraded and the paired session-block bootstrap confidence intervals remained below zero (`Brier [-0.001410, -0.000020]`, `log-loss [-0.002826, -0.000038]`).

## Per-sector observations

No frozen sector achieved the preregistered `research_eligible` verdict on any horizon.

The only repeated positive signal was Information Technology on the longer horizons:

- 3h: Brier improvement `+0.001253`, log-loss improvement `+0.002504`, 280 active pairs across 10 sessions, bootstrap probability of positive Brier/log-loss improvement about `0.9365`. The 95% intervals still crossed zero (`Brier [-0.000359, 0.002983]`, `log-loss [-0.000730, 0.005982]`).
- 5h: Brier improvement `+0.001303`, log-loss improvement `+0.002617`, 120 active pairs across 10 sessions, bootstrap probability of positive Brier improvement `0.9240`. The 95% intervals again crossed zero (`Brier [-0.000291, 0.003540]`, `log-loss [-0.000608, 0.007136]`).

Those are screening hints only. Treating them as proof, lowering the gate, changing ridge strength or redefining the taxonomy after seeing this result would be post-hoc tuning on the same evidence.

Communication Services was materially poor at 30m: Brier improvement `-0.000325`, log-loss improvement `-0.000651`, with both 95% bootstrap intervals below zero. At 1h its directional accuracy also fell by 10 percentage points on the active subset.

Consumer Discretionary did not demonstrate a stable proper-score advantage at any horizon. At 5h it had only 60 active pairs, below the fixed 80-observation gate.

## Decision

The current broad sector/ticker specialist calibration design is **not demonstrated** by this historical screen and must not be promoted or used to alter Regular-hours V3.1 runtime behavior.

Do not tune the existing gates, ridge penalty or sector taxonomy against this same screen in an attempt to manufacture a passing result. The frozen forward specialist cohort remains the decisive evidence path.

The Information Technology 3h/5h pattern is worth preserving as a preregistered future hypothesis, but not as a result to optimize against. If a narrower semiconductor/industry specialist is explored, give it a new research identity and evaluate it on a later untouched cohort rather than reusing this screen for approval.

## Next logical step

Keep the historical-screening infrastructure because it successfully falsified the broad design without touching runtime behavior. Continue score-blind forward collection for the frozen specialist cohort. A separate future PR may preregister a narrower long-horizon industry hypothesis before new outcome evidence is inspected; that proposal must retain direct-parent scoring, active-row-only coverage and a fresh untouched evaluation cohort.
