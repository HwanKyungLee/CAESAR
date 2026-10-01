"""순차 핏(`_run`)과 Fast 청크 핏(`_fit_alpha_range`)이 같은 입력에 같은 결과를 내는지 — 합성, 데이터 비의존.

2026-10-01 까지 두 경로가 핏 본체(~150줄)를 복사해 들고 있었고, etalon OFF 버그가 두 곳에 똑같이
들어갔었다(187e26a). 지금은 둘 다 `AnalysisWorker._fit_spectrum` 하나를 부른다. 이 테스트는 그
공유가 깨지거나(누가 한쪽에 다시 사본을 만들거나) 한쪽 호출 인자만 바뀌는 회귀를 잡는다.

지키는 것: 같은 알파 스캔 40개(잡음·크기를 바꿔 shift 가 실제로 움직이게)를 두 경로에 넣으면
  1. 청크 결과의 모든 키가 순차 결과에 있고, **값이 비트 단위로 같고, 키 순서도 같다**
     (순차에만 있는 열 — '{gas}_Smooth'(칼만) · 'MaskedPixels' · 'InputMode' — 은 빼고 비교)
  2. shift 궤적(다음 스캔으로 물려주는 값)이 같다
etalon ON/OFF 두 설정 모두.
"""
import io
import contextlib
import os
import sys

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QCoreApplication

_APP = QCoreApplication.instance() or QCoreApplication([])

from gui import worker as W
from tools.test_varpro_jacobian import POLY_ORDER, make_engine, ref_props, synth_scan

SEQ_ONLY = ("MaskedPixels", "InputMode")
N_SCANS = 40

_n_pass = _n_fail = 0


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def _norm(v):
    """비트 단위 비교용 정규화 — NaN 도 같으면 같다고 본다."""
    if isinstance(v, (float, np.floating)):
        return ("f", float(v).hex())
    if isinstance(v, np.ndarray):
        return ("a", v.dtype.str, v.shape, v.tobytes())
    if isinstance(v, dict):
        return ("d", [(k, _norm(x)) for k, x in v.items()])
    if isinstance(v, (list, tuple)):
        return ("l", [_norm(x) for x in v])
    return ("o", repr(v))


def _scans(eng):
    rng = np.random.default_rng(20261001)
    base = synth_scan(eng) * 1e-6                     # 알파 크기(워커가 스케일을 되돌린다)
    return [base * (1.0 + 0.05 * np.sin(k / 5.0)) + rng.normal(0, 2e-10, base.size)
            for k in range(N_SCANS)]


def _worker(eng, ys, use_etalon):
    p0 = [0.0, 1.0] + [0.1] * len(eng.gas_list) + [0.0] * (POLY_ORDER + 1)
    w = W.AnalysisWorker(eng, [("synthetic.dat", k) for k in range(len(ys))], 0, len(ys[0]) - 1,
                         p0, None, -1, ref_properties=ref_props(eng.gas_list))
    w.allow_negative_gas = True
    w.use_etalon = use_etalon
    w.is_running = True
    w._alpha_input_cache = {"synthetic.dat": True}    # 알파 입력으로 판정(파일 형식 검사 대신)
    return w


def main():
    eng = make_engine()
    ys = _scans(eng)
    wave = np.arange(len(ys[0]), dtype=float)
    old = (W.DataIO.parse_alpha_row_time, W.DataIO.load_alpha_trace_row_full)
    W.DataIO.parse_alpha_row_time = staticmethod(lambda *a: None)
    W.DataIO.load_alpha_trace_row_full = staticmethod(lambda fp, row: (wave, ys[row].copy(), 25.0, 1013.0))
    try:
        for use_etalon in (True, False):
            tag = f"etalon={'ON' if use_etalon else 'OFF'}"
            print(f"[{tag}]")
            seq = []
            w = _worker(eng, ys, use_etalon)
            w.result_ready.connect(lambda r, i, seq=seq: seq.append((i, r)))
            with contextlib.redirect_stdout(io.StringIO()):
                w._run()
            w2 = _worker(eng, ys, use_etalon)
            with contextlib.redirect_stdout(io.StringIO()):
                chunk, traj, _ef = w2._fit_alpha_range(
                    [(k, "synthetic.dat", k) for k in range(len(ys))], 0)

            fitted = [r for _, r in seq if "Chi2" in r]
            check(f"{tag}: 순차 {len(fitted)}/{N_SCANS} 핏", len(fitted) == N_SCANS,
                  str([r.get("Status") for _, r in seq][:3]))
            shifts = [r.get("Shift") for r in fitted]
            check(f"{tag}: shift 가 실제로 움직였다(경로 차이가 드러날 수 있는 입력)",
                  len({round(float(s), 6) for s in shifts}) > 5, str(shifts[:5]))
            check(f"{tag}: 결과 개수 같음", len(chunk) == len(seq), f"{len(chunk)} vs {len(seq)}")

            bad = []
            for (ia, a), (ib, b) in zip(seq, chunk):
                common_a = [(k, _norm(v)) for k, v in a.items()
                            if k not in SEQ_ONLY and not k.endswith("_Smooth")]
                common_b = [(k, _norm(v)) for k, v in b.items()]
                if ia != ib or common_a != common_b:
                    da, db = dict(common_a), dict(common_b)
                    bad.append((ia, sorted(k for k in set(da) | set(db) if da.get(k) != db.get(k))[:6]))
            check(f"{tag}: 청크 결과 = 순차 결과(공통 열, 값·키 순서 비트 동일)", not bad, str(bad[:3]))
            seq_traj = [r["Shift"] for r in fitted]
            check(f"{tag}: shift 궤적 같음", [_norm(x) for x in traj] == [_norm(x) for x in seq_traj])
    finally:
        W.DataIO.parse_alpha_row_time, W.DataIO.load_alpha_trace_row_full = (
            staticmethod(old[0]), staticmethod(old[1]))

    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)


if __name__ == "__main__":
    main()
