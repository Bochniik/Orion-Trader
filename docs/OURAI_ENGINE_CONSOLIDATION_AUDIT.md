# OurAI Engine Consolidation Audit

Status: architecture audit only. This document does **not** change runtime prediction, trading, order-routing, calibration, or model-promotion behavior.

## Goal

OrionTrader currently contains several prediction engines, research challengers, specialist registries, feature providers, scoring layers, and evaluation pipelines. OurAI is now intended to become the unified trading-prediction brain behind OrionTrader. The migration should therefore consolidate prediction responsibility without discarding useful market-data, feature-engineering, risk, session, or evaluation infrastructure.

The target architecture is:

```text
market/news/session data
        |
        v
Orion feature/context providers
        |
        v
OurAI unified forecast engine
        |
        +--> P(up) / P(down)
        +--> expected return %
        +--> uncertainty / prediction range
        +--> calibrated confidence
        +--> LONG / SHORT / NO_TRADE
        |
        v
OrionTrader orchestration + UI + later risk/execution
```

## Migration principles

1. Do not delete an incumbent prediction engine merely because OurAI exists.
2. Freeze duplicate/symbol-specific prediction-engine expansion unless it is needed as a benchmark or as an evidence source for the unified design.
3. Preserve useful deterministic features and market context as candidate inputs to OurAI.
4. Preserve leakage-safe evaluation, immutable evidence, walk-forward testing, settlement, and calibration infrastructure.
5. Retire a prediction path only after OurAI beats it on matched out-of-sample timestamps under a preregistered replacement gate.
6. Keep score semantics separate: Orion Score is a suitability score; it must not be re-labelled as a price probability.
7. Treat market-integrity output as anomaly/susceptibility evidence, not proof of illegal manipulation.
8. Prefer component-level features over opaque aggregate scores when training OurAI, while retaining aggregates for UI/explainability where useful.

## Inventory and recommended disposition

