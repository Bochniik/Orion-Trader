"""One lifecycle thread, bounded cycles and user-isolated current scanner state.

Only scanner state is mutable here. Prediction/evaluation records, model
artifacts and the staged opportunity formula are not modified.
"""
import hashlib
import logging
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from math import ceil
from threading import Event, Lock, RLock, Thread

from app.services.scanner_runtime import MarketClosed, MarketSessionUnverified, ScannerCancelled
from app.services.scanner_settings import ScannerSettings
from app.services.staged_market_scanner import finite, timestamp
from app.services.market_intelligence import current_categories, merge_observations
from app.services.opportunity_learning_runtime import OpportunityLearningRuntime

log = logging.getLogger("orion.scanner")

ORION_PICK_MIN_SCORE = 70.0
ORION_PICK_LIMIT_PER_HORIZON = 5


def utc_now():
    return datetime.now(timezone.utc)


def after(now, seconds):
    return (now + timedelta(seconds=seconds)).isoformat()


def age(value, now):
    stamp = timestamp(value)
    return (now - stamp).total_seconds() if stamp else None


def new_state():
    return {"schema_version": 1, "snapshot": None, "previous_snapshot": None,
            "last_successful_scan": None, "last_attempt_at": None, "failure": None,
            "last_cycle_diagnostics": None,
            "market_intelligence": {},
            "historical_market_intelligence": {}, "market_session": None,
            "research_setups": {}, "research_diagnostics": {},
            "learning_last_write": None, "learning_last_resolution": None,
            "active": {}, "next_broad_at": None, "next_active_at": None, "next_allowed_at": None,
            "universe": {"total_symbols": 0, "current_page": 0, "pages_completed": 0,
                         "symbols_scanned_this_cycle": 0, "next_offset": 0,
                         "last_full_rotation": None, "fingerprint": None, "rotation_complete": False}}


class _Session:
    def __init__(self, state, restored, runner, cancel, learning=None):
        self.state, self.restored, self.runner, self.cancel = state, restored, runner, cancel
        self.learning = learning
        self.cycle_running = False


