# OrionTrader ↔ OurAI: opt-in local read-only evidence (phase 1)

The Orion backend can now retrieve OurAI **verified historical-to-live
forward observation summaries** from a **local-only** OurAI bridge.

This is for *15-minute absolute price movement magnitude*, never a
directional probability, trade signal, validated edge, or order action.
Original OrionTrader forecasting/scanner/execution engines remain unchanged.

## Run on the same trusted desktop

1. In the `OurAI` checkout (terminal A):

   ```powershell
   git checkout main
   git pull origin main
   python -m scripts.serve_orion_forward_bridge --port 8765
   ```

2. In the `Orion-Trader` checkout (terminal B), **before** starting the
   FastAPI backend, opt in for local single-user use:

   ```powershell
   $env:OURAI_BRIDGE_ENABLED = "true"
   $env:OURAI_BRIDGE_PORT = "8765"
   python -m uvicorn app.main:app --reload
   ```

   Run terminal B from the `Orion-Trader/backend` directory, as normal.
   This opt-in is **off** by default. The backend connects only to fixed
   `127.0.0.1` using HTTP (2-second timeout, no HTTP proxy or external URL).

3. After authenticating to the OrionTrader backend, read:

   ```text
   GET /intelligence/ourai/forward-evidence
   ```

   The frontend helper is `getOurAIForwardEvidence()` from
   `frontend/src/api/api.js`. This first phase prepares the API; UI cards
   should be added separately after the local bridge is confirmed operational.

## Returned states

- `disabled`: no opt-in environment flag; no request to OurAI was made.
- `unavailable`: OurAI is stopped, its forward journal is missing or
  invalid, or the response fails strict numeric/contract validation.
  No evidence/MAE is substituted.
- `available`: upstream validated the journal and Orion validated a
  minimal safe schema. Includes resolved-only MAE for the frozen V3 model,
  linear reference and fixed null; per-symbol counts, overdue pending
  observations, and latest magnitude-only prediction timestamps.
- A reported `expected_magnitude_bps` is an **absolute** price movement.
  It does not imply `UP`, `DOWN`, `LONG` or `SHORT`.
- The provider is a local journal, not independent cryptographic attestation
  of exchange truth. Forward model effectiveness still requires multi-day,
  truly unseen settled sessions with non-overlap-aware confidence bounds.

## Security and scope

This is a **single-user desktop** opt-in. OurAI's local process is
intentionally unauthenticated at the application level (bound to IPv4
127.0.0.1 only), so enabling the Orion endpoint on a shared or
multi-user Orion instance would make this machine-wide evidence accessible
to every authenticated Orion account. **Do not enable on a multi-user
or remotely exposed deployment.** The Orion endpoint retains existing
session authentication; no extra public path or CORS exception is added.

The only upstream host is hard-coded to `127.0.0.1`; the operator can
configure the TCP port but cannot redirect the connector to cloud services
or a network hostname. Response keys are whitelisted, numeric fields and
counts validated, and an invalid/unreachable source fails closed. No
order endpoint or model-selection mechanism imports this service.

Tests: `python -m pytest backend/tests/test_ourai_bridge.py` from
the repository root, or `python -m pytest tests/test_ourai_bridge.py`
from the backend directory with the usual backend environment.
