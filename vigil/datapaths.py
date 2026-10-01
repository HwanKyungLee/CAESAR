"""vigil/datapaths.py — 다른 PC 에서도 Augur 산출물(FitSet·파장보정·레퍼런스)을 찾게 (2026-10-01).

프로파일과 그것이 가리키는 FitSet JSON 안의 경로는 만든 PC 의 절대경로다
(`C:/Doasis_Work/Output/fit setting/FitSet_….json`, FitSet 안의 `wl_path`·`refs[].path`).
다른 PC 에선 그대로 열 수 없어 농도·R 감시기가 '초기화 실패'로 떴다.

규칙(가볍게, 추측하지 않는다):
  1. 경로가 그대로 있으면 그대로 쓴다 — 만든 PC 에선 동작이 바뀌지 않는다.
  2. 없으면, 사용자가 대시보드에서 정한 **Augur 데이터 폴더**(그 PC 의 `Output` 에 해당) 아래에서
     원래 경로의 **꼬리**를 긴 것부터 붙여 본다:
        C:/Doasis_Work/Output/fit setting/X.json  →  <root>/Output/fit setting/X.json, <root>/fit setting/X.json, …
     처음으로 존재하는 것을 쓴다. 파일 이름만으로 아무 데서나 찾지는 않는다(엉뚱한 같은 이름 파일 방지 —
     최소 꼬리는 `폴더/파일`).
  3. 그래도 없으면 원래 경로를 돌려준다(호출부가 '파일 없음'으로 보고 — 조용히 대체하지 않음).
"""
from __future__ import annotations

import os
import re


def rebase(path, data_root):
    if not path:
        return path
    if os.path.exists(path) or not data_root:
        return path
    parts = [p for p in re.split(r"[\\/]+", str(path)) if p]
    if parts and re.fullmatch(r"[A-Za-z]:", parts[0]):
        parts = parts[1:]                         # 드라이브 문자는 꼬리에서 뺀다
    for k in range(0, max(0, len(parts) - 1)):    # 긴 꼬리부터, 최소 '폴더/파일'
        cand = os.path.join(data_root, *parts[k:])
        if os.path.exists(cand):
            return cand
    return path


def rebase_fitset_channel(ch: dict, data_root) -> dict:
    """FitSet 채널 dict 의 wl_path·refs[].path 를 rebase 한 사본(원본은 안 건드린다)."""
    out = dict(ch)
    if out.get("wl_path"):
        out["wl_path"] = rebase(out["wl_path"], data_root)
    refs = out.get("refs")
    if isinstance(refs, list):
        out["refs"] = [dict(r, path=rebase(r.get("path"), data_root)) if isinstance(r, dict) else r
                       for r in refs]
    return out
