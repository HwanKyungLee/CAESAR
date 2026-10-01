"""Alpha Pass 1 파싱 캐시 — raw 파일 하나의 **순수 파싱 결과**를 (파일, 채널, 픽셀범위)별 npz로.

배경: 알파 생성 시간의 대부분이 Pass 1의 'raw 전체 읽기 + 숫자 변환'이다(파일당 98 MB, 콜드 HDD에선
디스크가 병목, SSD에선 변환이 병목 — docs/HANDOFF.md 2026-09-19 §2·§5). 같은 raw로 알파를 다시
만들 때(세팅만 바꾼 재생성 — 대부분의 경우) 이 결과를 남겨 두면 raw를 아예 안 읽는다.

**무엇을 캐시하나 — 그리고 왜 여기서 끊나 (2026-10-02 재설계, SCHEMA 2)**
`core.data_io.extract_raw_file_for_parallel`의 반환값(flags·T·P·스펙트럼·행 시각) 그대로다. 이건
raw 파일 바이트와 (채널, 픽셀범위)만의 함수다. 분류(ZA/He/ambient)·퍼지 세틀링(`purge_settle_sec`)·
60 s 평균·dark·R(t)·알파식은 **전부 그 뒤**(gui/worker.py `_process_scan`·Pass 2)에서 매번 새로 계산된다.
→ 그 세팅들은 **키에 넣을 필요 자체가 없다.** 옛 설계(SCHEMA 1, 분류·평균까지 캐시)는 그 세팅을 키에
빠짐없이 넣어야 했고, 하나라도 빠지면 옛 캐시가 적중하는 위험이 있었다(HANDOFF 09-17 §4 경고).

**무효화 키**: raw(절대경로·크기·mtime_ns) · 채널 · 픽셀범위 · SCHEMA · **파서 지문**.
파서 지문 = 파싱 결과를 바꿀 수 있는 소스와 설정의 **내용 해시** — core/data_io.py · core/raw_parser.py ·
core/profile.py · 계기 프로파일 JSON 전부. 그중 하나라도 바뀌면 캐시 전체가 자동으로 무효가 된다
(사람이 SCHEMA를 올리는 걸 잊어도 옛 캐시가 적중하지 않게). 보수적이다 — data_io의 무관한 수정도 무효화.

**값 보존**: 스펙트럼은 raw 카운트(정수)라 0~65535 안이면 uint16으로 무손실 저장(아니면 float32 그대로),
나머지는 원래 dtype. 읽을 때 원래 dtype으로 되돌린다 → 캐시를 거쳐도 알파 출력 **바이트 동일**
(`tools/test_alpha_pass1_cache.py`: 끔 / 빈 캐시 / 찬 캐시 / 세팅 변경 / raw 변경 / 손상 파일).

**용량**: 전체 크기 raw(3708행) 하나에 ~15 MB(raw 98 MB의 1/6). 상한(기본 30 GB, `AUGUR_ALPHA_CACHE_GB`)을
넘으면 가장 오래 안 쓴 것부터 지운다. 위치 `cache/alpha_pass1/`(git 제외, `AUGUR_ALPHA_CACHE_DIR`로 변경).
끄기: `AUGUR_ALPHA_CACHE=0`. 캐시는 최적화일 뿐 — 읽기·쓰기 실패는 조용히 다시 파싱한다.
"""
from __future__ import annotations

import glob
import hashlib
import os

import numpy as np

SCHEMA = 2

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DIR = os.path.join(_ROOT, 'cache', 'alpha_pass1')
_DEFAULT_GB = 30.0
_FINGERPRINT = None


def cache_dir() -> str:
    return os.environ.get('AUGUR_ALPHA_CACHE_DIR') or _DEFAULT_DIR


def enabled() -> bool:
    return os.environ.get('AUGUR_ALPHA_CACHE', '1').strip() not in ('0', 'false', 'off', 'no')


def max_bytes() -> int:
    try:
        gb = float(os.environ.get('AUGUR_ALPHA_CACHE_GB', _DEFAULT_GB))
    except ValueError:
        gb = _DEFAULT_GB
    return int(max(gb, 0.0) * 1e9)


def _fingerprint_files() -> list:
    files = [os.path.join(_ROOT, 'core', n) for n in ('data_io.py', 'raw_parser.py', 'profile.py')]
    try:
        from core.profile import DEFAULT_PROFILE_DIR
        files += sorted(glob.glob(os.path.join(DEFAULT_PROFILE_DIR, '*.json')))
    except Exception:                              # noqa: BLE001 — 프로파일 폴더가 없으면 소스만
        pass
    return files


