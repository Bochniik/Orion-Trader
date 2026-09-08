
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import yfinance as yf


CACHE_TTL_SECONDS = 300
_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {
    "created_at_monotonic": 0.0,
    "payload": None,
}



COMPANY_NAMES: Dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "ORCL": "Oracle",
    "CRM": "Salesforce",
    "ADBE": "Adobe",
    "NOW": "ServiceNow",
    "INTU": "Intuit",
    "PANW": "Palo Alto Networks",
    "CRWD": "CrowdStrike",
    "PLTR": "Palantir",
    "NVDA": "NVIDIA",
    "AMD": "Advanced Micro Devices",
    "AVGO": "Broadcom",
    "QCOM": "Qualcomm",
    "MU": "Micron Technology",
    "AMAT": "Applied Materials",
    "LRCX": "Lam Research",
    "KLAC": "KLA",
    "INTC": "Intel",
    "TXN": "Texas Instruments",
    "XOM": "Exxon Mobil",
    "CVX": "Chevron",
    "COP": "ConocoPhillips",
    "EOG": "EOG Resources",
    "SLB": "SLB",
    "OXY": "Occidental Petroleum",
    "MPC": "Marathon Petroleum",
    "VLO": "Valero Energy",
    "PSX": "Phillips 66",
    "HAL": "Halliburton",
    "JPM": "JPMorgan Chase",
    "BAC": "Bank of America",
    "WFC": "Wells Fargo",
    "GS": "Goldman Sachs",
    "MS": "Morgan Stanley",
    "C": "Citigroup",
    "AXP": "American Express",
    "BLK": "BlackRock",
    "SCHW": "Charles Schwab",
    "COF": "Capital One",
    "LLY": "Eli Lilly",
    "UNH": "UnitedHealth Group",
    "JNJ": "Johnson & Johnson",
    "ABBV": "AbbVie",
    "MRK": "Merck",
    "TMO": "Thermo Fisher Scientific",
    "AMGN": "Amgen",
    "GILD": "Gilead Sciences",
    "ISRG": "Intuitive Surgical",
    "VRTX": "Vertex Pharmaceuticals",
    "AMZN": "Amazon",
    "WMT": "Walmart",
    "COST": "Costco",
    "HD": "Home Depot",
    "LOW": "Lowe's",
    "TGT": "Target",
    "NKE": "Nike",
    "SBUX": "Starbucks",
    "MCD": "McDonald's",
    "BKNG": "Booking Holdings",
    "GE": "GE Aerospace",
    "CAT": "Caterpillar",
    "DE": "Deere",
    "HON": "Honeywell",
    "RTX": "RTX",
    "LMT": "Lockheed Martin",
    "BA": "Boeing",
    "UPS": "UPS",
    "FDX": "FedEx",
    "ETN": "Eaton",
    "GOOGL": "Alphabet",
    "META": "Meta Platforms",
    "NFLX": "Netflix",
    "DIS": "Walt Disney",
    "TMUS": "T-Mobile US",
    "VZ": "Verizon",
    "T": "AT&T",
    "SPOT": "Spotify",
    "WBD": "Warner Bros. Discovery",
    "CMCSA": "Comcast",
    "NEE": "NextEra Energy",
    "SO": "Southern Company",
    "DUK": "Duke Energy",
    "CEG": "Constellation Energy",
    "VST": "Vistra",
    "AEP": "American Electric Power",
    "SRE": "Sempra",
    "D": "Dominion Energy",
    "EXC": "Exelon",
    "XEL": "Xcel Energy",
    "LIN": "Linde",
    "APD": "Air Products",
    "SHW": "Sherwin-Williams",
    "FCX": "Freeport-McMoRan",
    "NEM": "Newmont",
    "NUE": "Nucor",
    "DOW": "Dow",
    "DD": "DuPont",
    "ECL": "Ecolab",
    "MLM": "Martin Marietta Materials",
    "PLD": "Prologis",
    "AMT": "American Tower",
    "EQIX": "Equinix",
    "WELL": "Welltower",
    "SPG": "Simon Property Group",
    "O": "Realty Income",
    "PSA": "Public Storage",
    "DLR": "Digital Realty",
    "CCI": "Crown Castle",
    "VICI": "VICI Properties",
    "KO": "Coca-Cola",
    "PEP": "PepsiCo",
    "MDLZ": "Mondelez International",
    "KHC": "Kraft Heinz",
    "GIS": "General Mills",
    "K": "Kellanova",
    "HSY": "Hershey",
    "SJM": "J.M. Smucker",
    "CAG": "Conagra Brands",
    "TSN": "Tyson Foods",
    "TSLA": "Tesla",
    "RIVN": "Rivian Automotive",
    "LCID": "Lucid Group",
    "GM": "General Motors",
    "F": "Ford Motor",
    "LI": "Li Auto",
    "NIO": "NIO",
    "XPEV": "XPeng",
    "ON": "ON Semiconductor",
    "ALB": "Albemarle",
    "FTNT": "Fortinet",
    "ZS": "Zscaler",
    "OKTA": "Okta",
    "S": "SentinelOne",
    "CYBR": "CyberArk",
    "GEN": "Gen Digital",
    "TENB": "Tenable",
    "VRNS": "Varonis Systems",
    "IONQ": "IonQ",
    "RGTI": "Rigetti Computing",
    "QBTS": "D-Wave Quantum",
    "QUBT": "Quantum Computing",
    "IBM": "IBM",
    "RKLB": "Rocket Lab",
    "ASTS": "AST SpaceMobile",
    "LUNR": "Intuitive Machines",
    "RDW": "Redwire",
    "PL": "Planet Labs",
    "SPCE": "Virgin Galactic",
    "NOC": "Northrop Grumman",
    "GD": "General Dynamics",
    "LHX": "L3Harris Technologies",
    "HII": "Huntington Ingalls Industries",
    "KTOS": "Kratos Defense",
    "AVAV": "AeroVironment",
    "TER": "Teradyne",
    "ROK": "Rockwell Automation",
    "PATH": "UiPath",
    "SYM": "Symbotic",
    "CGNX": "Cognex",
    "ABB": "ABB",
    "REGN": "Regeneron Pharmaceuticals",
    "BIIB": "Biogen",
    "MRNA": "Moderna",
    "BMRN": "BioMarin Pharmaceutical",
    "ALNY": "Alnylam Pharmaceuticals",
    "ILMN": "Illumina",
    "CRSP": "CRISPR Therapeutics",
    "CCJ": "Cameco",
    "LEU": "Centrus Energy",
    "SMR": "NuScale Power",
    "OKLO": "Oklo",
    "BWXT": "BWX Technologies",
    "UEC": "Uranium Energy",
    "NXE": "NexGen Energy",
    "FSLR": "First Solar",
    "ENPH": "Enphase Energy",
    "SEDG": "SolarEdge Technologies",
    "NXT": "Nextracker",
    "RUN": "Sunrun",
    "BE": "Bloom Energy",
    "PLUG": "Plug Power",
    "AES": "AES",
    "COIN": "Coinbase",
    "MSTR": "Strategy",
    "MARA": "MARA Holdings",
    "RIOT": "Riot Platforms",
    "CLSK": "CleanSpark",
    "HOOD": "Robinhood Markets",
    "IREN": "IREN",
    "HUT": "Hut 8",
    "CIFR": "Cipher Mining",
    "SNOW": "Snowflake",
    "DDOG": "Datadog",
    "NET": "Cloudflare",
    "MDB": "MongoDB",
    "V": "Visa",
    "MA": "Mastercard",
    "PYPL": "PayPal",
    "SQ": "Block",
    "SOFI": "SoFi Technologies",
    "AFRM": "Affirm",
    "NU": "Nu Holdings",
    "FIS": "Fidelity National Information Services",
}



