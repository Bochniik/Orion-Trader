import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

try:
    from dotenv import load_dotenv

    # backend/.env
    BACKEND_ROOT = Path(__file__).resolve().parents[2]
    load_dotenv(BACKEND_ROOT / ".env")

    # OrionTrader/.env – fallback, ak je .env o úroveň vyššie
    load_dotenv(BACKEND_ROOT.parent / ".env")

except ImportError:
    # OrionTrader môže stále fungovať s premennými dodanými systémom.
    pass


ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class NewsItem:
    id: Optional[int]
    headline: str
    summary: str
    author: Optional[str]
    source: Optional[str]
    url: Optional[str]

    created_at: Optional[str]
    age_hours: Optional[float]

    sentiment_score: float
    relevance_score: float
    catalyst_strength: float
    effective_score: float

    direction: str
    catalyst_type: str
    catalyst_label: str

    matched_positive_terms: List[str]
    matched_negative_terms: List[str]
    matched_catalyst_terms: List[str]

    symbols: List[str]


@dataclass
class NewsAnalysisResult:
    symbol: str

    news_score: float
    catalyst_strength: float
    direction: str

    article_count: int
    relevant_article_count: int

    strongest_catalyst: Optional[str]
    strongest_catalyst_label: Optional[str]

    positive_articles: int
    negative_articles: int
    neutral_articles: int

    freshness: str
    newest_article_at: Optional[str]

    articles: List[Dict[str, Any]]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# CATALYST DEFINITIONS
# =============================================================================

CATALYSTS: Dict[str, Dict[str, Any]] = {
    "earnings": {
        "label": "Earnings",
        "weight": 1.00,
        "terms": [
            "earnings",
            "quarterly results",
            "quarter results",
            "financial results",
            "earnings report",
            "eps",
            "profit",
            "quarterly profit",
            "quarterly loss",
            "revenue",
        ],
    },

    "guidance": {
        "label": "Guidance",
        "weight": 1.00,
        "terms": [
            "guidance",
            "outlook",
            "forecast",
            "raises forecast",
            "cuts forecast",
            "raises guidance",
            "cuts guidance",
            "lowers guidance",
            "reaffirms guidance",
        ],
    },

    "fda": {
        "label": "FDA / Clinical",
        "weight": 1.00,
        "terms": [
            "fda",
            "food and drug administration",
            "clinical trial",
            "phase 1",
            "phase 2",
            "phase 3",
            "drug approval",
            "approved drug",
            "approval",
            "clinical data",
            "trial results",
            "primary endpoint",
        ],
    },

    "merger_acquisition": {
        "label": "M&A",
        "weight": 0.98,
        "terms": [
            "acquisition",
            "acquire",
            "acquires",
            "acquired",
            "merger",
            "takeover",
            "buyout",
            "strategic combination",
            "going private",
        ],
    },

    "legal_regulatory": {
        "label": "Legal / Regulatory",
        "weight": 0.90,
        "terms": [
            "sec investigation",
            "investigation",
            "lawsuit",
            "sued",
            "settlement",
            "antitrust",
            "regulatory",
            "regulator",
            "justice department",
            "department of justice",
            "doj",
            "ftc",
            "fine",
            "ban",
        ],
    },

    "analyst": {
        "label": "Analyst Action",
        "weight": 0.58,
        "terms": [
            "price target",
            "upgrade",
            "upgraded",
            "downgrade",
            "downgraded",
            "initiates coverage",
            "reiterates",
            "analyst",
            "overweight",
            "underweight",
            "buy rating",
            "sell rating",
        ],
    },

    "product": {
        "label": "Product / Technology",
        "weight": 0.72,
        "terms": [
            "launches",
            "launch",
            "new product",
            "product launch",
            "unveils",
            "introduces",
            "announces new",
            "new technology",
            "platform launch",
            "new platform",
        ],
    },

    "contract": {
        "label": "Contract / Partnership",
        "weight": 0.78,
        "terms": [
            "contract",
            "awarded contract",
            "wins contract",
            "partnership",
            "partners with",
            "strategic partnership",
            "agreement",
            "supply agreement",
            "customer agreement",
            "order",
        ],
    },

    "financing": {
        "label": "Financing / Dilution",
        "weight": 0.88,
        "terms": [
            "public offering",
            "secondary offering",
            "stock offering",
            "share offering",
            "registered direct offering",
            "private placement",
            "convertible notes",
            "debt offering",
            "capital raise",
            "raises capital",
        ],
    },

    "dividend_buyback": {
        "label": "Capital Return",
        "weight": 0.65,
        "terms": [
            "dividend",
            "special dividend",
            "share repurchase",
            "stock repurchase",
            "buyback",
            "repurchase program",
        ],
    },

    "insider": {
        "label": "Insider Activity",
        "weight": 0.58,
        "terms": [
            "insider buying",
            "insider purchase",
            "insider selling",
            "insider sale",
            "director buys",
            "ceo buys",
            "ceo sells",
        ],
    },

    "management": {
        "label": "Management",
        "weight": 0.62,
        "terms": [
            "ceo resigns",
            "ceo resignation",
            "new ceo",
            "appoints ceo",
            "cfo resigns",
            "new cfo",
            "management change",
        ],
    },

    "general": {
        "label": "General Company News",
        "weight": 0.30,
        "terms": [],
    },
}


