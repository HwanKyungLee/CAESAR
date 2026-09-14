"""레포 기준 경로 — 문헌 단면/파장보정처럼 레포에 번들된 입력 데이터와,
분석 산출물(재생성 가능)의 기본 저장 위치를 한곳에서 정의한다.

다른 컴퓨터로 옮겨도 그대로 동작해야 하므로 절대경로 하드코딩 대신
이 파일 위치(core/) 기준 상대경로로 계산한다.
"""
from __future__ import annotations

import os
import re

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


# ── 산출물 배치 (A3) ─────────────────────────────────────────────────────────
# 디렉터리는 **시간축만** 인코딩한다: campaign / 날짜 / 산출물종류.
# 창·poly·Neg·QC·refs 같은 '다른 순서로도 물어보게 되는' 패싯은 폴더가 아니라
# `.meta.json`에 있다(core/run_meta.py). 폴더로 패싯을 나누면 그 순서로만 탐색
# 가능해진다 — 옛 `{창}/{날짜}/{neg}/{QC}/` 4단이 그래서 답답했다.
#
#   output/{campaign}/{YYYY-MM-DD}/{fitting|alpha|R|figures}/
#   output/{campaign}/calibration/    wavecal · ILS · dark · offset
#   output/{campaign}/_autosave/      진행 중(정식 저장 성공 시 제거)
#   output/{campaign}/_archive/       밀려난 것 (절대 삭제 안 함)
#   output/{campaign}/_export/        사람에게 건네는 병합본

KINDS = ("fitting", "alpha", "R", "figures")
DEFAULT_CAMPAIGN = "default"


def safe_token(text, fallback="") -> str:
    """파일·폴더 이름 조각 → 영숫자와 `_`, `-`만. 빈 결과면 fallback.

    옛 파일명의 `[ ] ~ °`는 셸 글롭·엑셀 참조·백업 도구에서 깨진다.
    """
    token = re.sub(r"[^0-9A-Za-z_-]+", "_", str(text or "").strip()).strip("_-")
    return token or fallback


def campaign_dir(base: str, campaign=None) -> str:
    """`{base}/{campaign}`. campaign이 비면 DEFAULT_CAMPAIGN."""
    return os.path.join(base, safe_token(campaign, DEFAULT_CAMPAIGN))


def day_dir(base: str, campaign, day: str, kind: str = "fitting") -> str:
    """`{base}/{campaign}/{YYYY-MM-DD}/{kind}`.

    `day`는 'YYYY-MM-DD' 또는 'YYMMDD' 둘 다 받는다(호출부가 이미 YYMMDD를 쓴다).
    """
    return os.path.join(campaign_dir(base, campaign), iso_day(day),
                        safe_token(kind, "fitting"))


def special_dir(base: str, campaign, name: str) -> str:
    """`_autosave` · `_archive` · `_export` · `calibration` 처럼 날짜 밖에 사는 폴더."""
    return os.path.join(campaign_dir(base, campaign), name)


def iso_day(day: str) -> str:
    """'260904' → '2026-09-04'. 이미 ISO면 그대로. 못 읽으면 원문(폴더가 생기긴 해야 함)."""
    s = str(day or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{6}", s):
        return f"20{s[:2]}-{s[2:4]}-{s[4:6]}"
    return s or "unknown-date"


def short_day(day: str) -> str:
    """'2026-09-04' → '260904' (파일명 프리픽스용)."""
    s = str(day or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s[2:4] + s[5:7] + s[8:10]
    return s


def out_name(day, channel=None, label=None, runid=None, ext=".dat") -> str:
    """`260904_CH1_PNs_r3f8a1.dat` — 특수문자 없음.

    설정 태그(`px774-1550_Poly4_Sh[-1,1]_gT25`) 대신 runid 6자를 쓴다. 사람이 읽는
    설정은 `.meta.json`과 `.dat` 헤더에 있고, 앱이 diff로 보여준다.
    """
    parts = [short_day(day)]
    if channel is not None:
        parts.append(f"CH{int(channel)}")
    if label:
        parts.append(safe_token(label))
    if runid:
        parts.append(safe_token(runid))
    return "_".join(p for p in parts if p) + ext


def out_path(base: str, campaign, day, *, kind="fitting", channel=None,
             label=None, runid=None, ext=".dat") -> str:
    """전체 경로 한 방에. 폴더는 만들지 않는다(호출부가 makedirs)."""
    return os.path.join(day_dir(base, campaign, day, kind),
                        out_name(day, channel, label, runid, ext))