# Curated liquid US-equity discovery universe for V1.
# This is deliberately transparent and deterministic. V2 can replace/expand it
# with provider-driven full-universe classification without changing the API.
SECTORS: Dict[str, Dict[str, Any]] = {
    "technology": {
        "label": "Technology",
        "symbols": ["AAPL", "MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU", "PANW", "CRWD", "PLTR"],
    },
    "semiconductors": {
        "label": "Semiconductors",
        "symbols": ["NVDA", "AMD", "AVGO", "QCOM", "MU", "AMAT", "LRCX", "KLAC", "INTC", "TXN"],
    },
    "energy": {
        "label": "Energy",
        "symbols": ["XOM", "CVX", "COP", "EOG", "SLB", "OXY", "MPC", "VLO", "PSX", "HAL"],
    },
    "financials": {
        "label": "Financials",
        "symbols": ["JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SCHW", "COF"],
    },
    "healthcare": {
        "label": "Healthcare",
        "symbols": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "AMGN", "GILD", "ISRG", "VRTX"],
    },
    "consumer": {
        "label": "Consumer",
        "symbols": ["AMZN", "WMT", "COST", "HD", "LOW", "TGT", "NKE", "SBUX", "MCD", "BKNG"],
    },
    "industrials": {
        "label": "Industrials",
        "symbols": ["GE", "CAT", "DE", "HON", "RTX", "LMT", "BA", "UPS", "FDX", "ETN"],
    },
    "communication": {
        "label": "Communication Services",
        "symbols": ["GOOGL", "META", "NFLX", "DIS", "TMUS", "VZ", "T", "SPOT", "WBD", "CMCSA"],
    },
    "utilities": {
        "label": "Utilities",
        "symbols": ["NEE", "SO", "DUK", "CEG", "VST", "AEP", "SRE", "D", "EXC", "XEL"],
    },
    "materials": {
        "label": "Materials",
        "symbols": ["LIN", "APD", "SHW", "FCX", "NEM", "NUE", "DOW", "DD", "ECL", "MLM"],
    },
    "real_estate": {
        "label": "Real Estate",
        "symbols": ["PLD", "AMT", "EQIX", "WELL", "SPG", "O", "PSA", "DLR", "CCI", "VICI"],
    },
    "food_beverage": {
        "label": "Food & Beverage",
        "symbols": ["KO", "PEP", "MDLZ", "KHC", "GIS", "K", "HSY", "SJM", "CAG", "TSN"],
    },
}


