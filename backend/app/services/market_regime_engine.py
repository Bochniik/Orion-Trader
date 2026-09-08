from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

try:
    from dotenv import load_dotenv

    BACKEND_ROOT = Path(__file__).resolve().parents[2]

    load_dotenv(BACKEND_ROOT / ".env")
    load_dotenv(BACKEND_ROOT.parent / ".env")

except ImportError:
    pass


ALPACA_DATA_BASE = "https://data.alpaca.markets"


# =============================================================================
# SECTOR MAP
# =============================================================================

SECTOR_ETFS = {
    "technology": "XLK",
    "information technology": "XLK",

    "financials": "XLF",
    "financial": "XLF",

    "energy": "XLE",

    "healthcare": "XLV",
    "health care": "XLV",

    "industrials": "XLI",
    "industrial": "XLI",

    "consumer discretionary": "XLY",
    "consumer cyclical": "XLY",

    "consumer staples": "XLP",
    "consumer defensive": "XLP",

    "utilities": "XLU",

    "materials": "XLB",
    "basic materials": "XLB",

    "real estate": "XLRE",

    "communication services": "XLC",
    "communication": "XLC",
}


MARKET_SYMBOLS = {
    "broad_market": "SPY",
    "growth_tech": "QQQ",
    "small_caps": "IWM",
    "dow": "DIA",

    # Tradable volatility proxy.
    # VIX itself is an index and not a normal US equity ticker.
    "volatility_proxy": "VXX",
}


# =============================================================================
# MODELS
# =============================================================================

@dataclass
class SymbolRegime:
    symbol: str

    price: Optional[float]

    return_1d_pct: Optional[float]
    return_5d_pct: Optional[float]
    return_20d_pct: Optional[float]

    sma_20: Optional[float]
    sma_50: Optional[float]
    sma_200: Optional[float]

    volatility_20d_pct: Optional[float]

    trend_score: float
    momentum_score: float
    volatility_score: float

    regime_score: float

    data_points: int

    warning: Optional[str]


@dataclass
class MarketRegimeResult:
    market_score: float
    sector_score: float

    market_regime: str
    sector_regime: str

    risk_environment: str

    sector_etf: Optional[str]

    components: Dict[str, Dict[str, Any]]

    generated_at: str

    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# HELPERS
# =============================================================================

def _safe_float(
    value: Any,
    default: Optional[float] = None,
) -> Optional[float]:

    try:
        if value is None:
            return default

        result = float(value)

        if math.isnan(result) or math.isinf(result):
            return default

        return result

    except (TypeError, ValueError):
        return default


def _clamp(
    value: float,
    low: float = -1.0,
    high: float = 1.0,
) -> float:

    return max(
        low,
        min(high, value),
    )


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None

    return sum(values) / len(values)


def _stddev(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None

    mean = sum(values) / len(values)

    variance = sum(
        (value - mean) ** 2
        for value in values
    ) / (len(values) - 1)

    return math.sqrt(variance)


def _pct_change(
    newer: float,
    older: float,
) -> Optional[float]:

    if older == 0:
        return None

    return (
        (newer - older)
        / older
    ) * 100.0


def _normalize_signed(
    value: float,
    scale: float,
) -> float:

    if scale <= 0:
        return 0.0

    return _clamp(
        value / scale
    )


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


# =============================================================================
# CREDENTIALS
# =============================================================================

def _get_credentials() -> tuple[
    Optional[str],
    Optional[str],
]:

    key = (
        os.getenv("APCA_API_KEY_ID")
        or os.getenv("ALPACA_API_KEY")
        or os.getenv("ALPACA_API_KEY_ID")
        or os.getenv("APCA_API_KEY")
    )

    secret = (
        os.getenv("APCA_API_SECRET_KEY")
        or os.getenv("ALPACA_SECRET_KEY")
        or os.getenv("ALPACA_API_SECRET")
        or os.getenv("APCA_SECRET_KEY")
    )

    return key, secret


def _headers() -> Dict[str, str]:

    key, secret = _get_credentials()

    if not key or not secret:
        raise RuntimeError(
            "Alpaca credentials are missing."
        )

    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }


# =============================================================================
# DATA DOWNLOAD
# =============================================================================

