#!/usr/bin/env python3
"""
BTC B策略 V4.2 — 回測腳本
使用 OKX 真實歷史 K 線數據進行策略回測

執行方式：
  python3 backtest.py --start 2025-01-01 --end 2025-03-27
  python3 backtest.py --start 2024-01-01 --end 2024-12-31
  python3 backtest.py --start 2023-01-01 --end 2023-12-31

回測結果對照（V4.2 文件記錄）：
  2025年1月至今：策略-4.0% vs 買入持有-26.6%（跑贏+22.6%）
  最大回撤：6.6% | 勝率：63.2% | 交易次數：171次
"""

import sys
import os
import argparse
import json
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.indicators import add_all_indicators, get_latest_indicators
from core.scoring import calc_total_score, calc_position_size, get_ml_state
from config.settings import (
    TOTAL_CAPITAL, STOP_LOSS_PCT, MAX_POSITION, RESERVE_CAPITAL,
    TP1_SELL_RATIO, TP2_SELL_RATIO,
    TRAILING_STOP_TRIGGER, TRAILING_STOP_TRAIL,
    MIN_SCORE_TO_TRADE,
)


# ─────────────────────────────────────────
# 從 OKX 獲取歷史 K 線（分批獲取）
# ─────────────────────────────────────────
def fetch_historical_klines(start_date: str, end_date: str) -> pd.DataFrame:
    """從 OKX API 獲取指定日期範圍的歷史 1H K 線"""
    import requests

    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ts   = int(datetime.strptime(end_date,   "%Y-%m-%d").timestamp() * 1000)

    all_candles = []
    after = end_ts

    print(f"正在獲取 {start_date} ~ {end_date} 的歷史K線...")

    while after > start_ts:
        url = "https://www.okx.com/api/v5/market/history-candles"
        params = {
            "instId": "BTC-USDT",
            "bar":    "1H",
            "after":  str(after),
            "limit":  "300",
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
            candles = data.get("data", [])
            if not candles:
                break

            for c in candles:
                ts = int(c[0])
                if ts >= start_ts:
                    all_candles.append({
                        "timestamp": ts,
                        "open":   float(c[1]),
                        "high":   float(c[2]),
                        "low":    float(c[3]),
                        "close":  float(c[4]),
                        "volume": float(c[5]),
                    })

            after = int(candles[-1][0]) - 1
            import time
            time.sleep(0.2)   # 避免觸發頻率限制

        except Exception as e:
            print(f"獲取K線失敗: {e}")
            break

    df = pd.DataFrame(all_candles)
    if df.empty:
        return df

    df = df.drop_duplicates("timestamp")
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    print(f"共獲取 {len(df)} 根K線")
    return df


# ─────────────────────────────────────────
# 回測引擎
# ─────────────────────────────────────────
class Backtester:
    def __init__(self, initial_capital: float = 500.0):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.btc_held = 0.0
        self.entry_price = 0.0
        self.entry_usdt = 0.0
        self.stop_loss = 0.0
        self.highest_price = 0.0
        self.tp1_done = False
        self.tp2_done = False

        # 統計
        self.trades = []
        self.equity_curve = []
        self.max_equity = initial_capital
        self.max_drawdown = 0.0

    def _calc_equity(self, price: float) -> float:
        return self.capital + self.btc_held * price

    def _open(self, price: float, usdt: float, score: float, ts: int):
        self.entry_price   = price
        self.entry_usdt    = usdt
        self.btc_held      = usdt / price
        self.capital      -= usdt
        self.stop_loss     = price * (1 - STOP_LOSS_PCT)
        self.highest_price = price
        self.tp1_done      = False
        self.tp2_done      = False
        self.trades.append({
            "type": "BUY", "price": price, "usdt": usdt,
            "score": score, "ts": ts,
        })

    def _close(self, price: float, reason: str, ts: int):
        if self.btc_held <= 0:
            return
        proceeds = self.btc_held * price
        self.capital += proceeds
        pnl = proceeds - self.entry_usdt
        self.trades.append({
            "type": "SELL", "price": price, "usdt": proceeds,
            "pnl": pnl, "reason": reason, "ts": ts,
        })
        self.btc_held    = 0.0
        self.entry_price = 0.0
        self.entry_usdt  = 0.0

    def run(self, df: pd.DataFrame) -> dict:
        """執行回測，回傳統計結果"""
        df = add_all_indicators(df)

        for i in range(210, len(df)):   # 前210根用於指標預熱
            row = df.iloc[i]
            ind = get_latest_indicators(df.iloc[:i+1])
            price = ind["close"]
            ts    = int(row["timestamp"])

            # 更新權益曲線
            equity = self._calc_equity(price)
            self.equity_curve.append({"ts": ts, "equity": equity})

            # 更新最大回撤
            if equity > self.max_equity:
                self.max_equity = equity
            dd = (self.max_equity - equity) / self.max_equity
            if dd > self.max_drawdown:
                self.max_drawdown = dd

            # ── 持倉管理 ──
            if self.btc_held > 0:
                # 更新最高價
                if price > self.highest_price:
                    self.highest_price = price

                # 移動止損
                pnl_pct = (price - self.entry_price) / self.entry_price
                if pnl_pct >= 0.15:
                    new_sl = self.highest_price * TRAILING_STOP_TRAIL
                    if new_sl > self.stop_loss:
                        self.stop_loss = new_sl
                elif pnl_pct >= 0.10:
                    new_sl = self.entry_price * 1.05
                    if new_sl > self.stop_loss:
                        self.stop_loss = new_sl
                elif pnl_pct >= 0.05:
                    if self.entry_price > self.stop_loss:
                        self.stop_loss = self.entry_price

                # 固定止損
                if price <= self.stop_loss:
                    self._close(price, "固定止損", ts)
                    continue

                # 結構止損：跌破EMA200
                if not ind["above_ema200"]:
                    self._close(price, "結構止損EMA200", ts)
                    continue

                # ML狀態D止損
                if get_ml_state(ind) == "D":
                    self._close(price, "ML狀態D", ts)
                    continue

                # 計算評分（用於止盈判斷）
                bd = calc_total_score(ind)

                # 第一檔止盈（賣出30%）
                if not self.tp1_done:
                    if ind["rsi"] > 75 and ind["boll_pos"] > 0.95:
                        sell_btc = self.btc_held * TP1_SELL_RATIO
                        sell_usdt = sell_btc * price
                        self.capital += sell_usdt
                        self.btc_held -= sell_btc
                        self.entry_usdt *= (1 - TP1_SELL_RATIO)
                        self.tp1_done = True
                        self.trades.append({
                            "type": "TP1", "price": price,
                            "usdt": sell_usdt, "ts": ts,
                        })
                        continue

                # 第二檔止盈（賣出50%）
                if not self.tp2_done and self.tp1_done:
                    if ind["macd_cross_down"]:
                        sell_btc = self.btc_held * TP2_SELL_RATIO
                        sell_usdt = sell_btc * price
                        self.capital += sell_usdt
                        self.btc_held -= sell_btc
                        self.entry_usdt *= (1 - TP2_SELL_RATIO)
                        self.tp2_done = True
                        self.trades.append({
                            "type": "TP2", "price": price,
                            "usdt": sell_usdt, "ts": ts,
                        })
                        continue

                # 第三檔止盈（日線MACD死叉）
                if ind.get("macd_cross_down") and not ind["macd_bullish"]:
                    self._close(price, "TP3日線死叉", ts)
                    continue

            # ── 開倉決策 ──
            else:
                # 日線過濾
                daily_ok = sum([
                    ind["above_ema200"],
                    ind["macd_bullish"],
                    ind["rsi"] > 45,
                    ind["above_boll_mid"],
                ]) >= 2

                if not daily_ok:
                    continue

                # 成交量確認
                if ind["vol_ratio"] < 1.2:
                    continue

                # 評分計算
                bd = calc_total_score(ind)
                if bd.total < MIN_SCORE_TO_TRADE:
                    continue

                # 計算倉位
                usdt = calc_position_size(bd.total)
                if usdt <= 0:
                    continue

                available = self.capital - RESERVE_CAPITAL
                if available < usdt:
                    usdt = available
                if usdt < 20:
                    continue

                self._open(price, usdt, bd.total, ts)

        # 最終平倉（回測結束）
        if self.btc_held > 0:
            final_price = df.iloc[-1]["close"]
            self._close(final_price, "回測結束", int(df.iloc[-1]["timestamp"]))

        return self._calc_stats(df)

    def _calc_stats(self, df: pd.DataFrame) -> dict:
        """計算回測統計數據"""
        final_equity = self._calc_equity(df.iloc[-1]["close"])
        total_return = (final_equity - self.initial_capital) / self.initial_capital

        buy_hold_return = (df.iloc[-1]["close"] - df.iloc[210]["close"]) / df.iloc[210]["close"]

        sell_trades = [t for t in self.trades if t["type"] in ("SELL", "TP3")]
        wins = [t for t in sell_trades if t.get("pnl", 0) > 0]
        win_rate = len(wins) / len(sell_trades) if sell_trades else 0

        total_fee = len([t for t in self.trades if t["type"] == "BUY"]) * 0.001 * \
                    sum(t["usdt"] for t in self.trades if t["type"] == "BUY") / \
                    max(1, len([t for t in self.trades if t["type"] == "BUY"]))

        return {
            "initial_capital":  self.initial_capital,
            "final_equity":     round(final_equity, 2),
            "total_return_pct": round(total_return * 100, 2),
            "buy_hold_pct":     round(buy_hold_return * 100, 2),
            "outperform_pct":   round((total_return - buy_hold_return) * 100, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "win_rate_pct":     round(win_rate * 100, 2),
            "total_trades":     len([t for t in self.trades if t["type"] == "BUY"]),
            "sell_trades":      len(sell_trades),
        }


# ─────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="BTC B策略 V4.2 回測")
    parser.add_argument("--start", default="2025-01-01", help="開始日期 YYYY-MM-DD")
    parser.add_argument("--end",   default=datetime.now().strftime("%Y-%m-%d"),
                        help="結束日期 YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=500.0, help="初始資金 USDT")
    args = parser.parse_args()

    df = fetch_historical_klines(args.start, args.end)
    if df.empty:
        print("無法獲取歷史數據，回測終止")
        return

    bt = Backtester(initial_capital=args.capital)
    stats = bt.run(df)

    print("\n" + "=" * 60)
    print(f"BTC B策略 V4.2 回測結果 ({args.start} ~ {args.end})")
    print("=" * 60)
    print(f"  初始資金：{stats['initial_capital']:.2f} USDT")
    print(f"  最終權益：{stats['final_equity']:.2f} USDT")
    print(f"  策略收益：{stats['total_return_pct']:+.2f}%")
    print(f"  買入持有：{stats['buy_hold_pct']:+.2f}%")
    print(f"  跑贏死拿：{stats['outperform_pct']:+.2f}%")
    print(f"  最大回撤：{stats['max_drawdown_pct']:.2f}%")
    print(f"  勝率：{stats['win_rate_pct']:.1f}%")
    print(f"  交易次數：{stats['total_trades']} 次")
    print("=" * 60)

    # 儲存結果
    os.makedirs("data", exist_ok=True)
    result_file = f"data/backtest_{args.start}_{args.end}.json"
    with open(result_file, "w") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"\n回測結果已儲存至 {result_file}")


if __name__ == "__main__":
    main()
