"""vigil/monitors/r_monitor.py — R(반사율)/거울 헬스 (설계문서 §1.2, M2).

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

from vigil.alert_engine import OK, P0, P1, P2, SKIP
from vigil.monitors.running_mean import RunningMean

# 연속 이 횟수 이상 R 산출 실패하면 "정지 수준"으로 격상(§5 P0 예시: "R 산출 연속 실패").
FAIL_STREAK_FOR_P0 = 3
DEFAULT_ROI_NM = (430.0, 470.0)   # 프로파일에 roi_nm 없을 때의 폴백(reflectance_calc 기본 근방)
HISTORY_WINDOW = 20                # 롤링 기준선에 쓸 최근 R값 개수
MIN_HISTORY_FOR_BASELINE = 3       # 이보다 적으면 "베이스라인 축적 중"(경보 안 냄)
# ZA and He windows pair only when adjacent: at most this many non-calibration rows (role not
# za_*/he_*) between them. Yeosu order is He(512→510→513) then ZA(500) — He every 3 h, ZA hourly —
# so pairing "latest of each" used the ZA from an hour before (R scatter ×1.4–1.7, audit 2026-10-02 V2 §4).
# ponytail: row count assumes ~1 s scans; switch to row time if a slower instrument shows up.
MAX_PAIR_GAP_ROWS = 60


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

        self._za_buf = self._new_buf()
        self._he_buf = self._new_buf()
        self._last_za: Optional[tuple] = None   # (spectrum, T, P) — 가장 최근 완결된 윈도우 평균
        self._last_he: Optional[tuple] = None
        self._gap_za = 0                        # non-calibration rows since that window ended
        self._gap_he = 0
        self._history: deque = deque(maxlen=history_window)
        self._fail_streak = 0
        # (1-R)/d [cm^-1] per pixel of the last successful calibration; ConcMonitor builds
        # BBCEAS alpha from it. Not overwritten on failure (keep last good value, like
        # gui/worker.update_mirror_reflectivity).
        self.omr_d: Optional[np.ndarray] = None

    @staticmethod
    def _avg(buf) -> tuple:
        spec, t, p = buf
        return spec.mean(), float(t.mean()), float(p.mean())

    @staticmethod
    def _new_buf() -> tuple:
        """(스펙트럼, 온도, 압력) 누적 평균 — 행을 쌓지 않는다(running_mean 참조)."""
        return RunningMean(), RunningMean(), RunningMean()

    @staticmethod
    def _add(buf, spectrum, temp_c, press_mbar) -> None:
        buf[0].add(spectrum)
        buf[1].add(temp_c)
        buf[2].add(press_mbar)

    def observe(self, role: Optional[str], spectrum, temp_c: float, press_mbar: float):
        """새 행 한 개 관측. za_inject/he_inject 구간 동안 버퍼링하고, **인접한** ZA·He 윈도우 한
        쌍이 완결됐을 때만 R을 재계산해 반환(그리고 즉시 소비한다). 인접 = 두 윈도우 사이의 비교정 행이
        MAX_PAIR_GAP_ROWS 이하(어느 순서든). 더 떨어진 묵은 윈도우는 버린다 — He 가 1시간 전 ZA 와
        짝지어지지 않게. 이번 행으로 새 R이 안 나왔으면 None."""
        if not (role or "").startswith(("za_", "he_")):
            self._gap_za += 1
            self._gap_he += 1
        if role == "za_inject":
            self._add(self._za_buf, spectrum, temp_c, press_mbar)
        elif self._za_buf[0]:   # za 윈도우가 방금 끝남
            self._last_za = self._avg(self._za_buf)
            self._za_buf = self._new_buf()
            self._gap_za = 0
        if role == "he_inject":
            self._add(self._he_buf, spectrum, temp_c, press_mbar)
        elif self._he_buf[0]:   # he 윈도우가 방금 끝남
            self._last_he = self._avg(self._he_buf)
            self._he_buf = self._new_buf()
            self._gap_he = 0

        # the window that just completed has gap 0; the other one must be close to it
        if self._last_za is not None and self._gap_za > MAX_PAIR_GAP_ROWS:
            self._last_za = None
        if self._last_he is not None and self._gap_he > MAX_PAIR_GAP_ROWS:
            self._last_he = None
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
            return self._fail_status("no wavecal — cannot compute R (profile needs reflectance.wavecal_path)")
        calc = ReflectanceCalculator(cavity_len=self.cavity_len_cm, rl_factor=self.rl_factor)
        calc.add_za_spectrum(*self._last_za)
        calc.add_he_spectrum(*self._last_he)
        roi_lo, roi_hi = self.roi_nm
        try:
            wl, _r_raw, r_fit, omr_d = calc.calculate(
                wave_nm=self.wave_nm, roi_min=roi_lo, roi_max=roi_hi)
        except Exception as e:   # ReflectanceCalculator.calculate의 RuntimeError(품질게이트) 포함
            self._fail_streak += 1
            return self._fail_status(str(e))
        self._fail_streak = 0
        m = (wl >= roi_lo) & (wl <= roi_hi)
        # Outside the ROI the R curve is a polynomial extrapolation; clipped to R<=1 it gives
        # omr_d == 0 exactly, i.e. alpha 0 = fake 'no absorption'. Mark it NaN instead.
        self.omr_d = np.where(m, np.asarray(omr_d, dtype=float), np.nan)

        r_val = float(np.median(r_fit[m])) if m.any() else float(np.median(r_fit))
        metrics = {"R": r_val, "n_history": len(self._history)}
        self._history.append(r_val)

        if len(self._history) < MIN_HISTORY_FOR_BASELINE:
            # SKIP, not OK: without a baseline a mirror problem cannot raise anything yet — with He every
            # 3 h that is ~9 h of silence after start (audit 2026-10-02 V2 §4).
            return SKIP, (f"R={r_val:.5f} — building baseline {len(self._history)}/{MIN_HISTORY_FOR_BASELINE}, "
                          f"no drop alarm until then"), metrics

        baseline = float(np.median(list(self._history)[:-1]))
        drop = baseline - r_val
        metrics["baseline"] = baseline
        metrics["drop"] = drop
        if self.alarm_drop is not None and drop > self.alarm_drop:
            return P1, f"R sharp drop R={r_val:.5f} (baseline {baseline:.5f}, Δ{drop:.2e})", metrics
        if self.warn_drop is not None and drop > self.warn_drop:
            return P2, f"R gradual decline R={r_val:.5f} (baseline {baseline:.5f}, Δ{drop:.2e})", metrics
        return OK, f"R={r_val:.5f} (baseline {baseline:.5f})", metrics

    def _fail_status(self, reason: str):
        status = P0 if self._fail_streak >= FAIL_STREAK_FOR_P0 else P1
        return status, f"R computation failed ({self._fail_streak} in a row): {reason}", {"fail_streak": self._fail_streak}