# =============================================================================
# SENTIMENT DICTIONARY
# =============================================================================

# These are deliberately transparent deterministic rules.
# They are NOT an ML probability model.

POSITIVE_TERMS: Dict[str, float] = {
    "beats estimates": 1.00,
    "beats expectations": 1.00,
    "beat estimates": 0.95,
    "beat expectations": 0.95,

    "raises guidance": 1.00,
    "raises forecast": 0.95,
    "increases guidance": 0.95,

    "record revenue": 0.90,
    "record profit": 0.90,

    "better than expected": 0.85,
    "above expectations": 0.85,
    "strong demand": 0.75,
    "strong growth": 0.75,

    "approved": 0.85,
    "approval": 0.70,

    "positive trial": 0.90,
    "met primary endpoint": 0.95,
    "meets primary endpoint": 0.95,

    "acquisition offer": 0.85,
    "takeover offer": 0.90,

    "contract awarded": 0.80,
    "wins contract": 0.80,

    "upgrade": 0.55,
    "upgraded": 0.55,
    "raises price target": 0.50,

    "share buyback": 0.60,
    "stock buyback": 0.60,
    "repurchase program": 0.55,

    "dividend increase": 0.55,
    "raises dividend": 0.55,

    "profit rises": 0.65,
    "revenue rises": 0.60,
    "sales rise": 0.55,

    "expands": 0.35,
    "growth": 0.25,
    "record": 0.25,
}


NEGATIVE_TERMS: Dict[str, float] = {
    "misses estimates": 1.00,
    "misses expectations": 1.00,
    "missed estimates": 0.95,
    "missed expectations": 0.95,

    "cuts guidance": 1.00,
    "lowers guidance": 1.00,
    "cuts forecast": 0.95,
    "lowers forecast": 0.95,

    "profit warning": 1.00,

    "worse than expected": 0.85,
    "below expectations": 0.85,
    "weak demand": 0.75,

    "clinical trial failure": 1.00,
    "failed trial": 1.00,
    "missed primary endpoint": 1.00,
    "fails primary endpoint": 1.00,

    "fda rejection": 1.00,
    "fda rejects": 1.00,
    "rejected": 0.70,

    "investigation": 0.65,
    "sec investigation": 0.85,
    "criminal investigation": 0.95,

    "lawsuit": 0.50,
    "sued": 0.50,
    "fraud": 0.90,

    "downgrade": 0.55,
    "downgraded": 0.55,
    "cuts price target": 0.50,
    "lowers price target": 0.50,

    "public offering": 0.75,
    "secondary offering": 0.75,
    "stock offering": 0.75,
    "share offering": 0.75,
    "registered direct offering": 0.80,
    "dilution": 0.85,

    "bankruptcy": 1.00,
    "chapter 11": 1.00,
    "default": 0.90,

    "ceo resigns": 0.50,
    "cfo resigns": 0.45,

    "recall": 0.70,

    "layoffs": 0.35,
    "job cuts": 0.35,

    "revenue falls": 0.60,
    "sales fall": 0.55,
    "profit falls": 0.65,

    "decline": 0.25,
    "weakness": 0.25,
    "loss": 0.20,
}


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


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""

    value = value.lower()

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None

    if isinstance(value, datetime):
        dt = value

    else:
        try:
            text = str(value).strip()

            # RFC3339 commonly uses Z.
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"

            dt = datetime.fromisoformat(text)

        except (ValueError, TypeError):
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _hours_old(value: Any) -> Optional[float]:
    dt = _parse_datetime(value)

    if dt is None:
        return None

    age = (
        datetime.now(timezone.utc) - dt
    ).total_seconds() / 3600.0

    return max(0.0, age)


