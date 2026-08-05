"""I0(t)/R(t) 보간축 인덱스→실시각 전환의 실효과 데모 (2026-08-05).

배경
----
AlphaExportWorker의 I0(t)·자체 R(t) PCHIP 보간은 원래 global scan index를
x축으로 썼다(gui/worker.py). 정상 운영 중엔 스캔 간격이 거의 균일(~0.97초)해
인덱스가 시간의 좋은 대리(proxy)였지만, **파일 유실·장비 정지**가 있으면
스캔 카운트와 실제 경과시간이 어긋난다. core.step_guard.resolve_time_axis()
도입 후 실측 bytepack 초(sec)가 전부 유효하면 그걸 축으로 쓰도록 바뀌었다
(sec 결측 시엔 기존 인덱스로 안전 폴백 — 무회귀).

이 스크립트는 실제 raw 데이터 없이, 인덱스와 실시각이 크게 갈라지는 합성
시나리오(ZA #1과 ZA #2 사이에 3시간짜리 장비 정지가 있었지만 스캔 카운트는
안 늘어난 경우)를 만들어 두 축의 I0 보간값이 실제로 다른 답을 낸다는 것을
수치로 보여준다. (본 worker.py 로직 자체는 QThread 클로저 내부라 직접
호출은 어려우므로, 여기서는 동일한 알고리즘 — resolve_time_axis +
SegmentedPchip — 을 직접 재현한다.)

사용: python diagnostics/i0_time_axis_fix/demo_index_vs_time.py
"""
import io
import os
import sys

import numpy as np

# Windows CP949 콘솔에서 이모지/한글 깨짐 방지 (tools/r_trend_monitor.py와 동일 패턴)
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.step_guard import resolve_time_axis, SegmentedPchip


def main():
    # ── 시나리오: ZA 3회 주입, 2번째와 3번째 사이에 3시간 장비 정지 ──────────
    # 스캔 인덱스는 정지 중에도 늘지 않는다(장비가 멈췄으니 스캔 자체가 없음) —
    # 반면 실시각은 정지 시간만큼 그대로 3시간이 흐른다. 이게 핵심 괴리다.
    za_gidx = np.array([0.0, 100.0, 130.0])            # 스캔 카운트: 균일해 보임
    za_sec = np.array([0.0, 97.0, 97.0 + 30 * 0.97 + 3 * 3600.0])  # 실측 초: 3h 갭
    # I0(램프 밝기 대리) — 정지 후 캐비티/램프 상태가 서서히 변했다고 가정
    i0_val = np.array([1.0, 1.0, 0.7])   # 임의 단위, 감쇠 예시

    # 문제의 ambient 스캔: ZA#2 직후(인덱스로는 ZA#2에 훨씬 가깝다)지만,
    # 실제로는 장비 정지 '이후'(ZA#3 쪽)에 찍힌 스캔이라고 하자.
    amb_gidx = 105.0                      # 인덱스상 ZA#2(idx=100)에 훨씬 가까움
    amb_sec = 97.0 + 3 * 3600.0 + 60.0    # 실측 시각은 정지 '끝난 직후'(ZA#3 근처)

    x_idx, is_rt = resolve_time_axis(za_gidx, np.full_like(za_gidx, np.nan))
    assert not is_rt, "sec 결측 시나리오에서는 인덱스로 폴백해야 함"
    pchip_idx = SegmentedPchip(x_idx, i0_val)
    i0_via_index = pchip_idx(amb_gidx)

    x_sec, is_rt2 = resolve_time_axis(za_gidx, za_sec)
    assert is_rt2, "sec 전부 유효하면 실시각을 써야 함"
    pchip_sec = SegmentedPchip(x_sec, i0_val)
    i0_via_time = pchip_sec(amb_sec)

    print("=" * 70)
    print("I0(t) 보간: 인덱스축 vs 실시각축 — 장비정지(3h) 시나리오")
    print("=" * 70)
    print(f"ZA gidx : {za_gidx}")
    print(f"ZA sec  : {za_sec}  (2→3 사이 3h 정지)")
    print(f"ambient : gidx={amb_gidx}  sec={amb_sec:.1f}")
    print()
    print(f"인덱스축 보간 I0  = {i0_via_index:.4f}  "
          f"(ZA#2 쪽에 붙어 있다고 착각 — 정지 직전 값에 가깝게 나옴)")
    print(f"실시각축 보간 I0  = {i0_via_time:.4f}  "
          f"(실제로 정지 '이후' 시점이라 ZA#3 값에 가깝게 나옴 — 물리적으로 맞음)")
    diff = abs(i0_via_time - i0_via_index)
    print(f"\n차이: {diff:.4f} ({diff / i0_via_index * 100:.1f}%) "
          f"— 이만큼이 정지 구간을 포함한 캠페인 데이터에서 조용히 섞여 있었을 오차")

    assert diff > 0.05, "시나리오가 두 축을 실제로 갈라놓지 못함 — 데모 실패"
    print("\n✅ 데모 통과: 실시각 축이 인덱스 축과 실제로 다른(더 정확한) 답을 낸다.")

    # ── 결측(sec 일부 NaN) 시 안전 폴백 확인 — 무회귀 보장 ──────────────────
    za_sec_partial = za_sec.copy(); za_sec_partial[1] = np.nan
    x_fb, is_rt3 = resolve_time_axis(za_gidx, za_sec_partial)
    assert not is_rt3 and np.array_equal(x_fb, za_gidx), \
        "sec 일부 결측이면 인덱스로 안전 폴백해야 함(두 축을 섞으면 PCHIP 단조성 깨짐)"
    print("✅ 폴백 확인: sec 일부 결측 시 인덱스 축으로 안전하게 되돌아간다(무회귀).")


if __name__ == "__main__":
    main()
