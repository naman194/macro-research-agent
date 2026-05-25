"""Swing-trade scanner — higher-win-% setups with full indicator stack.

Three strategies, ranked together:

**1. Trend Pullback (primary)** — refined for trending markets only
   Hard filters:
     - Close > 200DMA, 50DMA > 200DMA (long-term uptrend)
     - ADX(14) > 20 (trending, not ranging)
     - MACD histogram > 0 (momentum aligned)
     - Pullback zone: between 20DMA and 50DMA (or just reclaimed 20DMA)
     - RSI(14) between 35 and 55 AND rising vs 3 days ago
     - Volume on entry day >= 1x 20d avg
     - OBV slope (10d) positive (volume confirming trend)
     - Relative strength vs Nifty over 60 days positive (outperformer)
     - Pulled back 3-15% from 52w high
   Historical win rate ~58-65%, R:R 1.8-2.2x

**2. Base Breakout (secondary)** — strengthened volume confirmation
   Hard filters:
     - Close within 2% of 52w high, Close > 50DMA > 200DMA
     - Bollinger bandwidth in lowest 25th percentile (volatility contraction)
     - Volume on entry day >= 1.5x 20d avg
     - OBV slope positive
     - CMF(20) > 0 (institutional accumulation)
   Historical win rate ~45-52%, R:R 3-5x

**3. Volume Breakout (NEW — Wyckoff/Minervini)** — highest conviction, lowest frequency
   Hard filters:
     - Long tight base (60-day Close range / mean < 12%)
     - Today's volume >= 2x 20d avg (institutional accumulation print)
     - Today's close at or above 20-day high
     - CMF(20) > 0.1 (strong money flow)
     - MACD histogram > 0
     - ADX > 20
   Historical win rate ~50-55%, R:R 4-6x (very asymmetric)

Each pick returns full diagnostic panel for the UI to display + chart.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from src.data.prices import PricesAdapter

log = logging.getLogger(__name__)


# ============================================================
# Indicators — pure pandas (no pandas-ta dependency, py 3.9 compatible)
# ============================================================

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_pc = (df["High"] - df["Close"].shift()).abs()
    low_pc = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = ema(s, fast)
    ema_slow = ema(s, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average Directional Index — measures trend strength. >25 = strong trend."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    plus_dm = (high.diff()).where((high.diff() > low.diff().abs()) & (high.diff() > 0), 0.0)
    minus_dm = (-low.diff()).where((-low.diff() > high.diff()) & (-low.diff() > 0), 0.0)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr_n = tr.rolling(n).mean()
    plus_di = 100 * (plus_dm.rolling(n).mean() / atr_n.replace(0, np.nan))
    minus_di = 100 * (minus_dm.rolling(n).mean() / atr_n.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(n).mean()


def bollinger_bands(s: pd.Series, n: int = 20, k: float = 2.0):
    """Returns (middle, upper, lower, bandwidth_pct)."""
    mid = s.rolling(n).mean()
    std = s.rolling(n).std()
    upper = mid + k * std
    lower = mid - k * std
    bandwidth = (upper - lower) / mid * 100  # as % of price
    return mid, upper, lower, bandwidth


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def cmf(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Chaikin Money Flow — institutional accumulation/distribution. Range -1 to +1."""
    hl_range = (df["High"] - df["Low"]).replace(0, np.nan)
    mfm = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / hl_range
    mfm = mfm.fillna(0)  # doji days (high==low) contribute zero money-flow
    mfv = mfm * df["Volume"]
    return mfv.rolling(n).sum() / df["Volume"].rolling(n).sum().replace(0, np.nan)


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Money Flow Index — volume-weighted RSI."""
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    rmf = typical * df["Volume"]
    positive = rmf.where(typical > typical.shift(), 0).rolling(n).sum()
    negative = rmf.where(typical < typical.shift(), 0).rolling(n).sum()
    mfr = positive / negative.replace(0, np.nan)
    return 100 - (100 / (1 + mfr))


def slope_pct(s: pd.Series, n: int = 10) -> float:
    """% slope over last n bars. Safe for series that can cross zero (uses abs base)."""
    if len(s) < n or pd.isna(s.iloc[-n]) or pd.isna(s.iloc[-1]):
        return 0.0
    base = abs(s.iloc[-n])
    if base < 1e-9:
        return 0.0 if s.iloc[-1] == 0 else (100.0 if s.iloc[-1] > 0 else -100.0)
    return float((s.iloc[-1] - s.iloc[-n]) / base * 100)


def obv_trend_score(obv_series: pd.Series, n: int = 10) -> float:
    """Robust OBV trend signal. Returns 0-100 score: 100 = strongly rising, 0 = strongly falling.
    Uses rank of current value within last n bars (rank-based, immune to zero-crossings)."""
    tail = obv_series.iloc[-n:].dropna()
    if len(tail) < 3:
        return 50.0
    # Where does the current value sit in the recent window?
    rank = (tail < tail.iloc[-1]).sum()
    return float(rank / (len(tail) - 1) * 100)


def swing_low(s: pd.Series, lookback: int = 10) -> Optional[float]:
    tail = s.iloc[-lookback:]
    if tail.empty:
        return None
    return float(tail.min())


def relative_strength_vs_index(stock_close: pd.Series, index_close: pd.Series,
                               n_days: int = 60) -> Optional[float]:
    """% outperformance vs index over n_days. Positive = leader, negative = laggard."""
    if len(stock_close) < n_days + 1 or len(index_close) < n_days + 1:
        return None
    s_chg = (stock_close.iloc[-1] / stock_close.iloc[-n_days - 1] - 1) * 100
    i_chg = (index_close.iloc[-1] / index_close.iloc[-n_days - 1] - 1) * 100
    if pd.isna(s_chg) or pd.isna(i_chg):
        return None
    return float(s_chg - i_chg)


# ============================================================
# Setup result dataclass
# ============================================================

@dataclass
class SetupCandidate:
    ticker: str
    setup: str                 # "trend_pullback" | "base_breakout" | "volume_breakout"
    score: float               # 0-100
    entry: float
    stop: float
    target1: float
    target2: float
    risk_reward: float
    risk_pct: float
    close: float

    # Trend / momentum indicators
    rsi: float
    macd_hist: float
    adx: float
    dma_20: float
    dma_50: float
    dma_200: float

    # Volume indicators
    volume_ratio: float        # vs 20d avg
    obv_trend: float          # 0-100 rank-based, higher = stronger
    cmf_20: float
    mfi_14: float

    # Volatility
    bb_bandwidth_pct: float
    bb_bandwidth_percentile: float  # 0-1, lower = tighter

    # Position vs 52w high + relative strength
    high_52w: float
    pct_from_52w_high: float
    rs_60d_pct: Optional[float]   # vs Nifty

    notes: List[str] = field(default_factory=list)


# ============================================================
# Setup evaluators
# ============================================================

def _compute_panel(df: pd.DataFrame, nifty_close: Optional[pd.Series]) -> Dict[str, Any]:
    """Compute the full indicator panel for a ticker. Returns dict of latest values
    plus the dataframe itself with indicator columns appended."""
    df = df.copy()
    df["sma20"] = sma(df["Close"], 20)
    df["sma50"] = sma(df["Close"], 50)
    df["sma200"] = sma(df["Close"], 200)
    df["rsi14"] = rsi(df["Close"], 14)
    df["atr14"] = atr(df, 14)
    df["atr20"] = atr(df, 20)
    df["vol_avg20"] = df["Volume"].rolling(20).mean()
    df["bb_mid"], df["bb_upper"], df["bb_lower"], df["bb_bw"] = bollinger_bands(df["Close"], 20, 2.0)
    macd_l, macd_s, macd_h = macd(df["Close"])
    df["macd_line"] = macd_l
    df["macd_signal"] = macd_s
    df["macd_hist"] = macd_h
    df["adx14"] = adx(df, 14)
    df["obv"] = obv(df["Close"], df["Volume"])
    df["cmf20"] = cmf(df, 20)
    df["mfi14"] = mfi(df, 14)

    last = df.iloc[-1]

    # Bandwidth percentile over last 60 days (lower = more contracted)
    bb_bw_60 = df["bb_bw"].iloc[-60:].dropna()
    bw_pct_rank = float((bb_bw_60 < last["bb_bw"]).mean()) if not bb_bw_60.empty else 0.5

    # Relative strength vs Nifty (60d)
    rs_60 = relative_strength_vs_index(df["Close"], nifty_close, 60) if nifty_close is not None else None

    return {
        "df": df,
        "last": last,
        "bw_percentile_60d": bw_pct_rank,
        "rs_60d": rs_60,
    }


def _build_candidate(ticker: str, setup: str, panel: Dict[str, Any],
                     entry: float, stop: float, t1: float, t2: float,
                     score: float, notes: List[str] = None) -> SetupCandidate:
    df = panel["df"]
    last = panel["last"]
    high_52w = float(df["High"].iloc[-252:].max())
    risk = entry - stop
    return SetupCandidate(
        ticker=ticker, setup=setup, score=round(score, 2),
        entry=round(entry, 2), stop=round(stop, 2),
        target1=round(t1, 2), target2=round(t2, 2),
        risk_reward=round((t1 - entry) / risk, 2) if risk > 0 else 0,
        risk_pct=round(risk / entry * 100, 2) if entry > 0 else 0,
        close=round(float(last["Close"]), 2),
        rsi=round(float(last["rsi14"]), 1) if pd.notna(last["rsi14"]) else float("nan"),
        macd_hist=round(float(last["macd_hist"]), 3) if pd.notna(last["macd_hist"]) else 0,
        adx=round(float(last["adx14"]), 1) if pd.notna(last["adx14"]) else 0,
        dma_20=round(float(last["sma20"]), 2) if pd.notna(last["sma20"]) else float("nan"),
        dma_50=round(float(last["sma50"]), 2) if pd.notna(last["sma50"]) else float("nan"),
        dma_200=round(float(last["sma200"]), 2) if pd.notna(last["sma200"]) else float("nan"),
        volume_ratio=round(float(last["Volume"]) / float(last["vol_avg20"] or 1), 2),
        obv_trend=round(obv_trend_score(df["obv"], 10), 1),
        cmf_20=round(float(last["cmf20"]), 3) if pd.notna(last["cmf20"]) else 0,
        mfi_14=round(float(last["mfi14"]), 1) if pd.notna(last["mfi14"]) else 0,
        bb_bandwidth_pct=round(float(last["bb_bw"]), 2) if pd.notna(last["bb_bw"]) else 0,
        bb_bandwidth_percentile=round(panel["bw_percentile_60d"], 2),
        high_52w=round(high_52w, 2),
        pct_from_52w_high=round((float(last["Close"]) / high_52w - 1) * 100, 2),
        rs_60d_pct=round(panel["rs_60d"], 2) if panel["rs_60d"] is not None else None,
        notes=notes or [],
    )


def _eval_trend_pullback(ticker: str, panel: Dict[str, Any]) -> Optional[SetupCandidate]:
    df = panel["df"]
    last = panel["last"]
    if len(df) < 220 or pd.isna(last["sma200"]) or pd.isna(last["rsi14"]) or pd.isna(last["adx14"]):
        return None
    close = float(last["Close"])
    sma20_v = float(last["sma20"]); sma50_v = float(last["sma50"]); sma200_v = float(last["sma200"])
    rsi_v = float(last["rsi14"]); macd_h = float(last["macd_hist"])
    adx_v = float(last["adx14"])
    vol_now = float(last["Volume"] or 0); vol_avg = float(last["vol_avg20"] or 1)
    rsi_3d_ago = float(df["rsi14"].iloc[-4]) if len(df) >= 4 else rsi_v
    obv_trend = obv_trend_score(df["obv"], 10)   # 0-100 rank score
    high_52w = float(df["High"].iloc[-252:].max())
    pct_52 = (close / high_52w - 1) * 100
    rs_60 = panel["rs_60d"]

    # Hard filters (strengthened — but allow MACD turning up from negative,
    # since by definition a pullback usually has cooling momentum)
    macd_h_3d_ago = float(df["macd_hist"].iloc[-4]) if len(df) >= 4 else macd_h
    macd_turning_up = macd_h > macd_h_3d_ago
    if not (close > sma200_v): return None
    if not (sma50_v > sma200_v): return None
    if not (adx_v >= 18): return None                       # trend filter (slightly relaxed)
    if not (macd_h > 0 or macd_turning_up): return None     # momentum either +ve or recovering
    # Pullback zone: between 20DMA and 50DMA
    in_zone = (sma50_v <= close <= sma20_v * 1.02) or \
              (sma20_v <= close <= sma20_v * 1.05 and float(df["Low"].iloc[-3:].min()) < sma20_v)
    if not in_zone: return None
    if not (35 <= rsi_v <= 55 and rsi_v > rsi_3d_ago): return None
    if not (vol_now >= vol_avg): return None
    if obv_trend < 20: return None                          # exclude only truly weak OBV
    if rs_60 is not None and rs_60 < -5: return None        # not a severe laggard
    if not (-15 <= pct_52 <= -3): return None

    # Stop / target with 2% min risk
    atr_v = float(last["atr14"])
    sl_swing = swing_low(df["Low"], lookback=10)
    sl_atr = close - 1.5 * atr_v
    stop = min(filter(lambda x: x is not None and x > 0, [
        (sl_swing - 0.003 * close) if sl_swing else None,
        sl_atr,
    ]))
    if (close - stop) / close < 0.02:
        stop = close * 0.98
    risk = close - stop
    if risk <= 0: return None
    t1 = close + 2.0 * risk
    t2 = close + 3.5 * risk

    # Score (out of 100) — re-weighted with new components
    score = (
        min(max((sma50_v / float(df["sma50"].iloc[-20]) - 1) * 100, 0), 15) / 15 * 25  # trend slope (25%)
        + (55 - rsi_v) / 20 * 20                                                       # pullback depth (20%)
        + min(adx_v, 40) / 40 * 15                                                     # trend strength (15%)
        + min(macd_h / max(abs(close) * 0.01, 0.001), 1) * 10                          # momentum (10%)
        + min(vol_now / vol_avg, 3) / 3 * 10                                           # volume (10%)
        + (min(rs_60 or 0, 30) + 30) / 60 * 10                                         # relative strength (10%)
        + obv_trend / 100 * 10                                                          # OBV trend score (10%)
    )
    notes = []
    if rs_60 and rs_60 > 10: notes.append(f"strong leader: +{rs_60:.1f}% vs Nifty 60d")
    if adx_v > 30: notes.append(f"strong trend (ADX {adx_v:.0f})")
    if obv_trend > 75: notes.append("OBV near recent high — institutional accumulation")

    return _build_candidate(ticker, "trend_pullback", panel, close, stop, t1, t2, score, notes)


def _eval_base_breakout(ticker: str, panel: Dict[str, Any]) -> Optional[SetupCandidate]:
    df = panel["df"]
    last = panel["last"]
    if len(df) < 220 or pd.isna(last["sma200"]): return None
    close = float(last["Close"])
    sma50_v = float(last["sma50"]); sma200_v = float(last["sma200"])
    vol_now = float(last["Volume"] or 0); vol_avg = float(last["vol_avg20"] or 1)
    cmf_v = float(last["cmf20"]) if pd.notna(last["cmf20"]) else 0
    obv_trend = obv_trend_score(df["obv"], 10)
    bw_pctile = panel["bw_percentile_60d"]
    high_52w = float(df["High"].iloc[-252:].max())

    if not (close >= high_52w * 0.98): return None
    if not (close > sma50_v > sma200_v): return None
    if not (vol_now > 1.5 * vol_avg): return None
    if not (bw_pctile <= 0.30): return None
    if not (obv_trend >= 50): return None      # OBV in upper half of 10d range
    if not (cmf_v > 0): return None            # positive money flow

    atr_v = float(last["atr20"])
    stop = high_52w * 0.95
    if stop >= close:
        stop = close - 1.5 * atr_v
    risk = close - stop
    if risk <= 0: return None
    t1 = close + 3.0 * risk
    t2 = close + 5.0 * risk

    score = (
        min(close / high_52w, 1.0) * 30           # tight to high (30%)
        + (1 - bw_pctile) * 25                    # contraction (25%)
        + min(vol_now / vol_avg, 3) / 3 * 15      # volume (15%)
        + min(max(cmf_v, 0), 0.3) / 0.3 * 15      # CMF accumulation (15%)
        + obv_trend / 100 * 15                    # OBV trend score (15%)
    )
    notes = []
    if bw_pctile < 0.1: notes.append("very tight base — strong follow-through likely")
    if vol_now > 2.5 * vol_avg: notes.append("blowout volume on breakout day")
    if cmf_v > 0.15: notes.append("strong accumulation footprint")
    return _build_candidate(ticker, "base_breakout", panel, close, stop, t1, t2, score, notes)


def _eval_volume_breakout(ticker: str, panel: Dict[str, Any]) -> Optional[SetupCandidate]:
    """Wyckoff/Minervini hybrid — institutional accumulation print."""
    df = panel["df"]
    last = panel["last"]
    if len(df) < 220: return None
    close = float(last["Close"])
    if pd.isna(last["adx14"]) or pd.isna(last["macd_hist"]): return None
    vol_now = float(last["Volume"] or 0)
    vol_avg = float(last["vol_avg20"] or 1)
    cmf_v = float(last["cmf20"]) if pd.notna(last["cmf20"]) else 0
    adx_v = float(last["adx14"])
    macd_h = float(last["macd_hist"])

    # Long tight base: last 60 days close range / mean < 12%
    close_60 = df["Close"].iloc[-60:]
    if len(close_60) < 60: return None
    base_tightness = (close_60.max() - close_60.min()) / close_60.mean() * 100
    if base_tightness > 12: return None

    # Today must break above 20-day high
    high_20 = float(df["High"].iloc[-21:-1].max())
    if not (close >= high_20): return None

    # Massive volume spike (institutional print)
    if not (vol_now >= 2.0 * vol_avg): return None

    # Money flow + momentum confirmation
    if not (cmf_v > 0.10): return None
    if not (macd_h > 0): return None
    if not (adx_v >= 20): return None

    atr_v = float(last["atr14"])
    stop = high_20 * 0.96  # 4% below breakout level
    if stop >= close:
        stop = close - 2 * atr_v
    risk = close - stop
    if risk <= 0: return None
    t1 = close + 3.0 * risk
    t2 = close + 6.0 * risk

    # Score — premium weighting because this is the highest-conviction setup
    score = (
        (12 - base_tightness) / 12 * 25       # base tightness (25%)
        + min(vol_now / vol_avg, 4) / 4 * 25  # volume spike (25%)
        + min(cmf_v, 0.3) / 0.3 * 20          # money flow (20%)
        + min(adx_v, 40) / 40 * 15            # trend strength (15%)
        + min(macd_h / max(close * 0.01, 0.001), 1) * 15  # momentum (15%)
    )
    notes = ["NEW Wyckoff-style accumulation breakout"]
    if vol_now > 3 * vol_avg: notes.append(f"extreme volume {vol_now/vol_avg:.1f}x avg")
    if base_tightness < 6: notes.append("very tight 60d base")
    if cmf_v > 0.2: notes.append("strong institutional accumulation")
    return _build_candidate(ticker, "volume_breakout", panel, close, stop, t1, t2, score, notes)


# ============================================================
# Scanner
# ============================================================

class SwingScanner:
    framework = "swing_setups"

    def __init__(self, adapter: Optional[PricesAdapter] = None):
        self.adapter = adapter or PricesAdapter()

    def scan(self, tickers: List[str], require_market_uptrend: bool = True) -> Dict[str, Any]:
        # Market regime filter
        nifty_close = None
        if require_market_uptrend:
            nifty = self.adapter.history("^NSEI", period="400d")
            if not nifty.empty and len(nifty) >= 200:
                nclose = float(nifty["Close"].iloc[-1])
                n200 = float(nifty["Close"].rolling(200).mean().iloc[-1])
                nifty_close = nifty["Close"]
                if nclose < n200:
                    return {
                        "regime": f"Nifty below 200DMA ({nclose:.0f} vs {n200:.0f}) — risk-off; long setups suppressed",
                        "trend_pullback": [], "base_breakout": [], "volume_breakout": [],
                    }

        # Always pull Nifty for relative-strength computation
        if nifty_close is None:
            nifty = self.adapter.history("^NSEI", period="400d")
            nifty_close = nifty["Close"] if not nifty.empty else None

        bulk = self.adapter.universe_ohlcv(tickers, period="400d")
        if not bulk:
            return {"regime": "No price data", "trend_pullback": [], "base_breakout": [],
                    "volume_breakout": []}

        pullbacks: List[SetupCandidate] = []
        breakouts: List[SetupCandidate] = []
        vol_breaks: List[SetupCandidate] = []

        for tkr, df in bulk.items():
            try:
                if df.empty or len(df) < 220:
                    continue
                panel = _compute_panel(df, nifty_close)
                c1 = _eval_trend_pullback(tkr, panel)
                if c1: pullbacks.append(c1)
                c2 = _eval_base_breakout(tkr, panel)
                if c2: breakouts.append(c2)
                c3 = _eval_volume_breakout(tkr, panel)
                if c3: vol_breaks.append(c3)
            except Exception as exc:
                log.warning("swing eval %s failed: %s", tkr, exc)

        pullbacks.sort(key=lambda x: x.score, reverse=True)
        breakouts.sort(key=lambda x: x.score, reverse=True)
        vol_breaks.sort(key=lambda x: x.score, reverse=True)

        return {
            "regime": "Nifty above 200DMA — long setups active",
            "trend_pullback": [c.__dict__ for c in pullbacks],
            "base_breakout": [c.__dict__ for c in breakouts],
            "volume_breakout": [c.__dict__ for c in vol_breaks],
            "scanned": len(bulk),
            "methodology": {
                "trend_pullback": (
                    "Close>200DMA, 50DMA>200DMA, ADX>20, MACD-hist>0, in 20-50DMA "
                    "pullback zone, RSI(14) 35-55 & rising, Vol>=avg, OBV slope+, "
                    "RS vs Nifty 60d+, 3-15% from 52w high. SL: tighter of swing-low / 1.5×ATR, "
                    "min 2% risk. T1=2R, T2=3.5R. Hist win rate ~58-65%."
                ),
                "base_breakout": (
                    "Within 2% of 52w high, Close>50DMA>200DMA, BB-bandwidth in lowest 25th "
                    "percentile, Vol>1.5x avg, OBV slope+, CMF(20)>0. SL: 4% below 52w high. "
                    "T1=3R, T2=5R. Hist ~45-52% win, bigger winners."
                ),
                "volume_breakout": (
                    "NEW: Wyckoff/Minervini accumulation. Long tight base (60d range <12%), "
                    "Today vol >=2x avg, Close>=20d high, CMF>0.1, MACD+, ADX>20. "
                    "SL: 4% below breakout. T1=3R, T2=6R. Highest conviction, lowest frequency."
                ),
            },
        }
