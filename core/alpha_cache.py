"""Alpha Pass1 중간산물 캐시 — raw 파싱·분류·60s평균 결과를 (파일,채널)별 npz로.

배경: 알파 생성 시간의 대부분이 'raw 전체 읽기+파싱'(Pass1)인데, 알파 계산(Pass2)이
실제로 쓰는 산출물은 파일당 ~1MB(ZA/He 스캔 + 60s 평균 ambient + T/P/시각)뿐이다.
이걸 npz로 남기면 재생성 때 해당 raw를 아예 안 읽는다(전캠페인 수 시간 → 수십 분).

캐시가 담는 건 보정 '이전' 단계까지만이다 — dark/offset/stray·R(t)·RL·Rayleigh·알파식은
전부 하류라서, 그런 세팅을 바꾼 재생성(대부분의 경우)에 캐시가 그대로 유효하다.

무효화 키(cache_key): raw 파일(절대경로·크기·mtime_ns) · 채널 · 픽셀범위 · avg_sec ·
ZA/He/amb 플래그 · SCHEMA. 분류/평균/HK 파싱 로직을 바꾸면 SCHEMA를 올려 전체 무효화할 것.

값 보존: 스펙트럼·평균 전부 float64 그대로 저장 → 캐시 경유 여부와 무관하게 알파 출력
바이트 동일(검증: scratchpad alpha_cache_verify.py — off/cold/warm == 수정 전 기준).
박사님 std_t 형식(per-bin) 경로는 60s 평균이 아니라 raw 스캔 binning이라 캐시를 안 탄다.
"""
from __future__ import annotations

import hashlib
import os

import numpy as np

SCHEMA = 1

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'cache', 'alpha_pass1')


def cache_key(fp: str, channel, pixel_min, pixel_max, avg_sec,
              flag_za, flag_he, flag_amb) -> str:
    """무효화 키 → sha1 hex. raw가 바뀌거나(크기/mtime) 분류·평균에 영향 주는
    설정이 바뀌면 다른 키 = 자동 미스. 파일이 없으면 OSError."""
    st = os.stat(fp)
    parts = [os.path.abspath(fp).lower(), str(st.st_size), str(st.st_mtime_ns),
             str(int(channel)), str(int(pixel_min)), str(int(pixel_max)),
             f"{float(avg_sec):g}",
             ','.join(str(int(x)) for x in sorted(flag_za or [])),
             ','.join(str(int(x)) for x in sorted(flag_he or [])),
             ','.join(str(int(x)) for x in sorted(flag_amb or [])),
             f"v{SCHEMA}"]
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()


def _path_for(key: str) -> str:
    return os.path.join(CACHE_DIR, key[:2], key + '.npz')


def load(key: str) -> dict | None:
    """적중 시 {이름: ndarray} dict, 미스/손상 시 None."""
    p = _path_for(key)
    if not os.path.exists(p):
        return None
    try:
        with np.load(p, allow_pickle=False) as z:
            d = {k: z[k] for k in z.files}
        if str(d.get('key')) != key:
            return None
        return d
    except Exception:
        return None


def save(key: str, **arrays) -> None:
    """원자적 저장(tmp→replace). 실패는 조용히 무시 — 캐시는 최적화일 뿐,
    없으면 다음 런이 그냥 다시 파싱한다."""
    p = _path_for(key)
    tmp = p[:-4] + '.tmp.npz'
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        np.savez(tmp[:-4], key=np.array(key), **arrays)   # savez가 .npz를 붙임
        os.replace(tmp, p)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
