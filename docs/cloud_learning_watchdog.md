# Orion cloud accelerated learning watchdog

The accelerated-learning workflow remains the only writer of persisted SIMULATED_FORWARD learning state.

A separate watchdog workflow runs every 15 minutes and only dispatches `cloud-accelerated-learning.yml` when:

- no cloud-learning run is queued, waiting, requested, pending, or in progress; and
- the newest cloud-learning run is at least 70 minutes old, or no prior run exists.

The main accelerated-learning workflow uses `cancel-in-progress: false` so a later push or recovery dispatch cannot discard a healthy in-progress replay before its artifact is persisted.

This watchdog does not read or mutate LIVE_FORWARD data and does not perform model promotion.
