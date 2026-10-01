"""블록 기준 이름 + 캠페인 레이아웃 라벨(2026-10-01) — 합성, 데이터 비의존.

레거시 R 경로가 블록 2053 을 'Hot PNs', 4101 을 'Hot ANs' 로 **하드코딩**해 여수 판정
(docs/채널정체_판정_2026-09-27.md: 2053 = ANs)과 반대였다. 어느 블록이 어느 셀인지는 캠페인·배치마다
바뀌므로 코드에 박지 않는다:
  · 파일·폴더 이름 = 블록 번호(Hot_blk2053) — 캠페인이 바뀌어도 틀리지 않는다
  · 화면 라벨 = core.raw_parser.block_label — 등록 레이아웃·날짜 범위가 아는 셀이면 그 이름
지키는 것:
1. block_label: 여수 기간 핫 → ANs/PNs, **같은 6181열이라도 기간 밖이면 이름을 주장하지 않음**,
   콜드 → NO2, 파일 없음 → 블록 번호만
2. R 곡선 폴더 후보: 새 이름 먼저, 2026-10-01 전 이름(R_Hot_PNs = 블록 2053)도 — 옛 결과가 계속 열린다
3. 레거시 키(hot_pns/hot_ans) 별칭이 같은 블록을 가리킨다(창·프리셋)
4. 명령줄 r_trend_monitor.main 이 합성 핫 폴더에서 끝까지 돌고 라벨을 레이아웃에서 붙인다
"""
import io
import contextlib
import os
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "tools")]

from core.raw_parser import block_channel_name, block_label

_n_pass = _n_fail = 0


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def _write_raw(path, ncols, n=5):
    with open(path, "w") as fh:
        for i in range(n):
            row = [0.0] * ncols
            row[0], row[1], row[4] = 183, 1000 + i * 100, 1
            fh.write("\t".join(str(v) for v in row) + "\n")


def main():
    with tempfile.TemporaryDirectory() as d:
        hot_in = os.path.join(d, "2026-05-20-007.dat"); _write_raw(hot_in, 6181)
        hot_out = os.path.join(d, "2026-09-27-001.dat"); _write_raw(hot_out, 6181)
        cold = os.path.join(d, "2026-05-20-008.dat"); _write_raw(cold, 6179)

        print("[1] block_label — 이름은 캠페인 레이아웃·날짜 범위가 정한다")
        with contextlib.redirect_stderr(io.StringIO()):
            check("여수 기간 핫 2053 → ANs", block_label(hot_in, 2053, "Hot") == "Hot ANs (block 2053)",
                  block_label(hot_in, 2053, "Hot"))
            check("여수 기간 핫 4101 → PNs", block_channel_name(hot_in, 4101) == "PNs")
            check("같은 6181열, 기간 밖(9/27) → 이름 주장 안 함",
                  block_label(hot_out, 2053) == "block 2053", block_label(hot_out, 2053))
            check("콜드 2053 → NO2", block_channel_name(cold, 2053) == "NO2")
            check("파일 없음 → 블록 번호만", block_label(os.path.join(d, "x.dat"), 4101) == "block 4101")
            check("경로 None → 블록 번호만", block_label(None, 2053, "Hot") == "Hot block 2053")

        print("[2] R 곡선 폴더 후보 — 새 이름 우선, 옛 이름도")
        import r_trend_monitor as rtm
        check("블록 2053: 새→옛", rtm.r_subdir_candidates("hot_blk2053") == ["R_Hot_blk2053", "R_Hot_PNs"])
        check("블록 4101: 새→옛", rtm.r_subdir_candidates("hot_blk4101") == ["R_Hot_blk4101", "R_Hot_ANs"])
        check("레거시 키 hot_pns = 블록 2053", rtm.r_subdir_candidates("hot_pns") == rtm.r_subdir_candidates("hot_blk2053"))
        check("GUI 라벨 'Hot blk2053' 도 같은 후보", rtm.r_subdir_candidates("Hot blk2053") == rtm.r_subdir_candidates("hot_blk2053"))
        check("모르는 키 → R_{key}", rtm.r_subdir_candidates("CH1") == ["R_CH1"])
        # 옛 결과만 있는 폴더에서 GUI 와 같은 규칙으로 찾으면 옛 폴더가 잡힌다
        old = os.path.join(d, "out", "R_Hot_PNs", "2026-05-20"); os.makedirs(old)
        open(os.path.join(old, "2026-05-20-007_R.dat"), "w").close()
        cands = [os.path.join(d, "out", sd, "2026-05-20", "2026-05-20-007_R.dat")
                 for sd in rtm.r_subdir_candidates("Hot blk2053")]
        check("옛 R_Hot_PNs 결과를 찾는다", next((c for c in cands if os.path.exists(c)), None) == cands[1])

        print("[3] 레거시 키 별칭 — 창·프리셋이 같은 블록")
        check("창 hot_pns = hot_blk2053", rtm.CH_FIT_WINDOW_NM["hot_pns"] == rtm.CH_FIT_WINDOW_NM["hot_blk2053"])
        check("창 hot_ans = hot_blk4101", rtm.CH_FIT_WINDOW_NM["hot_ans"] == rtm.CH_FIT_WINDOW_NM["hot_blk4101"])
        import rt_precompute as rtp
        pre = rtp._campaign_presets()
        check("프리셋 hot_pns 는 블록 2053", pre["hot_pns"] is pre["hot_blk2053"]
              and pre["hot_blk2053"].spec_start == 2053)
        check("프리셋 hot_ans 는 블록 4101", pre["hot_ans"] is pre["hot_blk4101"]
              and pre["hot_blk4101"].spec_start == 4101)

        print("[4] 명령줄 main — 합성 핫 폴더에서 끝까지, 라벨은 레이아웃에서")
        hot_dir = os.path.join(d, "hot"); os.makedirs(hot_dir)
        _write_raw(os.path.join(hot_dir, "2026-05-20-001.dat"), 6181, n=8)
        saved = {k: getattr(rtm, k) for k in ("COLD_DIR", "HOT_DIR", "COLD_FILES", "HOT_FILES",
                                               "OUTPUT_DIR", "SHOW_PLOT", "WAVE_CAL_COLD",
                                               "WAVE_CAL_HOT", "WAVE_CAL_HOT_ANS")}
        try:
            rtm.COLD_DIR, rtm.COLD_FILES = os.path.join(d, "nocold"), None
            rtm.HOT_DIR, rtm.HOT_FILES = hot_dir, None
            rtm.OUTPUT_DIR, rtm.SHOW_PLOT = os.path.join(d, "rout"), False
            rtm.WAVE_CAL_COLD = rtm.WAVE_CAL_HOT = rtm.WAVE_CAL_HOT_ANS = os.path.join(d, "none.txt")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                out = rtm.main()
            log = buf.getvalue()
            check("main 이 4개 값을 돌려준다(GUI data_ready 순서)", isinstance(out, tuple) and len(out) == 4)
            check("라벨에 레이아웃 셀 이름", "Hot ANs (block 2053)" in log and "Hot PNs (block 4101)" in log,
                  log[-400:])
            check("옛 하드코딩 라벨 없음", "Hot PNs (roi1)" not in log and "Hot ANs (roi2)" not in log)
        finally:
            for k, v in saved.items():
                setattr(rtm, k, v)

    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)


if __name__ == "__main__":
    main()
