"""
BTC B策略 V4.2 — 六維度綜合評分系統

維度狀態說明：
  ✅ 已驗證：技術分析
  🔄 近似模擬：機器學習、訂單流、鏈上數據、情緒指標
  ⏳ 待接入：跨市場（Yahoo Finance）、Polymarket
"""

from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger("btc_bot")


@dataclass
class ScoreBreakdown:
    """各維度評分明細"""
    ml_score:        float = 0.0   # 維度1：機器學習（近似）
    orderflow_score: float = 0.0   # 維度2：訂單流（近似）
    cross_market_score: float = 0.0  # 維度3：跨市場（手動/待接入）
    onchain_score:   float = 0.0   # 維度4：鏈上數據（近似）
    sentiment_score: float = 0.0   # 維度5：情緒指標（近似）
    polymarket_score: float = 0.0  # 維度6：Polymarket（手動/待接入）
    tech_score:      float = 0.0   # 技術分析（已驗證）
    total:           float = 0.0
    notes:           list  = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# 維度1：機器學習評分（近似版本 🔄）
# 用多因子線性組合代替隨機森林
# ─────────────────────────────────────────────────────────────
def score_ml(ind: dict) -> float:
    """
    近似 ML 評分公式：
      ml_score =
        (4H漲>2%) × 1.5 +
        (日線漲>3%) × 1.5 +
        (價格>EMA200) × 1.0 +
        (MACD多頭) × 1.0 +
        (RSI<40) × 1.0 -
        (RSI>70) × 1.0 -
        (成交量萎縮) × 0.5

    ml_score ≥ 3.0 → 狀態A（強勢多頭）→ +3分
    ml_score ≥ 1.5 → 狀態B（弱勢多頭）→ +2分
    ml_score ≥ 0.0 → 狀態C（中性）     →  0分
    ml_score < 0.0 → 狀態D（弱勢空頭）→ -2分
    """
    raw = 0.0
    raw += 1.5 if ind["change_4h"] > 0.02  else 0.0
    raw += 1.5 if ind["change_1d"] > 0.03  else 0.0
    raw += 1.0 if ind["above_ema200"]       else 0.0
    raw += 1.0 if ind["macd_bullish"]       else 0.0
    raw += 1.0 if ind["rsi"] < 40           else 0.0
    raw -= 1.0 if ind["rsi"] > 70           else 0.0
    raw -= 0.5 if ind["vol_ratio"] < 0.7    else 0.0

    if raw >= 3.0:
        return 3.0   # 狀態A
    elif raw >= 1.5:
        return 2.0   # 狀態B
    elif raw >= 0.0:
        return 0.0   # 狀態C
    else:
        return -2.0  # 狀態D


def get_ml_state(ind: dict) -> str:
    """回傳 ML 狀態標籤（A/B/C/D）"""
    raw = 0.0
    raw += 1.5 if ind["change_4h"] > 0.02  else 0.0
    raw += 1.5 if ind["change_1d"] > 0.03  else 0.0
    raw += 1.0 if ind["above_ema200"]       else 0.0
    raw += 1.0 if ind["macd_bullish"]       else 0.0
    raw += 1.0 if ind["rsi"] < 40           else 0.0
    raw -= 1.0 if ind["rsi"] > 70           else 0.0
    raw -= 0.5 if ind["vol_ratio"] < 0.7    else 0.0
    if raw >= 3.0: return "A"
    if raw >= 1.5: return "B"
    if raw >= 0.0: return "C"
    return "D"


# ─────────────────────────────────────────────────────────────
# 維度2：訂單流評分（近似版本 🔄）
# 用成交量比率代替大單分析
# ─────────────────────────────────────────────────────────────
def score_orderflow(ind: dict) -> float:
    """
    vol_ratio > 1.5 → +2分（大單活躍買入）
    vol_ratio > 1.2 → +1分
    vol_ratio < 0.7 → -1分（成交萎縮）
    """
    vr = ind["vol_ratio"]
    if vr > 1.5:
        return 2.0
    elif vr > 1.2:
        return 1.0
    elif vr < 0.7:
        return -1.0
    return 0.0


# ─────────────────────────────────────────────────────────────
# 維度3：跨市場評分（⏳待接入，目前接受手動輸入）
# ─────────────────────────────────────────────────────────────
def score_cross_market(manual_score: float = 0.0) -> float:
    """
    接受手動輸入的跨市場評分（-3 ~ +3）。
    每天早上查看納指/DXY方向後手動填入。
    接入 Yahoo Finance 後此函數將自動計算。
    """
    return float(max(-3.0, min(3.0, manual_score)))


def score_cross_market_auto(nasdaq_1d: float, dxy_1d: float,
                             gold_1d: float = 0.0,
                             bond_yield: float = 0.0,
                             nasdaq_consecutive_down: int = 0) -> float:
    """
    自動計算跨市場評分（接入 Yahoo Finance 後使用）。
    nasdaq_1d, dxy_1d, gold_1d：日漲跌幅（小數，如 0.01 = 1%）
    bond_yield：10年美債收益率
    nasdaq_consecutive_down：納指連續下跌天數
    """
    score = 0.0

    # 納斯達克（權重最高）
    if nasdaq_1d > 0.005:
        score += 2.0
    elif nasdaq_1d < -0.005:
        score -= 2.0
    if nasdaq_consecutive_down >= 3:
        score -= 3.0   # 禁止做多

    # 美元指數 DXY
    if dxy_1d < 0:
        score += 1.0
    if dxy_1d > 0.01:
        score -= 2.0

    # 黃金
    if gold_1d > 0.02:
        score += 1.0
    elif gold_1d < -0.01:
        score -= 1.0

    # 10年美債
    if bond_yield > 5.0:
        score -= 2.0

    return float(max(-5.0, min(5.0, score)))


# ─────────────────────────────────────────────────────────────
# 維度4：鏈上數據評分（近似版本 🔄）
# 用價格相對 EMA200 偏離近似 MVRV
# ─────────────────────────────────────────────────────────────
def score_onchain(ind: dict) -> float:
    """
    dev = (價格 - EMA200) / EMA200

    dev < -0.20 ≈ MVRV < 1（超賣）→ +3分
    dev < -0.10 ≈ MVRV 1-1.5     → +2分
    dev <  0.00 ≈ MVRV 1.5-2     → +1分
    dev <  0.15 ≈ MVRV 2-2.5     →  0分
    dev <  0.30 ≈ MVRV 2.5-3.5   → -1分
    dev ≥  0.30 ≈ MVRV > 3.5     → -2分
    """
    dev = ind["dev_ema200"]
    if dev < -0.20:
        return 3.0
    elif dev < -0.10:
        return 2.0
    elif dev < 0.00:
        return 1.0
    elif dev < 0.15:
        return 0.0
    elif dev < 0.30:
        return -1.0
    else:
        return -2.0


# ─────────────────────────────────────────────────────────────
# 維度5：情緒指標評分（近似版本 🔄）
# 用 RSI 近似恐惧贪婪指數，4H 漲跌幅近似資金費率
# ─────────────────────────────────────────────────────────────
def score_sentiment(ind: dict,
                    fear_greed: Optional[int] = None,
                    funding_rate: Optional[float] = None) -> float:
    """
    若有真實恐懼貪婪指數（0-100）和資金費率，優先使用真實數據。
    否則使用 RSI 和 4H 漲跌幅近似。
    """
    score = 0.0

    # ── 恐懼貪婪指數評分 ──
    if fear_greed is not None:
        fg = fear_greed
        if fg <= 10:    score += 3.0
        elif fg <= 25:  score += 2.0
        elif fg <= 45:  score += 1.0
        elif fg <= 55:  score += 0.0
        elif fg <= 75:  score -= 1.0
        elif fg <= 90:  score -= 2.0
        else:           score -= 3.0
    else:
        # RSI 近似
        rsi = ind["rsi"]
        if rsi < 20:    score += 3.0
        elif rsi < 35:  score += 2.0
        elif rsi < 45:  score += 1.0
        elif rsi <= 60: score += 0.0
        elif rsi <= 75: score -= 1.0
        else:           score -= 2.0

    # ── 資金費率評分 ──
    if funding_rate is not None:
        fr = funding_rate
        if fr < -0.0005:   score += 2.0
        elif fr <= 0.0005: score += 0.0
        elif fr <= 0.001:  score -= 1.0
        else:              score -= 2.0
    else:
        # 4H 漲跌幅近似
        ch4 = ind["change_4h"]
        if ch4 > 0.05:    score -= 2.0   # 多方過熱
        elif ch4 < -0.03: score += 1.0   # 空方過熱

    return score


# ─────────────────────────────────────────────────────────────
# 維度6：Polymarket 評分（⏳待接入，目前接受手動輸入）
# ─────────────────────────────────────────────────────────────
def score_polymarket(manual_score: float = 0.0) -> float:
    """
    接受手動輸入的 Polymarket 評分（-2 ~ +2）。
    每天查看 polymarket.com/crypto 後手動填入。
    接入 Polymarket API 後此函數將自動計算。
    """
    return float(max(-2.0, min(2.0, manual_score)))


# ─────────────────────────────────────────────────────────────
# 技術分析評分 ✅已驗證
# ─────────────────────────────────────────────────────────────
def score_technical(ind: dict, ind_4h: Optional[dict] = None) -> float:
    """
    日線多頭（價格>EMA200）：+1分
    4H 多頭（MACD多頭+EMA50）：+1分
    1H 有效信號+成交量確認：+1分
    成交量萎縮：-1分
    """
    score = 0.0

    # 日線多頭
    if ind["above_ema200"]:
        score += 1.0

    # 4H 多頭（若有4H指標則用，否則用1H近似）
    if ind_4h is not None:
        if ind_4h["macd_bullish"] and ind_4h["above_ema50"]:
            score += 1.0
    else:
        if ind["macd_bullish"] and ind["above_ema50"]:
            score += 1.0

    # 1H 有效信號
    has_signal = _detect_entry_signal(ind)
    vol_confirmed = ind["vol_ratio"] >= 1.2

    if has_signal and vol_confirmed:
        score += 1.0
    elif ind["vol_ratio"] < 0.7:
        score -= 1.0

    return score


def _detect_entry_signal(ind: dict) -> bool:
    """
    偵測三種入場信號（A/B/C）之一是否觸發。
    信號A：MACD金叉 + RSI 40-65
    信號B：布林下軌反彈 + RSI<35
    信號C：EMA20支撐 + RSI回調至50附近
    """
    # 信號A：MACD金叉
    if ind["macd_cross_up"] and 40 <= ind["rsi"] <= 65:
        return True

    # 信號B：布林下軌反彈
    if ind["boll_pos"] < 0.1 and ind["rsi"] < 35:
        return True

    # 信號C：EMA20支撐（價格接近EMA20）
    price_near_ema20 = abs(ind["close"] - ind["ema20"]) / ind["ema20"] < 0.005
    if price_near_ema20 and 45 <= ind["rsi"] <= 55:
        return True

    return False


# ─────────────────────────────────────────────────────────────
# 綜合評分計算
# ─────────────────────────────────────────────────────────────
def calc_total_score(
    ind: dict,
    ind_4h: Optional[dict] = None,
    fear_greed: Optional[int] = None,
    funding_rate: Optional[float] = None,
    cross_market_manual: float = 0.0,
    polymarket_manual: float = 0.0,
) -> ScoreBreakdown:
    """
    計算六維度綜合評分，回傳 ScoreBreakdown 物件。
    """
    bd = ScoreBreakdown()
    notes = []

    bd.ml_score        = score_ml(ind)
    bd.orderflow_score = score_orderflow(ind)
    bd.cross_market_score = score_cross_market(cross_market_manual)
    bd.onchain_score   = score_onchain(ind)
    bd.sentiment_score = score_sentiment(ind, fear_greed, funding_rate)
    bd.polymarket_score= score_polymarket(polymarket_manual)
    bd.tech_score      = score_technical(ind, ind_4h)

    bd.total = (
        bd.ml_score +
        bd.orderflow_score +
        bd.cross_market_score +
        bd.onchain_score +
        bd.sentiment_score +
        bd.polymarket_score +
        bd.tech_score
    )

    ml_state = get_ml_state(ind)
    notes.append(f"ML狀態:{ml_state} 評分:{bd.ml_score:+.1f}")
    notes.append(f"訂單流:{bd.orderflow_score:+.1f} (vol_ratio={ind['vol_ratio']:.2f})")
    notes.append(f"跨市場:{bd.cross_market_score:+.1f} (手動)")
    notes.append(f"鏈上:{bd.onchain_score:+.1f} (dev_ema200={ind['dev_ema200']:.3f})")
    notes.append(f"情緒:{bd.sentiment_score:+.1f} (RSI={ind['rsi']:.1f})")
    notes.append(f"Polymarket:{bd.polymarket_score:+.1f} (手動)")
    notes.append(f"技術:{bd.tech_score:+.1f}")
    notes.append(f"綜合:{bd.total:+.1f}")
    bd.notes = notes

    logger.info(" | ".join(notes))
    return bd


# ─────────────────────────────────────────────────────────────
# 倉位計算
# ─────────────────────────────────────────────────────────────
def calc_position_size(total_score: float) -> float:
    """
    根據綜合評分決定入場倉位（USDT）。

    ≥12分 → 200 USDT（40%）
    8-11分 → 150 USDT（30%）
    5-7分  → 100 USDT（20%）
    3-4分  →  50 USDT（10%）
    <3分   →   0 USDT（不開倉）
    """
    score = total_score
    if score >= 12:
        return 200.0
    elif score >= 8:
        return 150.0
    elif score >= 5:
        return 100.0
    elif score >= 3:
        return 50.0
    else:
        return 0.0