| Component | Current role | Disposition | Migration note |
| --- | --- | --- | --- |
| `news_engine.py` | Deterministic ticker news relevance, catalyst classification, time-decayed sentiment/effective score | **KEEP / FEATURE PROVIDER** | Feed structured news/catalyst features into OurAI. Current score is deterministic evidence, not a calibrated market probability. |
| Orion AI news commentary | Article summaries and narrative labels | **KEEP AS CONTEXT/UI; BENCHMARK AS FEATURE LATER** | Do not let free-form commentary directly control trades. Only add learned/news embeddings to prediction if they improve untouched OOS results. |
| `market_integrity_engine.py` | Heuristic anomalous-price-action / susceptibility analysis | **KEEP / FEATURE + RISK PROVIDER** | Prefer abnormal return/volume, wick, reversal, VWAP extension, liquidity, spread, float, catalyst mismatch and market/sector decoupling as separate features. |
| `market_integrity_service.py` | Bounded single-ticker adapter around integrity analysis | **KEEP / DATA ADAPTER** | Useful Orion-side context provider. |
| `orion_integrity_adjustment_engine.py` | Deterministic penalty to Orion Score | **KEEP FOR LEGACY SCORE UI; DO NOT USE AS PRICE PROBABILITY** | OurAI should learn predictive relevance from integrity components rather than inherit this hand-tuned score penalty as truth. |
| Premarket V5 prediction runtime | 5m/15m/30m premarket return + direction forecast with research gate | **BASELINE + MIGRATE FEATURES** | Retain as incumbent benchmark. Reuse causal feature concepts and NO_TRADE gating; retire its prediction head only after OurAI wins matched OOS evaluation. |
| Premarket data/context/scanner/session infrastructure | Premarket acquisition, context, candidate selection and session handling | **KEEP / ORION INFRASTRUCTURE** | Orion should continue producing clean point-in-time inputs for OurAI. |
| Regular-hours V1 analog engine | Same-session historical analog probabilities and expected move | **BASELINE / RESEARCH REFERENCE** | Valuable simple benchmark and expected-return reference. Do not promote its probabilities as truth. |
| Regular-hours V2/V3 ensemble | Conservative ensemble of analog/statistical paths | **BASELINE** | Keep until unified model proves superior. Its disagreement/shrinkage behavior is a useful benchmark for uncertainty handling. |
| Regular-hours V3.1 runtime | Reliability-filtered/canonical regular-hours prediction path | **PRIMARY INCUMBENT BASELINE** | Preserve matched OOS evidence, suppression policy and timestamp provenance during migration. |
| Symbol specialist registry (`NVDA`, `TSLA`, `AAPL`, `JPM`, etc.) | Per-symbol research identities and evidence gates | **FREEZE NEW DUPLICATE DEVELOPMENT; KEEP AS BENCHMARKS** | Their conceptual role moves inside OurAI through ticker identity/embeddings and, only if justified, specialist adapters/heads. Existing specialists remain useful controls. |
| `liquidity_engine.py` | Deterministic liquidity metrics, tiers and evidence gate context | **KEEP / FEATURE + UNIVERSE PROVIDER** | Excellent candidate for screening the universe and for cost/liquidity features in OurAI. |
| `market_regime_engine.py` | Market/sector trend, momentum, volatility and regime context | **KEEP / FEATURE PROVIDER** | Regime and sector context should become explicit model inputs, not a separate final prediction brain. |
| `predictive_features.py` | Leakage-aware intraday features and future target construction | **KEEP / CORE FEATURE INFRASTRUCTURE** | Strong basis for unified feature schema; extend carefully, preserving timestamp causality and unsupported-resolution nulls. |
| `orion_score_engine.py` | Deterministic buy-suitability composite | **KEEP FOR PRODUCT/UI; DECOUPLE FROM FORECAST** | Orion Score remains explainable suitability context. OurAI forecast probabilities and expected return must be separately calibrated outputs. |
| Evaluation / walk-forward / shadow-settlement / evidence-ledger / tournament tooling | Anti-leakage research and validation | **KEEP / EXPAND** | This is strategic infrastructure for OurAI and should be reused rather than rebuilt casually. |
| Historical challengers / rejected specialist variants | Research lineage | **ARCHIVE AS EVIDENCE, NOT ACTIVE BRAINS** | Keep reproducibility and decisions, but do not multiply runtime prediction paths. |

## Confirmed symbol-specialist scope

The current specialist registry contains:

- NVDA
- TSLA
- AAPL
- JPM
- RGTI
- IONQ
- OKLO
- SPCX
- MSFT
- AMD
- META
- NVTS

These should not evolve into twelve independent production brains. The preferred unified design is a shared model with ticker identity plus stock/sector/regime context. A small per-symbol specialist adapter is justified only if preregistered OOS evidence shows a material, stable benefit over the shared model.

## News migration

The deterministic news engine already contains useful structured evidence:

- catalyst type and catalyst strength
- signed sentiment
- ticker relevance
- time decay / freshness
- effective directional score
- article count and strongest catalyst

Phase 1 should feed these values as point-in-time features. A later learned news representation may be tested, but it must be evaluated against the deterministic baseline on the same untouched timestamps. Free-form summary text is never itself a probability or trade instruction.

## Market-integrity migration

The so-called manipulation layer should be treated as **market-integrity anomaly risk**. It currently includes evidence such as abnormal return/volume, wick rejection, reversal instability, VWAP extension, liquidity susceptibility, spread anomaly, low-float susceptibility, catalyst mismatch and market/sector decoupling.

OurAI should receive these components when they are available. The aggregate risk score can remain available to Orion UI and risk policy, but training should not assume that a high score proves manipulation or guarantees mean reversion/continuation. Level-2/order-cancellation evidence is currently insufficient for reliable spoofing/layering detection.

## Premarket migration