THEMES: Dict[str, Dict[str, Any]] = {
    "ai": {
        "label": "Artificial Intelligence",
        "symbols": ["NVDA", "MSFT", "GOOGL", "META", "AMZN", "AVGO", "AMD", "PLTR", "ORCL", "CRM"],
    },
    "ev": {
        "label": "Electric Vehicles",
        "symbols": ["TSLA", "RIVN", "LCID", "GM", "F", "LI", "NIO", "XPEV", "ON", "ALB"],
    },
    "oil_gas": {
        "label": "Oil & Gas",
        "symbols": ["XOM", "CVX", "COP", "EOG", "OXY", "SLB", "HAL", "MPC", "VLO", "PSX"],
    },
    "cybersecurity": {
        "label": "Cybersecurity",
        "symbols": ["CRWD", "PANW", "FTNT", "ZS", "OKTA", "S", "CYBR", "GEN", "TENB", "VRNS"],
    },
    "quantum": {
        "label": "Quantum Computing",
        "symbols": ["IONQ", "RGTI", "QBTS", "QUBT", "IBM", "GOOGL", "MSFT", "HON"],
    },
    "space": {
        "label": "Space",
        "symbols": ["RKLB", "ASTS", "LUNR", "RDW", "PL", "SPCE", "BA", "LMT", "NOC"],
    },
    "defense": {
        "label": "Defense",
        "symbols": ["LMT", "RTX", "NOC", "GD", "LHX", "HII", "BA", "KTOS", "AVAV"],
    },
    "robotics": {
        "label": "Robotics & Automation",
        "symbols": ["ISRG", "TER", "ROK", "PATH", "SYM", "CGNX", "ABB", "NVDA", "AMZN"],
    },
    "biotech": {
        "label": "Biotechnology",
        "symbols": ["VRTX", "REGN", "GILD", "AMGN", "BIIB", "MRNA", "BMRN", "ALNY", "ILMN", "CRSP"],
    },
    "nuclear": {
        "label": "Nuclear Energy",
        "symbols": ["CEG", "VST", "CCJ", "LEU", "SMR", "OKLO", "BWXT", "UEC", "NXE"],
    },
    "renewables": {
        "label": "Renewable Energy",
        "symbols": ["FSLR", "ENPH", "SEDG", "NXT", "RUN", "BE", "PLUG", "NEE", "AES"],
    },
    "crypto": {
        "label": "Crypto-related Equities",
        "symbols": ["COIN", "MSTR", "MARA", "RIOT", "CLSK", "HOOD", "IREN", "HUT", "CIFR"],
    },
    "cloud": {
        "label": "Cloud Computing",
        "symbols": ["MSFT", "AMZN", "GOOGL", "ORCL", "CRM", "NOW", "SNOW", "DDOG", "NET", "MDB"],
    },
    "fintech": {
        "label": "Fintech",
        "symbols": ["V", "MA", "PYPL", "SQ", "HOOD", "SOFI", "AFRM", "NU", "COIN", "FIS"],
    },
    "food": {
        "label": "Food",
        "symbols": ["KO", "PEP", "MDLZ", "KHC", "GIS", "K", "HSY", "SJM", "CAG", "TSN"],
    },
}


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _all_symbols() -> List[str]:
    values: List[str] = []
    for group in [*SECTORS.values(), *THEMES.values()]:
        values.extend(group["symbols"])
    return list(dict.fromkeys(values))


