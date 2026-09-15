"""CCD 포화 감지 회귀 — `raw_parser.count_saturated` 와 문턱의 단일 출처를 지킨다.

왜: Oculus 는 `profile.is_saturated`(adc_max 64000)로 포화를 잡는데 **Augur 본
파이프라인엔 검사가 아예 없었다** — 65535 스펙트럼이 경고 없이 α·피팅에 들어갔고
인젝션 실험에서 사람이 수동 체크리스트로 잡았다(보고서 §4-G).

실측 유병률(2026-09-16, 여수 24파일×매7행)이 처방을 정했다:
  ambient(flag=1)  콜드 0.00 % · 핫 0.00 %
  He(flag510)      콜드 3.45 % · 핫 21.43 %   <- 위험은 여기다
ZA/He 는 거울반사도 R 의 입력이고 R 은 이후 모든 ambient α 에 곱해진다.

`python tools/test_saturation.py` 로 단독 실행 가능.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.raw_parser import SATURATION_ADC_MAX, count_saturated  # noqa: E402


def test_counts_only_above_threshold():
    """문턱 초과만 센다 — 경계값(== 문턱)은 포화가 아니다."""
    spec = np.array([100.0, SATURATION_ADC_MAX, SATURATION_ADC_MAX + 1, 65535.0])
    assert count_saturated(spec) == 2, count_saturated(spec)
    assert count_saturated(np.full(2048, 40000.0)) == 0
    assert count_saturated(np.full(2048, 65535.0)) == 2048


def test_nan_is_not_saturation():
    """NaN(파싱 실패·결측)은 포화가 아니다 — 두 고장을 섞으면 진단이 무의미해진다."""
    spec = np.array([np.nan, np.inf, -np.inf, 65535.0])
    assert count_saturated(spec) == 1


def test_threshold_matches_oculus_profiles():
    """문턱이 Oculus 프로파일의 `saturation.adc_max` 와 갈리지 않는지.

    두 프로그램이 같은 계기의 같은 현상을 다른 숫자로 판정하면, 어느 쪽 경보를
    믿어야 하는지 아무도 모르게 된다(원칙 3).
    """
    import glob
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profs = glob.glob(os.path.join(root, "oculus", "profiles", "caesar_*.example.json"))
    assert profs, "oculus 프로파일 예제를 못 찾았다 — 경로가 바뀌었나?"
    seen = []
    for p in profs:
        with open(p, encoding="utf-8") as fh:
            v = json.load(fh).get("saturation", {}).get("adc_max")
        if v is not None:
            seen.append((os.path.basename(p), float(v)))
    assert seen, "프로파일에 saturation.adc_max 가 하나도 없다"
    bad = [(n, v) for n, v in seen if v != SATURATION_ADC_MAX]
    assert not bad, f"문턱 불일치: raw_parser={SATURATION_ADC_MAX} vs {bad}"


def test_empty_and_scalar_safe():
    assert count_saturated([]) == 0
    assert count_saturated([65535.0]) == 1


if __name__ == "__main__":
    test_counts_only_above_threshold()
    test_nan_is_not_saturation()
    test_threshold_matches_oculus_profiles()
    test_empty_and_scalar_safe()
    print(f"OK: saturation threshold {SATURATION_ADC_MAX:.0f} ADC verified")
