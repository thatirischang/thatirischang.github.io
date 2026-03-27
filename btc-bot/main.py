#!/usr/bin/env python3
"""
BTC B策略 V4.2 — 主程式入口
六維度機構級順勢交易系統

執行方式：
  python3 main.py                    # 正常啟動
  python3 main.py --dry-run          # 乾跑模式（不下單）
  python3 main.py --set-scores       # 互動式設置手動評分
  python3 main.py --status           # 查看當前持倉狀態

環境變數設定（建議使用 .env 檔案）：
  OKX_API_KEY=your_api_key
  OKX_SECRET_KEY=your_secret_key
  OKX_PASSPHRASE=your_passphrase
  OKX_SIMULATED=true   # true=模擬盤, false=實盤
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

# 確保 btc-bot 目錄在 Python 路徑中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import (
    LOG_DIR, LOG_FILE, MAIN_LOOP_INTERVAL_SEC, OKX_SIMULATED
)
from core.bot_engine import BotEngine
from core.okx_client import get_current_price, get_usdt_balance, get_btc_balance
from core.position_manager import PositionManager


# ─────────────────────────────────────────
# 日誌設定
# ─────────────────────────────────────────
def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, LOG_FILE)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger = logging.getLogger("btc_bot")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


# ─────────────────────────────────────────
# 互動式手動評分設置
# ─────────────────────────────────────────
def interactive_set_scores(engine: BotEngine):
    """
    互動式設置每日手動評分。
    每天早上執行一次，輸入跨市場和 Polymarket 評分。
    """
    print("\n" + "=" * 60)
    print("BTC B策略 V4.2 — 每日手動評分設置")
    print("=" * 60)

    print("\n【跨市場評分】（-3 ~ +3）")
    print("  納指日漲>0.5% → +2 | 日跌>0.5% → -2 | 連跌3天 → -3")
    print("  DXY下跌 → +1 | DXY日漲>1% → -2")
    print("  黃金漲>2% → +1 | 10年美債>5% → -2")
    cross = float(input("  輸入跨市場評分（預設0）: ").strip() or "0")

    print("\n【Polymarket評分】（-2 ~ +2）")
    print("  BTC高於預期概率上升 → +1 | 降息概率>60% → +2")
    print("  BTC低於預期概率上升 → -1 | 加息概率>30% → -2")
    poly = float(input("  輸入Polymarket評分（預設0）: ").strip() or "0")

    print("\n【恐懼貪婪指數】（0-100，Enter跳過使用RSI近似）")
    print("  查看：https://alternative.me/crypto/fear-and-greed-index/")
    fg_str = input("  輸入恐懼貪婪指數（Enter跳過）: ").strip()
    fear_greed = int(fg_str) if fg_str else None

    print("\n【資金費率】（如 0.0001 = 0.01%，Enter跳過自動獲取）")
    print("  查看：OKX合約界面 → BTC永續合約 → 資金費率")
    fr_str = input("  輸入資金費率（Enter跳過）: ").strip()
    funding_rate = float(fr_str) if fr_str else None

    engine.set_manual_scores(
        cross_market=cross,
        polymarket=poly,
        fear_greed=fear_greed,
        funding_rate=funding_rate,
    )
    print("\n✅ 手動評分已更新！")


# ─────────────────────────────────────────
# 狀態查詢
# ─────────────────────────────────────────
def show_status():
    """顯示當前持倉狀態和帳戶餘額"""
    pm = PositionManager()
    price = get_current_price()
    usdt  = get_usdt_balance()
    btc   = get_btc_balance()
    status = pm.get_status_summary(price)

    print("\n" + "=" * 60)
    print("BTC B策略 V4.2 — 當前狀態")
    print("=" * 60)
    print(f"  模式：{'模擬盤' if OKX_SIMULATED else '🔴 實盤'}")
    print(f"  BTC 現價：{price:.2f} USDT")
    print(f"  USDT 餘額：{usdt:.2f}")
    print(f"  BTC 餘額：{btc:.8f}")
    print()

    if status["has_position"]:
        pnl_pct  = status.get("current_pnl_pct", 0)
        pnl_usdt = status.get("current_pnl_usdt", 0)
        print(f"  ✅ 持倉中")
        print(f"  入場價：{status['entry_price']:.2f}")
        print(f"  入場金額：{status['entry_usdt']:.2f} USDT")
        print(f"  BTC數量：{status['btc_amount']:.8f}")
        print(f"  止損價：{status['stop_loss']:.2f}")
        print(f"  最高價：{status['highest_price']:.2f}")
        print(f"  當前盈虧：{pnl_pct:+.2f}% ({pnl_usdt:+.2f} USDT)")
        print(f"  入場評分：{status['entry_score']:.1f}")
        print(f"  加倉次數：{status['add_count']}")
        print(f"  入場時間：{status['entry_time']}")
    else:
        print("  ⬜ 無持倉")

    print()
    print(f"  累計交易次數：{status['total_trades']}")
    print(f"  累計盈虧：{status['total_pnl_usdt']:+.2f} USDT")
    print(f"  連續虧損次數：{status['consec_losses']}")
    print(f"  今日虧損：{status['daily_loss_usdt']:.2f} USDT")
    print("=" * 60)


# ─────────────────────────────────────────
# 主循環
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="BTC B策略 V4.2 機器人")
    parser.add_argument("--dry-run",    action="store_true", help="乾跑模式（不下單）")
    parser.add_argument("--set-scores", action="store_true", help="互動式設置手動評分")
    parser.add_argument("--status",     action="store_true", help="查看當前持倉狀態")
    args = parser.parse_args()

    logger = setup_logging()

    if args.status:
        show_status()
        return

    engine = BotEngine()

    if args.set_scores:
        interactive_set_scores(engine)

    mode = "模擬盤" if OKX_SIMULATED else "🔴 實盤"
    logger.info(f"BTC B策略 V4.2 啟動 | 模式={mode} | 乾跑={args.dry_run}")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("⚠️  乾跑模式：所有下單指令將被跳過")
        # 乾跑模式：monkey-patch 下單函數
        import core.okx_client as okx
        okx.place_market_buy   = lambda *a, **kw: {"code": "0", "data": [{"ordId": "DRY"}]}
        okx.place_market_sell  = lambda *a, **kw: {"code": "0", "data": [{"ordId": "DRY"}]}
        okx.place_stop_loss_order = lambda *a, **kw: {"code": "0", "data": [{"algoId": "DRY"}]}
        okx.cancel_algo_order  = lambda *a, **kw: {"code": "0"}

    # ── 主循環 ──
    last_hourly_run = 0

    while True:
        try:
            now = time.time()

            # 每小時執行一次（等待整點後60秒執行，確保K線已收盤）
            current_minute = datetime.now().minute
            current_second = datetime.now().second

            # 在每小時的第1分鐘執行（K線收盤後約60秒）
            if current_minute == 1 and (now - last_hourly_run) > 3000:
                engine.run_hourly()
                last_hourly_run = now

            time.sleep(MAIN_LOOP_INTERVAL_SEC)

        except KeyboardInterrupt:
            logger.info("收到中斷信號，機器人停止運行")
            break
        except Exception as e:
            logger.error(f"主循環發生錯誤: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
