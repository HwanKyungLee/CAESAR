"""oculus/monitors/lamp_monitor.py — 램프(LED) 세기 헬스.

HK 는 LED **온도**만 본다. 빛의 **세기**가 계단으로 바뀌거나(재정렬·필터 재장착·
LED 전류 조정) 꺼져도(광경로 차단) 지금까지는 아무 경보가 없었다. ZA(제로에어)
블록은 캐비티에 흡수체가 없을 때의 세기 = I₀ 이므로 램프 세기의 가장 깨끗한 지표다.

지표는 Augur I₀ 계단 가드와 같다: ZA 블록 스펙트럼의 채널 평균
(`gui/worker.py` `_i0_metric = nanmean(za_arr, axis=1)`) — 두 프로그램이 같은 사건을
같은 크기로 보게 한다.

판정은 인접 블록 차가 아니라 **최근 기준선(롤링 중앙값) 대비**다. `core.step_guard`
의 knot-to-knot 판정은 하루에 걸쳐 퍼진 계단(2026-06-05 CH2)을 못 잡았다.

등급:
  · 기준선의 dark_frac 미만              → P0 램프 꺼짐/광경로 차단 의심
  · |변화| > alarm_rel                   → P1 램프 세기 계단
  · |변화| > warn 문턱                   → P2 램프 세기 변화
    warn 문턱 = max(warn_rel, ADAPT_FACTOR × p95(기준선 대비 평소 이탈)) — `core.step_guard`
    와 같은 채널 적응 규칙. 콜드는 램프가 하루 주기로 ±8–10 % 출렁여 고정 5 % 면 블록의
    31 % 가 P2 였다. P1·P0 문턱은 적응시키지 않는다(계단·꺼짐은 채널과 무관하게 잡는다).
P0 블록은 기준선에 넣지 않는다(어두운 블록이 기준을 끌어내리면 복귀가 계단처럼 보인다).
계단 뒤 새 레벨은 넣는다 — 기준선이 ~history/2 블록 뒤 새 정상에 적응한다.

문턱 근거 (2026 여수, ZA 블록 = 시간당 1회):
  · 평상시: 핫 인접블록 변화 p95 0.6–1.3 %, 24블록 중앙값 대비 이탈 중앙 0.3 %
    (`diagnostics/i0_interp_2026-09/_cache_hot_*_b.npz`, 05-24~06-01)
  · 실사건: 핫 05-26 08:30→09:00 **+20 %** 계단, 콜드 06-15~16 정상의 **~4 %** 로 반복 추락
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from oculus.alert_engine import OK, P0, P1, P2

WARN_REL = 0.05
ALARM_REL = 0.15          # = core.step_guard.REL_FLOOR (핫 정상 drift p99.5 의 ~2배)
ADAPT_FACTOR = 2.0        # = core.step_guard.ADAPT_FACTOR
ADAPT_PCTL = 95.0
DARK_FRAC = 0.20
HISTORY_WINDOW = 24       # ≈ 하루치 ZA 블록
MIN_HISTORY_FOR_BASELINE = 3
MIN_SCANS_PER_BLOCK = 3   # 이보다 짧은 ZA 구간은 전이 조각 — 판정하지 않는다


class LampMonitor:
    """채널 하나의 램프 세기 추세. 매 행 `observe(role, spectrum)` — ZA 구간이 끝난
    행에서만 (status, msg, metrics) 를 돌려주고 나머지는 None."""

    def __init__(self, warn_rel: float = WARN_REL, alarm_rel: float = ALARM_REL,
                 dark_frac: float = DARK_FRAC, history_window: int = HISTORY_WINDOW):
        self.warn_rel = warn_rel
        self.alarm_rel = alarm_rel
        self.dark_frac = dark_frac
        self._buf: list = []
        self._history: deque = deque(maxlen=history_window)

    def observe(self, role: Optional[str], spectrum):
        if role == "za_inject":
            self._buf.append(float(np.nanmean(np.asarray(spectrum, dtype=float))))
            return None
        if not self._buf:
            return None
        scans, self._buf = self._buf, []
        if len(scans) < MIN_SCANS_PER_BLOCK:
            return None
        return self._evaluate(float(np.mean(scans)), len(scans))

    def _evaluate(self, level: float, n_scans: int):
        metrics = {"I": level, "n_scans": n_scans, "n_history": len(self._history)}
        if not np.isfinite(level):
            return P1, "램프 세기 산출 실패(NaN)", metrics
        if len(self._history) < MIN_HISTORY_FOR_BASELINE:
            self._history.append(level)
            return OK, (f"I={level:.0f} (기준선 축적 중 "
                        f"{len(self._history)}/{MIN_HISTORY_FOR_BASELINE})"), metrics

        hist = np.asarray(self._history, dtype=float)
        baseline = float(np.median(hist))
        rel = level / baseline - 1.0 if baseline > 0 else float("nan")
        warn = max(self.warn_rel,
                   ADAPT_FACTOR * float(np.percentile(np.abs(hist / baseline - 1.0), ADAPT_PCTL)))
        metrics.update(baseline=baseline, rel=rel, warn_rel=warn)
        if baseline > 0 and level < self.dark_frac * baseline:
            return P0, (f"램프 꺼짐/광경로 차단 의심 I={level:.0f} "
                        f"(기준 {baseline:.0f}의 {level / baseline:.0%})"), metrics
        self._history.append(level)
        if abs(rel) > self.alarm_rel:
            return P1, f"램프 세기 계단 {rel:+.1%} (I={level:.0f}, 기준 {baseline:.0f})", metrics
        if abs(rel) > warn:
            return P2, f"램프 세기 변화 {rel:+.1%} (I={level:.0f}, 기준 {baseline:.0f})", metrics
        return OK, f"I={level:.0f} ({rel:+.1%})", metrics
