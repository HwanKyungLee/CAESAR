"""oculus/monitors/hk_monitor.py — HK(Housekeeping) 밴드 헬스 (설계문서 §1.3, M1).

프로파일의 HK 지도가 물리 환산·밴드판정을 이미 갖고 있다(`profile.HK.read()`) —
이 모듈은 그 결과를 Oculus의 P0/P1/P2 어휘(§5)로 옮기고, CCD 포화를 더한다.
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

from oculus.alert_engine import OK, P0, P1, P2, worse
from oculus.profile import Profile, SEVERITY_ALARM, SEVERITY_WARN


def _fmt(label: str, val: float, unit: Optional[str]) -> str:
    u = f" {unit}" if unit else ""
    return f"{label}={val:.2f}{u}"


def evaluate_hk(profile: Profile, row, phase: Optional[str] = None):
    """한 행의 HK 블록 + 신호채널 포화를 평가 → (status, msg, metrics).

    status: OK | P2(주의) | P1(밴드이탈/부분포화) | P0(전채널포화).
    `phase`(그 행의 flag role)를 넘겨야 교정구간 오경보를 피한다(HKField.applies_to)."""
    readings = profile.hk.read(row, phase)
    issues: list = []
    worst = OK

    for key, (val, sev) in readings.items():
        field = profile.hk.field(key)
        label = field.label or key
        if not math.isfinite(val):
            issues.append(f"{label} 결측(NaN)")
            worst = worse(worst, P2)
            continue
        if sev == SEVERITY_ALARM:
            issues.append(_fmt(label, val, field.unit) + " 밴드이탈")
            worst = worse(worst, P1)
        elif sev == SEVERITY_WARN:
            issues.append(_fmt(label, val, field.unit) + " 경계")
            worst = worse(worst, P2)

    sig_channels = profile.signal_channels()
    saturated = []
    for ch in sig_channels:
        try:
            if profile.is_saturated(ch.slice(row)):
                saturated.append(ch.label or ch.id)
        except Exception:
            continue
    if saturated:
        if sig_channels and len(saturated) == len(sig_channels):
            issues.append(f"전 채널 CCD 포화: {', '.join(saturated)}")
            worst = worse(worst, P0)
        else:
            issues.append(f"CCD 포화: {', '.join(saturated)}")
            worst = worse(worst, P1)

    metrics = {"n_fields": len(readings), "n_issues": len(issues),
              "saturated_channels": saturated}
    if not issues:
        return OK, f"HK 정상 ({len(readings)}개 필드)", metrics
    return worst, "; ".join(issues), metrics