def _time_decay(age_hours: Optional[float]) -> float:
    """
    News influence decays with age.

    Approximate behaviour:

        0h   -> 1.00
        6h   -> ~0.84
        12h  -> ~0.71
        24h  -> ~0.50
        48h  -> ~0.25
        72h  -> ~0.125

    This is intentionally transparent and deterministic.
    """

    if age_hours is None:
        return 0.30

    half_life_hours = 24.0

    decay = 0.5 ** (
        age_hours / half_life_hours
    )

    return _clamp(
        decay,
        0.05,
        1.0,
    )


def _find_terms(
    text: str,
    dictionary: Dict[str, float],
) -> List[str]:

    matches: List[str] = []

    for term in dictionary:
        if term in text:
            matches.append(term)

    return matches


# =============================================================================
# CATALYST CLASSIFICATION
# =============================================================================

def classify_catalyst(
    headline: str,
    summary: str = "",
) -> Dict[str, Any]:

    headline_text = _normalize_text(headline)
    summary_text = _normalize_text(summary)

    combined = f"{headline_text} {summary_text}"

    best_type = "general"
    best_weight = CATALYSTS["general"]["weight"]
    best_matches: List[str] = []

    for catalyst_type, definition in CATALYSTS.items():

        if catalyst_type == "general":
            continue

        matches = [
            term
            for term in definition["terms"]
            if term in combined
        ]

        if not matches:
            continue

        candidate_weight = float(
            definition["weight"]
        )

        if candidate_weight > best_weight:
            best_type = catalyst_type
            best_weight = candidate_weight
            best_matches = matches

    definition = CATALYSTS[best_type]

    return {
        "type": best_type,
        "label": definition["label"],
        "strength": float(definition["weight"]),
        "matched_terms": best_matches,
    }


# =============================================================================
# SENTIMENT ENGINE
# =============================================================================

def score_text_sentiment(
    headline: str,
    summary: str = "",
) -> Dict[str, Any]:
    """
    Transparent rule-based sentiment.

    Headline has more influence than summary because headlines
    normally contain the primary market-moving information.

    Returns a signed score in [-1, +1].

    This is NOT a probability.
    """

    headline_text = _normalize_text(headline)
    summary_text = _normalize_text(summary)

    positive_matches: List[str] = []
    negative_matches: List[str] = []

    headline_positive = 0.0
    headline_negative = 0.0

    summary_positive = 0.0
    summary_negative = 0.0

    for term, weight in POSITIVE_TERMS.items():
        if term in headline_text:
            headline_positive += weight
            positive_matches.append(term)

        elif term in summary_text:
            summary_positive += weight * 0.50
            positive_matches.append(term)

    for term, weight in NEGATIVE_TERMS.items():
        if term in headline_text:
            headline_negative += weight
            negative_matches.append(term)

        elif term in summary_text:
            summary_negative += weight * 0.50
            negative_matches.append(term)

    positive_total = (
        headline_positive
        + summary_positive
    )

    negative_total = (
        headline_negative
        + summary_negative
    )

    total_strength = (
        positive_total
        + negative_total
    )

    if total_strength <= 0:
        score = 0.0

    else:
        score = (
            positive_total - negative_total
        ) / total_strength

    return {
        "score": round(
            _clamp(score),
            4,
        ),
        "positive_terms": sorted(
            set(positive_matches)
        ),
        "negative_terms": sorted(
            set(negative_matches)
        ),
    }


# =============================================================================
# RELEVANCE
# =============================================================================

def calculate_relevance(
    symbol: str,
    article: Dict[str, Any],
) -> float:
    """
    Estimates how directly an article relates to the selected symbol.

    If Alpaca explicitly tags the article with the requested symbol,
    relevance is high.
    """

    requested = symbol.upper().strip()

    article_symbols = [
        str(item).upper()
        for item in article.get("symbols", [])
        if item
    ]

    if requested in article_symbols:
        symbol_count = max(
            1,
            len(article_symbols),
        )

        # Single-company article gets the strongest weight.
        if symbol_count == 1:
            return 1.0

        if symbol_count <= 3:
            return 0.90

        if symbol_count <= 7:
            return 0.75

        return 0.60

    return 0.35


