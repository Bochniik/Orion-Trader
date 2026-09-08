from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import yfinance as yf


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
    return max(low, min(high, value))


def _utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _percent_value(
    value: Any,
) -> Optional[float]:
    """
    yfinance frequently returns growth/return values as decimals.

    Example:
        0.25 -> 25 %
    """

    number = _safe_float(value)

    if number is None:
        return None

    return number * 100.0


# =============================================================================
# GROWTH SCORE
# =============================================================================

def calculate_growth_score(
    *,
    revenue_growth: Optional[float],
    eps_growth: Optional[float],
    earnings_growth: Optional[float],
) -> float:

    values = []

    if revenue_growth is not None:
        values.append(
            _clamp(
                revenue_growth / 25.0
            )
        )

    if eps_growth is not None:
        values.append(
            _clamp(
                eps_growth / 30.0
            )
        )

    if earnings_growth is not None:
        values.append(
            _clamp(
                earnings_growth / 30.0
            )
        )

    if not values:
        return 0.0

    return round(
        sum(values) / len(values),
        4,
    )


# =============================================================================
# PROFITABILITY / BUSINESS QUALITY
# =============================================================================

def calculate_business_quality_score(
    *,
    return_on_equity: Optional[float],
    return_on_assets: Optional[float],
    operating_margin: Optional[float],
    profit_margin: Optional[float],
    gross_margin: Optional[float],
) -> float:

    scores = []

    if return_on_equity is not None:
        scores.append(
            _clamp(
                (
                    return_on_equity
                    - 10.0
                )
                / 20.0
            )
        )

    if return_on_assets is not None:
        scores.append(
            _clamp(
                (
                    return_on_assets
                    - 5.0
                )
                / 12.0
            )
        )

    if operating_margin is not None:
        scores.append(
            _clamp(
                (
                    operating_margin
                    - 10.0
                )
                / 20.0
            )
        )

    if profit_margin is not None:
        scores.append(
            _clamp(
                (
                    profit_margin
                    - 8.0
                )
                / 18.0
            )
        )

    if gross_margin is not None:
        scores.append(
            _clamp(
                (
                    gross_margin
                    - 25.0
                )
                / 35.0
            )
        )

    if not scores:
        return 0.0

    return round(
        sum(scores) / len(scores),
        4,
    )


# =============================================================================
# BALANCE SHEET SCORE
# =============================================================================

def calculate_balance_sheet_score(
    *,
    debt_to_equity: Optional[float],
    current_ratio: Optional[float],
    quick_ratio: Optional[float],
    total_cash: Optional[float],
    total_debt: Optional[float],
) -> float:

    scores = []

    if debt_to_equity is not None:

        # yfinance often reports this as percent-like value:
        # 50 ~= 0.50 D/E.
        normalized_de = (
            debt_to_equity / 100.0
            if debt_to_equity > 10
            else debt_to_equity
        )

        if normalized_de <= 0.30:
            debt_score = 1.0

        elif normalized_de <= 0.70:
            debt_score = 0.60

        elif normalized_de <= 1.20:
            debt_score = 0.15

        elif normalized_de <= 2.00:
            debt_score = -0.40

        else:
            debt_score = -0.85

        scores.append(
            debt_score
        )

    if current_ratio is not None:
        if current_ratio >= 2.0:
            scores.append(0.8)

        elif current_ratio >= 1.5:
            scores.append(0.5)

        elif current_ratio >= 1.0:
            scores.append(0.1)

        else:
            scores.append(-0.7)

    if quick_ratio is not None:
        if quick_ratio >= 1.5:
            scores.append(0.7)

        elif quick_ratio >= 1.0:
            scores.append(0.25)

        else:
            scores.append(-0.5)

    if (
        total_cash is not None
        and total_debt is not None
    ):
        if total_cash > total_debt:
            scores.append(0.7)

        elif total_debt == 0:
            scores.append(1.0)

        else:
            ratio = (
                total_cash
                / total_debt
            )

            if ratio >= 0.75:
                scores.append(0.25)

            elif ratio >= 0.40:
                scores.append(-0.15)

            else:
                scores.append(-0.6)

    if not scores:
        return 0.0

    return round(
        sum(scores) / len(scores),
        4,
    )