def fetch_daily_bars(
    symbol: str,
    *,
    lookback_days: int = 320,
    limit: int = 300,
    feed: Optional[str] = None,
    timeout: float = 10.0,
) -> List[Dict[str, Any]]:

    symbol = symbol.upper().strip()

    end = datetime.now(
        timezone.utc
    )

    start = end - timedelta(
        days=lookback_days
    )

    url = (
        f"{ALPACA_DATA_BASE}"
        f"/v2/stocks/{symbol}/bars"
    )

    feeds_to_try = []

    if feed:
        feeds_to_try.append(feed)
    else:
        # Prefer SIP if account supports it,
        # otherwise automatically fall back to IEX.
        feeds_to_try.extend(
            [
                "sip",
                "iex",
            ]
        )

    last_error = None

    for selected_feed in feeds_to_try:

        params: Dict[str, Any] = {
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": min(
                max(limit, 1),
                10000,
            ),
            "adjustment": "raw",
            "sort": "asc",
            "feed": selected_feed,
        }

        try:

            response = requests.get(
                url,
                headers=_headers(),
                params=params,
                timeout=timeout,
            )

        except requests.RequestException as exc:

            last_error = (
                f"{selected_feed}: "
                f"{exc}"
            )

            continue

        if response.status_code == 200:

            payload = response.json()

            bars = payload.get(
                "bars",
                [],
            )

            if isinstance(bars, list):
                return bars

            return []

        if response.status_code == 401:
            raise RuntimeError(
                "Alpaca authentication failed."
            )

        if response.status_code == 429:
            raise RuntimeError(
                "Alpaca rate limit reached."
            )

        if response.status_code == 403:

            last_error = (
                f"Feed {selected_feed} "
                f"is not available for {symbol}."
            )

            # Try next feed.
            continue

        last_error = (
            f"Alpaca returned HTTP "
            f"{response.status_code} "
            f"for {symbol} "
            f"using {selected_feed} feed."
        )

    raise RuntimeError(
        last_error
        or f"No Alpaca market data available for {symbol}."
    )


# =============================================================================
# SYMBOL ANALYSIS
# =============================================================================