# =============================================================================
# INDIVIDUAL ARTICLE SCORING
# =============================================================================

def analyze_article(
    symbol: str,
    article: Dict[str, Any],
) -> NewsItem:

    headline = str(
        article.get("headline") or ""
    ).strip()

    summary = str(
        article.get("summary") or ""
    ).strip()

    sentiment = score_text_sentiment(
        headline,
        summary,
    )

    catalyst = classify_catalyst(
        headline,
        summary,
    )

    relevance = calculate_relevance(
        symbol,
        article,
    )

    created_at = (
        article.get("created_at")
        or article.get("updated_at")
    )

    age_hours = _hours_old(created_at)

    decay = _time_decay(age_hours)

    sentiment_score = float(
        sentiment["score"]
    )

    catalyst_strength = float(
        catalyst["strength"]
    )

    # -------------------------------------------------------------------------
    # Effective directional impact
    # -------------------------------------------------------------------------

    effective_score = (
        sentiment_score
        * relevance
        * catalyst_strength
        * decay
    )

    effective_score = _clamp(
        effective_score
    )

    if effective_score >= 0.08:
        direction = "bullish"

    elif effective_score <= -0.08:
        direction = "bearish"

    else:
        direction = "neutral"

    raw_symbols = article.get(
        "symbols",
        [],
    )

    symbols = [
        str(value).upper()
        for value in raw_symbols
        if value
    ]

    source = (
        article.get("source")
        or article.get("author")
    )

    return NewsItem(
        id=article.get("id"),

        headline=headline,
        summary=summary,

        author=article.get("author"),
        source=source,

        url=article.get("url"),

        created_at=(
            str(created_at)
            if created_at
            else None
        ),

        age_hours=(
            round(age_hours, 2)
            if age_hours is not None
            else None
        ),

        sentiment_score=round(
            sentiment_score,
            4,
        ),

        relevance_score=round(
            relevance,
            4,
        ),

        catalyst_strength=round(
            catalyst_strength,
            4,
        ),

        effective_score=round(
            effective_score,
            4,
        ),

        direction=direction,

        catalyst_type=catalyst["type"],
        catalyst_label=catalyst["label"],

        matched_positive_terms=sentiment[
            "positive_terms"
        ],

        matched_negative_terms=sentiment[
            "negative_terms"
        ],

        matched_catalyst_terms=catalyst[
            "matched_terms"
        ],

        symbols=symbols,
    )


# =============================================================================
# ALPACA CREDENTIALS
# =============================================================================

def _get_alpaca_credentials() -> tuple[
    Optional[str],
    Optional[str],
]:
    """
    Supports several commonly used environment-variable names so this
    module can coexist with the current OrionTrader configuration.
    """

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


# =============================================================================
# ALPACA NEWS DOWNLOAD
# =============================================================================

