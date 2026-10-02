"""핫 프로파일 날짜 가드 자체검증 (2026-10-02 리뷰, 데이터 불필요).

핫 프로파일(2026 여수 채널 정체: block 2053 = ANs 300 °C)이 열 수(6181)만 보고 **모든** 6181열 파일에
붙어서, 8/11 이후 배치(block 2053 = cold)로 측정하면 실시간 ppb·R·경보가 경고 없이 엉뚱한 셀에 붙었다.
core/raw_parser 는 같은 레이아웃에 2026-05-01~08-31 에만 ANs/PNs 이름을 붙인다.
  1) 범위 안 파일 → 핫 미션, 범위 밖 → 기본(구조) 프로파일(셀 정체 없음), 날짜 없는 파일명 → 제한 없음
  2) 프로파일의 date_range == raw_parser 6181열 레이아웃의 date_range (두 곳이 갈라지지 않게)
  3) VigilApp: 범위 밖 핫 파일은 기본 프로파일로 감시하되 P2 'No mission'(농도·R 없음)을 한 번만 남긴다
"""
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_self_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _self_dir]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PyQt6.QtCore import QCoreApplication

_n_pass = _n_fail = 0
NC = 6181


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _rows(n, t0):
    out = []
    for k in range(n):
        cs = int((t0 + k) * 100)
        v = ["0"] * NC
        v[0], v[1], v[4] = str(cs >> 16), str(cs & 0xFFFF), "1"
        v[2053:6149] = ["9000"] * 4096
        out.append("\t".join(v))
    return "\n".join(out) + "\n"


def main():
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    from core import raw_parser
    from vigil.profile import DEFAULT_PROFILE_DIR, ProfileSet
    from vigil.run_vigil import VigilApp

    ps = ProfileSet.load_default()
    hot = ps.route(filename="2026-06-20-001 Hot.dat", n_columns=NC)
    check("6월 핫 파일 → 핫 프로파일", hot is not None and "hot" in hot.profile_id, hot and hot.profile_id)
    g10 = ps.route(filename="2026-10-02-001 Hot.dat", n_columns=NC)
    check("10월 핫 파일 → 기본(구조) 프로파일", g10 is not None and not g10.is_mission
          and [c.label for c in g10.channels] == ["ch0", "ch1", "ch2"], g10 and g10.profile_id)
    check("10월: date_excluded 가 이유를 알려준다",
          ps.date_excluded("2026-10-02-001 Hot.dat", NC) == [hot.profile_id])
    check("날짜 없는 파일명은 제한 없음", ps.route(filename="synthetic Hot.dat", n_columns=NC) is not None)
    check("경계 08-31 포함 · 09-01 제외",
          ps.route(filename="2026-08-31-024 Hot.dat", n_columns=NC) is not None
          and not ps.route(filename="2026-09-01-001 Hot.dat", n_columns=NC).is_mission)

    lay, _ = raw_parser.layout_for(NC, "2026-06-20-001 Hot.dat")
    check("프로파일 date_range == raw_parser 6181열 레이아웃 date_range",
          lay is not None and tuple(hot.match.date_range) == tuple(lay.date_range),
          (hot.match.date_range, lay and lay.date_range))

    d = tempfile.mkdtemp()
    try:
        raw, st = os.path.join(d, "raw"), os.path.join(d, "state")
        os.makedirs(raw)
        f = os.path.join(raw, "2026-10-02-001 Hot.dat")
        with open(f, "w") as fh:
            fh.write(_rows(5, 23_600_000))
        core = VigilApp(raw, DEFAULT_PROFILE_DIR, st)
        core.tick()
        with open(f, "a") as fh:
            fh.write(_rows(3, 23_600_005))
        core.tick()
        recs = [json.loads(x) for x in open(os.path.join(st, "status.jsonl"), encoding="utf-8")]
        warn = [r for r in recs if r.get("msg", "").startswith("No mission")]
        check("범위 밖 핫 파일: P2 'No mission'(기본으로 감시) 한 번", len(warn) == 1 and warn[0]["status"] == "P2",
              [r.get("msg") for r in recs][-3:])
        check("internal 오류 없음", not [r for r in recs if r.get("kind") == "internal"])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\nprofile date_range tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