def analyze_symbol_regime(
    symbol: str,
) -> SymbolRegime:

    try:
        bars = fetch_daily_bars(
            symbol
        )

    except Exception as exc:
        return SymbolRegime(
            symbol=symbol,
            price=None,

            return_1d_pct=None,
            return_5d_pct=None,
            return_20d_pct=None,

            sma_20=None,
            sma_50=None,
            sma_200=None,

            volatility_20d_pct=None,

            trend_score=0.0,
            momentum_score=0.0,
            volatility_score=0.0,

            regime_score=0.0,

            data_points=0,

            warning=str(exc),
        )

    closes = []

    for bar in bars:
        close = _safe_float(
            bar.get("c")
        )

        if close is not None:
            closes.append(close)

    if len(closes) < 5:
        return SymbolRegime(
            symbol=symbol,
            price=(
                closes[-1]
                if closes
                else None
            ),

            return_1d_pct=None,
            return_5d_pct=None,
            return_20d_pct=None,

            sma_20=None,
            sma_50=None,
            sma_200=None,

            volatility_20d_pct=None,

            trend_score=0.0,
            momentum_score=0.0,
            volatility_score=0.0,

            regime_score=0.0,

            data_points=len(closes),

            warning="Insufficient daily bars.",
        )

    price = closes[-1]

    # -------------------------------------------------------------------------
    # RETURNS
    # -------------------------------------------------------------------------

    return_1d = None
    return_5d = None
    return_20d = None

    if len(closes) >= 2:
        return_1d = _pct_change(
            closes[-1],
            closes[-2],
        )

    if len(closes) >= 6:
        return_5d = _pct_change(
            closes[-1],
            closes[-6],
        )

    if len(closes) >= 21:
        return_20d = _pct_change(
            closes[-1],
            closes[-21],
        )

    # -------------------------------------------------------------------------
    # MOVING AVERAGES
    # -------------------------------------------------------------------------

    sma20 = (
        _mean(closes[-20:])
        if len(closes) >= 20
        else None
    )

    sma50 = (
        _mean(closes[-50:])
        if len(closes) >= 50
        else None
    )

    sma200 = (
        _mean(closes[-200:])
        if len(closes) >= 200
        else None
    )

    # -------------------------------------------------------------------------
    # TREND SCORE
    # -------------------------------------------------------------------------

    trend_components: List[float] = []

    if sma20 is not None:
        trend_components.append(
            1.0
            if price > sma20
            else -1.0
        )

    if (
        sma20 is not None
        and sma50 is not None
    ):
        trend_components.append(
            1.0
            if sma20 > sma50
            else -1.0
        )

    if (
        sma50 is not None
        and sma200 is not None
    ):
        trend_components.append(
            1.0
            if sma50 > sma200
            else -1.0
        )

    if (
        sma200 is not None
    ):
        trend_components.append(
            1.0
            if price > sma200
            else -1.0
        )

    trend_score = (
        sum(trend_components)
        / len(trend_components)
        if trend_components
        else 0.0
    )

    # -------------------------------------------------------------------------
    # MOMENTUM SCORE
    # -------------------------------------------------------------------------

    momentum_parts: List[float] = []

    if return_1d is not None:
        momentum_parts.append(
            _normalize_signed(
                return_1d,
                2.0,
            )
            * 0.20
        )

    if return_5d is not None:
        momentum_parts.append(
            _normalize_signed(
                return_5d,
                5.0,
            )
            * 0.35
        )

    if return_20d is not None:
        momentum_parts.append(
            _normalize_signed(
                return_20d,
                10.0,
            )
            * 0.45
        )

    momentum_score = _clamp(
        sum(momentum_parts)
    )

    # -------------------------------------------------------------------------
    # VOLATILITY
    # -------------------------------------------------------------------------

    daily_returns: List[float] = []

    for index in range(
        max(
            1,
            len(closes) - 20,
        ),
        len(closes),
    ):

        older = closes[
            index - 1
        ]

        newer = closes[
            index
        ]

        if older != 0:
            daily_returns.append(
                (
                    newer - older
                )
                / older
            )

    volatility_20d = None
    volatility_score = 0.0

    if daily_returns:

        std = _stddev(
            daily_returns
        )

        if std is not None:

            # Annualized realized volatility.
            volatility_20d = (
                std
                * math.sqrt(252)
                * 100
            )

            # Volatility is not directional by itself.
            #
            # Low/moderate volatility = positive regime quality.
            # Extreme volatility = risk penalty.
            if volatility_20d < 15:
                volatility_score = 0.50

            elif volatility_20d < 25:
                volatility_score = 0.30

            elif volatility_20d < 40:
                volatility_score = 0.0

            elif volatility_20d < 60:
                volatility_score = -0.40

            else:
                volatility_score = -0.80

    # -------------------------------------------------------------------------
    # FINAL SYMBOL REGIME
    # -------------------------------------------------------------------------

    regime_score = (
        trend_score * 0.55
        + momentum_score * 0.35
        + volatility_score * 0.10
    )

    regime_score = _clamp(
        regime_score
    )

    return SymbolRegime(
        symbol=symbol,

        price=round(
            price,
            4,
        ),

        return_1d_pct=(
            round(return_1d, 3)
            if return_1d is not None
            else None
        ),

        return_5d_pct=(
            round(return_5d, 3)
            if return_5d is not None
            else None
        ),

        return_20d_pct=(
            round(return_20d, 3)
            if return_20d is not None
            else None
        ),

        sma_20=(
            round(sma20, 4)
            if sma20 is not None
            else None
        ),

        sma_50=(
            round(sma50, 4)
            if sma50 is not None
            else None
        ),

        sma_200=(
            round(sma200, 4)
            if sma200 is not None
            else None
        ),

        volatility_20d_pct=(
            round(
                volatility_20d,
                2,
            )
            if volatility_20d
            is not None
            else None
        ),

        trend_score=round(
            trend_score,
            4,
        ),

        momentum_score=round(
            momentum_score,
            4,
        ),

        volatility_score=round(
            volatility_score,
            4,
        ),

        regime_score=round(
            regime_score,
            4,
        ),

        data_points=len(closes),

        warning=None,
    )


# =============================================================================
# SECTOR
# =============================================================================

def resolve_sector_etf(
    sector: Optional[str],
) -> Optional[str]:

    if not sector:
        return None

    normalized = (
        str(sector)
        .strip()
        .lower()
    )

    return SECTOR_ETFS.get(
        normalized
    )


# =============================================================================
# LABELS
# =============================================================================

def _regime_label(
    score: float,
) -> str:

    if score >= 0.55:
        return "strong_bullish"

    if score >= 0.20:
        return "bullish"

    if score <= -0.55:
        return "strong_bearish"

    if score <= -0.20:
        return "bearish"

    return "neutral"


# =============================================================================
# MAIN ENGINE
# =============================================================================

