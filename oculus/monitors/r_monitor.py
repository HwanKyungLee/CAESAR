"""oculus/monitors/r_monitor.py — R(반사율)/거울 헬스 (설계문서 §1.2, M2).

ZA/He 스캔 쌍에서 R을 산출해 추세를 본다. 물리 계산은
`tools/reflectance_calc.ReflectanceCalculator`를 그대로 재사용(단일 출처, 그
계산기가 이미 Sellmeier 정본 Rayleigh 물리 + He/ZA contrast 품질게이트를 갖고
있다) — 이 모듈은 실시간 버퍼링(ZA/He 윈도우 완결 감지)과 추세 경보만 얹는다.

등급(§5): R 산출 실패 = P1(1회) → 연속 3회 이상이면 P0("R 산출 연속 실패").
급락(추세 대비, alarm_drop 초과) = P1. 완만한 드리프트(warn_drop 초과) = P2.

한 채널(=하나의 캐비티)에 `RMonitor` 하나. flag role별 행을 `observe()`에
계속 흘려주면 알아서 ZA/He 윈도우 경계를 감지해 필요할 때만 R을 재계산한다.
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from oculus.alert_engine import OK, P0, P1, P2

# 연속 이 횟수 이상 R 산출 실패하면 "정지 수준"으로 격상(§5 P0 예시: "R 산출 연속 실패").
FAIL_STREAK_FOR_P0 = 3
DEFAULT_ROI_NM = (430.0, 470.0)   # 프로파일에 roi_nm 없을 때의 폴백(reflectance_calc 기본 근방)
HISTORY_WINDOW = 20                # 롤링 기준선에 쓸 최근 R값 개수
MIN_HISTORY_FOR_BASELINE = 3       # 이보다 적으면 "베이스라인 축적 중"(경보 안 냄)


class RMonitor:
    """채널 하나의 R 추세 감시 상태 컨테이너.

        rm = RMonitor(wave_nm=wave, cavity_len_cm=51.8, rl_factor=0.933,
                      roi_nm=(444.1, 470.6), warn_drop=5e-4, alarm_drop=2e-3)
        result = rm.observe(role, spectrum, temp_c, press_mbar)  # 매 행 호출
        if result is not None:
            status, msg, metrics = result   # 이번 행으로 ZA/He 윈도우가 완결돼 R 갱신됨
    """

    def __init__(self, wave_nm: Optional[np.ndarray], cavity_len_cm: float = 51.8,
                 rl_factor: float = 0.933, roi_nm: Optional[tuple] = None,
                 warn_drop: Optional[float] = None, alarm_drop: Optional[float] = None,
                 history_window: int = HISTORY_WINDOW):
        self.wave_nm = wave_nm
        self.cavity_len_cm = cavity_len_cm
        self.rl_factor = rl_factor
        self.roi_nm = roi_nm or DEFAULT_ROI_NM
        self.warn_drop = warn_drop
        self.alarm_drop = alarm_drop

        self._za_buf: list = []
        self._he_buf: list = []
        self._last_za: Optional[tuple] = None   # (spectrum, T, P) — 가장 최근 완결된 윈도우 평균
        self._last_he: Optional[tuple] = None
        self._history: deque = deque(maxlen=history_window)
        self._fail_streak = 0

    @staticmethod
    def _avg(buf: list) -> tuple:
        spec = np.mean(np.array([b[0] for b in buf], dtype=float), axis=0)
        t = float(np.mean([b[1] for b in buf]))
        p = float(np.mean([b[2] for b in buf]))
        return spec, t, p

    def observe(self, role: Optional[str], spectrum, temp_c: float, press_mbar: float):
        """새 행 한 개 관측. za_inject/he_inject 구간 동안 버퍼링하고, **둘 다** 갓
        완결된 새 평균을 갖고 있을 때만 R을 재계산해 반환(그리고 즉시 소비/리셋한다) —
        그래야 이전 사이클의 묵은 za/he 평균이 이번 사이클의 새 평균과 잘못 짝지어져
        엉뚱한 R이 나오는 걸 막는다. 이번 행으로 새 R이 안 나왔으면 None."""
        if role == "za_inject":
            self._za_buf.append((spectrum, temp_c, press_mbar))
        elif self._za_buf:   # za 윈도우가 방금 끝남
            self._last_za = self._avg(self._za_buf)
            self._za_buf = []
        if role == "he_inject":
            self._he_buf.append((spectrum, temp_c, press_mbar))
        elif self._he_buf:   # he 윈도우가 방금 끝남
            self._last_he = self._avg(self._he_buf)
            self._he_buf = []

        if self._last_za is not None and self._last_he is not None:
            result = self._compute()
            self._last_za = None
            self._last_he = None
            return result
        return None

    def _compute(self):
        from tools.reflectance_calc import ReflectanceCalculator
        if self.wave_nm is None:
            self._fail_streak += 1
            return self._fail_status("wavecal 없음 — R 계산 불가(프로파일에 reflectance.wavecal_path 필요)")
        calc = ReflectanceCalculator(cavity_len=self.cavity_len_cm, rl_factor=self.rl_factor)
        calc.add_za_spectrum(*self._last_za)
        calc.add_he_spectrum(*self._last_he)
        roi_lo, roi_hi = self.roi_nm
        try:
            wl, _r_raw, r_fit, _omr_d = calc.calculate(
                wave_nm=self.wave_nm, roi_min=roi_lo, roi_max=roi_hi)
        except Exception as e:   # ReflectanceCalculator.calculate의 RuntimeError(품질게이트) 포함
            self._fail_streak += 1
            return self._fail_status(str(e))
        self._fail_streak = 0

        m = (wl >= roi_lo) & (wl <= roi_hi)
        r_val = float(np.median(r_fit[m])) if m.any() else float(np.median(r_fit))
        metrics = {"R": r_val, "n_history": len(self._history)}
        self._history.append(r_val)

        if len(self._history) < MIN_HISTORY_FOR_BASELINE:
            return OK, f"R={r_val:.5f} (기준선 축적 중 {len(self._history)}/{MIN_HISTORY_FOR_BASELINE})", metrics

        baseline = float(np.median(list(self._history)[:-1]))
        drop = baseline - r_val
        metrics["baseline"] = baseline
        metrics["drop"] = drop
        if self.alarm_drop is not None and drop > self.alarm_drop:
            return P1, f"R 급락 R={r_val:.5f} (기준 {baseline:.5f}, Δ{drop:.2e})", metrics
        if self.warn_drop is not None and drop > self.warn_drop:
            return P2, f"R 완만한 하락 R={r_val:.5f} (기준 {baseline:.5f}, Δ{drop:.2e})", metrics
        return OK, f"R={r_val:.5f} (기준 {baseline:.5f})", metrics

    def _fail_status(self, reason: str):
        status = P0 if self._fail_streak >= FAIL_STREAK_FOR_P0 else P1
        return status, f"R 산출 실패({self._fail_streak}회 연속): {reason}", {"fail_streak": self._fail_streak}