def _series_for_symbol(
    frame: pd.DataFrame,
    field: str,
    symbol: str,
) -> Optional[pd.Series]:
    if frame is None or frame.empty:
        return None

    try:
        if isinstance(frame.columns, pd.MultiIndex):
            if (field, symbol) in frame.columns:
                return pd.to_numeric(frame[(field, symbol)], errors="coerce")
            if (symbol, field) in frame.columns:
                return pd.to_numeric(frame[(symbol, field)], errors="coerce")

        if field in frame.columns and len(_all_symbols()) == 1:
            return pd.to_numeric(frame[field], errors="coerce")
    except Exception:
        return None

    return None


def _snapshot_rows(symbols: Iterable[str]) -> List[Dict[str, Any]]:
    symbols = list(dict.fromkeys(str(s).upper().strip() for s in symbols if s))
    if not symbols:
        return []

    try:
        data = yf.download(
            tickers=" ".join(symbols),
            period="1mo",
            interval="1d",
            group_by="column",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception:
        return []

    rows: List[Dict[str, Any]] = []

    for symbol in symbols:
        close = _series_for_symbol(data, "Close", symbol)
        high = _series_for_symbol(data, "High", symbol)
        low = _series_for_symbol(data, "Low", symbol)
        volume = _series_for_symbol(data, "Volume", symbol)

        if close is None or high is None or low is None or volume is None:
            continue

        table = pd.DataFrame({
            "close": close,
            "high": high,
            "low": low,
            "volume": volume,
        }).dropna(subset=["close"])

        if len(table) < 2:
            continue

        latest = table.iloc[-1]
        previous = table.iloc[-2]

        latest_close = _finite(latest["close"])
        previous_close = _finite(previous["close"])
        latest_high = _finite(latest["high"])
        latest_low = _finite(latest["low"])
        latest_volume = _finite(latest["volume"])

        if latest_close is None or previous_close in (None, 0):
            continue

        change_pct = ((latest_close / previous_close) - 1.0) * 100.0
        dollar_volume = (
            latest_close * latest_volume
            if latest_volume is not None
            else None
        )

        volume_history = pd.to_numeric(
            table["volume"].iloc[:-1].tail(20),
            errors="coerce",
        ).dropna()

        avg_volume = (
            float(volume_history.mean())
            if not volume_history.empty
            else None
        )

        relative_volume = (
            latest_volume / avg_volume
            if latest_volume is not None
            and avg_volume not in (None, 0)
            else None
        )

        range_pct = (
            ((latest_high - latest_low) / latest_close) * 100.0
            if latest_high is not None
            and latest_low is not None
            and latest_close > 0
            else None
        )

        range_position = None
        if (
            latest_high is not None
            and latest_low is not None
            and latest_high > latest_low
        ):
            range_position = (
                (latest_close - latest_low)
                / (latest_high - latest_low)
            )

        # Transparent proxy only. It is NOT broker/client buy/sell data and
        # NOT exchange order-flow. Positive means price closed toward the upper
        # part of the daily range with positive day return; negative vice versa.
        pressure_proxy = None
        if range_position is not None:
            signed_range = (range_position - 0.5) * 2.0
            signed_return = max(-1.0, min(1.0, change_pct / 5.0))
            pressure_proxy = max(
                -100.0,
                min(
                    100.0,
                    100.0 * (
                        0.65 * signed_range
                        + 0.35 * signed_return
                    ),
                ),
            )

        rows.append({
            "ticker": symbol,
            "company_name": COMPANY_NAMES.get(symbol, symbol),
            "price": round(latest_close, 4),
            "change_pct": round(change_pct, 3),
            "volume": int(latest_volume) if latest_volume is not None else None,
            "average_volume_20d": round(avg_volume, 2) if avg_volume is not None else None,
            "relative_volume": round(relative_volume, 3) if relative_volume is not None else None,
            "dollar_volume": round(dollar_volume, 2) if dollar_volume is not None else None,
            "daily_range_pct": round(range_pct, 3) if range_pct is not None else None,
            "pressure_proxy": round(pressure_proxy, 1) if pressure_proxy is not None else None,
            "as_of": table.index[-1].isoformat() if hasattr(table.index[-1], "isoformat") else str(table.index[-1]),
        })

    return rows


def _rank(rows: List[Dict[str, Any]], key: str, *, reverse: bool = True, limit: int = 15):
    usable = [row for row in rows if _finite(row.get(key)) is not None]
    return sorted(
        usable,
        key=lambda row: _finite(row.get(key)) or 0.0,
        reverse=reverse,
    )[:limit]


def _group_summary(
    rows_by_symbol: Dict[str, Dict[str, Any]],
    definition: Dict[str, Any],
) -> Dict[str, Any]:
    rows = [
        rows_by_symbol[symbol]
        for symbol in definition["symbols"]
        if symbol in rows_by_symbol
    ]

    changes = [
        float(row["change_pct"])
        for row in rows
        if _finite(row.get("change_pct")) is not None
    ]

    performance = (
        sum(changes) / len(changes)
        if changes
        else None
    )

    strongest = max(
        rows,
        key=lambda row: row.get("change_pct", -999999),
        default=None,
    )

    weakest = min(
        rows,
        key=lambda row: row.get("change_pct", 999999),
        default=None,
    )

    return {
        "label": definition["label"],
        "performance_pct": round(performance, 3) if performance is not None else None,
        "constituent_count": len(rows),
        "strongest": strongest,
        "weakest": weakest,
        "items": sorted(
            rows,
            key=lambda row: row.get("change_pct", -999999),
            reverse=True,
        ),
    }


def build_market_explorer(*, force_refresh: bool = False) -> Dict[str, Any]:
    now_monotonic = time.monotonic()

    with _CACHE_LOCK:
        cached = _CACHE.get("payload")
        age = now_monotonic - float(_CACHE.get("created_at_monotonic") or 0.0)

        if (
            not force_refresh
            and cached is not None
            and 0 <= age < CACHE_TTL_SECONDS
        ):
            return cached

    rows = _snapshot_rows(_all_symbols())
    by_symbol = {row["ticker"]: row for row in rows}

    lists = {
        "most_active": _rank(rows, "dollar_volume", reverse=True),
        "gainers": _rank(rows, "change_pct", reverse=True),
        "losers": _rank(rows, "change_pct", reverse=False),
        "relative_volume": _rank(rows, "relative_volume", reverse=True),
        "most_volatile": _rank(rows, "daily_range_pct", reverse=True),
        "buy_pressure": _rank(rows, "pressure_proxy", reverse=True),
        "sell_pressure": _rank(rows, "pressure_proxy", reverse=False),
    }

    sectors = {
        key: _group_summary(by_symbol, definition)
        for key, definition in SECTORS.items()
    }

    themes = {
        key: _group_summary(by_symbol, definition)
        for key, definition in THEMES.items()
    }

    payload = {
        "available": bool(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(_all_symbols()),
        "observed_symbols": len(rows),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "lists": lists,
        "sectors": sectors,
        "themes": themes,
        "semantics": {
            "most_active": "Ranked by latest daily dollar volume inside the V1 discovery universe.",
            "gainers_losers": "Latest completed daily close versus previous daily close.",
            "relative_volume": "Latest daily volume divided by prior 20-session average volume.",
            "buy_sell_pressure": (
                "Price-action pressure proxy derived from daily range position and daily return. "
                "It is NOT Trading 212 client activity, exchange order-flow, or actual buy/sell counts."
            ),
            "coverage": (
                "V1 uses a curated liquid US-equity discovery universe. It is not yet a complete "
                "all-listed-US-equity ranking."
            ),
        },
    }

    with _CACHE_LOCK:
        _CACHE["created_at_monotonic"] = now_monotonic
        _CACHE["payload"] = payload

    return payload


def get_group(group_type: str, group_id: str) -> Dict[str, Any]:
    payload = build_market_explorer()
    container = payload.get(group_type)

    if not isinstance(container, dict) or group_id not in container:
        return {
            "available": False,
            "error": "unknown_group",
        }

    return {
        "available": True,
        "generated_at": payload["generated_at"],
        "group_type": group_type,
        "group_id": group_id,
        **container[group_id],
        "semantics": payload["semantics"],
    }


if __name__ == "__main__":
    import json

    result = build_market_explorer(force_refresh=True)
    print(
        json.dumps(
            {
                "available": result["available"],
                "universe_size": result["universe_size"],
                "observed_symbols": result["observed_symbols"],
                "top_gainers": result["lists"]["gainers"][:5],
                "top_losers": result["lists"]["losers"][:5],
                "top_active": result["lists"]["most_active"][:5],
                "themes": {
                    key: {
                        "label": value["label"],
                        "performance_pct": value["performance_pct"],
                    }
                    for key, value in list(result["themes"].items())[:5]
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )
