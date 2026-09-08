# Milestone 3 — Point-in-time evidence and decision quality

Version `2.3.0`, 2026-09-02.

This release records the difference between when a market event happened and when Orion received it. Completed one-minute bars and explicitly requested broker snapshots are retained per user in a bounded evidence ledger. Corrections append a new observation; prior observations are never overwritten or silently pruned.

Every new final decision receives a prospectively frozen evaluation contract. It records the source, reference close, exact horizon close, neutral threshold, probability snapshot, and collection window at decision time. Decisions from earlier releases without that contract are legacy records and are not scored retroactively.

The `check_outcomes` job evaluates all eligible final decisions, including WAIT forecasts. It requires exact same-source reference and horizon observations, never substitutes a next bar, and keeps missing or revised observations unresolved. Settled labels are immutable; later checks are diagnostics only. Quality reporting selects non-overlapping windows before outcomes, reports coverage and distinct sessions, and remains descriptive. `review_ready` means enough evidence to inspect (100 settled records, 20 sessions and 80% due-window coverage); it never claims reliability, changes model weights, changes probabilities, or promotes a model.

My Stocks includes an expandable Decision quality panel and an opt-in Update outcomes action. Collection occurs only during explicit analysis, scans, or outcome checks; it is not an always-on recorder. The ledger is capped at 250,000 observations and stops at capacity without deleting user data.

The application remains assistant-only. There is no automatic order route, fill claim, achieved P&L calculation, or GPT-controlled probability. Orion AI may explain deterministic results only after the numeric pipeline completes.
