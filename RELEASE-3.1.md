# OrionTrader 3.1 — closed-session startup repair

## What changed

The closed-market guard previously stopped before universe/history retrieval.
Cold startup therefore had nothing to display, even with connected credentials.
Closed sessions now run a bounded historical market brief using the existing
Alpaca asset universe/calendar and Yahoo daily history. No new provider is used.

TODAY defaults to Most Active when a completed-session brief is available, unless
the user selected another category. Historical cards are expanded and show their
session date, STALE/HISTORICAL status and adjusted-close provenance. Clicking a
ticker still uses Analyze. Current rankings and historical rankings never mix.
During the regular session, the existing live scan resumes automatically.

## Data boundaries

- Latest completed regular session comes from the Alpaca calendar, including
  holidays and early closes: https://docs.alpaca.markets/us/reference/legacycalendar
- Require that exact daily session and the exact preceding session; do not
  substitute an older daily bar. Ignore today's unfinished daily row.
- Session return = adjusted close / preceding session adjusted close - 1.
- Activity = adjusted close × session shares (a proxy, not executed turnover).
- Relative volume = session shares / preceding up-to-20-session average shares.
- Reuse existing minimum price, average/session dollar volume and ten-session
  history gates. Partial liquidity score reuses dollar-volume, activity and
  volatility components; absent quote/trade evidence earns no points.
- No daily-data substitutes for quote pressure, intraday momentum, mean-reversion
  setups or model-qualified Orion Picks. These may legitimately be empty.
- Daily raw session labels are preserved; displayed observation time is the
  calendar session close, not fetch time. Provider revisions/finality are not
  independently verified. This is a historical market brief, not replay data.

## Reliability

Separate persisted historical pool/cursor; bounded 250-symbol pages by default;
existing request spacing and caches. Top lists accumulate across pages. Completed
rotations do not repeatedly download the whole universe. Missing exact daily bars
are not cached as successful observations; wholly unusable pages retry. Partial
pages advance and retain partial-coverage disclosure. Historical and live daily
caches are separated so an unfinished live candle cannot be reused after close.
Restart resumes the stored cursor; data remains stale. Next-open scheduling keeps
the existing minimum cycle spacing. GET endpoints never trigger downloads.

## Installation and verification

Stop both existing Orion processes, back up the existing app directory, and copy
the extracted OrionTrader folder's contents into the existing app folder. Preserve
your backend .env and data; the ZIP does not contain or overwrite them. Run the
normal start-orion.ps1 launcher, reload the browser, and verify the displayed 3.1
version (/health reports 3.1.0). Reconnect Alpaca Paper after backend restart because
credentials are memory-only. No database deletion or model retraining is needed.

Outside regular hours, TODAY should show the latest completed-session date and
historical market leaders after the first qualified page arrives. Universe coverage
is partial; a first page is not a market-wide ranking. Yahoo/Alpaca access failures
or insufficient data remain explicit and cannot be repaired by inventing results.

Validation: 147 focused scanner/category/authenticated-route tests, 36 frontend
category/polling/render tests, Python compilation and production build passed.
A real local backend process passed /health and /ready at version 3.1.0, started
the scanner thread and shut down cleanly. Provider responses
in tests are deterministic mocks. The development workspace has no connected user
Alpaca account; actual account/entitlement/network access must be checked in the
running installation. This release does not claim statistical predictive edge.
