# TSLA frozen symbol specialist v1

Status: **REJECTED** for this frozen specialist formulation on the inspected SIMULATED_FORWARD lockbox.

This result is research-only. It does not authorize runtime routing, LIVE_FORWARD changes, production promotion, or trading execution.

## Evidence provenance

- Source workflow: `Orion cloud accelerated learning`
- Source run: `37957840630`
- Source artifact id: `11632401720`
- Artifact name: `orion-accelerated-learning-state`
- Artifact digest: `sha256:6cd217974ea19a659e5b9193480fbb73635cc78deee9c9f4521b1e9b9ed903f6`
- Evidence database: `simulated_forward.db`
- Scope: `SIMULATED_FORWARD`
- Incumbent model version: `long-horizon-v5-20260911-a`
- Frozen target: `TSLA`
- Frozen sector: `Consumer Discretionary`
- Lockbox policy: latest 10 whole TSLA sessions; all earlier sessions are development-only.

The lockbox was not used to fit or refit the specialist offsets.

## 3h result

- development: 36 sessions, 864 TSLA observations
- lockbox: 10 sessions, 240 settled TSLA observations
- incumbent directional accuracy: **46.25%**
- specialist directional accuracy: **46.67%**
- accuracy delta: **+0.42 pp**
- incumbent Brier: **0.264686**
- specialist Brier: **0.262522**
- Brier improvement: **+0.002164**
- incumbent ECE: **0.136678**
- specialist ECE: **0.128427**
- ECE improvement: **+0.008251**
- session Brier win rate: **7/10**
- session-block bootstrap accuracy delta 95% CI: **[0.00 pp, +1.25 pp]**
- session-block bootstrap Brier improvement 95% CI: **[-0.001136, +0.005502]**

The observed improvement is far below Orion's preregistered +2 pp accuracy and +0.01 Brier gates, and the Brier uncertainty interval crosses zero.

## 5h result

- development: 33 sessions, 396 TSLA observations
- lockbox: 10 sessions, 120 settled TSLA observations
- incumbent directional accuracy: **44.17%**
- specialist directional accuracy: **43.33%**
- accuracy delta: **-0.83 pp**
- incumbent Brier: **0.256671**
- specialist Brier: **0.256363**
- Brier improvement: **+0.000307**
- incumbent ECE: **0.118081**
- specialist ECE: **0.116774**
- ECE improvement: **+0.001307**
- session Brier win rate: **6/10**
- session-block bootstrap accuracy delta 95% CI: **[-2.50 pp, 0.00 pp]**
- session-block bootstrap Brier improvement 95% CI: **[-0.000261, +0.000870]**

5h directional accuracy is worse than the incumbent. The proper-score improvement is negligible and its session-block uncertainty interval crosses zero.

## Decision

The frozen TSLA specialist formulation is **REJECTED** rather than tuned against this same lockbox. The inspected lockbox must not be reused to rescue this model by changing ridge, hierarchy, thresholds, sector definition, or gates.

Future TSLA work requires a genuinely new preregistered challenger and a fresh untouched lockbox. Orion should proceed to the next requested symbol, AAPL, while retaining this result as negative evidence.
