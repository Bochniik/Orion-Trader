
from __future__ import annotations

from typing import Any, Dict, Iterable, List


THEMES: Dict[str, Dict[str, Any]] = {
    "ai": {
        "label": "Artificial Intelligence",
        "description": "AI software, infrastructure, accelerators and materially AI-exposed businesses.",
    },
    "ev": {
        "label": "Electric Vehicles",
        "description": "Electric-vehicle manufacturers and directly exposed EV technology suppliers.",
    },
    "oil_gas": {
        "label": "Oil & Gas",
        "description": "Oil and gas producers, refiners and oilfield services.",
    },
    "cybersecurity": {
        "label": "Cybersecurity",
        "description": "Security software, identity and network-security businesses.",
    },
    "quantum": {
        "label": "Quantum Computing",
        "description": "Quantum-computing hardware, systems and enabling platforms.",
    },
    "space": {
        "label": "Space",
        "description": "Launch, satellite, spacecraft and space-infrastructure businesses.",
    },
    "defense": {
        "label": "Defense",
        "description": "Defense contractors and defense-technology businesses.",
    },
    "robotics": {
        "label": "Robotics & Automation",
        "description": "Industrial automation, surgical robotics and robotic systems.",
    },
    "biotech": {
        "label": "Biotechnology",
        "description": "Biotechnology and advanced therapeutics businesses.",
    },
    "nuclear": {
        "label": "Nuclear Energy",
        "description": "Nuclear generation, uranium and nuclear-technology businesses.",
    },
    "renewables": {
        "label": "Renewable Energy",
        "description": "Solar, renewable generation and clean-energy infrastructure.",
    },
    "crypto": {
        "label": "Crypto-related Equities",
        "description": "Public equities with material cryptocurrency exposure.",
    },
    "cloud": {
        "label": "Cloud Computing",
        "description": "Cloud infrastructure, platforms and cloud-native software.",
    },
    "fintech": {
        "label": "Fintech",
        "description": "Digital payments, brokerage and financial-technology businesses.",
    },
    "food": {
        "label": "Food",
        "description": "Food producers and packaged-food businesses.",
    },
}


# Theme membership is a classification catalogue, not a recommendation.
# The lists below are seed/override memberships. They can be expanded without
# changing market analytics or Orion Engine logic.
CURATED_THEME_MEMBERS: Dict[str, List[str]] = {
    "ai": [
        "NVDA", "AMD", "AVGO", "MSFT", "GOOGL", "META", "AMZN", "ORCL",
        "CRM", "PLTR", "SNOW", "DDOG", "NET", "MDB", "NOW", "ADBE",
        "PATH", "AI", "SMCI", "ARM", "MRVL", "MU", "QCOM", "INTC",
    ],
    "ev": [
        "TSLA", "RIVN", "LCID", "GM", "F", "NIO", "LI", "XPEV",
        "ON", "ALB", "CHPT", "BLNK", "QS", "ENVX",
    ],
    "oil_gas": [
        "XOM", "CVX", "COP", "EOG", "OXY", "SLB", "HAL", "MPC", "VLO",
        "PSX", "DVN", "FANG", "APA", "BKR", "KMI", "WMB", "LNG",
    ],
    "cybersecurity": [
        "CRWD", "PANW", "FTNT", "ZS", "OKTA", "S", "CYBR", "GEN",
        "TENB", "VRNS", "RBRK", "NET",
    ],
    "quantum": [
        "IONQ", "RGTI", "QBTS", "QUBT", "IBM", "GOOGL", "MSFT", "HON",
    ],
    "space": [
        "SPCX", "RKLB", "ASTS", "LUNR", "RDW", "PL", "SPCE", "BKSY",
        "IRDM", "GSAT", "SATL", "SIDU", "MNTS", "BA", "LMT", "NOC",
    ],
    "defense": [
        "LMT", "RTX", "NOC", "GD", "LHX", "HII", "KTOS", "AVAV",
        "BA", "LDOS", "CACI", "BWXT",
    ],
    "robotics": [
        "ISRG", "TER", "ROK", "PATH", "SYM", "CGNX", "ABB", "NVDA",
        "AMZN", "IRBT", "SERV",
    ],
    "biotech": [
        "VRTX", "REGN", "GILD", "AMGN", "BIIB", "MRNA", "BMRN", "ALNY",
        "ILMN", "CRSP", "NTLA", "BEAM", "EDIT", "SRPT",
    ],
    "nuclear": [
        "CEG", "VST", "CCJ", "LEU", "SMR", "OKLO", "BWXT", "UEC", "NXE",
        "UUUU", "DNN", "URG", "NNE",
    ],
    "renewables": [
        "FSLR", "ENPH", "SEDG", "NXT", "RUN", "BE", "PLUG", "NEE",
        "AES", "ARRY", "SHLS",
    ],
    "crypto": [
        "COIN", "MSTR", "MARA", "RIOT", "CLSK", "HOOD", "IREN", "HUT",
        "CIFR", "BTDR", "CORZ", "WULF",
    ],
    "cloud": [
        "MSFT", "AMZN", "GOOGL", "ORCL", "CRM", "NOW", "SNOW", "DDOG",
        "NET", "MDB", "ESTC", "CFLT", "DOCN", "GTLB",
    ],
    "fintech": [
        "V", "MA", "PYPL", "XYZ", "HOOD", "SOFI", "AFRM", "NU",
        "COIN", "FIS", "FI", "TOST", "UPST",
    ],
    "food": [
        "KO", "PEP", "MDLZ", "KHC", "GIS", "K", "HSY", "SJM", "CAG",
        "TSN", "CPB", "HRL", "MKC", "LW", "POST",
    ],
}


def themes_for_symbol(
    ticker: str,
    *,
    sector: str = "",
    industry: str = "",
    company_name: str = "",
) -> List[str]:
    ticker = str(ticker or "").strip().upper()

    direct = [
        theme_id
        for theme_id, members in CURATED_THEME_MEMBERS.items()
        if ticker in members
    ]

    # Conservative metadata rules. These rules add obvious broad classifications
    # but never use Orion Score or trading signals.
    text = " ".join(
        (
            str(sector or ""),
            str(industry or ""),
            str(company_name or ""),
        )
    ).lower()

    rules = {
        "biotech": (
            "biotechnology",
            "biotech",
        ),
        "oil_gas": (
            "oil & gas",
            "oil and gas",
            "oilfield",
            "petroleum",
        ),
        "food": (
            "packaged foods",
            "food products",
            "meat products",
        ),
        "cybersecurity": (
            "security software",
            "cybersecurity",
        ),
        "renewables": (
            "solar",
            "renewable",
        ),
        "fintech": (
            "financial technology",
            "payments",
        ),
    }

    inferred = [
        theme_id
        for theme_id, keywords in rules.items()
        if any(keyword in text for keyword in keywords)
    ]

    return list(
        dict.fromkeys(
            [*direct, *inferred]
        )
    )
