# Acceptance criteria

- No active cloud-learning run is cancelled by a later trigger.
- The watchdog does not dispatch while a learning run is active.
- The watchdog dispatches the existing learning workflow only when the newest run is at least 70 minutes old or absent.
- The watchdog never reads or mutates LIVE_FORWARD state and does not promote models.
