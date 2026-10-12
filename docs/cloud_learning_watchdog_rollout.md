# Cloud learning watchdog rollout

This rollout adds a redundant watchdog around the existing hourly Orion cloud accelerated learning workflow.

The watchdog does not write learning state itself. It only dispatches the existing workflow when no run is active and the newest run is stale for at least 70 minutes.

The accelerated-learning workflow remains SIMULATED_FORWARD-only and preserves in-progress runs instead of cancelling them on a later trigger.
