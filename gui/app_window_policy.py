"""gui/app_window_policy.py
allow_negative_gas 정책 해석 (gui/app_window.py에서 분리 — 순수 이동, 본문 동일).

§11(분석 실행)과 §14(시나리오 config)가 둘 다 쓰는데 §11만 믹스인으로 나가면서
gui.app_window <-> 믹스인 순환 임포트가 된다. 그래서 두 함수를 중립 모듈로 뺐다.
gui.app_window에서 재수출하므로 tools/test_test_fit_dialog.py의 임포트 경로는 그대로.
"""
import warnings

def _scenario_gas_policy(scenario, current):
    """Restore an explicit saved policy; old files visibly preserve the current UI policy."""
    if "allow_negative_gas" not in scenario:
        warnings.warn("legacy scenario has no allow_negative_gas; preserving current checkbox value",
                      RuntimeWarning, stacklevel=2)
        return bool(current), "legacy scenario fallback: current checkbox"
    value = scenario["allow_negative_gas"]
    if not isinstance(value, bool):
        raise TypeError("scenario allow_negative_gas must be bool")
    return value, "scenario"


def _channel_worker_gas_policy(use_cfg, cfg, live_value):
    if not isinstance(live_value, bool):
        raise TypeError("live allow_negative_gas must be bool")
    return _scenario_gas_policy(cfg, live_value)[0] if use_cfg else live_value