Premarket V5 is already close to the desired unified forecast contract: it produces both return magnitude and direction probability, checks regression/classifier agreement, estimates move relative to expected sigma and can emit `NO_TRADE` below a research gate.

Use it as the first incumbent benchmark for OurAI. Premarket-specific information should become session/regime features inside the unified model where possible:

- minutes to open
- early/mid/late regime
- gap magnitude
- VWAP distance
- session return
- momentum agreement
- gap/momentum alignment
- trend/volume and trend/volatility interactions
- volatility ratio
- coverage/freshness quality

The Orion premarket acquisition/session path remains useful even after the old V5 prediction head is retired.

## Regular-hours migration

The current regular-hours chain should be treated as incumbent evidence, not deleted:

```text
V1 historical analogs
      +
V2 statistical model
      |
      v
V3 conservative ensemble
      |
      v
V3.1 calibration/reliability suppression
```

V3.1 has useful safety semantics: ticker-specific reliability where validated, a conservative prior otherwise, source-timestamp provenance, and suppression of low-reliability probabilities. OurAI should eventually replace the final prediction path, but the migration gate must compare both systems on identical timestamps, symbols and horizons.

## OurAI unified forecast contract

The eventual Orion/OurAI interface should expose a versioned, point-in-time envelope similar to:

```json
{
  "symbol": "NVDA",
  "as_of": "...",
  "model_id": "...",
  "data_lineage": "...",
  "horizons": {
    "5m": {
      "probability_up": 0.0,
      "probability_down": 0.0,
      "expected_return_pct": 0.0,
      "return_q10_pct": 0.0,
      "return_q50_pct": 0.0,
      "return_q90_pct": 0.0,
      "calibrated_confidence": 0.0,
      "decision": "NO_TRADE"
    }
  }
}
```

Recommended initial horizons: 5m, 15m, 30m, 1h. Longer horizons can be added only with enough resolved OOS coverage.

## Replacement gate before retiring an incumbent

For every incumbent/horizon pair, compare OurAI and the incumbent on the exact same point-in-time observations. At minimum:

- chronological / purged or otherwise leakage-safe OOS evaluation
- same symbol universe and timestamps
- minimum observation and independent-session counts fixed before score inspection
- Brier score and log loss for direction probabilities
- calibration / ECE and reliability curves
- directional accuracy as a secondary metric
- expected-return MAE and/or robust loss
- quantile/prediction-interval coverage once distributional outputs exist
- abstention/NO_TRADE coverage and conditional performance
- net performance after conservative spread, slippage and fees
- session-block bootstrap or equivalent dependence-aware uncertainty
- explicit fail-closed behavior for missing/stale features
- no tuning on the same lockbox used for promotion

An incumbent is retired only when the unified model demonstrates a material, stable improvement and does not create a calibration or reliability regression.

## Immediate development plan

1. **Freeze expansion of independent stock-specific production engines.** Existing specialists remain research baselines.
2. Define a shared, point-in-time training table from Orion features with symbol, session and regime context.
3. Start with strong tabular baselines for direction + return magnitude before adding more complex temporal architectures.
4. Train/evaluate unified models on multiple liquid stocks, not one ticker at a time.
5. Add ticker identity and sector/regime context; test specialist adapters only after the shared model baseline is established.
6. Reuse Orion's leakage-safe evidence/settlement tooling to run matched incumbent-vs-OurAI tournaments.
7. Integrate the winning forecast contract into Orion while retaining Orion-side acquisition, risk, UI and audit lineage.
8. Remove old runtime prediction paths only in separate, reviewable PRs after replacement gates pass.

## Non-goals of this audit

- no deletion of existing engines
- no change to live trading or broker routes
- no change to probability/calibration thresholds
- no claim that any existing or future model can predict markets with certainty
- no automatic model promotion

This audit intentionally favors evidence-preserving consolidation over a destructive rewrite.
