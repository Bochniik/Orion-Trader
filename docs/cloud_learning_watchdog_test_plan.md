# Cloud learning watchdog test plan

The rollout is validated by a backend contract test and a dedicated pull-request workflow. The checks assert that the main learning workflow preserves in-progress runs and that the watchdog has actions write permission, a 15-minute schedule, an active-run guard, a 70-minute stale threshold, and dispatches only the existing cloud-learning workflow.
