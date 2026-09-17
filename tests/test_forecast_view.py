import importlib
import importlib.util
import pytest


def api():
    assert importlib.util.find_spec("chatglance.forecast_view"), (
        "forecast highlight missing"
    )
    return importlib.import_module("chatglance.forecast_view")


def forecast(probability=28, status="ok"):
    return {
        "status": status,
        "probability_24h_percent": probability,
        "source_updated_at": "2026-09-17T07:01:27+00:00",
        "source": "https://codexreset.org/",
        "horizon": "24h",
    }


def test_current_probability_is_highlighted_without_promising_safety():
    text = api().render_forecast(forecast(), 70)
    assert "reset-forecast" in text and "28%" in text and "15:01" in text
    assert "未触发预测否决" in text and "不代表不会重置" in text
    assert "https://codexreset.org/" in text and "实验性概率" in text


def test_high_probability_is_an_explicit_veto():
    text = api().render_forecast(forecast(91), 70)
    assert "is-veto" in text and "91%" in text and "预测否决：不用卡" in text


def test_threshold_equality_is_not_a_prediction_veto():
    assert "is-veto" not in api().render_forecast(forecast(70), 70)


@pytest.mark.parametrize("status", ["missing", "stale", "invalid"])
def test_unavailable_forecast_is_never_green(status):
    text = api().render_forecast(forecast(28, status), 70)
    assert "预测不可用" in text and "暂停自动用卡" in text
    assert "is-clear" not in text


def test_unconfigured_rule_is_only_display_not_a_false_pass():
    text = api().render_forecast(forecast(), None)
    assert "未配置预测否决" in text and "仅展示" in text
