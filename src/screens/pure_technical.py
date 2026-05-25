"""Pure technical strategies — short-hold, high-frequency, mean-reversion + breakout.

Three academically-backed strategies. Each is INTENTIONALLY simple — 2-3 filters max.
Combined into a "Pure Technical Multi" mode where the user picks which strategy fires.

CONSTRAINT TRADE-OFFS (math forces this):
  - High hit rate (70%+) → mean reversion → small R:R (0.8-1.2x), 3-7 day holds
  - High R:R (3-5x)    → breakouts        → 50-60% hit rate, longer holds
  - You cannot have both. Pick your edge.

1. CONNORS RSI(2) — high hit rate, low R:R
   Entry: Close > 200DMA (regime filter) AND RSI(2) < 10 (oversold within uptrend)
   Exit:  RSI(2) > 70 OR 5 trading days (whichever first)
   Stop:  Hard SL at -3% (rare to hit)
   Hist:  70-75% win rate, avg trade +1.5 to +2.5%

2. BB MEAN REVERSION — medium-high hit rate
   Entry: Close > 200DMA AND price tags lower BB(20, 2σ)
   Exit:  Price touches mid-BB OR 10 trading days
   Stop:  Hard SL at -4%
   Hist:  65-72% win rate

3. DONCHIAN-20 BREAKOUT — lower hit rate, higher R:R
   Entry: Close = 20-day high AND volume > 1.5x avg AND close > 50DMA
   Exit:  ATR(14) trail (close - 2*ATR), or 30-bar time stop
   Hist:  55-62% win rate, R:R 2-3x typical
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from src.data.prices import PricesAdapter
from src.screens.swing_setups import atr, bollinger_bands, rsi, sma

log = logging.getLogger(__name__)


@dataclass
class TechSignal:
    ticker: str
    strategy: str
    entry: float
    stop: float
    target_logic: str
    expected_hold_days: int
    expected_winrate_pct: float
    rsi_2: Optional[float] = None
    rsi_14: Optional[float] = None
    bb_position_pct: Optional[float] = None
    atr_pct: Optional[float] = None
    volume_ratio: Optional[float] = None
    close: float = 0
    dma_200: float = 0
    notes: List[str] = field(default_factory=list)


# ============================================================
# Indicators
# ============================================================

def rsi_2(s: pd.Series) -> pd.Series:
    """Connors-style RSI(2). Extremely sensitive — fires on minor oversold."""
    return rsi(s, 2)


# ============================================================
# 1. CONNORS RSI(2) MEAN REVERSION
# ============================================================

def eval_connors_rsi2(ticker: str, df: pd.DataFrame) -> Optional[TechSignal]:
    if df is None or df.empty or len(df) < 210:
        return None
    df = df.copy()
    df["sma200"] = sma(df["Close"], 200)
    df["rsi2"] = rsi_2(df["Close"])
    last = df.iloc[-1]
    if pd.isna(last["sma200"]) or pd.isna(last["rsi2"]):
        return None
    close = float(last["Close"])
    s200 = float(last["sma200"])
    r2 = float(last["rsi2"])
    if not (close > s200): return None    # uptrend regime
    if not (r2 < 10): return None         # extreme short-term oversold
    return TechSignal(
        ticker=ticker, strategy="connors_rsi2",
        entry=round(close, 2),
        stop=round(close * 0.97, 2),
        target_logic="Exit when RSI(2) > 70 OR after 5 trading days",
        expected_hold_days=5, expected_winrate_pct=72.0,
        rsi_2=round(r2, 1), close=round(close, 2), dma_200=round(s200, 2),
        notes=["Connors mean-reversion: extreme short-term oversold in confirmed uptrend"],
    )


def simulate_connors_trade(df: pd.DataFrame, entry_idx: int) -> Optional[Dict]:
    """Walk forward 5 bars OR exit when RSI(2) > 70 OR -3% SL hit."""
    if entry_idx + 1 >= len(df):
        return None
    entry = float(df.iloc[entry_idx]["Close"])
    sl = entry * 0.97
    # Need RSI(2) computed
    rsi2_series = rsi_2(df["Close"])
    for j in range(entry_idx + 1, min(entry_idx + 6, len(df))):
        bar = df.iloc[j]
        if float(bar["Low"]) <= sl:
            exit_price = sl; reason = "SL"; break
        if pd.notna(rsi2_series.iloc[j]) and float(rsi2_series.iloc[j]) > 70:
            exit_price = float(bar["Close"]); reason = "RSI_exit"; break
    else:
        j = min(entry_idx + 5, len(df) - 1)
        exit_price = float(df.iloc[j]["Close"])
        reason = "time_stop"
    days_held = (df.index[j].date() - df.index[entry_idx].date()).days
    ret = (exit_price / entry - 1) * 100 - 0.5  # slippage
    return {
        "entry_date": df.index[entry_idx].date().isoformat(),
        "exit_date": df.index[j].date().isoformat(),
        "entry": round(entry, 2), "exit": round(exit_price, 2),
        "days_held": days_held, "return_pct": round(ret, 2),
        "reason": reason, "won": ret > 0,
    }


# ============================================================
# 2. BOLLINGER BAND MEAN REVERSION
# ============================================================

def eval_bb_meanrev(ticker: str, df: pd.DataFrame) -> Optional[TechSignal]:
    if df is None or df.empty or len(df) < 210:
        return None
    df = df.copy()
    df["sma200"] = sma(df["Close"], 200)
    df["bb_mid"], df["bb_upper"], df["bb_lower"], _ = bollinger_bands(df["Close"], 20, 2.0)
    last = df.iloc[-1]
    if any(pd.isna(last[c]) for c in ["sma200", "bb_lower", "bb_mid", "bb_upper"]):
        return None
    close = float(last["Close"])
    s200 = float(last["sma200"])
    bl = float(last["bb_lower"]); bm = float(last["bb_mid"]); bu = float(last["bb_upper"])
    if not (close > s200): return None
    # Price tags lower band (within 1% of lower band)
    if not (close <= bl * 1.01): return None
    pos_pct = (close - bl) / (bu - bl) * 100 if bu > bl else 50
    return TechSignal(
        ticker=ticker, strategy="bb_meanrev",
        entry=round(close, 2),
        stop=round(close * 0.96, 2),
        target_logic=f"Exit at BB middle band (₹{bm:.1f}) OR 10 trading days",
        expected_hold_days=10, expected_winrate_pct=68.0,
        bb_position_pct=round(pos_pct, 1), close=round(close, 2), dma_200=round(s200, 2),
        notes=[f"Price at lower BB ({pos_pct:.0f}% band position); revert to mid (₹{bm:.1f})"],
    )


def simulate_bb_trade(df: pd.DataFrame, entry_idx: int) -> Optional[Dict]:
    if entry_idx + 1 >= len(df):
        return None
    entry = float(df.iloc[entry_idx]["Close"])
    sl = entry * 0.96
    _, _, _, _ = bollinger_bands(df["Close"], 20, 2.0)
    bb_mid_series, _, _, _ = bollinger_bands(df["Close"], 20, 2.0)
    bb_mid_at_entry = float(bb_mid_series.iloc[entry_idx]) if pd.notna(bb_mid_series.iloc[entry_idx]) else entry * 1.02
    target = bb_mid_at_entry
    for j in range(entry_idx + 1, min(entry_idx + 11, len(df))):
        bar = df.iloc[j]
        if float(bar["Low"]) <= sl:
            exit_price = sl; reason = "SL"; break
        if float(bar["High"]) >= target:
            exit_price = target; reason = "T_midband"; break
    else:
        j = min(entry_idx + 10, len(df) - 1)
        exit_price = float(df.iloc[j]["Close"])
        reason = "time_stop"
    days_held = (df.index[j].date() - df.index[entry_idx].date()).days
    ret = (exit_price / entry - 1) * 100 - 0.5
    return {
        "entry_date": df.index[entry_idx].date().isoformat(),
        "exit_date": df.index[j].date().isoformat(),
        "entry": round(entry, 2), "exit": round(exit_price, 2),
        "days_held": days_held, "return_pct": round(ret, 2),
        "reason": reason, "won": ret > 0,
    }


# ============================================================
# 3. DONCHIAN-20 BREAKOUT
# ============================================================

def eval_donchian20(ticker: str, df: pd.DataFrame) -> Optional[TechSignal]:
    if df is None or df.empty or len(df) < 60:
        return None
    df = df.copy()
    df["sma50"] = sma(df["Close"], 50)
    df["atr14"] = atr(df, 14)
    df["vol_avg20"] = df["Volume"].rolling(20).mean()
    last = df.iloc[-1]
    if pd.isna(last["sma50"]) or pd.isna(last["atr14"]):
        return None
    close = float(last["Close"])
    s50 = float(last["sma50"])
    atr_v = float(last["atr14"])
    vol_now = float(last["Volume"] or 0); vol_avg = float(last["vol_avg20"] or 1)
    high20 = float(df["High"].iloc[-21:-1].max())
    if not (close >= high20): return None
    if not (close > s50): return None
    if not (vol_now >= 1.5 * vol_avg): return None
    stop = close - 2 * atr_v
    return TechSignal(
        ticker=ticker, strategy="donchian20",
        entry=round(close, 2),
        stop=round(stop, 2),
        target_logic=f"ATR(14) trailing stop at close - 2*ATR (initial: ₹{stop:.1f})",
        expected_hold_days=20, expected_winrate_pct=58.0,
        atr_pct=round(atr_v / close * 100, 2),
        volume_ratio=round(vol_now / vol_avg, 2),
        close=round(close, 2), dma_200=round(s50, 2),
        notes=[f"20-day high breakout with {vol_now/vol_avg:.1f}x volume confirmation"],
    )


def simulate_donchian_trade(df: pd.DataFrame, entry_idx: int) -> Optional[Dict]:
    if entry_idx + 1 >= len(df):
        return None
    entry = float(df.iloc[entry_idx]["Close"])
    atr_series = atr(df, 14)
    atr_v = float(atr_series.iloc[entry_idx]) if pd.notna(atr_series.iloc[entry_idx]) else entry * 0.02
    trail_stop = entry - 2 * atr_v
    max_close = entry
    for j in range(entry_idx + 1, min(entry_idx + 31, len(df))):
        bar = df.iloc[j]
        bar_low = float(bar["Low"]); bar_high = float(bar["High"]); bar_close = float(bar["Close"])
        # Update trailing stop on new highs
        if bar_close > max_close:
            max_close = bar_close
            new_stop = max_close - 2 * (float(atr_series.iloc[j]) if pd.notna(atr_series.iloc[j]) else atr_v)
            if new_stop > trail_stop:
                trail_stop = new_stop
        if bar_low <= trail_stop:
            exit_price = trail_stop; reason = "trail_stop"; break
    else:
        j = min(entry_idx + 30, len(df) - 1)
        exit_price = float(df.iloc[j]["Close"])
        reason = "time_stop"
    days_held = (df.index[j].date() - df.index[entry_idx].date()).days
    ret = (exit_price / entry - 1) * 100 - 0.5
    return {
        "entry_date": df.index[entry_idx].date().isoformat(),
        "exit_date": df.index[j].date().isoformat(),
        "entry": round(entry, 2), "exit": round(exit_price, 2),
        "days_held": days_held, "return_pct": round(ret, 2),
        "reason": reason, "won": ret > 0,
    }


# ============================================================
# Scanner — live picks
# ============================================================

STRATEGIES = {
    "connors_rsi2": eval_connors_rsi2,
    "bb_meanrev": eval_bb_meanrev,
    "donchian20": eval_donchian20,
}


def scan_pure_technical(tickers: List[str],
                        prices: Optional[PricesAdapter] = None
                        ) -> Dict[str, List[TechSignal]]:
    """Run all 3 strategies on universe. Returns dict by strategy."""
    prices = prices or PricesAdapter()
    bulk = prices.universe_ohlcv(tickers, period="300d")
    out = {s: [] for s in STRATEGIES.keys()}
    for tkr, df in bulk.items():
        if df.empty or len(df) < 210:
            continue
        for name, fn in STRATEGIES.items():
            try:
                s = fn(tkr, df)
                if s:
                    out[name].append(s)
            except Exception as exc:
                log.warning("eval %s %s: %s", name, tkr, exc)
    return out


# ============================================================
# Backtest
# ============================================================

SIMULATORS = {
    "connors_rsi2": simulate_connors_trade,
    "bb_meanrev": simulate_bb_trade,
    "donchian20": simulate_donchian_trade,
}


def backtest_pure_technical(tickers: List[str], strategy: str = "connors_rsi2",
                             years: int = 4,
                             prices: Optional[PricesAdapter] = None) -> Dict[str, Any]:
    """Walk-forward backtest of pure-technical strategy."""
    if strategy not in STRATEGIES:
        return {"error": f"unknown strategy: {strategy}"}
    eval_fn = STRATEGIES[strategy]
    sim_fn = SIMULATORS[strategy]
    prices = prices or PricesAdapter()
    period_days = years * 365 + 250

    trades = []
    for tkr in tickers:
        try:
            df = prices.history(f"{tkr}.NS", period=f"{period_days}d")
            if df.empty or len(df) < 250:
                continue
            i = 220
            while i < len(df) - 32:
                window = df.iloc[: i + 1]
                signal = eval_fn(tkr, window)
                if signal is not None:
                    sim = sim_fn(df, i)
                    if sim:
                        trades.append({"ticker": tkr, **sim})
                        # Skip ahead past the trade exit
                        i = i + max(sim["days_held"], 1)
                        continue
                i += 1
        except Exception as exc:
            log.warning("backtest %s %s: %s", strategy, tkr, exc)

    if not trades:
        return {"error": "No trades fired during backtest."}

    rets = [t["return_pct"] for t in trades]
    wins = sum(1 for r in rets if r > 0)
    avg_win = np.mean([r for r in rets if r > 0]) if any(r > 0 for r in rets) else 0
    avg_loss = np.mean([r for r in rets if r <= 0]) if any(r <= 0 for r in rets) else 0
    return {
        "strategy": strategy,
        "n_trades": len(trades),
        "hit_rate_pct": round(wins / len(trades) * 100, 1),
        "wins": wins, "losses": len(trades) - wins,
        "avg_return_pct": round(sum(rets) / len(rets), 2),
        "median_return_pct": round(float(np.median(rets)), 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "win_loss_ratio": round(abs(avg_win / avg_loss), 2) if avg_loss < 0 else 0,
        "expectancy_pct": round(sum(rets) / len(rets), 2),
        "best_trade": round(max(rets), 2),
        "worst_trade": round(min(rets), 2),
        "avg_days_held": round(sum(t["days_held"] for t in trades) / len(trades), 1),
        "trades": trades,
    }
