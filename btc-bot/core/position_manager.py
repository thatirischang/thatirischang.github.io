"""
BTC B策略 V4.2 — 倉位管理模組
負責追蹤持倉狀態、止損止盈邏輯、加倉規則
"""

import json
import logging
import os
from dataclasses import dataclass, asdict, field
from typing import Optional
from datetime import datetime

from config.settings import (
    STOP_LOSS_PCT,
    TRAILING_STOP_TRIGGER,
    TRAILING_STOP_BREAKEVEN,
    TRAILING_STOP_LOCK_5,
    TRAILING_STOP_TRAIL,
    TP1_SELL_RATIO, TP2_SELL_RATIO, TP3_SELL_RATIO,
    MAX_POSITION, TOTAL_CAPITAL, RESERVE_CAPITAL,
    MAX_DAILY_LOSS_PCT, MAX_CONSEC_LOSSES,
    MAX_FUNDING_RATE,
)

logger = logging.getLogger("btc_bot")
STATE_FILE = "data/position_state.json"


@dataclass
class Position:
    """單筆持倉記錄"""
    entry_price:   float = 0.0       # 入場價格
    entry_usdt:    float = 0.0       # 入場金額（USDT）
    btc_amount:    float = 0.0       # 持有 BTC 數量
    stop_loss:     float = 0.0       # 當前止損價格
    highest_price: float = 0.0       # 持倉期間最高價
    entry_score:   float = 0.0       # 入場時綜合評分
    entry_time:    str   = ""        # 入場時間（ISO格式）
    algo_order_id: str   = ""        # 止損條件單 ID
    add_count:     int   = 0         # 已加倉次數
    tp1_done:      bool  = False     # 第一檔止盈是否已執行
    tp2_done:      bool  = False     # 第二檔止盈是否已執行
    is_open:       bool  = False     # 是否有持倉


@dataclass
class RiskState:
    """風控狀態記錄"""
    daily_loss_usdt:    float = 0.0   # 今日已虧損 USDT
    daily_loss_date:    str   = ""    # 記錄日期
    consec_losses:      int   = 0     # 連續虧損次數
    pause_until:        str   = ""    # 暫停交易至（ISO格式）
    ml_state_d_count:   int   = 0     # ML 狀態D 連續小時數
    total_trades:       int   = 0     # 總交易次數
    total_pnl_usdt:     float = 0.0   # 累計盈虧 USDT