def analyze_market_regime(
    *,
    sector: Optional[str] = None,
    sector_etf: Optional[str] = None,
) -> Dict[str, Any]:

    warnings: List[str] = []

    # -------------------------------------------------------------------------
    # BROAD MARKET
    # -------------------------------------------------------------------------

    spy = analyze_symbol_regime(
        MARKET_SYMBOLS[
            "broad_market"
        ]
    )

    qqq = analyze_symbol_regime(
        MARKET_SYMBOLS[
            "growth_tech"
        ]
    )

    iwm = analyze_symbol_regime(
        MARKET_SYMBOLS[
            "small_caps"
        ]
    )

    dia = analyze_symbol_regime(
        MARKET_SYMBOLS[
            "dow"
        ]
    )

    vxx = analyze_symbol_regime(
        MARKET_SYMBOLS[
            "volatility_proxy"
        ]
    )

    all_components = [
        spy,
        qqq,
        iwm,
        dia,
        vxx,
    ]

    for component in all_components:
        if component.warning:
            warnings.append(
                f"{component.symbol}: "
                f"{component.warning}"
            )

    # -------------------------------------------------------------------------
    # MARKET SCORE
    # -------------------------------------------------------------------------

    market_score = (
        spy.regime_score * 0.40
        + qqq.regime_score * 0.25
        + iwm.regime_score * 0.20
        + dia.regime_score * 0.15
    )

    # -------------------------------------------------------------------------
    # VOLATILITY PROXY
    #
    # VXX rising = more risk / fear.
    # Therefore its directional regime should act inversely.
    # -------------------------------------------------------------------------

    volatility_penalty = (
        -vxx.momentum_score
        * 0.15
    )

    market_score += (
        volatility_penalty
    )

    market_score = _clamp(
        market_score
    )

    # -------------------------------------------------------------------------
    # SECTOR
    # -------------------------------------------------------------------------

    resolved_sector_etf = (
        sector_etf
        or resolve_sector_etf(
            sector
        )
    )

    sector_component = None

    if resolved_sector_etf:

        sector_component = (
            analyze_symbol_regime(
                resolved_sector_etf
            )
        )

        if sector_component.warning:
            warnings.append(
                f"{resolved_sector_etf}: "
                f"{sector_component.warning}"
            )

        sector_score = (
            sector_component.regime_score
        )

    else:
        # Do NOT invent a sector score.
        sector_score = 0.0

        if sector:
            warnings.append(
                f"No sector ETF mapping for sector: {sector}"
            )

    # -------------------------------------------------------------------------
    # RISK ENVIRONMENT
    # -------------------------------------------------------------------------

    if (
        market_score <= -0.45
        or vxx.momentum_score >= 0.65
    ):
        risk_environment = "risk_off"

    elif (
        market_score >= 0.45
        and vxx.momentum_score <= 0.25
    ):
        risk_environment = "risk_on"

    else:
        risk_environment = "mixed"

    components = {
        "SPY": asdict(spy),
        "QQQ": asdict(qqq),
        "IWM": asdict(iwm),
        "DIA": asdict(dia),
        "VXX": asdict(vxx),
    }

    if sector_component:
        components[
            sector_component.symbol
        ] = asdict(
            sector_component
        )

    return MarketRegimeResult(
        market_score=round(
            market_score,
            4,
        ),

        sector_score=round(
            sector_score,
            4,
        ),

        market_regime=_regime_label(
            market_score
        ),

        sector_regime=_regime_label(
            sector_score
        ),

        risk_environment=risk_environment,

        sector_etf=(
            resolved_sector_etf
        ),

        components=components,

        generated_at=_utc_now(),

        warnings=warnings,
    ).to_dict()


# =============================================================================
# CONTEXT FOR STRATEGY ENGINE
# =============================================================================

def get_strategy_market_context(
    *,
    sector: Optional[str] = None,
    sector_etf: Optional[str] = None,
) -> Dict[str, Any]:

    result = analyze_market_regime(
        sector=sector,
        sector_etf=sector_etf,
    )

    return {
        "market_score": result[
            "market_score"
        ],

        "sector_score": result[
            "sector_score"
        ],

        "market_regime": result[
            "market_regime"
        ],

        "sector_regime": result[
            "sector_regime"
        ],

        "risk_environment": result[
            "risk_environment"
        ],

        "sector_etf": result[
            "sector_etf"
        ],

        "market_components": result[
            "components"
        ],

        "market_warnings": result[
            "warnings"
        ],
    }


# =============================================================================
# MANUAL TEST
# =============================================================================

if __name__ == "__main__":

    import json
    import sys

    sector = (
        " ".join(
            sys.argv[1:]
        )
        if len(sys.argv) > 1
        else "technology"
    )

    result = analyze_market_regime(
        sector=sector
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )