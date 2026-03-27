"""
BTC B策略 V4.2 — OKX API 客戶端
負責從 OKX 獲取 K 線、資金費率、帳戶資訊等數據
"""

import time
import hmac
import hashlib
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
import pandas as pd

from config.settings import (
    OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE,
    OKX_SIMULATED, SYMBOL,
)

logger = logging.getLogger("btc_bot")

BASE_URL = "https://www.okx.com"


def _sign(timestamp: str, method: str, path: str, body: str = "") -> str:
    """生成 OKX API 簽名"""
    msg = f"{timestamp}{method}{path}{body}"
    mac = hmac.new(OKX_SECRET_KEY.encode(), msg.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def _headers(method: str, path: str, body: str = "") -> dict:
    """生成帶簽名的請求標頭"""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    sig = _sign(ts, method, path, body)
    headers = {
        "OK-ACCESS-KEY":        OKX_API_KEY,
        "OK-ACCESS-SIGN":       sig,
        "OK-ACCESS-TIMESTAMP":  ts,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type":         "application/json",
    }
    if OKX_SIMULATED:
        headers["x-simulated-trading"] = "1"
    return headers


def _get(path: str, params: dict = None) -> dict:
    """發送 GET 請求"""
    url = BASE_URL + path
    try:
        resp = requests.get(url, params=params, headers=_headers("GET", path), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0":
            logger.warning(f"OKX API 錯誤: {data.get('msg')} (code={data.get('code')})")
        return data
    except Exception as e:
        logger.error(f"OKX GET 請求失敗 {path}: {e}")
        return {}


def _post(path: str, body: dict) -> dict:
    """發送 POST 請求"""
    url = BASE_URL + path
    body_str = json.dumps(body)
    try:
        resp = requests.post(url, data=body_str,
                             headers=_headers("POST", path, body_str), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0":
            logger.warning(f"OKX API 錯誤: {data.get('msg')} (code={data.get('code')})")
        return data
    except Exception as e:
        logger.error(f"OKX POST 請求失敗 {path}: {e}")
        return {}


# ─────────────────────────────────────────────────────────────
# K 線數據
# ─────────────────────────────────────────────────────────────
def get_klines(inst_id: str = SYMBOL, bar: str = "1H", limit: int = 300) -> pd.DataFrame:
    """
    獲取 K 線數據。
    bar 可為 "1m", "5m", "15m", "1H", "4H", "1D" 等。
    回傳 DataFrame（open, high, low, close, volume），按時間升序排列。
    """
    path = "/api/v5/market/candles"
    params = {"instId": inst_id, "bar": bar, "limit": str(limit)}
    data = _get(path, params)

    if not data or "data" not in data:
        logger.error(f"無法獲取 K 線數據 {inst_id} {bar}")
        return pd.DataFrame()

    rows = []
    for candle in data["data"]:
        # OKX 格式：[ts, open, high, low, close, vol, volCcy, ...]
        rows.append({
            "timestamp": int(candle[0]),
            "open":      float(candle[1]),
            "high":      float(candle[2]),
            "low":       float(candle[3]),
            "close":     float(candle[4]),
            "volume":    float(candle[5]),
        })

    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────
# 資金費率
# ─────────────────────────────────────────────────────────────
def get_funding_rate(inst_id: str = "BTC-USDT-SWAP") -> Optional[float]:
    """
    獲取 BTC 永續合約當前資金費率。
    回傳浮點數（如 0.0001 = 0.01%），失敗回傳 None。
    """
    path = "/api/v5/public/funding-rate"
    params = {"instId": inst_id}
    data = _get(path, params)
    try:
        return float(data["data"][0]["fundingRate"])
    except Exception:
        logger.warning("無法獲取資金費率")
        return None


# ─────────────────────────────────────────────────────────────
# 帳戶餘額
# ─────────────────────────────────────────────────────────────
def get_balance(ccy: str = "USDT") -> float:
    """獲取指定幣種的可用餘額"""
    path = "/api/v5/account/balance"
    params = {"ccy": ccy}
    data = _get(path, params)
    try:
        for detail in data["data"][0]["details"]:
            if detail["ccy"] == ccy:
                return float(detail["availBal"])
    except Exception:
        logger.warning(f"無法獲取 {ccy} 餘額")
    return 0.0


def get_btc_balance() -> float:
    """獲取 BTC 可用餘額"""
    return get_balance("BTC")


def get_usdt_balance() -> float:
    """獲取 USDT 可用餘額"""
    return get_balance("USDT")


# ─────────────────────────────────────────────────────────────
# 下單
# ─────────────────────────────────────────────────────────────
def place_market_buy(usdt_amount: float, inst_id: str = SYMBOL) -> dict:
    """
    以市價買入，指定 USDT 金額。
    回傳 OKX 下單回應。
    """
    path = "/api/v5/trade/order"
    body = {
        "instId":  inst_id,
        "tdMode":  "cash",
        "side":    "buy",
        "ordType": "market",
        "sz":      str(round(usdt_amount, 2)),
        "tgtCcy":  "quote_ccy",   # 以 USDT 計價
    }
    logger.info(f"市價買入 {usdt_amount} USDT ({inst_id})")
    return _post(path, body)


def place_market_sell(btc_amount: float, inst_id: str = SYMBOL) -> dict:
    """
    以市價賣出，指定 BTC 數量。
    回傳 OKX 下單回應。
    """
    path = "/api/v5/trade/order"
    body = {
        "instId":  inst_id,
        "tdMode":  "cash",
        "side":    "sell",
        "ordType": "market",
        "sz":      str(round(btc_amount, 8)),
    }
    logger.info(f"市價賣出 {btc_amount} BTC ({inst_id})")
    return _post(path, body)


def place_stop_loss_order(btc_amount: float, stop_price: float,
                          inst_id: str = SYMBOL) -> dict:
    """
    設置止損單（條件單）。
    stop_price：觸發價格（入場價 × 0.97）
    """
    path = "/api/v5/trade/order-algo"
    body = {
        "instId":    inst_id,
        "tdMode":    "cash",
        "side":      "sell",
        "ordType":   "conditional",
        "sz":        str(round(btc_amount, 8)),
        "slTriggerPx": str(round(stop_price, 2)),
        "slOrdPx":   "-1",   # -1 = 市價止損
        "slTriggerPxType": "last",
    }
    logger.info(f"設置止損單 觸發價={stop_price:.2f} 數量={btc_amount:.8f} BTC")
    return _post(path, body)


def cancel_algo_order(algo_id: str, inst_id: str = SYMBOL) -> dict:
    """取消條件單（止損單）"""
    path = "/api/v5/trade/cancel-algos"
    body = [{"algoId": algo_id, "instId": inst_id}]
    return _post(path, body)


# ─────────────────────────────────────────────────────────────
# 查詢持倉
# ─────────────────────────────────────────────────────────────
def get_open_orders(inst_id: str = SYMBOL) -> list:
    """查詢當前掛單"""
    path = "/api/v5/trade/orders-pending"
    params = {"instId": inst_id, "instType": "SPOT"}
    data = _get(path, params)
    return data.get("data", [])


def get_algo_orders(inst_id: str = SYMBOL) -> list:
    """查詢當前條件單（止損單）"""
    path = "/api/v5/trade/orders-algo-pending"
    params = {"instId": inst_id, "instType": "SPOT", "ordType": "conditional"}
    data = _get(path, params)
    return data.get("data", [])


def get_current_price(inst_id: str = SYMBOL) -> float:
    """獲取當前市場價格"""
    path = "/api/v5/market/ticker"
    params = {"instId": inst_id}
    data = _get(path, params)
    try:
        return float(data["data"][0]["last"])
    except Exception:
        logger.warning("無法獲取當前價格")
        return 0.0