# =============================================================================
# VALUATION SCORE
# =============================================================================

def calculate_valuation_score(
    *,
    trailing_pe: Optional[float],
    forward_pe: Optional[float],
    peg_ratio: Optional[float],
    price_to_sales: Optional[float],
    price_to_book: Optional[float],
    free_cash_flow_yield: Optional[float],
) -> float:
    """
    Generic deterministic valuation score.

    This is deliberately conservative because valuation differs heavily
    between industries.

    Later we should compare valuation against sector peers instead of
    relying only on absolute thresholds.
    """

    scores = []

    pe = (
        forward_pe
        if forward_pe is not None
        else trailing_pe
    )

    if pe is not None and pe > 0:

        if pe <= 12:
            scores.append(0.85)

        elif pe <= 20:
            scores.append(0.55)

        elif pe <= 30:
            scores.append(0.15)

        elif pe <= 45:
            scores.append(-0.25)

        elif pe <= 70:
            scores.append(-0.55)

        else:
            scores.append(-0.8)

    if peg_ratio is not None and peg_ratio > 0:

        if peg_ratio <= 1.0:
            scores.append(0.8)

        elif peg_ratio <= 1.5:
            scores.append(0.45)

        elif peg_ratio <= 2.0:
            scores.append(0.1)

        elif peg_ratio <= 3.0:
            scores.append(-0.35)

        else:
            scores.append(-0.65)

    if (
        price_to_sales is not None
        and price_to_sales > 0
    ):

        if price_to_sales <= 2:
            scores.append(0.6)

        elif price_to_sales <= 5:
            scores.append(0.2)

        elif price_to_sales <= 10:
            scores.append(-0.25)

        else:
            scores.append(-0.6)

    if (
        price_to_book is not None
        and price_to_book > 0
    ):

        if price_to_book <= 2:
            scores.append(0.45)

        elif price_to_book <= 5:
            scores.append(0.05)

        elif price_to_book <= 10:
            scores.append(-0.25)

        else:
            scores.append(-0.5)

    if free_cash_flow_yield is not None:

        if free_cash_flow_yield >= 8:
            scores.append(0.9)

        elif free_cash_flow_yield >= 5:
            scores.append(0.55)

        elif free_cash_flow_yield >= 3:
            scores.append(0.2)

        elif free_cash_flow_yield > 0:
            scores.append(-0.15)

        else:
            scores.append(-0.7)

    if not scores:
        return 0.0

    return round(
        sum(scores) / len(scores),
        4,
    )


# =============================================================================
# EARNINGS REVISION PROXY
# =============================================================================

def calculate_earnings_revision_score(
    info: Dict[str, Any],
) -> float:
    """
    yfinance does not provide a universally reliable analyst revision
    history in every environment, so this uses available forward-vs-current
    earnings growth fields as a conservative proxy.

    Do NOT call this a calibrated analyst revision probability.
    """

    earnings_growth = _percent_value(
        info.get("earningsGrowth")
    )

    earnings_quarterly_growth = _percent_value(
        info.get("earningsQuarterlyGrowth")
    )

    scores = []

    if earnings_growth is not None:
        scores.append(
            _clamp(
                earnings_growth / 30.0
            )
        )

    if earnings_quarterly_growth is not None:
        scores.append(
            _clamp(
                earnings_quarterly_growth
                / 30.0
            )
        )

    if not scores:
        return 0.0

    return round(
        sum(scores) / len(scores),
        4,
    )


# =============================================================================
# FCF
# =============================================================================