def fetch_alpaca_news(
    symbol: str,
    *,
    lookback_hours: int = 72,
    limit: int = 30,
    include_content: bool = False,
    timeout: float = 10.0,
) -> List[Dict[str, Any]]:
    """
    Fetch recent Alpaca news for one stock.

    Alpaca currently exposes:
        GET https://data.alpaca.markets/v1beta1/news

    The request is intentionally REST-based so this module does not
    require the alpaca-py NewsClient.
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError(
            "Symbol cannot be empty."
        )

    key, secret = _get_alpaca_credentials()

    if not key or not secret:
        raise RuntimeError(
            "Alpaca API credentials are missing. "
            "Expected APCA_API_KEY_ID / APCA_API_SECRET_KEY "
            "or compatible ALPACA_* environment variables."
        )

    now = datetime.now(timezone.utc)

    start = (
        now - timedelta(
            hours=max(1, lookback_hours)
        )
    ).isoformat()

    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }

    params = {
        "symbols": symbol,
        "start": start,
        "sort": "desc",
        "limit": max(
            1,
            min(int(limit), 50),
        ),
        "include_content": str(
            bool(include_content)
        ).lower(),
    }

    response = requests.get(
        ALPACA_NEWS_URL,
        headers=headers,
        params=params,
        timeout=timeout,
    )

    if response.status_code == 401:
        raise RuntimeError(
            "Alpaca rejected the API credentials (401)."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "Alpaca news access is forbidden for this account/feed (403)."
        )

    if response.status_code == 429:
        raise RuntimeError(
            "Alpaca news rate limit reached (429)."
        )

    response.raise_for_status()

    payload = response.json()

    news = payload.get(
        "news",
        [],
    )

    if not isinstance(news, list):
        return []

    return news


# =============================================================================
# AGGREGATION
# =============================================================================

def _weighted_news_average(
    articles: Iterable[NewsItem],
) -> float:

    numerator = 0.0
    denominator = 0.0

    for article in articles:

        # Highly relevant and important catalysts count more.
        importance = (
            article.relevance_score
            * article.catalyst_strength
        )

        if article.age_hours is not None:
            importance *= _time_decay(
                article.age_hours
            )

        numerator += (
            article.sentiment_score
            * importance
        )

        denominator += importance

    if denominator <= 0:
        return 0.0

    return _clamp(
        numerator / denominator
    )


def _aggregate_catalyst_strength(
    articles: List[NewsItem],
) -> float:
    """
    Returns strength of the most relevant fresh catalyst, not an average.
    A major earnings/FDA event should not be diluted by several weak
    generic articles.
    """

    if not articles:
        return 0.0

    strengths: List[float] = []

    for article in articles:

        freshness = _time_decay(
            article.age_hours
        )

        strength = (
            article.catalyst_strength
            * article.relevance_score
            * freshness
        )

        strengths.append(strength)

    if not strengths:
        return 0.0

    return _clamp(
        max(strengths),
        0.0,
        1.0,
    )


def _freshness_label(
    newest_age_hours: Optional[float],
) -> str:

    if newest_age_hours is None:
        return "unknown"

    if newest_age_hours <= 1:
        return "very_fresh"

    if newest_age_hours <= 6:
        return "fresh"

    if newest_age_hours <= 24:
        return "recent"

    if newest_age_hours <= 72:
        return "aging"

    return "stale"


# =============================================================================
# MAIN NEWS ENGINE
# =============================================================================

def analyze_news(
    symbol: str,
    *,
    lookback_hours: int = 72,
    limit: int = 30,
    min_relevance: float = 0.50,
    include_content: bool = False,
) -> Dict[str, Any]:
    """
    Main public API.

    Example:

        result = analyze_news("NVDA")

        print(result["news_score"])
        print(result["catalyst_strength"])

    Returned news_score:
        -1.0 = strongly bearish news context
         0.0 = neutral / insufficient evidence
        +1.0 = strongly bullish news context

    IMPORTANT:
    news_score is NOT a probability of future price movement.
    """

    symbol = symbol.upper().strip()

    if not symbol:
        raise ValueError(
            "Symbol cannot be empty."
        )

    warnings: List[str] = []

    try:
        raw_articles = fetch_alpaca_news(
            symbol,
            lookback_hours=lookback_hours,
            limit=limit,
            include_content=include_content,
        )

    except Exception as exc:
        # News failure must never crash the stock-analysis pipeline.
        return NewsAnalysisResult(
            symbol=symbol,

            news_score=0.0,
            catalyst_strength=0.0,
            direction="neutral",

            article_count=0,
            relevant_article_count=0,

            strongest_catalyst=None,
            strongest_catalyst_label=None,

            positive_articles=0,
            negative_articles=0,
            neutral_articles=0,

            freshness="unavailable",
            newest_article_at=None,

            articles=[],

            warnings=[
                f"News unavailable: {exc}"
            ],
        ).to_dict()

    analyzed: List[NewsItem] = []

    for raw_article in raw_articles:

        try:
            item = analyze_article(
                symbol,
                raw_article,
            )

            analyzed.append(item)

        except Exception as exc:
            warnings.append(
                f"Could not analyze one news article: {exc}"
            )

    relevant = [
        article
        for article in analyzed
        if article.relevance_score >= min_relevance
    ]

    # Fall back to all explicitly requested articles if relevance filtering
    # somehow removes everything.
    scoring_articles = (
        relevant
        if relevant
        else analyzed
    )

    news_score = _weighted_news_average(
        scoring_articles
    )

    catalyst_strength = (
        _aggregate_catalyst_strength(
            scoring_articles
        )
    )

    # -------------------------------------------------------------------------
    # Avoid strong directional claims from one weak generic headline.
    # -------------------------------------------------------------------------

    if len(scoring_articles) == 1:

        single = scoring_articles[0]

        if single.catalyst_type == "general":
            news_score *= 0.50

    news_score = round(
        _clamp(news_score),
        4,
    )

    catalyst_strength = round(
        _clamp(
            catalyst_strength,
            0.0,
            1.0,
        ),
        4,
    )

    # -------------------------------------------------------------------------
    # Final direction
    # -------------------------------------------------------------------------

    if news_score >= 0.12:
        direction = "bullish"

    elif news_score <= -0.12:
        direction = "bearish"

    else:
        direction = "neutral"

    # -------------------------------------------------------------------------
    # Counts
    # -------------------------------------------------------------------------

    positive_count = sum(
        article.direction == "bullish"
        for article in scoring_articles
    )

    negative_count = sum(
        article.direction == "bearish"
        for article in scoring_articles
    )

    neutral_count = sum(
        article.direction == "neutral"
        for article in scoring_articles
    )

    # -------------------------------------------------------------------------
    # Newest article
    # -------------------------------------------------------------------------

    valid_dates = []

    for article in analyzed:

        parsed = _parse_datetime(
            article.created_at
        )

        if parsed is not None:
            valid_dates.append(
                (
                    parsed,
                    article,
                )
            )

    if valid_dates:

        newest_datetime, newest_article = max(
            valid_dates,
            key=lambda item: item[0],
        )

        newest_article_at = (
            newest_datetime.isoformat()
        )

        newest_age = (
            newest_article.age_hours
        )

    else:
        newest_article_at = None
        newest_age = None

    freshness = _freshness_label(
        newest_age
    )

    # -------------------------------------------------------------------------
    # Strongest catalyst
    # -------------------------------------------------------------------------

    strongest = None

    if scoring_articles:

        strongest = max(
            scoring_articles,
            key=lambda article: (
                article.catalyst_strength
                * article.relevance_score
                * _time_decay(
                    article.age_hours
                )
            ),
        )

    # -------------------------------------------------------------------------
    # Sort for UI / Orion AI
    # -------------------------------------------------------------------------

    analyzed.sort(
        key=lambda article: (
            abs(article.effective_score),
            article.catalyst_strength,
        ),
        reverse=True,
    )

    return NewsAnalysisResult(
        symbol=symbol,

        news_score=news_score,
        catalyst_strength=catalyst_strength,
        direction=direction,

        article_count=len(analyzed),
        relevant_article_count=len(relevant),

        strongest_catalyst=(
            strongest.catalyst_type
            if strongest
            else None
        ),

        strongest_catalyst_label=(
            strongest.catalyst_label
            if strongest
            else None
        ),

        positive_articles=positive_count,
        negative_articles=negative_count,
        neutral_articles=neutral_count,

        freshness=freshness,
        newest_article_at=newest_article_at,

        articles=[
            asdict(article)
            for article in analyzed
        ],

        warnings=warnings,
    ).to_dict()


# =============================================================================
# SMALLER OUTPUT FOR STRATEGY ENGINE
# =============================================================================

def get_strategy_news_context(
    symbol: str,
    *,
    lookback_hours: int = 72,
    limit: int = 30,
) -> Dict[str, Any]:
    """
    Convenience function for strategy_engine.py.

    Example result:

        {
            "news_score": 0.61,
            "catalyst_strength": 0.84,
            "news_direction": "bullish",
            ...
        }
    """

    analysis = analyze_news(
        symbol,
        lookback_hours=lookback_hours,
        limit=limit,
    )

    return {
        "news_score": analysis[
            "news_score"
        ],

        "catalyst_strength": analysis[
            "catalyst_strength"
        ],

        "news_direction": analysis[
            "direction"
        ],

        "news_freshness": analysis[
            "freshness"
        ],

        "news_article_count": analysis[
            "article_count"
        ],

        "news_relevant_article_count": analysis[
            "relevant_article_count"
        ],

        "strongest_catalyst": analysis[
            "strongest_catalyst"
        ],

        "strongest_catalyst_label": analysis[
            "strongest_catalyst_label"
        ],

        "news_articles": analysis[
            "articles"
        ],

        "news_warnings": analysis[
            "warnings"
        ],
    }


# =============================================================================
# MANUAL TEST
# =============================================================================

if __name__ == "__main__":

    import json
    import sys

    ticker = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "AAPL"
    )

    result = analyze_news(
        ticker
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )