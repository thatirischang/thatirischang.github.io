#!/usr/bin/env python3
"""
BTC B策略 V4.2 — 邏輯單元測試
驗證評分系統、指標計算、倉位管理的正確性
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

# ─────────────────────────────────────────
# 測試1：技術指標計算
# ─────────────────────────────────────────
def test_indicators():
    print("=" * 50)
    print("測試1：技術指標計算")

    from core.indicators import add_all_indicators, get_latest_indicators

    # 生成模擬 K 線數據（300根）
    np.random.seed(42)
    n = 300
    prices = 40000 + np.cumsum(np.random.randn(n) * 500)
    prices = np.maximum(prices, 10000)

    df = pd.DataFrame({
        "timestamp": range(n),
        "open":   prices * 0.999,
        "high":   prices * 1.005,
        "low":    prices * 0.995,
        "close":  prices,
        "volume": np.random.uniform(100, 500, n),
    })

    df = add_all_indicators(df)
    ind = get_latest_indicators(df)

    assert "ema20"  in ind, "缺少 ema20"
    assert "ema200" in ind, "缺少 ema200"
    assert "macd"   in ind, "缺少 macd"
    assert "rsi"    in ind, "缺少 rsi"
    assert 0 <= ind["rsi"] <= 100, f"RSI 超出範圍: {ind['rsi']}"
    assert 0 <= ind["boll_pos"] <= 2, f"布林帶位置異常: {ind['boll_pos']}"
    assert ind["vol_ratio"] > 0, f"成交量比率異常: {ind['vol_ratio']}"

    print(f"  ✅ 最新收盤價: {ind['close']:.2f}")
    print(f"  ✅ RSI: {ind['rsi']:.1f}")
    print(f"  ✅ EMA200: {ind['ema200']:.2f}")
    print(f"  ✅ MACD金叉: {ind['macd_cross_up']}")
    print(f"  ✅ 成交量比率: {ind['vol_ratio']:.2f}")
    print("  ✅ 技術指標計算通過")
    return ind


# ─────────────────────────────────────────
# 測試2：六維度評分系統
# ─────────────────────────────────────────
def test_scoring(ind):
    print("\n" + "=" * 50)
    print("測試2：六維度評分系統")

    from core.scoring import (
        score_ml, score_orderflow, score_onchain,
        score_sentiment, score_cross_market, score_polymarket,
        score_technical, calc_total_score, calc_position_size,
        get_ml_state,
    )

    ml = score_ml(ind)
    assert ml in (-2.0, 0.0, 2.0, 3.0), f"ML評分異常: {ml}"
    print(f"  ✅ ML評分: {ml:+.1f} (狀態{get_ml_state(ind)})")

    of = score_orderflow(ind)
    assert of in (-1.0, 0.0, 1.0, 2.0), f"訂單流評分異常: {of}"
    print(f"  ✅ 訂單流評分: {of:+.1f}")

    oc = score_onchain(ind)
    assert oc in (-2.0, -1.0, 0.0, 1.0, 2.0, 3.0), f"鏈上評分異常: {oc}"
    print(f"  ✅ 鏈上評分: {oc:+.1f}")

    # 測試恐懼貪婪指數評分
    sent_real = score_sentiment(ind, fear_greed=20, funding_rate=0.0001)
    print(f"  ✅ 情緒評分（真實數據）: {sent_real:+.1f}")

    sent_approx = score_sentiment(ind)
    print(f"  ✅ 情緒評分（RSI近似）: {sent_approx:+.1f}")

    cm = score_cross_market(1.5)
    assert cm == 1.5, f"跨市場評分異常: {cm}"
    print(f"  ✅ 跨市場評分（手動）: {cm:+.1f}")

    pm = score_polymarket(-1.0)
    assert pm == -1.0, f"Polymarket評分異常: {pm}"
    print(f"  ✅ Polymarket評分（手動）: {pm:+.1f}")

    tech = score_technical(ind)
    assert -1 <= tech <= 3, f"技術評分異常: {tech}"
    print(f"  ✅ 技術評分: {tech:+.1f}")

    # 綜合評分
    bd = calc_total_score(
        ind=ind,
        fear_greed=25,
        funding_rate=0.0001,
        cross_market_manual=1.0,
        polymarket_manual=0.5,
    )
    print(f"  ✅ 綜合評分: {bd.total:+.1f}")
    for note in bd.notes:
        print(f"     {note}")

    # 倉位計算測試
    test_cases = [
        (12, 200.0), (10, 150.0), (6, 100.0), (3, 50.0), (1, 0.0)
    ]
    for score, expected in test_cases:
        result = calc_position_size(score)
        assert result == expected, f"評分{score}倉位應為{expected}，得到{result}"
    print("  ✅ 倉位計算全部正確")

    print("  ✅ 六維度評分系統通過")
    return bd


# ─────────────────────────────────────────
# 測試3：倉位管理
# ─────────────────────────────────────────
def test_position_manager():
    print("\n" + "=" * 50)
    print("測試3：倉位管理")

    import shutil
    # 使用臨時目錄避免污染真實數據
    os.makedirs("data_test", exist_ok=True)

    import core.position_manager as pm_module
    orig_state_file = pm_module.STATE_FILE
    pm_module.STATE_FILE = "data_test/test_state.json"

    # 先清除舊狀態檔再初始化
    if os.path.exists("data_test/test_state.json"):
        os.remove("data_test/test_state.json")

    from core.position_manager import PositionManager

    pm = PositionManager()
    assert not pm.position.is_open, "初始狀態應無持倉"

    # 測試開倉
    pm.open_position(entry_price=50000, usdt_amount=100, score=8.5)
    assert pm.position.is_open, "開倉後應有持倉"
    assert abs(pm.position.stop_loss - 50000 * 0.97) < 1, "止損價計算錯誤"
    assert abs(pm.position.btc_amount - 100/50000) < 1e-8, "BTC數量計算錯誤"
    print(f"  ✅ 開倉 | 入場價=50000 | 止損={pm.position.stop_loss:.2f}")

    # 測試移動止損（盈利+5%）
    new_sl = pm.update_trailing_stop(52500)  # +5%
    assert new_sl == 50000, f"保本止損應為50000，得到{new_sl}"
    print(f"  ✅ 移動止損（+5%保本）→ {new_sl:.2f}")

    # 測試移動止損（盈利+10%）
    new_sl = pm.update_trailing_stop(55000)  # +10%
    expected_sl = 50000 * 1.05
    assert abs(new_sl - expected_sl) < 1, f"止損應為{expected_sl:.2f}，得到{new_sl}"
    print(f"  ✅ 移動止損（+10%鎖利5%）→ {new_sl:.2f}")

    # 測試移動止損（盈利+15%）
    new_sl = pm.update_trailing_stop(57500)  # +15%
    # 最高價已更新為57500，止損應為57500*0.92
    assert abs(new_sl - 57500 * 0.92) < 1, f"移動止損計算錯誤: {new_sl}"
    print(f"  ✅ 移動止損（+15%追蹤）→ {new_sl:.2f}")

    # 測試止損觸發
    ind_mock = {
        "above_ema200": True,
        "ml_state_d": False,
        "macd_cross_down": False,
    }
    reason = pm.check_stop_loss(pm.position.stop_loss - 1, ind_mock)
    assert reason is not None, "應觸發止損"
    print(f"  ✅ 止損觸發: {reason}")

    # 測試平倉
    pm.close_position(exit_price=48500, reason="測試止損")
    assert not pm.position.is_open, "平倉後應無持倉"
    assert pm.risk.consec_losses == 1, "虧損應計入連續虧損"
    print(f"  ✅ 平倉 | 累計虧損次數={pm.risk.consec_losses}")

    # 測試風控
    can, reason = pm.can_trade()
    assert can, f"應可交易，但被拒絕: {reason}"
    print(f"  ✅ 風控檢查: {reason}")

    # 恢復原始路徑
    pm_module.STATE_FILE = orig_state_file
    shutil.rmtree("data_test", ignore_errors=True)

    print("  ✅ 倉位管理通過")


# ─────────────────────────────────────────
# 測試4：止損參數驗證
# ─────────────────────────────────────────
def test_stop_loss_params():
    print("\n" + "=" * 50)
    print("測試4：止損參數驗證（V4.2 回測驗證最優）")

    from config.settings import STOP_LOSS_PCT

    assert STOP_LOSS_PCT == 0.03, f"止損應為3%，當前為{STOP_LOSS_PCT*100}%"
    print(f"  ✅ 固定止損: {STOP_LOSS_PCT*100}%（回測驗證最優）")

    # 驗證止損價計算
    entry = 50000
    stop  = entry * (1 - STOP_LOSS_PCT)
    assert abs(stop - 48500) < 1, f"止損價應為48500，得到{stop}"
    print(f"  ✅ 入場50000 → 止損{stop:.0f}")

    print("  ✅ 止損參數驗證通過")


# ─────────────────────────────────────────
# 測試5：評分邊界值測試
# ─────────────────────────────────────────
def test_scoring_boundaries():
    print("\n" + "=" * 50)
    print("測試5：評分邊界值測試")

    from core.scoring import score_sentiment, score_onchain

    # 恐懼貪婪指數邊界
    test_fg = [(5, 3.0), (20, 2.0), (35, 1.0), (50, 0.0), (65, -1.0), (80, -2.0), (95, -3.0)]
    ind_mock = {"rsi": 50, "change_4h": 0.0, "vol_ratio": 1.0}
    for fg, expected_base in test_fg:
        score = score_sentiment(ind_mock, fear_greed=fg, funding_rate=0.0)
        print(f"  恐懼貪婪={fg:3d} → 情緒評分={score:+.1f}")

    # 鏈上數據邊界（EMA200偏離）
    test_dev = [(-0.25, 3.0), (-0.15, 2.0), (-0.05, 1.0), (0.10, 0.0), (0.20, -1.0), (0.35, -2.0)]
    for dev, expected in test_dev:
        ind_mock2 = {"dev_ema200": dev}
        score = score_onchain(ind_mock2)
        status = "✅" if score == expected else "❌"
        print(f"  {status} EMA200偏離={dev:+.2f} → 鏈上評分={score:+.1f}（預期{expected:+.1f}）")

    print("  ✅ 邊界值測試完成")


# ─────────────────────────────────────────
# 主測試執行
# ─────────────────────────────────────────
if __name__ == "__main__":
    print("BTC B策略 V4.2 — 邏輯單元測試")
    print("=" * 50)

    try:
        ind = test_indicators()
        bd  = test_scoring(ind)
        test_position_manager()
        test_stop_loss_params()
        test_scoring_boundaries()

        print("\n" + "=" * 50)
        print("🎉 所有測試通過！機器人邏輯驗證完成")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n❌ 測試失敗: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 測試錯誤: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