class ScannerScheduler:
    def __init__(self, store, runner_factory, connected, settings=None, *, clock=None):
        self.store, self.runner_factory, self.connected = store, runner_factory, connected
        self.settings = settings or ScannerSettings.from_env()
        self.clock = clock or utc_now
        self.price_age_limit = self.settings.stage_config().maximum_snapshot_age_seconds
        self.sessions, self.lock, self.cycle_lock = {}, RLock(), Lock()
        self.stop_event, self.wake = Event(), Event()
        self.thread = None

    def _load_state(self, user_id):
        try:
            saved = self.store.load(user_id)
            if saved is None:
                return new_state(), False
            if (not isinstance(saved, dict) or saved.get("schema_version") != 1
                    or not isinstance(saved.get("active"), dict) or not isinstance(saved.get("universe"), dict)
                    or saved.get("snapshot") is not None and not isinstance(saved["snapshot"], dict)):
                raise ValueError("Invalid scanner state document")
            return {**new_state(), **saved}, True
        except Exception as exc:
            state = new_state()
            state["failure"] = {"at": self.clock().isoformat(), "mode": "recovery",
                                "reason": "state_read_failed:" + type(exc).__name__}
            return state, False

    def activate_user(self, user_id, database_path, *, restart=False):
        """Called after authenticated broker connection/login, never by a GET."""
        user_id = str(user_id)
        with self.lock:
            previous = self.sessions.get(user_id)
            # Session-cookie restoration must not cancel in-flight work or
            # reset the universe cursor whenever /auth/session is read.
            if previous and not previous.cancel.is_set() and not restart:
                return False
            if not self.settings.enabled or not self._is_connected(user_id):
                return False
            if previous:
                previous.cancel.set()
            state, restored = self._load_state(user_id)
            now = self.clock()
            state["next_broad_at"] = now.isoformat()
            state["next_active_at"] = after(now, self.settings.active_interval_seconds)
            # A restart refresh is bounded and does not bypass request spacing.
            cancel = Event()
            runner = self.runner_factory(user_id, database_path, cancel)

            # Persistent learning history lives in a separate SQLite database
            # beside the application's existing DB. Replacing Python files does
            # not delete this database.
            learning = OpportunityLearningRuntime(
                user_id,
                database_path,
            )

            self.sessions[user_id] = _Session(
                state,
                restored,
                runner,
                cancel,
                learning=learning,
            )
        self.wake.set()
        return True

    def deactivate_user(self, user_id):
        with self.lock:
            session = self.sessions.get(str(user_id))
            if session:
                session.cancel.set()
        self.wake.set()

    def _is_connected(self, user_id):
        return self.provider_availability(user_id)["available"]

    def provider_availability(self, user_id):
        try:
            result = self.connected(user_id)
            if isinstance(result, dict):
                return {**result, "available": result.get("available") is True}
            return {"available": result is True, "reason_code": "provider_configured" if result is True else "provider_not_connected",
                    "message": "Market-data source is connected." if result is True else "No market-data source is connected for this user."}
        except Exception:
            return {"available": False, "reason_code": "provider_configuration_check_failed",
                    "message": "Market-data configuration could not be checked."}

    def _prune(self, state, now):
        state["active"] = {symbol: item for symbol, item in state["active"].items()
                           if age(item.get("last_interesting_at"), now) is not None
                           and 0 <= age(item["last_interesting_at"], now) < self.settings.active_ttl_seconds
                           and item.get("inactive_cycles", 0) < self.settings.inactive_cycles}

    def run_scan_cycle(self, user_id, mode="broad", *, now=None):
        """Manual one-cycle entry point; also used by the timer, no scheduler needed.

        Explicit now is a deterministic provider cutoff. Real cycles leave it
        unset so the existing core checks freshness after provider retrieval.
        """
        if mode not in {"broad", "active"}:
            raise ValueError("Scan mode must be broad or active")
        user_id = str(user_id)
        if not self.cycle_lock.acquire(blocking=False):
            return {"status": "busy"}
        session = None
        fixed_now, started = now, now or self.clock()
        try:
            with self.lock:
                session = self.sessions.get(user_id)
                if not session or session.cancel.is_set() or not self._is_connected(user_id):
                    return {"status": "unavailable", "reason": "broker_not_connected_or_session_inactive"}
                if timestamp(session.state.get("next_allowed_at")) and started < timestamp(session.state["next_allowed_at"]):
                    return {"status": "rate_limited"}
                state = deepcopy(session.state)
                session.cycle_running = True
            self._prune(state, started)
            selected = []
            try:
                closed = False
                if mode == "broad" or state["active"]:
                    try:
                        session.runner.prepare()
                        state["market_session"] = "open"
                    except MarketClosed:
                        if not callable(getattr(session.runner, "historical_page", None)):
                            raise
                        closed = True
                        state["market_session"] = "closed"
                if closed:
                    state["historical_market_intelligence"] = session.runner.historical_page(
                        state.get("historical_market_intelligence"), now=started)
                    state["failure"] = None
                    result = None
                elif mode == "broad":
                    universe = session.runner.universe()
                    normalized = {s.strip().upper() for s in universe.get("tickers", []) if isinstance(s, str)}
                    # Identical acceptance to the staged core: otherwise its
                    # filtered page offsets and our rotation cursor diverge.
                    symbols = sorted(s for s in normalized if s and len(s) <= 15
                                     and all(c.isalnum() or c in ".-^" for c in s))
                    fingerprint = hashlib.sha256("\n".join(symbols).encode()).hexdigest()
                    rotation = state["universe"]
                    if rotation.get("fingerprint") != fingerprint or rotation.get("page_size") != self.settings.page_size:
                        rotation = dict(new_state()["universe"], fingerprint=fingerprint, universe_changed_at=started.isoformat())
                        state["universe"] = rotation
                        state["active"] = {s: item for s, item in state["active"].items() if s in set(symbols)}
                    if rotation.get("rotation_complete"):
                        rotation.update(next_offset=0, pages_completed=0, symbols_scanned_this_cycle=0, rotation_complete=False)
                    offset = rotation.get("next_offset", 0)
                    if offset >= len(symbols):
                        offset = 0
                    selected = symbols[offset:offset + self.settings.page_size]
                    result = session.runner.scan(symbols, offset=offset, now=fixed_now)
                else:
                    symbols = sorted(state["active"])
                    selected = symbols
                    if not symbols:
                        # Empty active refresh is a no-op, not evidence that a broad
                        # universe scan found nothing. No provider request is needed.
                        result = None
                    else:
                        result = session.runner.scan(symbols, offset=0, now=fixed_now)
                finished = fixed_now or self.clock()
                if result is not None:
                    research = result.get("research_setups")
                    if research is not None:
                        pool = state.setdefault("research_setups", {})
                        observed = set(result.get("market_observed_symbols") or [])
                        for key in list(pool):
                            if pool[key]["ticker"] in observed:
                                pool.pop(key)
                        for key in research.get("evaluated_keys", []):
                            pool.pop(key, None)
                        research_items = list(
                            research.get(
                                "items",
                                [],
                            )
                        )

                        for row in research_items:
                            pool[row["ticker"] + ":" + row["horizon"]] = row

                        # Persistent learning history is separate from the
                        # bounded in-memory research_setups pool.
                        if session.learning is not None and research_items:
                            learning_write = session.learning.observe(
                                research_items,
                                observed_at=finished.isoformat(),
                            )
                            state[
                                "learning_last_write"
                            ] = learning_write

                        # Bounded cross-page research state, not journal history.
                        ordered_pool = sorted(pool, key=lambda key: (-(timestamp(pool[key]["data_timestamp"]).timestamp()), -pool[key]["quality_score"], key))
                        state["research_setups"] = {k: pool[k] for k in ordered_pool[:300]}
                        state["research_diagnostics"] = {k: deepcopy(v) for k, v in research.items() if k != "items"}
                    # Reuse screened inputs, including symbols without a fitted
                    # model. A partial provider failure only invalidates symbols
                    # actually observed; missing rows retain their original age.
                    if "market_intelligence_rows" in result:
                        state["market_intelligence"] = merge_observations(
                            state.get("market_intelligence"), result["market_intelligence_rows"],
                            invalidated=result.get("market_observed_symbols", []) if result.get("partial_failure") else selected,
                            now=finished, config=self.settings.stage_config(),
                            universe=set(symbols) if mode == "broad" else None)
                        state["market_intelligence"].update(
                            provider=deepcopy(session.runner.provider),
                            partial_failure=bool(result.get("partial_failure")))
                        if mode == "broad":
                            state["market_intelligence"]["last_broad_scan_at"] = finished.isoformat()
                    state["last_cycle_diagnostics"] = {
                        "at": finished.isoformat(), "mode": mode,
                        "stage_counts": deepcopy(result.get("stage_counts") or {}),
                        "partial_failure": bool(result.get("partial_failure")),
                        "provider_failure_count": len(result.get("errors") or []),
                    }
                    # Market observations and model-qualified picks are separate
                    # results. A usable partial page must advance even when no
                    # saved model can produce a pick, otherwise page one starves
                    # the entire rotation indefinitely.
                    partial_empty = bool(result.get("partial_failure") and not result.get("candidates"))
                    valid_market_rows = finite((result.get("stage_counts") or {}).get("valid_data_count")) or 0
                    if partial_empty and valid_market_rows <= 0:
                        raise RuntimeError("incomplete_provider_scan")
                    if not (partial_empty and state.get("snapshot") and not state["snapshot"].get("candidates")
                            and state.get("previous_snapshot")):
                        state["previous_snapshot"] = state.get("snapshot")
                    state["snapshot"] = {"generated_at": result.get("generated_at", finished.isoformat()),
                                         "scan_mode": mode, "provider": deepcopy(session.runner.provider),
                                         "candidates": (result.get("candidates") or [])[:self.settings.result_limit],
                                         "partial_failure": bool(result.get("partial_failure")),
                                         "diagnostics": {key: deepcopy(result.get(key)) for key in (
                                             "stage_counts", "exclusion_counts", "capacity_exclusions", "unavailable_analyses")},
                                         "provider_failure_count": len(result.get("errors") or [])}
                    state["last_successful_scan"] = finished.isoformat()
                    state["failure"] = None

                    # Outcome resolution is bounded and non-fatal. It only uses
                    # already-due forecasts and never changes the prediction
                    # that created them.
                    if session.learning is not None:
                        state[
                            "learning_last_resolution"
                        ] = session.learning.resolve(
                            now=finished,
                            max_forecasts=12,
                        )

                    self._update_active(state, result, selected, finished)
                    if mode == "broad":
                        rotation = state["universe"]
                        rotation.update(total_symbols=len(symbols), page_size=self.settings.page_size,
                                        current_page=offset // self.settings.page_size + 1 if symbols else 0,
                                        pages_total=ceil(len(symbols) / self.settings.page_size),
                                        source=universe.get("source"), complete_us_universe=False,
                                        next_offset=offset + len(selected),
                                        pages_completed=rotation["pages_completed"] + int(bool(symbols)),
                                        symbols_scanned_this_cycle=rotation["symbols_scanned_this_cycle"] + len(selected))
                        if rotation["next_offset"] >= len(symbols) and symbols:
                            rotation.update(next_offset=0, last_full_rotation=finished.isoformat(), rotation_complete=True)
                status = "historical_completed" if closed else "completed" if result is not None else "no_active_candidates"
            except ScannerCancelled:
                return {"status": "cancelled"}
            except Exception as exc:
                finished = fixed_now or self.clock()
                if isinstance(exc, MarketClosed):
                    reason, message = "market_closed", "The regular market session is closed. The provider is connected; any last valid results remain stale until scanning resumes."
                elif isinstance(exc, MarketSessionUnverified):
                    reason, message = "market_session_unverified", "The provider is connected but did not return a valid market-session state. Orion will retry automatically."
                else:
                    reason = "scan_failed:" + type(exc).__name__
                    message = "The configured provider scan failed (" + type(exc).__name__ + "). Orion will retry automatically; inspect provider connectivity and market-data access."
                    # Extract only the documented status prefix, never an API
                    # response body (which may contain sensitive information).
                    http_status = re.match(r"Alpaca paper API error \((\d{3})\):", str(exc))
                    if http_status:
                        code = http_status.group(1)
                        reason = "alpaca_http_" + code
                        detail = {"401": "credentials were rejected; reconnect Alpaca",
                                  "403": "access was denied; check market-data permissions/entitlements",
                                  "429": "the provider rate limit was reached"}.get(code, "the provider request failed")
                        message = f"Alpaca HTTP {code}: {detail}. No new scan is published; automatic retry remains bounded."
                    elif str(exc) == "incomplete_provider_scan":
                        message = "Provider data was incomplete and no valid candidate was returned. Last valid results are retained as stale; Orion will retry automatically."
                state["failure"] = {"at": finished.isoformat(), "mode": mode, "reason": reason, "message": message}
                status = "failed"
                log.warning("scanner cycle failed mode=%s reason=%s", mode, reason)
            state["last_attempt_at"] = started.isoformat()
            state["next_allowed_at"] = after(finished, self.settings.minimum_cycle_gap_seconds)
            state["next_active_at"] = after(finished, self.settings.active_interval_seconds)
            if mode == "broad":
                state["next_broad_at"] = after(finished, self.settings.broad_interval_seconds)
                next_open = timestamp((state.get("historical_market_intelligence") or {}).get("next_open"))
                if state.get("market_session") == "closed" and next_open:
                    state["next_broad_at"] = min(timestamp(state["next_broad_at"]),
                                                max(next_open, timestamp(state["next_allowed_at"]))).isoformat()
            with self.lock:
                if session.cancel.is_set() or self.sessions.get(user_id) is not session or not self._is_connected(user_id):
                    return {"status": "cancelled"}
                try:
                    self.store.save(user_id, state)
                except Exception as exc:
                    # Do not publish an unpersisted new result or retry every
                    # scheduler tick while storage is unavailable.
                    failed = deepcopy(session.state)
                    failed.update({key: state[key] for key in (
                        "last_attempt_at", "next_allowed_at", "next_active_at", "next_broad_at", "last_cycle_diagnostics")})
                    failed["failure"] = {"at": finished.isoformat(), "mode": mode,
                                         "reason": "state_write_failed:" + type(exc).__name__}
                    session.state = failed
                    log.warning("scanner state write failed type=%s", type(exc).__name__)
                    return {"status": "failed", "mode": mode}
                session.state = state
                if status in {"completed", "historical_completed"}:
                    session.restored = False
            counts = ((state.get("snapshot") or {}).get("diagnostics") or {}).get("stage_counts") or {}
            log.info("scanner cycle mode=%s status=%s screened=%s analyzed=%s returned=%s", mode, status,
                     counts.get("screened_count", 0), counts.get("fully_analyzed", 0), counts.get("returned", 0))
            return {"status": status, "mode": mode}
        finally:
            if session:
                with self.lock:
                    session.cycle_running = False
            self.cycle_lock.release()

    def _update_active(self, state, result, selected, now):
        interesting = {r["ticker"]: r for r in result.get("active_candidates", []) if r.get("ticker") in selected}
        for row in result.get("candidates") or []:
            if row.get("ticker") in selected:
                interesting.setdefault(row["ticker"], row)
        if not result.get("partial_failure"):
            for symbol in set(selected) & set(state["active"]) - set(interesting):
                state["active"][symbol]["inactive_cycles"] += 1
        for symbol, item in interesting.items():
            price_age, feature_age = age(item.get("data_timestamp"), now), age(item.get("feature_timestamp"), now)
            if price_age is None or feature_age is None or not 0 <= price_age <= self.price_age_limit or not 0 <= feature_age <= self.settings.maximum_feature_age_seconds:
                continue
            state["active"][symbol] = {"ticker": symbol, "last_interesting_at": now.isoformat(), "inactive_cycles": 0,
                                       "fast_signal_score": finite(item.get("fast_signal_score")) or 0,
                                       "activity_score": finite(item.get("activity_score")) or 0,
                                       "liquidity_score": finite(item.get("liquidity_score")) or 0,
                                       "setup_tags": item.get("setup_tags") or []}
        self._prune(state, now)
        ordered = sorted(state["active"].values(), key=lambda r: (-r["fast_signal_score"], -r["liquidity_score"], r["ticker"]))
        state["active"] = {r["ticker"]: r for r in ordered[:self.settings.active_limit]}

    def run_due_once(self, *, now=None):
        fixed_now = now
        now = now or self.clock()
        due = []
        with self.lock:
            for user, session in self.sessions.items():
                if session.cancel.is_set() or not self._is_connected(user):
                    continue
                minimum = timestamp(session.state.get("next_allowed_at")) or now
                broad = timestamp(session.state.get("next_broad_at")) or now
                active = timestamp(session.state.get("next_active_at")) or now
                if max(broad, minimum) <= now:
                    due.append((broad, 0, user, "broad"))
                elif session.state["active"] and max(active, minimum) <= now:
                    due.append((active, 1, user, "active"))
        if not due:
            return {"status": "idle"}
        _, _, user, mode = min(due)
        return self.run_scan_cycle(user, mode, now=fixed_now)

    def start(self):
        if not self.settings.enabled:
            return False
        with self.lock:
            if self.thread and self.thread.is_alive():
                return not self.stop_event.is_set()
            self.stop_event.clear()
            self.thread = Thread(target=self._loop, name="orion-scanner", daemon=True)
            self.thread.start()
        return True

    def _loop(self):
        log.info("scanner loop started broad=%ss active=%ss", self.settings.broad_interval_seconds, self.settings.active_interval_seconds)
        try:
            while not self.stop_event.is_set():
                try:
                    self.run_due_once()
                except Exception as exc:
                    log.warning("scanner pass failed type=%s", type(exc).__name__)
                self.wake.wait(1)
                self.wake.clear()
        finally:
            log.info("scanner loop stopped")

    def stop(self, timeout=5):
        self.stop_event.set()
        with self.lock:
            for session in self.sessions.values():
                session.cancel.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=timeout)
        return not self.thread or not self.thread.is_alive()

    def current_state(self, user_id, *, now=None):
        now, user_id = now or self.clock(), str(user_id)
        with self.lock:
            session = self.sessions.get(user_id)
            if session:
                state, restored = deepcopy(session.state), session.restored
            else:
                state, restored = self._load_state(user_id)
            session_active = bool(session and not session.cancel.is_set() and self._is_connected(user_id))
            cycle_running = bool(session and session.cycle_running)
        self._prune(state, now)
        snapshot = state.get("snapshot") or {}
        snapshot_age = age(snapshot.get("generated_at"), now)
        stale = bool(state.get("failure") or state.get("market_session") == "closed" or restored or not session_active or not self.settings.enabled
                     or snapshot_age is None or not 0 <= snapshot_age <= self.settings.snapshot_ttl_seconds)
        known_delayed = (snapshot.get("provider") or {}).get("feature_feed_delayed") is True
        rows = [self._candidate_view(row, now, stale, snapshot.get("partial_failure", False), known_delayed)
                for row in snapshot.get("candidates") or []]
        top = [row for row in rows if row["scanner_freshness"]["state"] not in {"stale", "unavailable"}]
        top.sort(key=lambda r: (not r["eligible_for_current"], -r["freshness_adjusted_score"], r["ticker"]))
        fresh = "unavailable" if not snapshot else "stale" if stale or rows and not top else (
            "delayed" if any(r["scanner_freshness"]["state"] == "delayed" for r in top)
            or snapshot.get("provider", {}).get("feature_feed_delayed") else "current")
        status = ("disabled" if not self.settings.enabled else "unavailable" if not snapshot else "stale" if fresh == "stale"
                  else "partial_failure" if snapshot.get("partial_failure") else "no_high_quality_candidates" if not top else "ready")
        availability = self.provider_availability(user_id)
        failure = state.get("failure") or {}
        if not self.settings.enabled:
            message = "Continuous scanning is disabled by ORION_SCANNER_ENABLED=false."
        elif not availability["available"]:
            message = availability["message"]
        elif failure:
            message = failure.get("message") or "Scanner could not recover or persist its state: " + failure["reason"]
            if not snapshot and failure.get("reason") == "market_closed":
                status = "market_closed"
        elif not session_active:
            message = "Provider is configured but this user's scanner session is inactive. Restore your authenticated session or sign in again."
            if not snapshot:
                status = "inactive"
        elif not snapshot:
            status = "starting"
            message = "Market-data source is connected. The first bounded scanner page is queued or running."
        elif snapshot.get("partial_failure"):
            message = "A partial market scan was published. Some provider data could not be evaluated; coverage is incomplete."
            if not snapshot.get("candidates"):
                message += " No model-qualified Orion Picks were produced; usable market observations remain available in the other TODAY categories."
        else:
            message = "Latest scanner observations are available; freshness and partial coverage apply."
        historical = state.get("historical_market_intelligence") or {}
        if state.get("market_session") == "closed" and availability["available"] and not failure and self.settings.enabled:
            status = "market_closed"
            message = ("Regular market closed. Latest completed-session market categories are available in TODAY; "
                       "historical prices are not live signals. No new Orion Picks are generated while closed.")
            if not historical.get("observations"):
                message = "Regular market closed. No liquidity-qualified completed-session observations received yet; historical loading will retry automatically."
        last_known = rows if not top else []
        if not rows and snapshot.get("partial_failure"):
            last_known = [self._candidate_view(row, now, True, True, known_delayed)
                          for row in (state.get("previous_snapshot") or {}).get("candidates") or []]
        return {"status": status, "generated_at": snapshot.get("generated_at"), "as_of": now.isoformat(),
                "research_opportunities": self.opportunity_state(user_id, now=now),
                "message": message, "provider_availability": availability,
                "last_successful_scan": state["last_successful_scan"], "last_attempt_at": state["last_attempt_at"],
                "scanner_running": bool(self.thread and self.thread.is_alive() and not self.stop_event.is_set() and session_active),
                "cycle_running": cycle_running, "session_active": session_active,
                "scan_mode": snapshot.get("scan_mode"), "provider": snapshot.get("provider"),
                "freshness": {"state": fresh, "snapshot_age_seconds": snapshot_age, "restored_unverified": restored,
                              "ideal_feature_age_seconds": self.settings.ideal_feature_age_seconds,
                              "maximum_feature_age_seconds": self.settings.maximum_feature_age_seconds,
                              "snapshot_ttl_seconds": self.settings.snapshot_ttl_seconds,
                              "delayed_penalty_points": self.settings.delayed_penalty_points},
                "universe": historical.get("universe", state["universe"]) if state.get("market_session") == "closed" else state["universe"],
                "historical_session": historical.get("session_date"), "active_candidate_count": len(state["active"]),
                "active_candidates": list(state["active"].values()), "top_candidates": top[:self.settings.result_limit],
                "last_known_candidates": last_known,
                "previous_snapshot": state.get("previous_snapshot") if not snapshot.get("candidates") else None,
                "diagnostics": {**(snapshot.get("diagnostics") or {}), "last_failure": state["failure"],
                                "last_cycle": state.get("last_cycle_diagnostics"),
                                "partial_failure": snapshot.get("partial_failure", False),
                                "provider_failure_count": snapshot.get("provider_failure_count", 0),
                                "next_broad_at": state["next_broad_at"], "next_active_at": state["next_active_at"],
                                "waiting_for_broker": not session_active,
                                "volume_semantics": "Dollar volume = price × session shares; relative volume = existing elapsed-session rate proxy. The $1M gate can exclude early-session names."},
                "safety_boundary": "Research state only; no alerts, orders, training, probability changes or evaluation writes."}

    def opportunity_state(self, user_id, *, now=None):
        now = now or self.clock()

        with self.lock:
            session = self.sessions.get(str(user_id))
            state = (
                deepcopy(session.state)
                if session
                else self._load_state(str(user_id))[0]
            )

            unavailable = (
                not self.settings.enabled
                or bool(state.get("failure"))
                or not session
                or session.cancel.is_set()
                or session.restored
                or not self._is_connected(str(user_id))
            )

        groups = {
            key: []
            for key in (
                "day",
                "swing",
                "long_term",
            )
        }

        orion_picks = {
            key: []
            for key in (
                "day",
                "swing",
                "long_term",
            )
        }

        last_known = []

        for row in (
            state.get(
                "research_setups"
            )
            or {}
        ).values():

            item = deepcopy(
                row
            )

            quote_age = age(
                item.get(
                    "data_timestamp"
                ),
                now,
            )

            feature_age = age(
                item.get(
                    "feature_timestamp"
                ),
                now,
            )

            feature_limit = (
                1200
                if item[
                    "horizon"
                ] == "day"
                else 7 * 86400
            )

            stale = (
                unavailable
                or state.get(
                    "market_session"
                ) == "closed"
                or quote_age is None
                or not 0 <= quote_age <= self.price_age_limit
                or feature_age is None
                or not 0 <= feature_age <= feature_limit
            )

            item[
                "freshness"
            ] = (
                "stale"
                if stale
                else "delayed"
            )

            forecast_target = timestamp(
                item.get(
                    "confidence_target_timestamp"
                )
            )

            if (
                forecast_target
                and forecast_target <= now
            ):
                item.update(
                    confidence=None,
                    confidence_kind="expired_forecast",
                )

            if stale:
                last_known.append(
                    item
                )
                continue

            horizon = item.get(
                "horizon"
            )

            if horizon not in groups:
                continue

            groups[
                horizon
            ].append(
                item
            )

            adjusted_orion_score = finite(
                item.get(
                    "adjusted_orion_score",
                    item.get(
                        "orion_score"
                    ),
                )
            )

            # Orion Picks remain score-gated, but use the integrity-adjusted
            # Orion Score. V3.1 affects ordering/state through
            # opportunity_rank_score rather than becoming a probability gate.
            if (
                item.get(
                    "orion_evaluated"
                ) is True
                and item.get(
                    "orion_pick_eligible"
                ) is True
                and adjusted_orion_score is not None
                and adjusted_orion_score >= ORION_PICK_MIN_SCORE
            ):
                orion_picks[
                    horizon
                ].append(
                    item
                )

        # Preserve the existing research ordering for the general opportunity
        # groups so old UI/API consumers do not silently change meaning.
        for group in groups.values():
            group.sort(
                key=lambda r: (
                    -(
                        finite(
                            r.get(
                                "quality_score"
                            )
                        )
                        or 0
                    ),
                    -(
                        finite(
                            r.get(
                                "average_dollar_volume"
                            )
                        )
                        or 0
                    ),
                    r.get(
                        "ticker"
                    )
                    or "",
                )
            )

            del group[
                10:
            ]

        # Final user-facing Orion Picks use the Opportunity Rank Score. The
        # integrity-adjusted Orion Score remains the first fallback and liquidity
        # remains a tie-breaker.
        for group in orion_picks.values():
            group.sort(
                key=lambda r: (
                    -(
                        finite(
                            r.get(
                                "opportunity_rank_score"
                            )
                        )
                        or finite(
                            r.get(
                                "adjusted_orion_score"
                            )
                        )
                        or finite(
                            r.get(
                                "orion_score"
                            )
                        )
                        or 0
                    ),
                    -(
                        finite(
                            r.get(
                                "adjusted_orion_score"
                            )
                        )
                        or finite(
                            r.get(
                                "orion_score"
                            )
                        )
                        or 0
                    ),
                    -(
                        finite(
                            r.get(
                                "average_dollar_volume"
                            )
                        )
                        or 0
                    ),
                    r.get(
                        "ticker"
                    )
                    or "",
                )
            )

            del group[
                ORION_PICK_LIMIT_PER_HORIZON:
            ]

        pick_count = sum(
            len(
                group
            )
            for group in orion_picks.values()
        )

        return {
            "groups": groups,

            "orion_picks": (
                orion_picks
            ),

            "orion_pick_threshold": (
                ORION_PICK_MIN_SCORE
            ),

            "orion_pick_count": (
                pick_count
            ),

            "orion_pick_status": (
                "picks_available"
                if pick_count
                else "no_high_quality_candidates"
            ),

            "last_known": (
                last_known[
                    :30
                ]
            ),

            "as_of": (
                now.isoformat()
            ),

            "diagnostics": (
                state.get(
                    "research_diagnostics",
                    {},
                )
            ),

            "universe": (
                state[
                    "universe"
                ]
            ),

            "semantics": (
                "General research groups retain professional setup quality. "
                "Orion Picks require a completed unified Orion analysis and "
                f"adjusted Orion Score >= {ORION_PICK_MIN_SCORE:.0f}. "
                "Final pick ordering uses Opportunity Rank Score, which keeps "
                "adjusted Orion Score dominant and permits only a small V3.1 "
                "Day-probability adjustment when usable evidence exists. "
                "Opportunity Rank Score and Orion Score are not probabilities. "
                "Day, Swing and Long-Term picks are ranked separately."
            ),
        }


    def market_intelligence(self, user_id, *, now=None):
        """Read-only view: no provider fetch, scan admission, or model call."""
        now, user_id = now or self.clock(), str(user_id)
        with self.lock:
            session = self.sessions.get(user_id)
            if session:
                state, restored = deepcopy(session.state), session.restored
            else:
                state, restored = self._load_state(user_id)
            active = bool(session and not session.cancel.is_set() and self._is_connected(user_id))
        data = state.get("market_intelligence") or {}
        historical = state.get("historical_market_intelligence") or {}
        # Never merge daily historical closes with current snapshots. Keep the
        # completed-session brief visible until the live pool has today's rows.
        from app.services.market_intelligence import session_date
        use_history = bool(historical.get("session_date") and (
            state.get("market_session") == "closed" or not data.get("observations")
            or data.get("session_date") != session_date(now.isoformat())))
        if use_history:
            data = historical
        result = current_categories(data, now=now, settings=self.settings,
                                    force_stale=bool(use_history or state.get("market_session") == "closed" or restored or not active or not self.settings.enabled or state.get("failure")),
                                    include_previous_session=use_history or state.get("market_session") == "closed" or (state.get("failure") or {}).get("reason") == "market_closed")
        result["coverage"].update(universe=deepcopy(data.get("universe", state["universe"])), last_broad_scan_at=data.get("last_broad_scan_at"))
        result.update(provider=data.get("provider"), session_active=active,
                      provider_availability=self.provider_availability(user_id),
                      message=(state.get("failure") or {}).get("message") or self.provider_availability(user_id).get("message"),
                      restored_unverified=restored, enabled=self.settings.enabled,
                      partial_failure=bool(data.get("partial_failure") or state.get("failure")),
                      last_failure=state.get("failure"))
        result.update(display_mode="historical" if use_history else "live", market_session=state.get("market_session"))
        if use_history:
            result.update(session_date=data["session_date"], session_close=data.get("session_close"),
                          limitations=data.get("limitations"),
                          message="Latest completed session: " + data["session_date"] + ". Historical daily closes, not live prices or trading signals. "
                          + ("Live scanning resumes at the next market open." if state.get("market_session") == "closed" else "Waiting for current-session observations."))
            result["coverage"].update(last_page_missing_symbols=len(data.get("missing_symbols") or []),
                                      last_page_valid_symbols=data.get("valid_data_count", 0),
                                      provider_failure_count=data.get("provider_failure_count", 0))
            if not data.get("observations"):
                result["message"] += (" No usable daily history for the latest session was returned on this page; automatic retry remains active."
                                      if not data.get("valid_data_count") else " This page contained no stocks passing the existing liquidity thresholds; scanning continues across the universe.")
            result["categories"]["unusual_volume"]["semantics"] = "Completed-session volume / preceding 20-session average; not elapsed-session relative volume."
            result["categories"]["most_active"]["semantics"] = "Adjusted session close × session shares: an activity proxy, not executed turnover or Most Bought."
        return result

    def _candidate_view(self, row, now, stale, partial, known_delayed=False):
        view = deepcopy(row)
        price_age, feature_age = age(row.get("data_timestamp"), now), age(row.get("feature_timestamp"), now)
        missing = price_age is None or feature_age is None
        invalid = missing or min(price_age, feature_age) < 0
        expired = not invalid and (price_age > self.price_age_limit or feature_age > self.settings.maximum_feature_age_seconds)
        delayed = known_delayed or row.get("delayed") is True or not invalid and feature_age > self.settings.ideal_feature_age_seconds
        label = "unavailable" if invalid else "stale" if stale or expired else "delayed" if delayed else "current"
        excess = max(0, (feature_age or 0) - self.settings.ideal_feature_age_seconds)
        penalty = self.settings.delayed_penalty_points * min(1, excess / (self.settings.maximum_feature_age_seconds - self.settings.ideal_feature_age_seconds))
        view["scanner_freshness"] = {"state": label, "price_age_seconds": price_age, "feature_age_seconds": feature_age,
                                     "penalty_points": round(penalty, 4)}
        view["freshness_adjusted_score"] = round(max(0, (finite(row.get("opportunity_score")) or 0) - penalty), 4)
        view["eligible_for_current"] = label == "current" and not partial
        view["trade_permission_current"] = view["eligible_for_current"] and row.get("actionable") is True
        return view
