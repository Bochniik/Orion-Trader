from __future__ import annotations

import logging
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from math import isfinite
from threading import Event, RLock, Thread
from typing import Any, Dict, Optional

from app.services.premarket_candidate_selector import screen_premarket_candidates
from app.services.premarket_data_adapter import PremarketDataAdapter
from app.services.premarket_live_engine import (
    premarket_session_active,
    synthesize_live_premarket_candidate,
)
from app.services.premarket_ranking_engine import rank_premarket_candidate

log = logging.getLogger("orion.premarket.continuous")


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def baseline_from_snapshot(snapshot: Any) -> Optional[Dict[str, Any]]:
    """Build completed-session liquidity context from an Alpaca snapshot."""
    if not isinstance(snapshot, dict):
        return None
    previous = snapshot.get("prevDailyBar") or snapshot.get("previousDailyBar") or {}
    close = _finite(previous.get("c"))
    volume = _finite(previous.get("v"))
    if close is None or close <= 0 or volume is None or volume < 0:
        return None
    return {
        "price": close,
        "previous_close": close,
        "dollar_volume": close * volume,
        "volume": volume,
    }


class PremarketContinuousScheduler:
    """Continuous 04:00-09:30 ET premarket research scanner.

    Frozen 06:45/08:00/09:15 snapshots remain separate evidence checkpoints.
    This service is the live product path: while the backend is alive and a user
    has an active Alpaca research connection it repeatedly discovers liquid names,
    screens current premarket activity, runs Premarket V5 and publishes a ranked
    live state. It never enables order submission.
    """

    def __init__(self, broker, market_data, *, interval_seconds: Optional[int] = None, clock=None):
        self.broker = broker
        self.market_data = market_data
        self.interval_seconds = max(
            60,
            int(interval_seconds or os.getenv("ORION_PREMARKET_SCAN_INTERVAL_SECONDS", "180")),
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.adapter = PremarketDataAdapter(broker, market_data)
        self.lock = RLock()
        self.active_users: set[str] = set()
        self.states: Dict[str, Dict[str, Any]] = {}
        self.stop_event = Event()
        self.wake = Event()
        self.thread: Optional[Thread] = None

    @staticmethod
    def _empty_state(now: datetime) -> Dict[str, Any]:
        return {
            "status": "waiting_for_premarket",
            "session": "premarket",
            "generated_at": None,
            "last_attempt_at": None,
            "last_successful_scan": None,
            "next_scan_at": now.isoformat(),
            "candidates": [],
            "diagnostics": {},
            "failure": None,
            "research_only": True,
            "order_submission_enabled": False,
        }

    def activate_user(self, user_id: str) -> None:
        now = self.clock()
        key = str(user_id)
        with self.lock:
            self.active_users.add(key)
            self.states.setdefault(key, self._empty_state(now))
            self.states[key]["next_scan_at"] = now.isoformat()
        self.wake.set()

    def deactivate_user(self, user_id: str) -> None:
        with self.lock:
            self.active_users.discard(str(user_id))
        self.wake.set()

    def _provider_connected(self, user_id: str) -> bool:
        try:
            return self.broker.status(user_id).get("connected") is True
        except Exception:
            return False

    def _build_baselines(self, user_id: str, symbols: list[str]) -> Dict[str, Dict[str, Any]]:
        snapshots = self.broker.snapshots(user_id, symbols)
        observations: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            baseline = baseline_from_snapshot((snapshots or {}).get(symbol))
            if baseline is not None:
                observations[symbol] = baseline
        return observations

    def run_cycle(self, user_id: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or self.clock()
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        key = str(user_id)

        with self.lock:
            state = deepcopy(self.states.setdefault(key, self._empty_state(now)))
        state["last_attempt_at"] = now.isoformat()

        if not premarket_session_active(now):
            state.update(
                status="waiting_for_premarket",
                candidates=[],
                failure=None,
                next_scan_at=(now + timedelta(seconds=self.interval_seconds)).isoformat(),
            )
            with self.lock:
                self.states[key] = state
            return {"status": state["status"], "candidate_count": 0}

        if not self._provider_connected(key):
            state.update(
                status="provider_unavailable",
                failure={"reason": "alpaca_not_connected", "at": now.isoformat()},
                next_scan_at=(now + timedelta(seconds=self.interval_seconds)).isoformat(),
            )
            with self.lock:
                self.states[key] = state
            return {"status": state["status"], "candidate_count": 0}

        try:
            discovery, discovery_errors = self.broker.liquidity_candidates(key, limit=100)
            symbols = list(dict.fromkeys(str(symbol).strip().upper() for symbol in discovery if symbol))
            observations = self._build_baselines(key, symbols)
            screened = screen_premarket_candidates(
                self.broker,
                key,
                observations,
                now=now,
                pool_limit=100,
                finalist_limit=15,
                batch_size=50,
                maximum_age_minutes=30,
            )

            candidates = []
            analysis_failures = []
            for screen_row in screened.get("items") or []:
                symbol = screen_row["ticker"]
                try:
                    setup = self.adapter.build(
                        key,
                        symbol,
                        now=now,
                        previous_close_override=screen_row.get("previous_close"),
                        average_dollar_volume=screen_row.get("baseline_dollar_volume"),
                    )
                    rank = rank_premarket_candidate(setup)
                    predictive = setup.get("predictive_outlook") or {}
                    v5 = predictive.get("premarket_research") or {}
                    live = synthesize_live_premarket_candidate(
                        ticker=symbol,
                        setup=setup.get("analysis") or setup,
                        rank=rank,
                        v5_outlook=v5,
                        now=now,
                    )
                    live.update(
                        premarket_price=setup.get("premarket_price"),
                        previous_close=setup.get("previous_close"),
                        gap_pct=setup.get("gap_pct"),
                        data_timestamp=setup.get("data_timestamp"),
                        predictive_as_of=setup.get("predictive_as_of"),
                        predictive_feed=setup.get("predictive_feed"),
                        screen_score=screen_row.get("premarket_screen_score"),
                        rank_score=rank.get("premarket_rank_score"),
                        setup_score=setup.get("premarket_score"),
                        feed=setup.get("feed"),
                        delayed=setup.get("delayed"),
                    )
                    candidates.append(live)
                except Exception as exc:
                    analysis_failures.append({
                        "ticker": symbol,
                        "reason": "analysis_failed:" + type(exc).__name__,
                    })

            candidates.sort(
                key=lambda row: (
                    row.get("direction") == "NO_TRADE",
                    -(row.get("premarket_orion_score") or 0.0),
                    -max(row.get("probability_up") or 0.0, row.get("probability_down") or 0.0),
                    row.get("ticker") or "",
                )
            )

            state.update(
                status="ready" if candidates else "no_current_candidates",
                generated_at=now.isoformat(),
                last_successful_scan=now.isoformat(),
                next_scan_at=(now + timedelta(seconds=self.interval_seconds)).isoformat(),
                candidates=candidates[:15],
                failure=None,
                diagnostics={
                    "discovery_symbol_count": len(symbols),
                    "baseline_count": len(observations),
                    "discovery_errors": list(discovery_errors or []),
                    "screen": {k: deepcopy(v) for k, v in screened.items() if k != "items"},
                    "analysis_failure_count": len(analysis_failures),
                    "analysis_failures": analysis_failures[:10],
                    "scan_interval_seconds": self.interval_seconds,
                    "architecture": "continuous_live_premarket",
                    "frozen_checkpoints_are_evidence_only": True,
                },
            )
        except Exception as exc:
            state.update(
                status="scan_failed",
                failure={"reason": "premarket_scan_failed:" + type(exc).__name__, "at": now.isoformat()},
                next_scan_at=(now + timedelta(seconds=self.interval_seconds)).isoformat(),
            )
            log.warning("continuous premarket scan failed type=%s", type(exc).__name__)

        with self.lock:
            self.states[key] = state
        return {"status": state["status"], "candidate_count": len(state.get("candidates") or [])}

    def current_state(self, user_id: str) -> Dict[str, Any]:
        now = self.clock()
        key = str(user_id)
        with self.lock:
            state = deepcopy(self.states.get(key) or self._empty_state(now))
            active = key in self.active_users
        state["scanner_running"] = bool(
            self.thread and self.thread.is_alive() and not self.stop_event.is_set() and active
        )
        state["session_active"] = premarket_session_active(now)
        state["as_of"] = now.isoformat()
        state["semantics"] = (
            "Continuous 04:00-09:30 ET premarket research scanner. P(UP)/P(DOWN) "
            "come from Premarket V5 short-horizon forecasts; Premarket Orion Score "
            "is a separate deterministic research-quality score, not probability."
        )
        return state

    def run_due_once(self, *, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or self.clock()
        with self.lock:
            users = sorted(self.active_users)
            states = {user: deepcopy(self.states.get(user) or self._empty_state(now)) for user in users}
        due = []
        for user in users:
            raw = states[user].get("next_scan_at")
            try:
                stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else now
            except ValueError:
                stamp = now
            if stamp <= now:
                due.append(user)
        if not due:
            return {"status": "idle"}
        return self.run_cycle(due[0], now=now)

    def start(self) -> bool:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return True
            self.stop_event.clear()
            self.thread = Thread(target=self._loop, name="orion-premarket-scanner", daemon=True)
            self.thread.start()
        return True

    def _loop(self) -> None:
        log.info("continuous premarket loop started interval=%ss", self.interval_seconds)
        try:
            while not self.stop_event.is_set():
                try:
                    self.run_due_once()
                except Exception as exc:
                    log.warning("continuous premarket pass failed type=%s", type(exc).__name__)
                self.wake.wait(1)
                self.wake.clear()
        finally:
            log.info("continuous premarket loop stopped")

    def stop(self, timeout: int = 5) -> bool:
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=timeout)
        return not self.thread or not self.thread.is_alive()