def parser_fingerprint() -> str:
    """파싱 결과를 바꿀 수 있는 소스·설정 파일 내용의 해시(프로세스당 한 번)."""
    global _FINGERPRINT
    if _FINGERPRINT is None:
        h = hashlib.sha1()
        for p in _fingerprint_files():
            h.update(os.path.basename(p).encode('utf-8'))
            try:
                with open(p, 'rb') as fh:
                    h.update(fh.read())
            except OSError:
                h.update(b'<missing>')
        _FINGERPRINT = h.hexdigest()
    return _FINGERPRINT


def cache_key(fp: str, channel, pixel_min, pixel_max) -> str:
    """무효화 키 → sha1 hex. raw가 바뀌거나(크기/mtime) 파서 코드·프로파일이 바뀌면 다른 키.
    분석 세팅(퍼지·flag·평균·dark …)은 캐시 뒤에서 계산되므로 키에 없다. 파일이 없으면 OSError."""
    st = os.stat(fp)
    parts = [os.path.abspath(fp).lower(), str(st.st_size), str(st.st_mtime_ns),
             str(int(channel)), str(int(pixel_min)), str(int(pixel_max)),
             f"s{SCHEMA}", parser_fingerprint()]
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()


def _path_for(key: str) -> str:
    return os.path.join(cache_dir(), key[:2], key + '.npz')


def has(key: str) -> bool:
    return os.path.exists(_path_for(key))


def load(key: str):
    """적중 시 (flags, Ts, Ps, specs, secs) — extract_raw_file_for_parallel 반환과 같은 dtype·모양.
    미스·손상·키 불일치면 None(호출측이 다시 파싱한다)."""
    p = _path_for(key)
    if not os.path.exists(p):
        return None
    try:
        with np.load(p, allow_pickle=False) as z:
            if str(z['key']) != key or int(z['schema']) != SCHEMA:
                return None
            flags = z['flags'].astype(np.int64, copy=False)
            Ts = z['Ts'].astype(np.float64, copy=False)
            Ps = z['Ps'].astype(np.float64, copy=False)
            specs = z['specs'].astype(np.float32)          # uint16 → float32 (정수라 정확)
            secs = z['secs'].astype(np.float64, copy=False)
        n = len(flags)
        if not (len(Ts) == len(Ps) == len(secs) == n and specs.shape[0] == n):
            return None
        try:
            os.utime(p, None)                              # LRU: 최근 사용 표시
        except OSError:
            pass
        return flags, Ts, Ps, specs, secs
    except Exception:                                      # noqa: BLE001 — 손상 → 다시 파싱
        return None


def save(key: str, flags, Ts, Ps, specs, secs) -> None:
    """원자적 저장(tmp → replace). 실패는 조용히 무시 — 다음 런이 다시 파싱한다."""
    p = _path_for(key)
    tmp = p[:-4] + '.tmp.npz'
    try:
        specs = np.asarray(specs)
        u = None
        if specs.size and np.isfinite(specs).all() and specs.min() >= 0 and specs.max() <= 65535:
            u = specs.astype(np.uint16)
            if not np.array_equal(u.astype(specs.dtype), specs):
                u = None                                   # 정수가 아니다 — float32 그대로
        os.makedirs(os.path.dirname(p), exist_ok=True)
        np.savez(tmp[:-4], key=np.array(key), schema=np.array(SCHEMA),
                 flags=np.asarray(flags), Ts=np.asarray(Ts), Ps=np.asarray(Ps),
                 specs=u if u is not None else specs.astype(np.float32), secs=np.asarray(secs))
        os.replace(tmp, p)
    except Exception:                                      # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass


def prune(limit: int | None = None) -> int:
    """상한을 넘으면 가장 오래 안 쓴(mtime) 것부터 지운다 → 지운 바이트 수."""
    limit = max_bytes() if limit is None else int(limit)
    ents = []
    for p in glob.glob(os.path.join(cache_dir(), '*', '*.npz')):
        try:
            st = os.stat(p)
            ents.append((st.st_mtime, st.st_size, p))
        except OSError:
            pass
    total = sum(s for _, s, _ in ents)
    freed = 0
    for _, s, p in sorted(ents):
        if total - freed <= limit:
            break
        try:
            os.remove(p)
            freed += s
        except OSError:
            pass
    return freed


def usage() -> tuple:
    """(파일 수, 바이트) — 상태 표시용."""
    n = b = 0
    for p in glob.glob(os.path.join(cache_dir(), '*', '*.npz')):
        try:
            b += os.path.getsize(p)
            n += 1
        except OSError:
            pass
    return n, b