class PositionManager:
    """
    管理 BTC B策略的倉位狀態與風控邏輯。
    狀態持久化到 JSON 檔案，重啟後可恢復。
    """

    def __init__(self):
        self.position = Position()
        self.risk     = RiskState()
        self._load_state()

    # ─────────────────────────────────────────
    # 狀態持久化
    # ─────────────────────────────────────────
    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                self.position = Position(**state.get("position", {}))
                self.risk     = RiskState(**state.get("risk", {}))
                logger.info("已載入持倉狀態")
            except Exception as e:
                logger.warning(f"載入狀態失敗，使用初始狀態: {e}")

    def _save_state(self):
        os.makedirs("data", exist_ok=True)
        state = {
            "position": asdict(self.position),
            "risk":     asdict(self.risk),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    # ─────────────────────────────────────────
    # 開倉
    # ─────────────────────────────────────────
    def open_position(self, entry_price: float, usdt_amount: float,
                      score: float, algo_order_id: str = "") -> bool:
        """
        記錄開倉資訊，計算初始止損價格。
        回傳 True 表示成功記錄。
        """
        if self.position.is_open:
            logger.warning("已有持倉，不可重複開倉")
            return False

        btc_amount = usdt_amount / entry_price
        stop_loss  = entry_price * (1 - STOP_LOSS_PCT)

        self.position = Position(
            entry_price   = entry_price,
            entry_usdt    = usdt_amount,
            btc_amount    = btc_amount,
            stop_loss     = stop_loss,
            highest_price = entry_price,
            entry_score   = score,
            entry_time    = datetime.now().isoformat(),
            algo_order_id = algo_order_id,
            is_open       = True,
        )
        self._save_state()
        logger.info(
            f"開倉記錄 | 入場價={entry_price:.2f} | "
            f"金額={usdt_amount:.2f} USDT | BTC={btc_amount:.8f} | "
            f"止損={stop_loss:.2f} | 評分={score:.1f}"
        )
        return True

    # ─────────────────────────────────────────
    # 平倉
    # ─────────────────────────────────────────
    def close_position(self, exit_price: float, reason: str = ""):
        """
        記錄平倉，更新風控狀態。
        """
        if not self.position.is_open:
            return

        pnl = (exit_price - self.position.entry_price) / self.position.entry_price
        pnl_usdt = self.position.entry_usdt * pnl

        logger.info(
            f"平倉 | 出場價={exit_price:.2f} | "
            f"PnL={pnl*100:.2f}% ({pnl_usdt:+.2f} USDT) | 原因={reason}"
        )

        # 更新風控
        self.risk.total_trades += 1
        self.risk.total_pnl_usdt += pnl_usdt

        today = datetime.now().strftime("%Y-%m-%d")
        if self.risk.daily_loss_date != today:
            self.risk.daily_loss_usdt = 0.0
            self.risk.daily_loss_date = today

        if pnl_usdt < 0:
            self.risk.daily_loss_usdt += abs(pnl_usdt)
            self.risk.consec_losses   += 1
        else:
            self.risk.consec_losses = 0

        # 重置持倉
        self.position = Position()
        self._save_state()

    # ─────────────────────────────────────────
    # 加倉
    # ─────────────────────────────────────────
    def add_position(self, current_price: float, add_usdt: float,
                     algo_order_id: str = "") -> bool:
        """
        順勢加倉邏輯。
        條件：盈利≥5%、加倉次數<2、總倉位不超過350 USDT
        """
        if not self.position.is_open:
            return False
        if self.position.add_count >= 2:
            logger.info("已達最大加倉次數（2次）")
            return False

        current_pnl = (current_price - self.position.entry_price) / self.position.entry_price
        if current_pnl < 0.05:
            logger.info(f"盈利不足5%（當前{current_pnl*100:.1f}%），不加倉")
            return False

        total_after = self.position.entry_usdt + add_usdt
        if total_after > MAX_POSITION:
            logger.info(f"加倉後超過最大倉位限制（{MAX_POSITION} USDT）")
            return False

        add_btc = add_usdt / current_price
        # 計算加權均價
        total_btc  = self.position.btc_amount + add_btc
        total_cost = self.position.entry_usdt + add_usdt
        new_avg    = total_cost / total_btc

        self.position.btc_amount    = total_btc
        self.position.entry_usdt    = total_cost
        self.position.entry_price   = new_avg
        self.position.stop_loss     = new_avg * (1 - STOP_LOSS_PCT)
        self.position.algo_order_id = algo_order_id
        self.position.add_count    += 1

        self._save_state()
        logger.info(
            f"加倉 #{self.position.add_count} | "
            f"加倉金額={add_usdt:.2f} USDT | 新均價={new_avg:.2f} | "
            f"新止損={self.position.stop_loss:.2f}"
        )
        return True

    # ─────────────────────────────────────────
    # 移動止損更新
    # ─────────────────────────────────────────
    def update_trailing_stop(self, current_price: float) -> Optional[float]:
        """
        根據當前價格更新移動止損。
        回傳新的止損價格（若有更新），否則回傳 None。
        """
        if not self.position.is_open:
            return None

        # 更新最高價
        if current_price > self.position.highest_price:
            self.position.highest_price = current_price

        entry  = self.position.entry_price
        high   = self.position.highest_price
        pnl    = (current_price - entry) / entry
        new_sl = None

        if pnl >= 0.15:
            # 盈利+15% → 止損移至最高價×0.92
            candidate = high * TRAILING_STOP_TRAIL
            if candidate > self.position.stop_loss:
                new_sl = candidate
                logger.info(f"移動止損更新（+15%）→ {new_sl:.2f}")

        elif pnl >= 0.10:
            # 盈利+10% → 止損移至入場價+5%
            candidate = entry * (1 + TRAILING_STOP_LOCK_5)
            if candidate > self.position.stop_loss:
                new_sl = candidate
                logger.info(f"移動止損更新（+10%）→ {new_sl:.2f}")

        elif pnl >= 0.05:
            # 盈利+5% → 止損移至入場價（保本）
            candidate = entry
            if candidate > self.position.stop_loss:
                new_sl = candidate
                logger.info(f"移動止損更新（+5% 保本）→ {new_sl:.2f}")

        if new_sl is not None:
            self.position.stop_loss = new_sl
            self._save_state()

        return new_sl

    # ─────────────────────────────────────────
    # 止盈判斷
    # ─────────────────────────────────────────
    def check_take_profit(self, ind: dict, score: float,
                          funding_rate: Optional[float] = None) -> Optional[str]:
        """
        檢查三檔止盈條件。
        回傳 "TP1" / "TP2" / "TP3" 或 None。
        """
        if not self.position.is_open:
            return None

        # 第一檔（賣出30%）
        if not self.position.tp1_done:
            tp1_rsi   = ind["rsi"] > 75 and ind["boll_pos"] > 0.95
            tp1_score = score < 4
            if tp1_rsi or tp1_score:
                return "TP1"

        # 第二檔（賣出50%）
        if not self.position.tp2_done:
            tp2_macd = ind["macd_cross_down"]
            tp2_fund = funding_rate is not None and funding_rate > 0.001
            if tp2_macd or tp2_fund:
                return "TP2"

        # 第三檔（全部賣出）
        tp3_daily_macd = ind.get("daily_macd_cross_down", False)
        tp3_ml_d       = ind.get("ml_state_d", False)
        if tp3_daily_macd or tp3_ml_d:
            return "TP3"

        return None

    # ─────────────────────────────────────────
    # 止損判斷
    # ─────────────────────────────────────────
    def check_stop_loss(self, current_price: float, ind: dict) -> Optional[str]:
        """
        檢查止損條件（固定止損 + 結構止損）。
        回傳觸發原因字串，或 None。
        """
        if not self.position.is_open:
            return None

        # 固定止損 -3%
        if current_price <= self.position.stop_loss:
            return f"固定止損觸發 ({current_price:.2f} <= {self.position.stop_loss:.2f})"

        # 結構止損：日線跌破 EMA200
        if not ind.get("above_ema200", True):
            return "結構止損：日線跌破EMA200"

        # 結構止損：ML 狀態D
        if ind.get("ml_state_d", False):
            return "結構止損：ML切換到狀態D"

        return None

    # ─────────────────────────────────────────
    # 風控檢查
    # ─────────────────────────────────────────
    def can_trade(self, ml_state: str = "C",
                  funding_rate: Optional[float] = None) -> tuple[bool, str]:
        """
        檢查是否可以開新倉。
        回傳 (True/False, 原因說明)。
        """
        # 暫停期間
        if self.risk.pause_until:
            pause_dt = datetime.fromisoformat(self.risk.pause_until)
            if datetime.now() < pause_dt:
                return False, f"暫停交易中（至 {self.risk.pause_until}）"
            else:
                self.risk.pause_until = ""
                self._save_state()

        # 單日最大虧損
        today = datetime.now().strftime("%Y-%m-%d")
        if self.risk.daily_loss_date == today:
            max_daily = TOTAL_CAPITAL * MAX_DAILY_LOSS_PCT
            if self.risk.daily_loss_usdt >= max_daily:
                return False, f"今日虧損已達上限 ({self.risk.daily_loss_usdt:.2f} USDT)"

        # 連續虧損
        if self.risk.consec_losses >= MAX_CONSEC_LOSSES:
            from datetime import timedelta
            pause_until = (datetime.now() + timedelta(days=1)).isoformat()
            self.risk.pause_until = pause_until
            self.risk.consec_losses = 0
            self._save_state()
            return False, f"連續虧損{MAX_CONSEC_LOSSES}次，暫停1天"

        # ML 狀態D 持續
        if ml_state == "D":
            self.risk.ml_state_d_count += 1
        else:
            self.risk.ml_state_d_count = 0

        if self.risk.ml_state_d_count >= 3:
            return False, "ML狀態D持續3小時以上，暫停交易"

        # 資金費率過高
        if funding_rate is not None and funding_rate > MAX_FUNDING_RATE:
            return False, f"資金費率過高 ({funding_rate*100:.4f}%)，不開新倉"

        return True, "OK"

    # ─────────────────────────────────────────
    # 狀態摘要
    # ─────────────────────────────────────────
    def get_status_summary(self, current_price: float = 0.0) -> dict:
        """回傳當前狀態摘要（用於日誌或監控）"""
        pos = self.position
        summary = {
            "has_position":    pos.is_open,
            "entry_price":     pos.entry_price,
            "entry_usdt":      pos.entry_usdt,
            "btc_amount":      pos.btc_amount,
            "stop_loss":       pos.stop_loss,
            "highest_price":   pos.highest_price,
            "entry_score":     pos.entry_score,
            "entry_time":      pos.entry_time,
            "add_count":       pos.add_count,
            "total_trades":    self.risk.total_trades,
            "total_pnl_usdt":  self.risk.total_pnl_usdt,
            "consec_losses":   self.risk.consec_losses,
            "daily_loss_usdt": self.risk.daily_loss_usdt,
        }
        if pos.is_open and current_price > 0:
            pnl_pct = (current_price - pos.entry_price) / pos.entry_price * 100
            summary["current_pnl_pct"] = pnl_pct
            summary["current_pnl_usdt"] = pos.entry_usdt * pnl_pct / 100
        return summary
