"""
BTC B策略 V4.2 — 主機器人執行引擎
每根 1 小時 K 線收盤後執行完整的六維度評分與交易決策
"""

import logging
import time
from datetime import datetime
from typing import Optional

from config.settings import (
    SYMBOL, MIN_SCORE_TO_TRADE, MAX_POSITION,
    STOP_LOSS_PCT, TP1_SELL_RATIO, TP2_SELL_RATIO,
    MAIN_LOOP_INTERVAL_SEC, ORDERFLOW_INTERVAL_SEC,
    SENTIMENT_INTERVAL_SEC, ONCHAIN_INTERVAL_SEC,
)
from core.indicators import add_all_indicators, get_latest_indicators
from core.scoring import (
    calc_total_score, calc_position_size,
    get_ml_state, score_cross_market, score_polymarket,
)
from core.okx_client import (
    get_klines, get_funding_rate, get_current_price,
    get_usdt_balance, get_btc_balance,
    place_market_buy, place_market_sell,
    place_stop_loss_order, cancel_algo_order,
)
from core.position_manager import PositionManager

logger = logging.getLogger("btc_bot")


class BotEngine:
    """
    B策略 V4.2 機器人執行引擎。

    執行流程（每小時 K 線收盤）：
      Step1  機器學習評分（自動近似）
      Step2  訂單流評分（自動近似）
      Step3  跨市場評分（手動/待接入）
      Step4  鏈上數據評分（自動近似）
      Step5  情緒評分（自動近似/手動真實）
      Step6  Polymarket評分（手動/待接入）
      Step7  技術信號（自動已驗證）
      Step8  計算綜合評分
      Step9  評分 < 2 → 不操作
      Step10 評分 ≥ 2 → 按評分確定倉位開倉
      Step11 立即設置止損單
    """

    def __init__(self):
        self.pm = PositionManager()

        # 手動輸入快取（每天更新一次）
        self._cross_market_score: float = 0.0
        self._polymarket_score:   float = 0.0
        self._fear_greed:         Optional[int] = None
        self._funding_rate:       Optional[float] = None

        # 計時器
        self._last_orderflow_update  = 0.0
        self._last_sentiment_update  = 0.0
        self._last_onchain_update    = 0.0
        self._last_hourly_candle_ts  = 0

    # ─────────────────────────────────────────
    # 手動輸入介面（每天早上更新）
    # ─────────────────────────────────────────
    def set_manual_scores(self,
                          cross_market: float = 0.0,
                          polymarket: float = 0.0,
                          fear_greed: Optional[int] = None,
                          funding_rate: Optional[float] = None):
        """
        設置手動輸入的評分（每天早上查看後更新）。

        cross_market：跨市場評分（-3 ~ +3）
          - 納指日漲>0.5% → +2，日跌>0.5% → -2
          - DXY下跌 → +1，DXY單日漲>1% → -2
          - 連續3天下跌 → -3（禁止做多）

        polymarket：Polymarket評分（-2 ~ +2）
          - BTC高於預期概率上升 → +1
          - 降息概率>60% → +2

        fear_greed：恐懼貪婪指數（0-100），None = 用RSI近似
        funding_rate：資金費率（如 0.0001 = 0.01%），None = 用4H漲跌幅近似
        """
        self._cross_market_score = float(cross_market)
        self._polymarket_score   = float(polymarket)
        self._fear_greed         = fear_greed
        self._funding_rate       = funding_rate
        logger.info(
            f"手動評分更新 | 跨市場={cross_market:+.1f} | "
            f"Polymarket={polymarket:+.1f} | "
            f"恐懼貪婪={fear_greed} | 資金費率={funding_rate}"
        )

    # ─────────────────────────────────────────
    # 自動獲取資金費率
    # ─────────────────────────────────────────
    def _refresh_funding_rate(self):
        """每8小時自動更新資金費率"""
        now = time.time()
        if now - self._last_sentiment_update >= SENTIMENT_INTERVAL_SEC:
            fr = get_funding_rate()
            if fr is not None:
                self._funding_rate = fr
                logger.info(f"資金費率更新: {fr*100:.4f}%")
            self._last_sentiment_update = now

    # ─────────────────────────────────────────
    # 核心：每小時執行一次的決策循環
    # ─────────────────────────────────────────
    def run_hourly(self):
        """
        每根 1H K 線收盤後執行完整的六維度評分與交易決策。
        """
        logger.info("=" * 60)
        logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 開始執行小時決策")

        # ── 獲取 K 線數據 ──
        df_1h = get_klines(SYMBOL, bar="1H", limit=300)
        df_4h = get_klines(SYMBOL, bar="4H", limit=100)

        if df_1h.empty:
            logger.error("無法獲取1H K線，跳過本次執行")
            return

        df_1h = add_all_indicators(df_1h)
        ind_1h = get_latest_indicators(df_1h)

        ind_4h = None
        if not df_4h.empty:
            df_4h = add_all_indicators(df_4h)
            ind_4h = get_latest_indicators(df_4h)

        current_price = ind_1h["close"]
        ml_state = get_ml_state(ind_1h)

        # 將 ML 狀態D 注入 ind_1h
        ind_1h["ml_state_d"] = (ml_state == "D")

        # ── 自動更新資金費率 ──
        self._refresh_funding_rate()

        # ── 風控檢查 ──
        can_trade, reason = self.pm.can_trade(ml_state, self._funding_rate)

        # ── 持倉管理（優先於開倉邏輯）──
        if self.pm.position.is_open:
            self._manage_open_position(current_price, ind_1h, ind_4h)

        # ── 計算綜合評分 ──
        bd = calc_total_score(
            ind        = ind_1h,
            ind_4h     = ind_4h,
            fear_greed = self._fear_greed,
            funding_rate = self._funding_rate,
            cross_market_manual = self._cross_market_score,
            polymarket_manual   = self._polymarket_score,
        )

        # ── 開倉決策 ──
        if not self.pm.position.is_open:
            if not can_trade:
                logger.info(f"風控暫停開倉: {reason}")
            elif bd.total < MIN_SCORE_TO_TRADE:
                logger.info(f"評分不足（{bd.total:.1f} < {MIN_SCORE_TO_TRADE}），不開倉")
            else:
                self._execute_entry(current_price, bd.total, ind_1h, ind_4h)

        # ── 加倉決策 ──
        elif self.pm.position.is_open and can_trade:
            self._check_add_position(current_price, bd.total, ind_1h, ind_4h)

        # ── 輸出狀態摘要 ──
        status = self.pm.get_status_summary(current_price)
        logger.info(
            f"狀態摘要 | 持倉={status['has_position']} | "
            f"評分={bd.total:.1f} | 價格={current_price:.2f} | "
            f"累計PnL={status['total_pnl_usdt']:+.2f} USDT"
        )

    # ─────────────────────────────────────────
    # 開倉執行
    # ─────────────────────────────────────────
    def _execute_entry(self, price: float, score: float,
                       ind_1h: dict, ind_4h: Optional[dict]):
        """執行開倉：下市價買單 + 設置止損單"""

        # 日線過濾（至少滿足2項）
        daily_conditions = [
            ind_1h["above_ema200"],
            ind_1h["macd_bullish"],
            ind_1h["rsi"] > 45,
            ind_1h["above_boll_mid"],
        ]
        if sum(daily_conditions) < 2:
            logger.info(f"日線過濾未通過（{sum(daily_conditions)}/4），不開倉")
            return

        # 成交量確認
        if ind_1h["vol_ratio"] < 1.2:
            logger.info(f"成交量不足（vol_ratio={ind_1h['vol_ratio']:.2f}），不開倉")
            return

        # 計算倉位
        usdt_amount = calc_position_size(score)
        if usdt_amount <= 0:
            return

        # 檢查可用餘額
        available = get_usdt_balance()
        if available < usdt_amount + 150:  # 保留150 USDT留底
            logger.warning(f"USDT餘額不足（可用={available:.2f}，需要={usdt_amount+150:.2f}）")
            usdt_amount = max(0, available - 150)
            if usdt_amount < 50:
                logger.warning("可用資金不足50 USDT，不開倉")
                return

        # 下市價買單
        result = place_market_buy(usdt_amount)
        if not result or result.get("code") != "0":
            logger.error(f"開倉下單失敗: {result}")
            return

        # 設置止損單
        stop_price = price * (1 - STOP_LOSS_PCT)
        btc_amount = usdt_amount / price
        sl_result = place_stop_loss_order(btc_amount, stop_price)
        algo_id = ""
        if sl_result and sl_result.get("code") == "0":
            try:
                algo_id = sl_result["data"][0]["algoId"]
            except Exception:
                pass

        # 記錄持倉
        self.pm.open_position(price, usdt_amount, score, algo_id)
        logger.info(
            f"✅ 開倉成功 | 評分={score:.1f} | 金額={usdt_amount:.2f} USDT | "
            f"止損={stop_price:.2f}"
        )

    # ─────────────────────────────────────────
    # 持倉管理（止損/止盈/移動止損）
    # ─────────────────────────────────────────
    def _manage_open_position(self, price: float, ind_1h: dict,
                               ind_4h: Optional[dict]):
        """管理已開倉位：檢查止損、止盈、更新移動止損"""

        # 更新移動止損
        new_sl = self.pm.update_trailing_stop(price)
        if new_sl is not None:
            # 取消舊止損單，設置新止損單
            if self.pm.position.algo_order_id:
                cancel_algo_order(self.pm.position.algo_order_id)
            btc = self.pm.position.btc_amount
            sl_result = place_stop_loss_order(btc, new_sl)
            if sl_result and sl_result.get("code") == "0":
                try:
                    self.pm.position.algo_order_id = sl_result["data"][0]["algoId"]
                    self.pm._save_state()
                except Exception:
                    pass

        # 計算當前評分（用於止盈判斷）
        bd = calc_total_score(
            ind=ind_1h, ind_4h=ind_4h,
            fear_greed=self._fear_greed,
            funding_rate=self._funding_rate,
            cross_market_manual=self._cross_market_score,
            polymarket_manual=self._polymarket_score,
        )

        # 止損檢查
        sl_reason = self.pm.check_stop_loss(price, ind_1h)
        if sl_reason:
            btc = self.pm.position.btc_amount
            result = place_market_sell(btc)
            if result and result.get("code") == "0":
                logger.info(f"🔴 止損出場 | {sl_reason}")
                self.pm.close_position(price, reason=sl_reason)
            return

        # 止盈檢查
        tp = self.pm.check_take_profit(ind_1h, bd.total, self._funding_rate)
        if tp:
            self._execute_take_profit(tp, price, bd.total)

    # ─────────────────────────────────────────
    # 止盈執行
    # ─────────────────────────────────────────
    def _execute_take_profit(self, tp_level: str, price: float, score: float):
        """執行分批止盈"""
        pos = self.pm.position

        if tp_level == "TP1" and not pos.tp1_done:
            sell_btc = pos.btc_amount * TP1_SELL_RATIO
            result = place_market_sell(sell_btc)
            if result and result.get("code") == "0":
                pos.tp1_done = True
                pos.btc_amount -= sell_btc
                pos.entry_usdt *= (1 - TP1_SELL_RATIO)
                self.pm._save_state()
                logger.info(f"🟡 第一檔止盈（賣出30%）| 價格={price:.2f}")

        elif tp_level == "TP2" and not pos.tp2_done:
            sell_btc = pos.btc_amount * TP2_SELL_RATIO
            result = place_market_sell(sell_btc)
            if result and result.get("code") == "0":
                pos.tp2_done = True
                pos.btc_amount -= sell_btc
                pos.entry_usdt *= (1 - TP2_SELL_RATIO)
                self.pm._save_state()
                logger.info(f"🟡 第二檔止盈（賣出50%）| 價格={price:.2f}")

        elif tp_level == "TP3":
            sell_btc = pos.btc_amount
            result = place_market_sell(sell_btc)
            if result and result.get("code") == "0":
                logger.info(f"🟢 第三檔止盈（全部賣出）| 價格={price:.2f}")
                self.pm.close_position(price, reason="TP3全部止盈")

    # ─────────────────────────────────────────
    # 加倉決策
    # ─────────────────────────────────────────
    def _check_add_position(self, price: float, score: float,
                             ind_1h: dict, ind_4h: Optional[dict]):
        """
        順勢加倉條件：
          ✅ 當前倉位盈利 ≥ 5%
          ✅ 出現新的1H MACD金叉
          ✅ 4H趨勢未改變
          ✅ 綜合評分仍 ≥ 6分
          ✅ 成交量比率 > 1.2
          ✅ 總倉位不超過350 USDT
        """
        pos = self.pm.position
        if not pos.is_open or pos.add_count >= 2:
            return

        pnl = (price - pos.entry_price) / pos.entry_price
        if pnl < 0.05:
            return
        if not ind_1h["macd_cross_up"]:
            return
        if ind_4h and not ind_4h["macd_bullish"]:
            return
        if score < 6:
            return
        if ind_1h["vol_ratio"] < 1.2:
            return

        # 加倉量：第一次=初始倉位×50%，第二次=初始倉位×30%
        ratios = [0.5, 0.3]
        add_ratio = ratios[pos.add_count]
        add_usdt = pos.entry_usdt * add_ratio

        if pos.entry_usdt + add_usdt > MAX_POSITION:
            add_usdt = MAX_POSITION - pos.entry_usdt
            if add_usdt < 20:
                return

        result = place_market_buy(add_usdt)
        if result and result.get("code") == "0":
            # 取消舊止損，設置新止損
            if pos.algo_order_id:
                cancel_algo_order(pos.algo_order_id)
            new_avg_stop = (pos.entry_price * pos.btc_amount + price * (add_usdt / price)) / \
                           (pos.btc_amount + add_usdt / price) * (1 - 0.03)
            sl_result = place_stop_loss_order(
                pos.btc_amount + add_usdt / price, new_avg_stop
            )
            algo_id = ""
            if sl_result and sl_result.get("code") == "0":
                try:
                    algo_id = sl_result["data"][0]["algoId"]
                except Exception:
                    pass
            self.pm.add_position(price, add_usdt, algo_id)
            logger.info(f"✅ 加倉成功 | 加倉金額={add_usdt:.2f} USDT | 評分={score:.1f}")