def calculate_fcf_metrics(
    info: Dict[str, Any],
) -> Dict[str, Optional[float]]:

    free_cash_flow = _safe_float(
        info.get("freeCashflow")
    )

    market_cap = _safe_float(
        info.get("marketCap")
    )

    free_cash_flow_yield = None

    if (
        free_cash_flow is not None
        and market_cap is not None
        and market_cap > 0
    ):
        free_cash_flow_yield = (
            free_cash_flow
            / market_cap
        ) * 100.0

    return {
        "free_cash_flow": (
            free_cash_flow
        ),

        "free_cash_flow_yield": (
            free_cash_flow_yield
        ),
    }


# =============================================================================
# FETCH
# =============================================================================

def fetch_fundamentals(
    symbol: str,
) -> Dict[str, Any]:

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError(
            "Symbol cannot be empty."
        )

    ticker = yf.Ticker(
        symbol
    )

    info = ticker.info

    if not isinstance(
        info,
        dict,
    ):
        raise RuntimeError(
            f"No fundamental information available for {symbol}."
        )

    return info


# =============================================================================
# MAIN ENGINE
# =============================================================================

def get_fundamental_strategy_data(
    symbol: str,
) -> Dict[str, Any]:

    symbol = symbol.upper().strip()

    warnings = []

    info = fetch_fundamentals(
        symbol
    )

    # -------------------------------------------------------------------------
    # GROWTH
    # -------------------------------------------------------------------------

    revenue_growth = _percent_value(
        info.get("revenueGrowth")
    )

    earnings_growth = _percent_value(
        info.get("earningsGrowth")
    )

    earnings_quarterly_growth = (
        _percent_value(
            info.get(
                "earningsQuarterlyGrowth"
            )
        )
    )

    # Best available EPS growth proxy.
    eps_growth = (
        earnings_quarterly_growth
        if earnings_quarterly_growth
        is not None
        else earnings_growth
    )

    # -------------------------------------------------------------------------
    # PROFITABILITY
    # -------------------------------------------------------------------------

    roe = _percent_value(
        info.get("returnOnEquity")
    )

    roa = _percent_value(
        info.get("returnOnAssets")
    )

    gross_margin = _percent_value(
        info.get("grossMargins")
    )

    operating_margin = _percent_value(
        info.get("operatingMargins")
    )

    profit_margin = _percent_value(
        info.get("profitMargins")
    )

    # yfinance does not always expose ROIC directly.
    # Do not invent it.
    roic = None

    # -------------------------------------------------------------------------
    # BALANCE SHEET
    # -------------------------------------------------------------------------

    debt_to_equity = _safe_float(
        info.get("debtToEquity")
    )

    current_ratio = _safe_float(
        info.get("currentRatio")
    )

    quick_ratio = _safe_float(
        info.get("quickRatio")
    )

    total_cash = _safe_float(
        info.get("totalCash")
    )

    total_debt = _safe_float(
        info.get("totalDebt")
    )

    balance_sheet_score = (
        calculate_balance_sheet_score(
            debt_to_equity=debt_to_equity,
            current_ratio=current_ratio,
            quick_ratio=quick_ratio,
            total_cash=total_cash,
            total_debt=total_debt,
        )
    )

    # -------------------------------------------------------------------------
    # VALUATION
    # -------------------------------------------------------------------------

    trailing_pe = _safe_float(
        info.get("trailingPE")
    )

    forward_pe = _safe_float(
        info.get("forwardPE")
    )

    peg_ratio = _safe_float(
        info.get("pegRatio")
    )

    price_to_sales = _safe_float(
        info.get("priceToSalesTrailing12Months")
    )

    price_to_book = _safe_float(
        info.get("priceToBook")
    )

    fcf = calculate_fcf_metrics(
        info
    )

    free_cash_flow = fcf[
        "free_cash_flow"
    ]

    free_cash_flow_yield = fcf[
        "free_cash_flow_yield"
    ]

    valuation_score = (
        calculate_valuation_score(
            trailing_pe=trailing_pe,
            forward_pe=forward_pe,
            peg_ratio=peg_ratio,
            price_to_sales=price_to_sales,
            price_to_book=price_to_book,
            free_cash_flow_yield=free_cash_flow_yield,
        )
    )

    # -------------------------------------------------------------------------
    # QUALITY
    # -------------------------------------------------------------------------

    business_quality_score = (
        calculate_business_quality_score(
            return_on_equity=roe,
            return_on_assets=roa,
            operating_margin=operating_margin,
            profit_margin=profit_margin,
            gross_margin=gross_margin,
        )
    )

    growth_score = (
        calculate_growth_score(
            revenue_growth=revenue_growth,
            eps_growth=eps_growth,
            earnings_growth=earnings_growth,
        )
    )

    earnings_revision_score = (
        calculate_earnings_revision_score(
            info
        )
    )

    # -------------------------------------------------------------------------
    # MISSING DATA WARNINGS
    # -------------------------------------------------------------------------

    if revenue_growth is None:
        warnings.append(
            "Revenue growth unavailable."
        )

    if eps_growth is None:
        warnings.append(
            "EPS/earnings growth unavailable."
        )

    if roic is None:
        warnings.append(
            "ROIC unavailable; not estimated."
        )

    if free_cash_flow is None:
        warnings.append(
            "Free cash flow unavailable."
        )

    # -------------------------------------------------------------------------
    # RESULT
    # -------------------------------------------------------------------------

    return {
        "symbol": symbol,

        "company_name": (
            info.get("longName")
            or info.get("shortName")
        ),

        "sector": info.get(
            "sector"
        ),

        "industry": info.get(
            "industry"
        ),

        "market_cap": _safe_float(
            info.get("marketCap")
        ),

        # ---------------------------------------------------------------------
        # Inputs expected by strategy_engine long-term branch
        # ---------------------------------------------------------------------

        "revenue_growth": (
            revenue_growth
        ),

        "eps_growth": (
            eps_growth
        ),

        "free_cash_flow_growth": None,

        "roic": roic,

        "roe": roe,

        "debt_to_equity": (
            debt_to_equity
        ),

        "valuation_score": (
            valuation_score
        ),

        "earnings_revision_score": (
            earnings_revision_score
        ),

        "balance_sheet_score": (
            balance_sheet_score
        ),

        "business_quality_score": (
            business_quality_score
        ),

        "growth_score": (
            growth_score
        ),

        # ---------------------------------------------------------------------
        # Additional raw fundamentals for future use / Orion explanations
        # ---------------------------------------------------------------------

        "earnings_growth": (
            earnings_growth
        ),

        "return_on_assets": (
            roa
        ),

        "gross_margin": (
            gross_margin
        ),

        "operating_margin": (
            operating_margin
        ),

        "profit_margin": (
            profit_margin
        ),

        "current_ratio": (
            current_ratio
        ),

        "quick_ratio": (
            quick_ratio
        ),

        "total_cash": (
            total_cash
        ),

        "total_debt": (
            total_debt
        ),

        "free_cash_flow": (
            free_cash_flow
        ),

        "free_cash_flow_yield": (
            free_cash_flow_yield
        ),

        "trailing_pe": (
            trailing_pe
        ),

        "forward_pe": (
            forward_pe
        ),

        "peg_ratio": (
            peg_ratio
        ),

        "price_to_sales": (
            price_to_sales
        ),

        "price_to_book": (
            price_to_book
        ),

        "fundamental_generated_at": (
            _utc_now_iso()
        ),

        "warnings": warnings,
    }


# =============================================================================
# MANUAL TEST
# =============================================================================

if __name__ == "__main__":

    import json
    import sys

    ticker = (
        sys.argv[1].upper()
        if len(sys.argv) > 1
        else "AAPL"
    )

    result = (
        get_fundamental_strategy_data(
            ticker
        )
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )