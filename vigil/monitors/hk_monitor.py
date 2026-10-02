"""vigil/monitors/hk_monitor.py — HK(Housekeeping) 밴드 헬스 (설계문서 §1.3, M1).

프로파일의 HK 지도가 물리 환산·밴드판정을 이미 갖고 있다(`profile.HK.read()`) —
이 모듈은 그 결과를 Vigil의 P0/P1/P2 어휘(§5)로 옮기고, CCD 포화를 더한다.
피팅이 필요 없어(§7 "두 번째로 싸고 가치 큼") watcher가 이미 파싱해 둔 행만 있으면 된다.

등급 매핑(§5 예시에 맞춤):
  · HK 밴드 ALARM 이탈           → P1 ("오븐/압력 밴드 이탈"과 동일 부류)
  · HK 밴드 WARN 이탈 · 센서 결측 → P2 ("센서 1개 결측"과 동일 부류)
  · 신호채널 일부 포화            → P1
  · 신호채널 전부 포화            → P0 ("전 채널 CCD 포화" — §5 P0 예시 그대로)
"""
from __future__ import annotations

import math
from typing import Optional

from vigil.alert_engine import OK, P0, P1, P2, worse
from vigil.profile import Profile, SEVERITY_ALARM, SEVERITY_WARN


def _fmt(label: str, val: float, unit: Optional[str]) -> str:
    u = f" {unit}" if unit else ""
    return f"{label}={val:.2f}{u}"


def evaluate_hk(profile: Profile, row, phase: Optional[str] = None, channels=None):
    """한 행의 HK 블록 + 신호채널 포화를 평가 → (status, msg, metrics).

    status: OK | P2(주의) | P1(밴드이탈/부분포화) | P0(전채널포화).
    `phase`(그 행의 flag role)를 넘겨야 교정구간 오경보를 피한다(HKField.applies_to).
    channels = 포화를 볼 블록(기본: signal 채널). 기본 프로파일이면 호출측이 빛이 들어오는 auto 블록을 넘긴다.
    결측(raw 0·65535 — HK.read 가 NaN 으로)은 **밴드가 있거나 채널의 1순위 캐비티 센서인 필드만** P2 —
    표시용 필드에는 늘 죽어 있는 열(templed4·tempcell3 등)이 있어 경보하면 상시 P2 가 된다."""
    readings = profile.hk.read(row, phase)
    issues: list = []
    worst = OK
    # 결측을 알릴 필드: 밴드가 있거나, 어느 신호 채널의 **1순위** 캐비티 압력·온도 센서(n_air·R 에 쓰임 —
    # 빠지면 다음 순위로 넘어가 값이 달라진다). 늘 죽어 있는 표시용 열은 조용히.
    primary = {keys[0] for ch in profile.signal_channels()
               for keys in (ch.pressure_keys(), ch.temp_keys()) if keys}

    for key, (val, sev) in readings.items():
        field = profile.hk.field(key)
        label = field.label or key
        if not math.isfinite(val):
            if field.warn is not None or field.alarm is not None or key in primary:
                issues.append(f"{label} missing (no reading)")
                worst = worse(worst, P2)
            continue
        if sev == SEVERITY_ALARM:
            issues.append(_fmt(label, val, field.unit) + " out of band")
            worst = worse(worst, P1)
        elif sev == SEVERITY_WARN:
            issues.append(_fmt(label, val, field.unit) + " near limit")
            worst = worse(worst, P2)

    sig_channels = profile.signal_channels() if channels is None else list(channels)
    saturated = []
    for ch in sig_channels:
        try:
            if profile.is_saturated(ch.slice(row)):
                saturated.append(ch.label or ch.id)
        except Exception:
            continue
    if saturated:
        if sig_channels and len(saturated) == len(sig_channels):
            issues.append(f"CCD saturated on all channels: {', '.join(saturated)}")
            worst = worse(worst, P0)
        else:
            issues.append(f"CCD saturated: {', '.join(saturated)}")
            worst = worse(worst, P1)

    metrics = {"n_fields": len(readings), "n_issues": len(issues),
              "saturated_channels": saturated, "readings": readings}
    if not issues:
        return OK, f"HK normal ({len(readings)} fields)", metrics
    return worst, "; ".join(issues), metrics
