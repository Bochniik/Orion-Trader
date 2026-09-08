"""Bounded single-process job runner. Cancellation suppresses all later commits.

CPU/network stages are cooperative: an in-flight operation may finish before a
slot is released. Slots are NEVER released early on cancellation or timeout.
"""
from contextvars import ContextVar, copy_context
from threading import RLock, Thread, Timer
from time import monotonic
import uuid

from app.services.core_store import CoreStore


class JobStopped(Exception):
    pass


class JobsBusy(Exception):
    pass


job_control = ContextVar("core_job_control", default=None)


def checkpoint(stage=None):
    control = job_control.get()
    if control:
        control.checkpoint(stage)


class JobControl:
    def __init__(self, manager, store, job_id, timeout):
        self.manager, self.store, self.id = manager, store, job_id
        self.deadline = monotonic() + timeout
        self.stopped = False

    def checkpoint(self, stage=None):
        with self.manager.lock:
            if self.stopped:
                raise JobStopped()
            if monotonic() >= self.deadline:
                self.stop("timed_out", "Time limit reached; no new decision published.")
                raise JobStopped()
            if stage:
                self.store.update_job(self.id, "running", stage)

    def commit(self, callback):
        with self.manager.lock:
            self.checkpoint()
            return callback()

    def stop(self, state="cancelled", message="Cancelled. No further results will be published."):
        with self.manager.lock:
            self.stopped = True
            self.store.update_job(self.id, state, message)


class CoreJobManager:
    def __init__(self, max_workers=2, timeout=300):
        self.owner = uuid.uuid4().hex
        self.max_workers, self.timeout = max_workers, timeout
        self.lock, self.active, self.known = RLock(), {}, set()

    def store(self, path):
        store = CoreStore(path)
        with self.lock:
            key = str(store.path)
            if key not in self.known:
                store.recover(self.owner)
                self.known.add(key)
        return store

    def start(self, user, path, kind, ticker, run):
        store = self.store(path)
        with self.lock:
            previous = self.active.get(str(user))
            if previous:
                control, previous_kind, previous_ticker = previous
                if not control.stopped and (kind, ticker) == (previous_kind, previous_ticker):
                    return store.job(control.id)
                raise JobsBusy("The previous task is still finishing. Please try again shortly.")
            if len(self.active) >= self.max_workers:
                raise JobsBusy("Analysis capacity is busy. Please try again shortly.")
            job_id = uuid.uuid4().hex
            store.create_job(job_id, self.owner, kind, ticker)
            control = JobControl(self, store, job_id, self.timeout)
            self.active[str(user)] = (control, kind, ticker)
            context = copy_context()

            def worker():
                timer = Timer(self.timeout, lambda: control.stop("timed_out", "Time limit reached; no new decision published."))
                timer.daemon = True
                timer.start()
                try:
                    control.checkpoint("Checking data readiness")
                    def scoped_run():
                        token = job_control.set(control)
                        try:
                            return run(control)
                        finally:
                            job_control.reset(token)
                    result = context.run(scoped_run)
                    control.commit(lambda: store.finish(job_id, result, kind))
                except JobStopped:
                    pass
                except Exception:
                    # Provider messages may contain URLs or secrets.
                    store.update_job(job_id, "failed", "The review could not finish. No result is being presented as current.")
                finally:
                    timer.cancel()
                    with self.lock:
                        self.active.pop(str(user), None)

            Thread(target=worker, name="orion-core-job", daemon=True).start()
            return store.job(job_id)

    def cancel(self, user, path, job_id):
        store = self.store(path)
        store.job(job_id)  # ownership is the per-user database, never the UUID alone
        with self.lock:
            active = self.active.get(str(user))
            if active and active[0].id == job_id:
                active[0].stop()
        return store.job(job_id)

    def stop_user(self, user):
        with self.lock:
            active = self.active.get(str(user))
            if active:
                active[0].stop()

    def stop_all(self):
        with self.lock:
            for control, _, _ in self.active.values():
                control.stop("interrupted", "Backend stopped. Run the review again.")


core_job_manager = CoreJobManager()
