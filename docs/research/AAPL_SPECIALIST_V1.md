# AAPL frozen symbol specialist v1

Status: **REJECTED** for this frozen specialist formulation on the inspected SIMULATED_FORWARD lockbox.

Research-only. No LIVE_FORWARD mutation, runtime routing, automatic production promotion, or trading authorization.

## Evidence provenance

- Source workflow: `Orion cloud accelerated learning`
- Source run: `37957840630`
- Source artifact id: `11632401720`
- Artifact digest: `sha256:6cd217974ea19a659e5b9193480fbb73635cc78deee9c9f4521b1e9b9ed903f6`
- Database: `simulated_forward.db`
- Scope: `SIMULATED_FORWARD`
- Incumbent model version: `long-horizon-v5-20260911-a`
- Frozen target: `AAPL`
- Frozen sector: `Information Technology`
- Lockbox: latest 10 whole AAPL sessions, excluded from fitting.

## 3h

- development: 37 sessions / 887 AAPL observations
- lockbox: 10 sessions / 240 observations
- incumbent accuracy: **47.50%**
- specialist accuracy: **47.08%**
- accuracy delta: **-0.42 pp**
- incumbent Brier: **0.250262**
- specialist Brier: **0.248450**
- Brier improvement: **+0.001812**
- incumbent ECE: **0.095543**
- specialist ECE: **0.095991**
- ECE delta: **-0.000448** (worse)
- session Brier wins: **6/10**
- session-block accuracy delta 95% CI: **[-9.58 pp, +9.58 pp]**
- session-block Brier improvement 95% CI: **[-0.008876, +0.012591]**

The specialist worsens directional accuracy and calibration. Proper-score uncertainty crosses zero.

## 5h

- development: 34 sessions / 407 AAPL observations
- lockbox: 10 sessions / 120 observations
- incumbent accuracy: **49.17%**
- specialist accuracy: **49.17%**
- accuracy delta: **0.00 pp**
- incumbent Brier: **0.259782**
- specialist Brier: **0.270533**
- Brier improvement: **-0.010751** (worse)
- incumbent ECE: **0.062848**
- specialist ECE: **0.128802**
- ECE delta: **-0.065954** (materially worse)
- session Brier wins: **4/10**
- session-block accuracy delta 95% CI: **[0.00 pp, 0.00 pp]**
- session-block Brier improvement 95% CI: **[-0.041266, +0.019687]**

The 5h specialist materially worsens Brier score and calibration.

## Decision

This frozen AAPL formulation is **REJECTED**. Do not tune ridge, thresholds, hierarchy or gates against this inspected lockbox. A future AAPL challenger must be preregistered as a genuinely new design and evaluated on a fresh untouched lockbox.

Proceed to the next requested symbol: **JPM**.
