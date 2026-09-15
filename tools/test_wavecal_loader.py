"""파장축 파서 회귀 — `DataIO.load_wavecal_array`가 단일 출처인지 지킨다.

왜: 파장축은 모든 숫자의 x축인데 같은 파서가 4벌 복제돼 있었다(gui 2 + core.refit +
tools.optimize_params). 2026-09 대조에서 셋 다 같은 답을 내는 것을 확인하고 하나로 합쳤다.
이 테스트는 **합친 하나가 계속 옳은지**를 본다: 저장소의 실측 Calib 파일 전부에 대해
pandas 경로(`load_wavecal_array`)와 `np.loadtxt`가 같은 배열을 내야 한다.

`python tools/test_wavecal_loader.py`로 단독 실행 가능.
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.data_io import DataIO  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _calib_files():
    return sorted(glob.glob(os.path.join(_ROOT, "reference_data", "wv_cal", "**", "Calib_*.txt"),
                            recursive=True))


def test_matches_loadtxt():
    """실측 Calib 파일: pandas 파서 == np.loadtxt (주석 헤더 有/無 모두)."""
    files = _calib_files()
    assert files, "reference_data/wv_cal에 Calib_*.txt가 하나도 없다 — 경로가 바뀌었나?"
    headered = False
    for f in files:
        wl = DataIO.load_wavecal_array(f)
        assert wl is not None, f"파싱 실패: {f}"
        ref = np.loadtxt(f)                      # np.loadtxt는 기본이 comments='#'
        assert ref.ndim == 1, f"열이 2개 이상인 wavecal 등장 — 첫 열/마지막 열 규약 재검토 필요: {f}"
        assert np.array_equal(np.asarray(wl, float), ref), f"파서 불일치: {f}"
        assert np.all(np.diff(wl) > 0), f"파장축이 단조증가가 아니다: {f}"
        assert 200.0 < wl[0] < 1100.0, f"nm 범위 밖(픽셀 인덱스를 읽은 것 아닌가?): {f} → {wl[0]}"
        with open(f, encoding="utf-8", errors="replace") as fh:
            headered |= fh.read(1) == "#"
    assert headered, "주석 헤더가 있는 Calib 파일이 표본에 없다 — comment='#' 경로가 안 덮인다"


def test_rejects_non_wavecal():
    """같은 폴더의 FWHM_Analysis_*.txt 같은 건 배열이 아니라 None이어야 한다."""
    others = glob.glob(os.path.join(_ROOT, "reference_data", "wv_cal", "**", "FWHM_Analysis_*.txt"),
                       recursive=True)
    for f in others:
        assert DataIO.load_wavecal_array(f) is None, f"wavecal이 아닌 파일을 파장축으로 받았다: {f}"


if __name__ == "__main__":
    test_matches_loadtxt()
    test_rejects_non_wavecal()
    print(f"OK: {len(_calib_files())} calib files verified")
