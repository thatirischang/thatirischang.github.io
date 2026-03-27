"""
BTC B策略 V4.2 — 技術指標計算模組 ✅已驗證
計算 MACD、RSI、布林帶、EMA、成交量比率等指標
"""

import numpy as np
import pandas as pd
from config.settings import (
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    RSI_PERIOD, BOLL_PERIOD, BOLL_STD,
    EMA_SHORT, EMA_MID, EMA_LONG,
    VOL_MA_PERIOD, VOL_CONFIRM_RATIO,
)


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """計算指數移動平均線（EMA）"""
    return series.ewm(span=period, adjust=False).mean()


def calc_macd(close: pd.Series):
    """
    計算 MACD（12/26/9）
    回傳 (macd_line, signal_line, histogram)
    """
    ema_fast   = calc_ema(close, MACD_FAST)
    ema_slow   = calc_ema(close, MACD_SLOW)
    macd_line  = ema_fast - ema_slow
    signal_line= calc_ema(macd_line, MACD_SIGNAL)
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """計算 RSI（14）"""
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def calc_bollinger(close: pd.Series):
    """
    計算布林帶（MA20 / 2σ）
    回傳 (upper, middle, lower)
    """
    middle = close.rolling(BOLL_PERIOD).mean()
    std    = close.rolling(BOLL_PERIOD).std()
    upper  = middle + BOLL_STD * std
    lower  = middle - BOLL_STD * std
    return upper, middle, lower


def calc_volume_ratio(volume: pd.Series) -> pd.Series:
    """計算成交量比率（當前成交量 / 20根均量）"""
    vol_ma = volume.rolling(VOL_MA_PERIOD).mean()
    return volume / vol_ma.replace(0, np.nan)


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    對 OHLCV DataFrame 計算所有技術指標，並新增欄位。
    輸入 DataFrame 需包含欄位：open, high, low, close, volume
    """
    df = df.copy()

    # EMA
    df["ema20"]  = calc_ema(df["close"], EMA_SHORT)
    df["ema50"]  = calc_ema(df["close"], EMA_MID)
    df["ema200"] = calc_ema(df["close"], EMA_LONG)

    # MACD
    df["macd"], df["macd_signal"], df["macd_hist"] = calc_macd(df["close"])

    # RSI
    df["rsi"] = calc_rsi(df["close"])

    # 布林帶
    df["boll_upper"], df["boll_mid"], df["boll_lower"] = calc_bollinger(df["close"])

    # 成交量比率
    df["vol_ratio"] = calc_volume_ratio(df["volume"])

    # 價格相對 EMA200 偏離（用於近似 MVRV）
    df["dev_ema200"] = (df["close"] - df["ema200"]) / df["ema200"]

    # 漲跌幅
    df["change_1h"] = df["close"].pct_change(1)
    df["change_4h"] = df["close"].pct_change(4)
    df["change_1d"] = df["close"].pct_change(24)

    return df


def get_latest_indicators(df: pd.DataFrame) -> dict:
    """
    從已計算指標的 DataFrame 中取出最新一根K線的所有指標值。
    回傳 dict，方便評分模組使用。
    """
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    # MACD 金叉 / 死叉判斷
    macd_cross_up   = (prev["macd"] < prev["macd_signal"]) and (last["macd"] >= last["macd_signal"])
    macd_cross_down = (prev["macd"] > prev["macd_signal"]) and (last["macd"] <= last["macd_signal"])
    macd_bullish    = last["macd"] > last["macd_signal"]

    # 布林帶位置
    boll_range = last["boll_upper"] - last["boll_lower"]
    boll_pos   = (last["close"] - last["boll_lower"]) / boll_range if boll_range > 0 else 0.5

    return {
        "close":         float(last["close"]),
        "ema20":         float(last["ema20"]),
        "ema50":         float(last["ema50"]),
        "ema200":        float(last["ema200"]),
        "macd":          float(last["macd"]),
        "macd_signal":   float(last["macd_signal"]),
        "macd_hist":     float(last["macd_hist"]),
        "macd_cross_up": macd_cross_up,
        "macd_cross_down": macd_cross_down,
        "macd_bullish":  macd_bullish,
        "rsi":           float(last["rsi"]),
        "boll_upper":    float(last["boll_upper"]),
        "boll_mid":      float(last["boll_mid"]),
        "boll_lower":    float(last["boll_lower"]),
        "boll_pos":      float(boll_pos),
        "vol_ratio":     float(last["vol_ratio"]) if not np.isnan(last["vol_ratio"]) else 1.0,
        "dev_ema200":    float(last["dev_ema200"]),
        "change_1h":     float(last["change_1h"]),
        "change_4h":     float(last["change_4h"]),
        "change_1d":     float(last["change_1d"]),
        "above_ema200":  last["close"] > last["ema200"],
        "above_ema50":   last["close"] > last["ema50"],
        "above_boll_mid":last["close"] > last["boll_mid"],
    }
