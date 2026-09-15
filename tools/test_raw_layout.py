"""raw 레이아웃 레지스트리 회귀 검사 — 캠페인별 컬럼 지도를 **데이터로** 다룬다.

지키는 것:
  1. 2026 여수 내장 구성(6179 cold / 6181 hot)의 파싱 결과가 하드코딩 시절과 같다.
     (채널 블록·HK 절대열·kind, 그리고 HK 맵 **객체 동일성** — 기존 코드가 `is`로 본다)
  2. 미등록 ncols는 구조적 폴백으로 간다(HK는 추측하지 않는다 = 빈 맵).
  3. 같은 ncols 중복 등록은 **조용히 덮지 않는다** — 다른 캠페인의 HK로 파싱하는 사고 방지.
  4. Oculus 캠페인 프로파일(`oculus/profiles/*.json`)로 레이아웃을 등록할 수 있고,
     그 결과 채널 블록이 내장 표와 **일치**한다(= 한 파일로 양쪽을 몰 수 있다).
  5. 단위 환산은 **core가 단일 출처** — 프로파일이 반올림한 scale을 적어놔도 core 값을 쓴다.
  6. `tools/channel_map.json`의 채널→wavecal 폴더가 캠페인 프로파일과 **일치**한다
     (같은 매핑이 두 파일에 있으면 어긋난다 — 실제로 2026-09-14에 둘 다 반대로 들어가 있었다).
  7. **새 캠페인은 JSON만 폴더에 넣으면 잡힌다**(autoload). 아는 ncols는 안 덮는다.

    python tools/test_raw_layout.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import raw_parser as RP

_FAIL = []


def check(name, cond, extra=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s  %s" % (name, extra))
        _FAIL.append(name)


def _synth_row(ncols, path, flag=500):
    """열마다 값이 다른 한 행 — HK 열을 잘못 짚으면 값이 달라져 드러난다."""
    vals = [str(3000 + i) for i in range(ncols)]
    vals[RP.COL_TIME_LO] = "1234"
    vals[RP.COL_TIME_HI] = "5678"
    vals[RP.COL_EXPOSURE] = "50"
    vals[RP.COL_TEMP_CCD] = "-1000"
    vals[RP.COL_FLAG] = str(flag)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(vals) + "\n")
    return path


def test_builtin_layouts(d):
    print("[1] 2026 여수 내장 구성")
    cold = RP.RawParser(_synth_row(6179, os.path.join(d, "cold.dat")))
    hot = RP.RawParser(_synth_row(6181, os.path.join(d, "hot.dat")))

    check("cold kind", cold.layout.kind == "cold", cold.layout.kind)
    check("hot kind", hot.layout.kind == "hot", hot.layout.kind)
    check("cold 채널 = NO2 primary",
          cold.layout.spec_blocks == {"NO2": RP.SPEC_PRIMARY}, cold.layout.spec_blocks)
    check("hot 채널 = PNs primary + ANs secondary",
          hot.layout.spec_blocks == {"PNs": RP.SPEC_PRIMARY, "ANs": RP.SPEC_SECONDARY},
          hot.layout.spec_blocks)
    # 기존 코드가 `is`로 본다(tools/test_raw_parser.py) — 레지스트리가 사본을 만들면 깨진다
    check("cold hk_map is ColdHKMap", cold.layout.hk_map is RP.ColdHKMap)
    check("hot hk_map is HotHKMap", hot.layout.hk_map is RP.HotHKMap)

    # HK 절대열이 맞는지 값으로 확인 — 합성 행은 col i에 3000+i가 들어있다
    r = next(hot.iter_rows())
    check("hot HK 절대열(ANs_oven=6151)",
          abs(r.hk["ANs_oven"] - (3000 + 6151) * 0.01) < 1e-9, r.hk["ANs_oven"])
    check("hot HK 압력(P_PNs=6162, P_SCALE)",
          abs(r.hk["P_PNs"] - (3000 + 6162) * RP.P_SCALE) < 1e-9, r.hk["P_PNs"])
    rc = next(cold.iter_rows())
    check("cold HK 절대열(cavity_T=6173)",
          abs(rc.hk["cavity_T"] - (3000 + 6173) * 0.01) < 1e-9, rc.hk["cavity_T"])
    check("bytepack 수식((col0<<16)|col1)",
          rc.bytepack_sec == ((1234 << 16) | 5678) / 100.0, rc.bytepack_sec)


def test_unknown_ncols(d):
    print("[2] 미등록 ncols → 구조적 폴백")
    p = RP.RawParser(_synth_row(6177, os.path.join(d, "unk.dat")))
    check("kind에 structural 표시", "structural" in p.layout.kind, p.layout.kind)
    check("채널은 구조적으로 추론", p.layout.spec_blocks == {"ch1": RP.SPEC_PRIMARY,
                                                    "ch2": RP.SPEC_SECONDARY},
          p.layout.spec_blocks)
    # HK는 추측하지 않는다 — 틀린 HK는 없는 HK보다 위험하다
    check("HK는 빈 맵", p.layout.hk_map == {})
    check("행의 hk도 빔", next(p.iter_rows()).hk == {})


def test_short_header_row(d):
    """LabVIEW가 파일 맨 앞에 쓰는 flag=0 헤더행은 데이터행보다 열이 적다
    (2026 여수 핫 실측: 헤더 6177 vs 데이터 6181, 1314개 중 22개).
    첫 행 하나로 파일을 판정하면 등록 레이아웃과 안 맞아 hk_map={}로 조용히
    떨어진다 — 실제로 2026-08-10-001.dat이 kind=unknown·HK 0개로 나왔었다."""
    print("[2-B] 짧은 헤더행으로 시작하는 파일 → 데이터행 기준으로 판정")
    path = os.path.join(d, "hdr.dat")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(str(3000 + i) for i in range(6177)) + "\n")   # 헤더행(짧음)
        for _ in range(3):
            vals = [str(3000 + i) for i in range(6181)]
            vals[RP.COL_TIME_LO], vals[RP.COL_TIME_HI] = "1234", "5678"
            vals[RP.COL_FLAG] = "500"
            fh.write("\t".join(vals) + "\n")
    p = RP.RawParser(path)
    check("헤더행이 아니라 데이터행 열수로 판정", p.layout.ncols == 6181, p.layout.ncols)
    check("kind=hot", p.layout.kind == "hot", p.layout.kind)
    check("hk_map 채워짐", p.layout.hk_map is RP.HotHKMap)
    row = next(r for r in p.iter_rows() if r.flag == 500)
    check("HK 값이 실제로 읽힘(ANs_oven=6151)",
          abs(row.hk["ANs_oven"] - (3000 + 6151) * 0.01) < 1e-9, row.hk.get("ANs_oven"))
    # 등록 레이아웃이 하나도 안 나오면 기존 폴백(첫 데이터행 기준)을 유지해야 한다
    path2 = os.path.join(d, "allshort.dat")
    with open(path2, "w", encoding="utf-8") as fh:
        for _ in range(3):
            fh.write("\t".join(str(3000 + i) for i in range(6177)) + "\n")
    p2 = RP.RawParser(path2)
    check("전부 미등록이면 폴백 유지", "structural" in p2.layout.kind and p2.layout.ncols == 6177,
          (p2.layout.kind, p2.layout.ncols))


def test_wide_header_row(d):
    """헤더행이 데이터행보다 **넓은** 경우 — 콜드 실측.

    2026-06-11-020.dat: 헤더 6177 > 데이터 6174 (HK 선두 5열 손실, 파일 전체 성질).
    첫 행으로 판정하면 layout.ncols=6177이 되고, iter_rows의 `len(toks) < ncols`
    가드가 데이터행을 **전부** 버린다 — 실측으로 3694행 중 1행(그 헤더행)만 나왔다.
    콜드 751개 중 4개가 이 모양이다(census 2026-09-15). 훑은 행들의 최빈 열수를 써야 한다."""
    print("[2-C] 헤더행이 데이터행보다 넓은 파일 -> 데이터행을 버리지 않는다")

    def _write(path, header_n, data_n, n_data, flag="1"):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\t".join(str(3000 + i) for i in range(header_n)) + "\n")
            for _ in range(n_data):
                vals = [str(3000 + i) for i in range(data_n)]
                vals[RP.COL_FLAG] = flag
                fh.write("\t".join(vals) + "\n")
        return path

    # (a) 실측 그대로: 헤더 6177 > 데이터 6174. 6174는 등록 구성이므로 cold로 잡혀야 한다.
    p = RP.RawParser(_write(os.path.join(d, "widehdr.dat"), 6177, 6174, 8))
    check("(a) 데이터행 열수로 판정", p.layout.ncols == 6174, p.layout.ncols)
    check("(a) 데이터행을 버리지 않는다", sum(1 for _ in p.iter_rows()) == 9)
    check("(a) 등록 구성이라 cold + HK 있음",
          p.layout.kind == "cold" and p.layout.hk_map is RP.Cold6174HKMap,
          (p.layout.kind, list(p.layout.hk_map)))

    # (b) 등록 안 된 폭에서도 같은 보호가 걸려야 한다(헤더 6177 > 데이터 6170, 둘 다 미등록)
    UNREG = 6170
    assert UNREG not in RP.CAMPAIGN_LAYOUTS, "이 검사는 미등록 폭이어야 의미가 있다"
    p2 = RP.RawParser(_write(os.path.join(d, "widehdr_unreg.dat"), 6177, UNREG, 6))
    check("(b) 미등록이어도 최빈(데이터행) 열수로 판정", p2.layout.ncols == UNREG, p2.layout.ncols)
    check("(b) 데이터행을 버리지 않는다", sum(1 for _ in p2.iter_rows()) == 7)
    # 미등록이면 HK는 추측하지 않는다 — 틀린 HK > 없는 HK
    check("(b) HK는 빈 맵", p2.layout.hk_map == {}, p2.layout.hk_map)
    check("(b) kind에 structural 표시", "structural" in p2.layout.kind, p2.layout.kind)

    # (c) 등록 구성이 섞여 있으면 최빈값보다 **등록 쪽이 이긴다**
    path3 = os.path.join(d, "mixed.dat")
    with open(path3, "w", encoding="utf-8") as fh:
        fh.write("\t".join(str(3000 + i) for i in range(6177)) + "\n")      # 미등록
        fh.write("\t".join(str(3000 + i) for i in range(UNREG)) + "\n")     # 미등록
        vals = [str(3000 + i) for i in range(6179)]                          # 등록(cold)
        vals[RP.COL_FLAG] = "1"
        fh.write("\t".join(vals) + "\n")
    p3 = RP.RawParser(path3)
    check("(c) 등록 구성(6179)이 최빈값보다 우선", p3.layout.ncols == 6179, p3.layout.ncols)
    check("(c) 그때 kind=cold", p3.layout.kind == "cold", p3.layout.kind)


def test_cold_6174_layout(d):
    """2026-06-11~06-15 콜드 구성(6174) — HK 선두 5열 결손.

    이 구성이 등록돼 있어야 raw_parser가 data_io(hk_shift)와 **같은 답**을 낸다.
    등록 전엔 hk_map={}이라 같은 raw에 대해 두 리더가 다른 답을 냈다(원칙 3 위반).
    지도는 ColdHKMap에서 -5로 **파생**한다 — 열 번호를 두 번 적으면 사본이 된다."""
    print("[2-D] 콜드 6174 구성(HK 선두 5열 결손) 등록")
    lay = RP.CAMPAIGN_LAYOUTS.get(6174)
    check("6174가 등록돼 있다", lay is not None)
    if lay is None:
        return
    check("kind=cold", lay.kind == "cold", lay.kind)
    check("채널은 정상 콜드와 동일(NO2 primary)",
          lay.spec_blocks() == {"NO2": RP.SPEC_PRIMARY}, lay.spec_blocks())
    # ★ 파생 관계 고정: 6174 지도의 모든 열 = ColdHKMap 열 - 5
    check("HK 열이 ColdHKMap에서 정확히 -5 파생",
          all(lay.hk_map[k][0] == RP.ColdHKMap[k][0] - RP.COLD_6174_LEAD_LOSS
              for k in RP.ColdHKMap),
          {k: (RP.ColdHKMap[k][0], lay.hk_map[k][0]) for k in RP.ColdHKMap})
    check("스케일·단위는 그대로",
          all(lay.hk_map[k][1:] == RP.ColdHKMap[k][1:] for k in RP.ColdHKMap))

    # 합성 행으로 실제 판독 — 열을 잘못 짚으면 값이 달라진다
    p = RP.RawParser(_synth_row(6174, os.path.join(d, "cold6174.dat"), flag=1))
    check("6174 raw가 cold로 파싱됨", p.layout.kind == "cold", p.layout.kind)
    row = next(p.iter_rows())
    check("cavity_P를 6155에서 읽는다",
          abs(row.hk["cavity_P"] - (3000 + 6155) * RP.P_SCALE) < 1e-9, row.hk.get("cavity_P"))
    check("cavity_T를 6168에서 읽는다",
          abs(row.hk["cavity_T"] - (3000 + 6168) * 0.01) < 1e-9, row.hk.get("cavity_T"))
    # 명목 절대열(6173)로 읽으면 다른 값이 나온다는 것 자체를 고정 — 이게 함정의 본체
    check("명목 6173과는 다른 값이어야 한다",
          abs(row.hk["cavity_T"] - (3000 + 6173) * 0.01) > 1e-6)

    # 정상 6179는 영향 없음
    c = RP.RawParser(_synth_row(6179, os.path.join(d, "cold6179b.dat"), flag=1))
    check("정상 6179는 그대로 ColdHKMap", c.layout.hk_map is RP.ColdHKMap)


def test_cold_6174_profile():
    """Oculus가 6174 파일을 배정할 수 있어야 한다 — 없으면 5일치가 감시 사각지대."""
    print("[4-B] Oculus 프로파일이 6174를 라우팅한다")
    from core.profile import ProfileSet

    ps = ProfileSet.load_default()
    got = ps.route(filename="2026-06-11-020.dat", n_columns=6174)
    check("6174 -> 전용 프로파일", got is not None and got.profile_id.endswith("_6174"),
          got.profile_id if got else None)
    # 정상 구성이 이 프로파일로 새지 않아야 한다
    g79 = ps.route(filename="2026-06-11-001.dat", n_columns=6179)
    check("6179는 여전히 기본 콜드", g79 is not None and g79.profile_id == "caesar_cold_2026yeosu",
          g79.profile_id if g79 else None)
    g81 = ps.route(filename="2026-05-18-001.dat", n_columns=6181)
    check("6181은 여전히 핫", g81 is not None and g81.profile_id == "caesar_hot_2026yeosu",
          g81.profile_id if g81 else None)
    if got is None:
        return
    keys = {f.key for f in got.hk.fields}
    check("p_cavity/t_cavity 키가 유지됨(채널 설정이 이 이름을 참조)",
          {"p_cavity", "t_cavity"} <= keys, sorted(keys))
    # 프로파일 rel도 -5 관계여야 한다
    base = ps.by_id("caesar_cold_2026yeosu")
    brel = {f.key: f.rel for f in base.hk.fields}
    check("프로파일 rel도 정상구성 -5",
          all(f.rel == brel[f.key] - 5 for f in got.hk.fields if f.key in brel),
          {f.key: (brel.get(f.key), f.rel) for f in got.hk.fields})


def test_register_guard():
    print("[3] 중복 등록 가드")
    try:
        RP.register_campaign_layout(6179, "other", {"X": "primary"}, {})
        check("중복 등록은 예외", False, "예외가 안 났다")
    except ValueError as e:
        check("중복 등록은 예외", "replace=True" in str(e), str(e))
    try:
        RP.register_campaign_layout(99991, "x", {"X": "nosuchrole"}, {})
        check("모르는 역할은 예외", False, "예외가 안 났다")
    except ValueError:
        check("모르는 역할은 예외", True)
    finally:
        RP.CAMPAIGN_LAYOUTS.pop(99991, None)


def test_oculus_profile_adapter():
    print("[4] Oculus 캠페인 프로파일로 등록")
    saved = dict(RP.CAMPAIGN_LAYOUTS)
    try:
        for fn, ncols in (("caesar_cold.example.json", 6179),
                          ("caesar_hot.example.json", 6181)):
            path = os.path.join(_ROOT, "oculus", "profiles", fn)
            if not os.path.exists(path):
                check("프로파일 존재: %s" % fn, False, path)
                continue
            builtin = saved[ncols]
            lay = RP.load_campaign_layout(path, kind="from-profile", replace=True)
            check("%s: ncols" % fn, lay.ncols == ncols, lay.ncols)
            # ★ 핵심 — 프로파일이 정한 채널 블록이 내장 표와 같다(= 한 파일로 양쪽 구동 가능)
            check("%s: 채널 블록이 내장과 일치" % fn,
                  lay.spec_blocks() == builtin.spec_blocks(),
                  (lay.spec_blocks(), builtin.spec_blocks()))
            check("%s: source에 파일명 기록" % fn, lay.source == fn, lay.source)
            # HK 절대열 = start_col + rel
            press = [v for v in lay.hk_map.values() if v[3] == "press"]
            check("%s: 압력 열이 잡힘" % fn, bool(press), lay.hk_map)
            # 단위 환산은 core 상수 — 프로파일의 반올림값(0.6895)이 아니다
            check("%s: 압력 scale = core P_SCALE" % fn,
                  all(abs(v[1] - RP.P_SCALE) < 1e-12 for v in press),
                  [v[1] for v in press])
    finally:
        RP.CAMPAIGN_LAYOUTS.clear()
        RP.CAMPAIGN_LAYOUTS.update(saved)
    check("검사 후 레지스트리 원복", RP.CAMPAIGN_LAYOUTS[6179].source == "builtin",
          RP.CAMPAIGN_LAYOUTS[6179].source)


def test_channel_map_matches_profiles():
    print("[5] channel_map ↔ 캠페인 프로파일 매핑 대조")
    from tools import optimize_params as OP

    bad = OP.verify_channel_map_against_profiles()
    check("현재 두 파일이 일치", bad == [], bad)

    # 일부러 어긋뜨리면 실제로 잡히는지 — 안 잡히면 이 검사는 장식이다
    swapped = dict(OP.KEY2WLDIR)
    if "ans" in swapped and "pns" in swapped:
        swapped["ans"], swapped["pns"] = swapped["pns"], swapped["ans"]
        caught = OP.verify_channel_map_against_profiles(key2wldir=swapped)
        check("뒤바꾼 매핑을 잡아낸다", len(caught) == 2, caught)
    else:
        check("뒤바꾼 매핑을 잡아낸다", False, "ans/pns 키가 없다")


def test_autoload_new_campaign(d):
    print("[6] 새 캠페인 JSON 자동 등록")
    import json
    import shutil

    src = os.path.join(_ROOT, "oculus", "profiles", "caesar_cold.example.json")
    if not os.path.exists(src):
        check("원본 프로파일 존재", False, src)
        return
    with open(src, encoding="utf-8") as fh:
        prof = json.load(fh)

    # 캐비티가 하나 더 켜진 가상의 다음 캠페인 — 열 수가 다르므로 새 구성이다
    new_ncols = 6179 + 2048
    prof["profile_id"] = "caesar_next_2027demo"
    prof["match"]["n_columns"] = new_ncols
    prof["match"]["filename_glob"] = "*Demo*.dat"
    pdir = os.path.join(d, "profiles")
    os.makedirs(pdir, exist_ok=True)
    shutil.copy(os.path.join(_ROOT, "oculus", "profiles", "_schema.json"), pdir)
    with open(os.path.join(pdir, "caesar_next.json"), "w", encoding="utf-8") as fh:
        json.dump(prof, fh, ensure_ascii=False)

    saved = dict(RP.CAMPAIGN_LAYOUTS)
    try:
        got = RP.autoload_campaign_layouts(pdir, verbose=False)
        check("새 ncols가 등록됨", [l.ncols for l in got] == [new_ncols],
              [l.ncols for l in got])
        check("레지스트리에 들어감", new_ncols in RP.CAMPAIGN_LAYOUTS)
        check("campaign 라벨 기록", RP.CAMPAIGN_LAYOUTS[new_ncols].campaign
              == "caesar_next_2027demo", RP.CAMPAIGN_LAYOUTS[new_ncols].campaign)
        # 그 구성의 raw가 실제로 파싱되는지 — 등록만 되고 안 읽히면 의미 없다
        pr = RP.RawParser(_synth_row(new_ncols, os.path.join(d, "next.dat")))
        check("새 구성 raw가 파싱됨", pr.layout.kind == "caesar_next_2027demo",
              pr.layout.kind)
        check("새 구성 HK가 읽힘", bool(next(pr.iter_rows()).hk))
        # 두 번 돌려도 중복 등록으로 터지지 않는다(가드에 걸려 조용히 건너뜀)
        again = RP.autoload_campaign_layouts(pdir, verbose=False)
        check("재실행은 무해", again == [], again)
        # 기본(여수) 구성은 그대로 — 프로파일이 이기지 않는다
        check("여수 기본 유지", RP.CAMPAIGN_LAYOUTS[6179].source == "builtin",
              RP.CAMPAIGN_LAYOUTS[6179].source)
    finally:
        RP.CAMPAIGN_LAYOUTS.clear()
        RP.CAMPAIGN_LAYOUTS.update(saved)


def main() -> int:
    d = tempfile.mkdtemp(prefix="raw-layout-")
    test_builtin_layouts(d)
    test_unknown_ncols(d)
    test_short_header_row(d)
    test_wide_header_row(d)
    test_cold_6174_layout(d)
    test_cold_6174_profile()
    test_register_guard()
    test_oculus_profile_adapter()
    test_channel_map_matches_profiles()
    test_autoload_new_campaign(d)
    if _FAIL:
        print("raw layout tests: %d FAIL" % len(_FAIL))
        return 1
    print("raw layout self-check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
