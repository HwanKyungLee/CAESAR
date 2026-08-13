"""tools/test_raw_parser.py — core/raw_parser.py 레이아웃 감지 단위테스트.

커버:
  1) 등록된 레이아웃(ncols=6179 cold / 6181 hot)은 이전과 동일하게 판정됨(회귀)
  2) 미등록 ncols → 구조적 폴백(spec_blocks_for_ncols)이 채널 블록을 추론하고
     hk_map은 비워둠(추측 안 함)
  3) spec_blocks_for_ncols 경계값(META_COLS 미만 등)

사용: python tools/test_raw_parser.py → 전부 PASS면 exit 0
"""
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.raw_parser import (RawParser, ColdHKMap, HotHKMap, SPEC_PRIMARY,
                             SPEC_SECONDARY, META_COLS, spec_blocks_for_ncols)

_n_pass = 0
_n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _write_row_file(ncols: int) -> str:
    """토큰 수 ncols인 한 줄짜리 raw 파일을 임시폴더에 만들고 경로 반환."""
    d = tempfile.mkdtemp()
    fp = os.path.join(d, "synthetic.dat")
    with open(fp, "w") as fh:
        fh.write("\t".join("1" for _ in range(ncols)) + "\n")
    return fp


def test_known_layouts_unchanged():
    print("[1] 등록된 레이아웃(cold/hot) 회귀 확인")
    p_cold = RawParser(_write_row_file(6179))
    check("cold kind", p_cold.layout.kind == "cold", p_cold.layout.kind)
    check("cold hk_map == ColdHKMap", p_cold.layout.hk_map is ColdHKMap)
    check("cold spec_blocks", p_cold.layout.spec_blocks == {"NO2": SPEC_PRIMARY},
          p_cold.layout.spec_blocks)

    p_hot = RawParser(_write_row_file(6181))
    check("hot kind", p_hot.layout.kind == "hot", p_hot.layout.kind)
    check("hot hk_map == HotHKMap", p_hot.layout.hk_map is HotHKMap)
    check("hot spec_blocks", p_hot.layout.spec_blocks == {"PNs": SPEC_PRIMARY, "ANs": SPEC_SECONDARY},
          p_hot.layout.spec_blocks)


def test_unregistered_ncols_structural_fallback():
    print("[2] 미등록 ncols → 구조적 폴백(스펙트럼은 추론, HK는 비움)")
    # 가상의 3채널(hot과 같은 HK폭 32컬럼 가정 시 6181+2048=8229)
    p3 = RawParser(_write_row_file(8229))
    check("kind에 'unknown(' 접두", p3.layout.kind.startswith("unknown("), p3.layout.kind)
    check("HK맵은 비움(추측 안 함)", p3.layout.hk_map == {}, p3.layout.hk_map)
    check("3개 채널 블록 추론", len(p3.layout.spec_blocks) == 3, p3.layout.spec_blocks)
    check("ch1 블록이 SPEC_PRIMARY와 일치", p3.layout.spec_blocks.get("ch1") == SPEC_PRIMARY,
          p3.layout.spec_blocks.get("ch1"))
    check("ch2 블록이 SPEC_SECONDARY와 일치", p3.layout.spec_blocks.get("ch2") == SPEC_SECONDARY,
          p3.layout.spec_blocks.get("ch2"))
    check("ch3 블록이 SECONDARY 바로 뒤", p3.layout.spec_blocks.get("ch3") == (6149, 8197),
          p3.layout.spec_blocks.get("ch3"))

    # 아예 짧은/이상한 파일 — 크래시 없이 빈 채널 목록
    p_short = RawParser(_write_row_file(10))
    check("META_COLS 미만이면 채널 0개, 크래시 없음", p_short.layout.spec_blocks == {},
          p_short.layout.spec_blocks)


def test_spec_blocks_for_ncols_direct():
    print("[3] spec_blocks_for_ncols 경계값")
    check("ncols < META_COLS → 빈 dict", spec_blocks_for_ncols(100) == {})
    check("ncols == META_COLS → 빈 dict(꽉 찬 블록 없음)", spec_blocks_for_ncols(META_COLS) == {})
    check("정확히 한 블록", spec_blocks_for_ncols(META_COLS + 2048) == {"ch1": SPEC_PRIMARY})
    # cold/hot 알려진 ncols에서도(등록 분기 밖에서 직접 호출 시) 구조적으로 일관됨
    check("6179에서도 ch1==SPEC_PRIMARY", spec_blocks_for_ncols(6179)["ch1"] == SPEC_PRIMARY)


def main():
    for t in (test_known_layouts_unchanged, test_unregistered_ncols_structural_fallback,
              test_spec_blocks_for_ncols_direct):
        t()
    print(f"\nraw_parser tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
