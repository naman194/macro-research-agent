"""Project-wide constants and configuration."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_DB = CACHE_DIR / "cache.sqlite"

# override=True so values in .env always win over shell exports (which may be stale
# or empty from a previous session)
load_dotenv(PROJECT_ROOT / ".env", override=True)


def _get_secret(key: str) -> str:
    """Resolve a secret in order:
    1. Streamlit Cloud (st.secrets) — when deployed
    2. Process environment (.env loaded above) — local dev
    Returns "" if neither has the key.
    """
    # Streamlit Cloud: st.secrets exposes secrets injected via the dashboard UI
    try:
        import streamlit as st
        # Avoid raising when running outside streamlit context (st.secrets touched lazily)
        if hasattr(st, "secrets") and key in st.secrets:
            v = st.secrets[key]
            if v:
                return str(v).strip()
    except Exception:
        pass
    return os.getenv(key, "").strip()


ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
FRED_API_KEY = _get_secret("FRED_API_KEY")
SCREENER_PREMIUM_SESSIONID = _get_secret("SCREENER_PREMIUM_SESSIONID")

# Ticker → screener.in URL slug override for names where NSE symbol != screener slug.
# Discovered via screener's search API. Refresh annually or when a name re-lists.
SCREENER_SLUG_OVERRIDES = {
    "TATAMOTORS": "TMCV",       # Tata Motors split into TMCV (commercial) + TMPV
    "LTIM": "MINDTREE",         # screener.in still uses legacy MINDTREE slug post-merger
    "AARTI": "AARTIIND",
    "MAHANAGAR": "MGL",         # Mahanagar Gas
    "BLUESTAR": "BLUESTARCO",
    "ZOMATO": "ETERNAL",        # Zomato rebranded to Eternal Ltd (Mar-2025)
}

ANTHROPIC_MODEL = "claude-opus-4-7"

# Cache TTLs (seconds)
TTL_MACRO = 7 * 24 * 3600      # weekly
TTL_FUNDAMENTALS = 30 * 24 * 3600  # monthly (results are quarterly anyway)
TTL_QUOTES = 60 * 60           # hourly
TTL_FILINGS = 6 * 3600         # 6 hours

# NSE sector mapping — coarse buckets for sector-level aggregation
SECTOR_MAP = {
    "Banks": "Financials",
    "Finance": "Financials",
    "Insurance": "Financials",
    "Software": "IT",
    "IT - Software": "IT",
    "Pharmaceuticals": "Healthcare",
    "Healthcare": "Healthcare",
    "Auto": "Consumer Discretionary",
    "Auto Ancillaries": "Consumer Discretionary",
    "Consumer Durables": "Consumer Discretionary",
    "Retailing": "Consumer Discretionary",
    "FMCG": "Consumer Staples",
    "Personal Care": "Consumer Staples",
    "Cement": "Materials",
    "Chemicals": "Materials",
    "Metals": "Materials",
    "Steel": "Materials",
    "Oil & Gas": "Energy",
    "Power": "Utilities",
    "Capital Goods": "Industrials",
    "Construction": "Industrials",
    "Infrastructure": "Industrials",
    "Logistics": "Industrials",
    "Telecom": "Communication Services",
    "Media": "Communication Services",
    "Realty": "Real Estate",
}

# Curated ticker → screener.in-style sector mapping for the default universe.
# screener.in's HTML doesn't expose sector cleanly; we override with this map so the
# structural-risk overlay can actually fire.
TICKER_SECTOR_MAP = {
    "RELIANCE": "Oil & Gas", "ONGC": "Oil & Gas", "COALINDIA": "Oil & Gas",
    "BPCL": "Oil & Gas", "IOC": "Oil & Gas",
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "LTIM": "IT", "MPHASIS": "IT", "PERSISTENT": "IT", "COFORGE": "IT", "LTTS": "IT",
    "HDFCBANK": "Banks", "ICICIBANK": "Banks", "SBIN": "Banks", "KOTAKBANK": "Banks",
    "AXISBANK": "Banks", "INDUSINDBK": "Banks", "BANDHANBNK": "Banks",
    "IDFCFIRSTB": "Banks", "FEDERALBNK": "Banks", "AUBANK": "Banks",
    "BAJFINANCE": "Finance", "BAJAJFINSV": "Finance", "MUTHOOTFIN": "Finance",
    "CHOLAFIN": "Finance", "SHRIRAMFIN": "Finance",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "DABUR": "FMCG", "GODREJCP": "FMCG", "MARICO": "FMCG", "TATACONSUM": "FMCG",
    "COLPAL": "FMCG", "VBL": "FMCG", "UNITDSPR": "FMCG",
    "SUNPHARMA": "Pharmaceuticals", "DRREDDY": "Pharmaceuticals", "CIPLA": "Pharmaceuticals",
    "DIVISLAB": "Pharmaceuticals", "TORNTPHARM": "Pharmaceuticals", "ZYDUSLIFE": "Pharmaceuticals",
    "APOLLOHOSP": "Healthcare", "MEDANTA": "Healthcare", "FORTIS": "Healthcare",
    "MAXHEALTH": "Healthcare", "NH": "Healthcare", "ASTERDM": "Healthcare",
    "KIMS": "Healthcare", "RAINBOW": "Healthcare", "JUBLPHARMA": "Healthcare",
    "MARUTI": "Auto", "M&M": "Auto", "TATAMOTORS": "Auto",
    "BAJAJ-AUTO": "Auto", "HEROMOTOCO": "Auto", "EICHERMOT": "Auto", "TVSMOTOR": "Auto",
    "BOSCHLTD": "Auto Ancillaries", "MOTHERSON": "Auto Ancillaries",
    "ULTRACEMCO": "Cement", "SHREECEM": "Cement", "GRASIM": "Cement", "AMBUJACEM": "Cement",
    "PIDILITIND": "Chemicals", "BERGEPAINT": "Chemicals", "ASIANPAINT": "Chemicals",
    "JSWSTEEL": "Steel", "TATASTEEL": "Steel", "JINDALSTEL": "Steel",
    "HINDALCO": "Metals", "VEDL": "Metals",
    "BHARTIARTL": "Telecom",
    "LT": "Capital Goods", "ABB": "Capital Goods", "SIEMENS": "Capital Goods",
    "HAL": "Capital Goods",
    "POWERGRID": "Power", "NTPC": "Power", "TATAPOWER": "Power", "ADANIPOWER": "Power",
    "TITAN": "Consumer Durables", "PAGEIND": "Consumer Durables",
    "DMART": "Retailing", "TRENT": "Retailing",
    "ADANIENT": "Capital Goods", "ADANIPORTS": "Logistics", "INDIGO": "Logistics",
    "LICI": "Insurance", "HDFCLIFE": "Insurance", "SBILIFE": "Insurance",
    "ICICIGI": "Insurance", "ICICIPRULI": "Insurance",
    "JIOFIN": "Finance",
    # Defence & Aerospace
    "BEL": "Defence", "BHEL": "Defence", "BDL": "Defence",
    "MAZDOCK": "Defence", "MIDHANI": "Defence", "GRSE": "Defence",
    # Renewables (separate from generic Power)
    "ADANIGREEN": "Renewable Energy", "INOXWIND": "Renewable Energy",
    "SUZLON": "Renewable Energy", "BOROSILRNW": "Renewable Energy",
    "WAAREE": "Renewable Energy", "PREMIERENE": "Renewable Energy",
    # Aviation
    "INTERGLOBE": "Aviation", "SPICEJET": "Aviation",
    # Hotels
    "INDHOTEL": "Hotels", "LEMONTREE": "Hotels", "CHALET": "Hotels", "EIH": "Hotels",
    "MAHLIFE": "Hotels",
    # Sugar / Ethanol
    "TRIVENI": "Sugar", "BALRAMCHIN": "Sugar", "DHAMPURSUG": "Sugar",
    "DALMIASUG": "Sugar", "PRAJIND": "Sugar",
    # Agri / Fertilizers
    "UPL": "Fertilizers", "COROMANDEL": "Fertilizers", "CHAMBLFERT": "Fertilizers",
    "GNFC": "Fertilizers", "RCF": "Fertilizers", "NFL": "Fertilizers",
    "DEEPAKFERT": "Fertilizers", "GSFC": "Fertilizers",
    # Internet / E-commerce / Digital
    "ZOMATO": "Internet", "PAYTM": "Internet", "NYKAA": "Internet",
    "POLICYBZR": "Internet", "DELHIVERY": "Internet", "IRCTC": "Internet",
    "NAUKRI": "Internet",
    # Textiles
    "ARVIND": "Textiles", "WELCORP": "Textiles", "KPRMILL": "Textiles",
    "VARDHACRLC": "Textiles", "TRIDENT": "Textiles", "RAYMOND": "Textiles",
    # ===== Expanded universe additions =====
    # NIFTY Next 50 + large midcaps
    "AMBUJACEM": "Cement", "SHREECEM": "Cement", "JKCEMENT": "Cement",
    "ACC": "Cement", "RAMCOCEM": "Cement",
    "BAJAJHLDNG": "Finance", "CHOLAFIN": "Finance", "JIOFIN": "Finance",
    "PFC": "Finance", "RECLTD": "Finance", "IRFC": "Finance",
    "SBICARD": "Finance", "SHRIRAMFIN": "Finance",
    "POONAWALLA": "Finance", "MANAPPURAM": "Finance",
    "BANKBARODA": "Banks", "CANBK": "Banks", "PNB": "Banks",
    "ICICIPRULI": "Insurance", "ICICIGI": "Insurance", "LICI": "Insurance",
    "GICRE": "Insurance", "STARHEALTH": "Insurance", "NIACL": "Insurance",
    "MFSL": "Insurance",
    "ABB": "Capital Goods", "BOSCHLTD": "Auto Ancillaries",
    "HAVELLS": "Capital Goods", "SIEMENS": "Capital Goods",
    "CUMMINSIND": "Capital Goods", "POLYCAB": "Capital Goods",
    "DLF": "Realty", "LODHA": "Realty", "OBEROIRLTY": "Realty",
    "GODREJPROP": "Realty",
    "DMART": "Retailing", "TRENT": "Retailing", "ABFRL": "Retailing",
    "JUBLFOOD": "Retailing", "DEVYANI": "Retailing", "WESTLIFE": "Retailing",
    "GAIL": "Oil & Gas", "IOC": "Oil & Gas", "PETRONET": "Oil & Gas",
    "GUJGASLTD": "Oil & Gas", "MAHANAGAR": "Oil & Gas",
    "INDIGO": "Aviation",
    "TATAPOWER": "Power", "JSWENERGY": "Power", "ADANIPOWER": "Power",
    "NHPC": "Power",
    "TORNTPHARM": "Pharmaceuticals", "ZYDUSLIFE": "Pharmaceuticals",
    "BIOCON": "Pharmaceuticals", "LUPIN": "Pharmaceuticals",
    "AUROPHARMA": "Pharmaceuticals", "GLENMARK": "Pharmaceuticals",
    "ABBOTINDIA": "Pharmaceuticals", "AJANTPHARM": "Pharmaceuticals",
    "TVSMOTOR": "Auto", "MOTHERSON": "Auto Ancillaries",
    "BHARATFORG": "Auto Ancillaries", "MRF": "Auto Ancillaries",
    "BALKRISIND": "Auto Ancillaries",
    "COLPAL": "FMCG", "UNITDSPR": "FMCG", "VBL": "FMCG",
    "NAUKRI": "Internet", "ZOMATO": "Internet",
    "INDIAMART": "Internet", "CARTRADE": "Internet", "RAILTEL": "Internet",
    "OFSS": "IT", "TATAELXSI": "IT", "TATACOMM": "Telecom",
    "JINDALSTEL": "Steel", "VEDL": "Metals",
    "PIIND": "Chemicals", "SRF": "Chemicals", "DEEPAKNTR": "Chemicals",
    "NAVINFLUOR": "Chemicals", "AARTI": "Chemicals", "ATUL": "Chemicals",
    "DIXON": "Consumer Durables", "AMBER": "Consumer Durables",
    "VOLTAS": "Consumer Durables", "BLUESTAR": "Consumer Durables",
    "HAL": "Defence", "BHEL": "Defence",
    "BSE": "Finance", "CDSL": "Finance",
    "SUNTV": "Media", "ROUTE": "Telecom",
}

# NIFTY 500 universe — Phase 1 ships with a curated 50-name subset for speed;
# expand to full 500 in Phase 2 once caching is hardened.
DEFAULT_UNIVERSE = [
    # NIFTY 50 core
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR",
    "BHARTIARTL", "ITC", "SBIN", "LT", "KOTAKBANK", "HCLTECH", "AXISBANK",
    "ASIANPAINT", "MARUTI", "BAJFINANCE", "WIPRO", "SUNPHARMA", "TITAN",
    "ULTRACEMCO", "NESTLEIND", "M&M", "POWERGRID", "NTPC", "TATAMOTORS",
    "BAJAJFINSV", "ONGC", "TECHM", "JSWSTEEL", "TATASTEEL", "HINDALCO",
    "ADANIENT", "COALINDIA", "GRASIM", "BAJAJ-AUTO", "DRREDDY", "CIPLA",
    "EICHERMOT", "BRITANNIA", "HEROMOTOCO", "DIVISLAB", "APOLLOHOSP",
    "TATACONSUM", "PIDILITIND", "DABUR", "GODREJCP", "MARICO", "BERGEPAINT",
    "MUTHOOTFIN", "PAGEIND",
    # NIFTY Next 50 + large midcaps for High Conviction breadth
    "ABB", "AMBUJACEM", "BAJAJHLDNG", "BANKBARODA", "BOSCHLTD", "CANBK",
    "CHOLAFIN", "COLPAL", "DLF", "DMART", "GAIL", "HAVELLS", "HAL", "ICICIGI",
    "ICICIPRULI", "IOC", "INDIGO", "IRFC", "JINDALSTEL", "JIOFIN", "LICI",
    "LODHA", "NAUKRI", "NHPC", "PFC", "PNB", "RECLTD", "SBICARD", "SHREECEM",
    "SIEMENS", "TATAPOWER", "TORNTPHARM", "TVSMOTOR", "TRENT", "UNITDSPR",
    "VBL", "VEDL", "ZOMATO", "ZYDUSLIFE",
    # High-quality midcaps known for strong fundamentals
    "PERSISTENT", "COFORGE", "LTIM", "MPHASIS", "LTTS",        # IT mid
    "AUBANK", "FEDERALBNK", "IDFCFIRSTB", "INDUSINDBK", "BANDHANBNK",  # mid banks
    "SHRIRAMFIN", "BAJAJHLDNG",                                 # NBFCs
    "BIOCON", "LUPIN", "AUROPHARMA", "GLENMARK", "ABBOTINDIA",  # pharma mid
    "MOTHERSON", "BHARATFORG", "MRF", "BALKRISIND",            # auto anc
    "TATAELXSI", "POLYCAB", "CUMMINSIND", "BHEL",              # cap goods / engineering
    "PIIND", "SRF", "DEEPAKNTR", "NAVINFLUOR", "AARTI", "ATUL", # specialty chem
    "PETRONET", "GUJGASLTD", "MAHANAGAR",                       # gas distribution
    "JSWENERGY", "ADANIPOWER", "TATAPOWER",                     # power mid
    "DIXON", "AMBER", "VOLTAS", "BLUESTAR",                     # consumer durable / EMS
    "ABFRL", "AJANTPHARM", "GODREJPROP", "OBEROIRLTY",         # consumer / realty
    "JUBLFOOD", "DEVYANI", "WESTLIFE",                          # QSR
    "JKCEMENT", "ACC", "RAMCOCEM",                              # cement mid
    "OFSS", "TATACOMM", "ROUTE",                                # IT/Telecom
    "INDIAMART", "CARTRADE", "RAILTEL",                         # internet/digital
    "POONAWALLA", "MANAPPURAM",                                 # NBFC mid
    "BSE", "CDSL",                                              # exchanges
    "GICRE", "STARHEALTH", "NIACL",                             # insurance mid
    "MFSL", "SUNTV",                                            # finance + media
]
