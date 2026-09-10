# Regular-hours V4 frozen benchmark failure diagnostic

The first frozen real-data benchmark completed on 2026-09-10 against the predeclared 60d/5m universe `AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AMD, SPY, QQQ`. The immutable evidence result was `v4_not_demonstrated` with benchmark SHA-256 `4ec8d0a305f10b7d95a81f03cd4cfec46517b20e2baeea780c6e9714942eaab3`.

## Aggregate result

Against raw V3, V4 regressed at 30m (Brier improvement -0.000420; log-loss improvement -0.000829) and failed the proper-score gate at 1h (Brier -0.000125; log loss +0.000102). At 3h and 5h the aggregate proper scores were positive (+0.001742/+0.004539 and +0.001194/+0.002409 respectively), but only 2/10 and 1/10 symbols were session-stable research-eligible, so neither horizon passed.

Against held-out leakage-safe V3.1, 30m again regressed (Brier -0.000344; log loss -0.000703). The 1h, 3h and 5h aggregate proper scores were slightly positive, but session stability failed on every horizon; research-eligible symbol counts were 0/10, 1/10 and 0/10 respectively.

## Decision

V4 is rejected unchanged. This result must not be used to tune V4 and rerun the same frozen dataset until it passes. The benchmark remains a diagnostic record, not a development target.

The strongest reproducible finding is that the V4 regime interaction is harmful at 30m against both incumbents. There is a weaker hypothesis that the regime-aware feature family may contain useful information at longer horizons, because 3h/5h aggregate proper scores improved while symbol/session stability did not. That is not promotion evidence.

## Next safe step

Do not modify V4. If pursuing the longer-horizon hypothesis, specify a distinct V5 regular-hours challenger before observing a new evaluation window, narrow its design objective to stable 3h/5h probability quality, and keep 30m/1h on the incumbent path unless separate evidence supports replacement. The new candidate must re-enter the full paired walk-forward tournament against V3 and V3.1 on a fresh chronological holdout and then pass forward cloud-shadow evidence before any runtime consideration.

`backend/evals/diagnose_intraday_v4_failure.py` codifies these failure classes so future frozen benchmark artifacts can be evaluated consistently without ad-hoc interpretation.
