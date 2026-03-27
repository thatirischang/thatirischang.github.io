# BTC B策略 V4.2 — 機器人

> 六維度機構級順勢交易系統（誠實修正版）

---

## 策略概覽

| 項目 | 數值 |
|------|------|
| 策略類型 | 多維度順勢交易（趨勢跟隨） |
| 執行方式 | 機器人自動執行 |
| 主執行週期 | 1小時K線收盤 |
| 資金規模 | 500 USDT（試水階段） |
| 固定止損 | -3%（回測驗證最優） |
| 月費用 | 0 USDT（全部免費數據） |

### 2025年1月至今回測結果（已驗證 ✅）

| 指標 | 數值 |
|------|------|
| 策略收益 | -4.0% |
| 買入持有 | -26.6% |
| 跑贏死拿 | **+22.6%**（少虧 113 USDT） |
| 最大回撤 | 6.6% |
| 勝率 | 63.2% |
| 交易次數 | 171 次 |

---

## 目錄結構

```
btc-bot/
├── main.py              # 主程式入口
├── backtest.py          # 回測腳本
├── requirements.txt     # 依賴套件
├── .env.example         # 環境變數範本
├── config/
│   └── settings.py      # 所有可調參數
├── core/
│   ├── indicators.py    # 技術指標計算（MACD/RSI/布林帶/EMA）
│   ├── scoring.py       # 六維度評分系統
│   ├── okx_client.py    # OKX API 客戶端
│   ├── position_manager.py  # 倉位管理與風控
│   └── bot_engine.py    # 主執行引擎
├── data/
│   └── position_state.json  # 持倉狀態（自動生成）
└── logs/
    └── btc_bot_b.log    # 執行日誌（自動生成）
```

---

## 快速開始

### 1. 安裝依賴

```bash
cd btc-bot
pip install -r requirements.txt
```

### 2. 設定 API 金鑰

```bash
cp .env.example .env
# 編輯 .env 填入 OKX API 金鑰
```

或直接設定環境變數：

```bash
export OKX_API_KEY=your_api_key
export OKX_SECRET_KEY=your_secret_key
export OKX_PASSPHRASE=your_passphrase
export OKX_SIMULATED=true   # 先用模擬盤測試
```

### 3. 乾跑測試（不下單）

```bash
python3 main.py --dry-run
```

### 4. 每天早上設置手動評分

```bash
python3 main.py --set-scores
```

需要手動查看並輸入：
- 跨市場評分（納指/DXY方向）
- Polymarket 評分
- 恐懼貪婪指數（可選，否則用RSI近似）
- 資金費率（可選，否則自動獲取）

### 5. 查看當前狀態

```bash
python3 main.py --status
```

### 6. 正式啟動

```bash
# 確認模擬盤測試2週無誤後，改為實盤
export OKX_SIMULATED=false
python3 main.py
```

---

## 六維度評分系統

| 維度 | 狀態 | 最高分 | 最低分 |
|------|------|--------|--------|
| 機器學習（近似）🔄 | 多因子線性 | +3 | -2 |
| 訂單流（近似）🔄 | 成交量比率 | +2 | -1 |
| 跨市場（手動）⏳ | 每天手動輸入 | +3 | -3 |
| 鏈上數據（近似）🔄 | 價格偏離EMA200 | +3 | -2 |
| 情緒指標（近似）🔄 | RSI近似 | +3 | -2 |
| Polymarket（手動）⏳ | 每天手動輸入 | +2 | -2 |
| 技術分析（已驗證）✅ | 完整指標 | +3 | -1 |
| **當前總分** | | **+19** | **-13** |

### 倉位對應

| 綜合評分 | 倉位 | 金額 |
|---------|------|------|
| ≥12分 | 40% | 200 USDT |
| 8-11分 | 30% | 150 USDT |
| 5-7分 | 20% | 100 USDT |
| 3-4分 | 10% | 50 USDT |
| <3分 | 0% | 不開倉 |

---

## 風控規則

| 規則 | 數值 |
|------|------|
| 固定止損 | -3%（回測驗證最優） |
| 單筆最大虧損 | 1.5%（7.5 USDT） |
| 單日最大虧損 | 3%（15 USDT） |
| 連續虧損暫停 | 3次後暫停1天 |
| 永久留底 | 150 USDT（鎖死不動） |
| 最大同時持倉 | 350 USDT（70%） |

---

## 回測

```bash
# 回測 2025年1月至今
python3 backtest.py --start 2025-01-01

# 回測 2024全年
python3 backtest.py --start 2024-01-01 --end 2024-12-31

# 回測 2023全年
python3 backtest.py --start 2023-01-01 --end 2023-12-31
```

---

## 實施路線圖

### 第1個月（當前）
- ✅ 技術分析自動執行
- ✅ 止損 -3%（回測驗證）
- ✅ 六維度評分系統
- 🔄 每天手動補充跨市場/Polymarket評分

### 第2個月
- ⏳ Yahoo Finance 跨市場自動接入
- ⏳ OKX 大單真實識別
- ⏳ Polymarket API 自動讀取

### 第3個月
- ⏳ 隨機森林機器學習模型
- ⏳ CryptoQuant 真實鏈上數據
- ⏳ 六維度全自動運行

---

## 免責聲明

本機器人僅供學習研究用途。加密貨幣交易存在高度風險，過去的回測結果不代表未來表現。請在充分理解策略邏輯後，先以模擬盤測試，確認無誤後再以小資金實盤驗證。
