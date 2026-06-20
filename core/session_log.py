"""세션 로그: stdout/stderr를 logs/session_*.log 로 tee한다.

기존 print() 진단 출력([R-CAL]/[ParallelFit]/[AlphaExport] 등)을 콘솔에 그대로
보여주면서 동시에 타임스탬프 파일로 남긴다. 밤샘 런이 죽었을 때 crash.log(하드
크래시)와 함께 "그 직전 무슨 일이 있었나"를 사후 추적할 수 있다. 기존 print 호출은
하나도 안 고친다(콘솔 리다이렉트만).

오래된 로그는 자동 정리(기본 최근 30개 유지)한다.
"""
from __future__ import annotations

import datetime as _dt
import glob
import os
import sys

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')


class _Tee:
    """원본 스트림과 로그 파일에 동시에 쓰는 얇은 래퍼.

    pythonw 등으로 콘솔이 없으면 원본 스트림이 None일 수 있으므로 그 경우엔
    파일에만 쓴다. 각 write 후 flush 해 크래시 직전 줄도 디스크에 남긴다.
    """

    def __init__(self, original, fh):
        self._original = original
        self._fh = fh

    def write(self, text):
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass
        try:
            self._fh.write(text)
            self._fh.flush()
        except Exception:
            pass

    def flush(self):
        for s in (self._original, self._fh):
            try:
                if s is not None:
                    s.flush()
            except Exception:
                pass

    def isatty(self):
        return bool(self._original is not None and getattr(self._original, 'isatty', lambda: False)())


def _prune(keep: int) -> None:
    try:
        logs = sorted(glob.glob(os.path.join(_LOG_DIR, 'session_*.log')))
        for old in logs[:-keep]:
            os.remove(old)
    except Exception:
        pass


def install(keep: int = 30) -> str | None:
    """세션 tee를 설치하고 로그 파일 경로를 반환한다(실패 시 None)."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        path = os.path.join(_LOG_DIR, f"session_{_dt.datetime.now():%Y%m%d_%H%M%S}.log")
        fh = open(path, 'a', encoding='utf-8')
        fh.write(f"===== 세션 시작 {_dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        fh.flush()
        sys.stdout = _Tee(sys.stdout, fh)
        sys.stderr = _Tee(sys.stderr, fh)
        _prune(keep)
        return path
    except Exception:
        return None
