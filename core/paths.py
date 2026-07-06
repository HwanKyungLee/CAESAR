"""레포 기준 경로 — 문헌 단면/파장보정처럼 레포에 번들된 입력 데이터와,
분석 산출물(재생성 가능)의 기본 저장 위치를 한곳에서 정의한다.

다른 컴퓨터로 옮겨도 그대로 동작해야 하므로 절대경로 하드코딩 대신
이 파일 위치(core/) 기준 상대경로로 계산한다.
"""
from __future__ import annotations

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REFERENCE_DIR = os.path.join(REPO_ROOT, "reference_data", "raw")
WV_CAL_DIR = os.path.join(REPO_ROOT, "reference_data", "wv_cal")
DEFAULT_OUTPUT_DIR = os.path.join(REPO_ROOT, "output")


def resolve_ref_path(path: str) -> str:
    """시나리오 JSON/채널 config에 저장된 레퍼런스·wavecal 경로를 해석한다.

    절대경로가 존재하면 그대로 쓴다(다른 폴더 배치를 쓰는 기존 시나리오 호환).
    존재하지 않으면 REPO_ROOT 기준 상대경로로 재해석을 시도한다. 그래도 없으면
    원본 문자열을 그대로 반환한다 — 호출부의 기존 os.path.exists() 가드가
    "파일 없음"으로 처리하는 동작은 그대로 유지된다.
    """
    if not path:
        return path
    if os.path.isabs(path) and os.path.exists(path):
        return path
    candidate = os.path.join(REPO_ROOT, path)
    return candidate if os.path.exists(candidate) else path
