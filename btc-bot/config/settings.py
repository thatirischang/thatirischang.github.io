"""
BTC B策略 V4.2 — 設定檔
六維度機構級順勢交易系統

使用前請將 OKX API 金鑰填入此檔案，
或設定對應的環境變數。
"""

import os

# ─────────────────────────────────────────
# OKX API 設定（請填入真實金鑰或設定環境變數）
# ─────────────────────────────────────────
OKX_API_KEY    = os.getenv("OKX_API_KEY",    "YOUR_API_KEY")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY", "YOUR_SECRET_KEY")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE", "YOUR_PASSPHRASE")

# 是否為模擬盤（True = 模擬盤，False = 實盤）
OKX_SIMULATED  = os.getenv("OKX_SIMULATED", "true").lower() == "true"

# ─────────────────────────────────────────
# 交易對設定
# ─────────────────────────────────────────
SYMBOL          = "BTC-USDT"          # 現貨交易對
INST_TYPE       = "SPOT"              # 交易類型

# ─────────────────────────────────────────
# 資金管理（V4.2 回測驗證）
# ─────────────────────────────────────────
TOTAL_CAPITAL   = 500.0               # 總資金 USDT
RESERVE_CAPITAL = 150.0               # 永久留底，鎖死不動
MAX_POSITION    = 350.0               # 最大同時持倉 USDT（70%）

# 單次入場仓位（按綜合評分）
POSITION_MAP = {
    12: 200.0,   # ≥12分 → 200 USDT（40%）最強信號
     8: 150.0,   #  8-11分 → 150 USDT（30%）標準信號
     5: 100.0,   #  5-7分 → 100 USDT（20%）一般信號
     3:  50.0,   #  3-4分 →  50 USDT（10%）弱信號
     0:   0.0,   #  <3分 → 不開倉
}

# ─────────────────────────────────────────
# 止損 / 止盈參數（V4.2 回測驗證最優）
# ─────────────────────────────────────────
STOP_LOSS_PCT          = 0.03    # 固定止損 -3%（回測驗證最優）
TRAILING_STOP_TRIGGER  = 0.05    # 盈利 +5% 啟動移動止損
TRAILING_STOP_BREAKEVEN= 0.05    # 盈利 +5% → 止損移至入場價
TRAILING_STOP_LOCK_5   = 0.05    # 盈利 +10% → 止損移至入場價+5%
TRAILING_STOP_TRAIL    = 0.92    # 盈利 +15% → 止損移至最高價×0.92

# 三檔止盈比例
TP1_SELL_RATIO  = 0.30   # 第一檔：賣出持倉 30%
TP2_SELL_RATIO  = 0.50   # 第二檔：賣出持倉 50%
TP3_SELL_RATIO  = 1.00   # 第三檔：賣出剩餘全部

# ─────────────────────────────────────────
# 技術指標參數（V4.2 已驗證）
# ─────────────────────────────────────────
MACD_FAST       = 12
MACD_SLOW       = 26
MACD_SIGNAL     = 9
RSI_PERIOD      = 14
BOLL_PERIOD     = 20
BOLL_STD        = 2.0
EMA_SHORT       = 20
EMA_MID         = 50
EMA_LONG        = 200
VOL_MA_PERIOD   = 20
VOL_CONFIRM_RATIO = 1.2   # 成交量確認倍數

# ─────────────────────────────────────────
# 評分門檻
# ─────────────────────────────────────────
MIN_SCORE_TO_TRADE  = 2    # 低於此分不開倉
SCORE_PAUSE_ML_D    = 3    # ML 狀態D 持續幾小時暫停交易

# ─────────────────────────────────────────
# 風險管理
# ─────────────────────────────────────────
MAX_DAILY_LOSS_PCT  = 0.03   # 單日最大虧損 3%（15 USDT）
MAX_CONSEC_LOSSES   = 3      # 連續虧損次數上限，觸發後暫停1天
MAX_FUNDING_RATE    = 0.001  # 資金費率 > 0.1% 不開新倉

# ─────────────────────────────────────────
# 執行頻率設定
# ─────────────────────────────────────────
MAIN_LOOP_INTERVAL_SEC  = 60     # 主循環間隔（秒）
ORDERFLOW_INTERVAL_SEC  = 300    # 訂單流更新間隔（5分鐘）
SENTIMENT_INTERVAL_SEC  = 28800  # 情緒指標更新間隔（8小時）
ONCHAIN_INTERVAL_SEC    = 14400  # 鏈上數據更新間隔（4小時）

# ─────────────────────────────────────────
# 日誌設定
# ─────────────────────────────────────────
LOG_DIR  = "logs"
LOG_FILE = "btc_bot_b.log"
