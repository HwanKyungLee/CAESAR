"""raw 레이아웃 레지스트리 회귀 검사 — 채널 정의는 **vigil/profiles/*.json 한 곳**에서 온다.

지키는 것:
  1. 프로파일에서 만든 2026 여수 구성(6179 cold / 6181 hot / 6174 cold)이 옛 내장 표(아래
     LEGACY_* — 2026-10-02 단일화 전 core/raw_parser 에 있던 값 그대로)와 **같은 열·scale·kind**를
     만든다. 키 이름만 프로파일 이름으로 바뀌었다(LEGACY_RENAME).
  2. 미등록 ncols는 구조적 폴백으로 간다(HK는 추측하지 않는다 = 빈 맵).
  3. 같은 ncols·**겹치는 날짜** 중복 등록은 조용히 덮지 않는다. 날짜가 안 겹치면 같은 ncols 에
     여러 구성을 둘 수 있고 `layout_for` 가 파일 날짜로 고른다(배치가 바뀐 뒤의 프로파일).
  4. 단위 환산은 **core가 단일 출처** — 프로파일이 반올림한 scale을 적어놔도 core 값을 쓴다.
  5. `tools/channel_map.json`의 채널→wavecal 폴더가 캠페인 프로파일과 **일치**한다.
  6. **새 구성은 JSON만 폴더에 넣으면 잡힌다**(autoload) — 새 열 수든, 같은 열 수의 새 날짜든.
     채널을 추가하면(콜드 블록 4101 을 신호로) Augur 가 그 블록을 채널로 읽고 그 채널의 cavity
     센서로 T/P 를 고른다 — 코드를 안 고친다.
  7. core/data_io 의 T/P 는 프로파일 채널 cavity 목록을 따른다(우선순위·결측 폴백).

    python tools/test_raw_layout.py
"""
from __future__ import annotations
# 한글 Windows 콘솔(cp949)에서 직접 실행해도 '—'·'✓' 등에서 죽지 않게(2026-10-01).
import sys as _sys_utf8
for _stream in (_sys_utf8.stdout, _sys_utf8.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import raw_parser as RP

_FAIL = []

# ── 2026-10-02 단일화 전 core/raw_parser 내장 표 — 이제 **검사 기준값**으로만 산다 ──────────
# (이름 → (절대열, scale, unit, kind)). 프로파일이 이 열들을 같은 scale·kind 로 만들어야 한다.
LEGACY_HOT = {
    "templed1": (6149, 0.01, "C", "temp"), "templed2": (6150, 0.01, "C", "temp"),
    "ANs_oven": (6151, 0.01, "C", "temp"), "templed4": (6152, 0.01, "C", "temp"),
    "temppreh": (6153, 0.01, "C", "temp"), "PNs_oven": (6154, 0.01, "C", "temp"),
    "cavity_gas_T": (6155, 0.01, "C", "temp"),
    "P_PNs": (6162, RP.P_SCALE, "mbar", "press"), "P_ANs": (6164, RP.P_SCALE, "mbar", "press"),
    "tempcell1": (6174, 0.01, "C", "temp"), "tempcell2": (6175, 0.01, "C", "temp"),
    "tempcell3": (6176, 0.01, "C", "temp"), "tempsptrm": (6177, 0.01, "C", "temp"),
}
LEGACY_COLD = {
    "cavity_P": (6160, RP.P_SCALE, "mbar", "press"),
    "cavity_T": (6173, 0.01, "C", "temp"),
    "tempsptrm": (6174, 0.01, "C", "temp"),
}
LEGACY_COLD_6174 = {k: (c - 5, sc, u, kd) for k, (c, sc, u, kd) in LEGACY_COLD.items()}
LEGACY_RENAME = {   # 옛 이름 → 프로파일 키
    "ANs_oven": "oven_ans_setpoint", "PNs_oven": "oven_pns_setpoint", "temppreh": "preheater",
    "cavity_gas_T": "cell_heater", "P_PNs": "p_pns_cavity", "P_ANs": "p_ans_cavity",
    "tempsptrm": "t_spectrometer", "cavity_P": "p_cavity", "cavity_T": "t_cavity",
}


def check(name, cond, extra=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s  %s" % (name, extra))
        _FAIL.append(name)


@contextlib.contextmanager
def _saved_registry():
    saved = {k: list(v) for k, v in RP.CAMPAIGN_LAYOUTS.items()}
    try:
        yield
    finally:
        RP.CAMPAIGN_LAYOUTS.clear()
        RP.CAMPAIGN_LAYOUTS.update(saved)


def _synth_row(ncols, path, flag=500, overrides=None):
    """열마다 값이 다른 한 행 — HK 열을 잘못 짚으면 값이 달라져 드러난다."""
    vals = [str(3000 + i) for i in range(ncols)]
    vals[RP.COL_TIME_LO] = "1234"
    vals[RP.COL_TIME_HI] = "5678"
    vals[RP.COL_EXPOSURE] = "50"
    vals[RP.COL_TEMP_CCD] = "-1000"
    vals[RP.COL_FLAG] = str(flag)
    for c, v in (overrides or {}).items():
        vals[c] = str(v)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(vals) + "\n")
    return path


def _same_as_legacy(lay, legacy):
    """legacy 의 모든 항목이 lay.hk_map 에 (새 이름으로) 같은 열·scale·kind 로 있는가."""
    bad = {}
    for old, (col, sc, _u, kd) in legacy.items():
        ent = lay.hk_map.get(LEGACY_RENAME.get(old, old))
        if ent is None or ent[0] != col or abs(ent[1] - sc) > 1e-15 or ent[3] != kd:
            bad[old] = (col, ent)
    return bad


def test_profile_layouts_match_legacy(d):
    print("[1] 프로파일에서 만든 2026 여수 구성 = 옛 내장 표")
    for ncols, legacy, kind, chans in ((6179, LEGACY_COLD, "cold", {"NO2": RP.SPEC_PRIMARY}),
                                       (6174, LEGACY_COLD_6174, "cold", {"NO2": RP.SPEC_PRIMARY}),
                                       (6181, LEGACY_HOT, "hot",
                                        {"ANs": RP.SPEC_PRIMARY, "PNs": RP.SPEC_SECONDARY})):
        lay, _ = RP.layout_for(ncols)
        check(f"{ncols}: 등록됨(프로파일에서)", lay is not None and lay.source.endswith(".json"),
              lay and lay.source)
        if lay is None:
            continue
        check(f"{ncols}: kind={kind}, campaign=2026-yeosu",
              lay.kind == kind and lay.campaign == "2026-yeosu", (lay.kind, lay.campaign))
        check(f"{ncols}: 채널 블록", lay.spec_blocks() == chans, lay.spec_blocks())
        bad = _same_as_legacy(lay, legacy)
        check(f"{ncols}: 옛 HK 열·scale·kind 전부 재현", not bad, bad)
    check("핫만 날짜 구간(여수 2026-05-01~08-31)",
          RP.layout_for(6181)[0].date_range == ("2026-05-01", "2026-08-31")
          and RP.layout_for(6179)[0].date_range is None)

    # 파싱 결과로도 — 합성 행은 col i 에 3000+i
    hot = RP.RawParser(_synth_row(6181, os.path.join(d, "2026-06-01-001 hot.dat")))
    cold = RP.RawParser(_synth_row(6179, os.path.join(d, "cold.dat")))
    r = next(hot.iter_rows())
    check("hot HK 절대열(oven_ans_setpoint=6151)",
          abs(r.hk["oven_ans_setpoint"] - (3000 + 6151) * 0.01) < 1e-9, r.hk.get("oven_ans_setpoint"))
    check("hot HK 압력(p_pns_cavity=6162, P_SCALE)",
          abs(r.hk["p_pns_cavity"] - (3000 + 6162) * RP.P_SCALE) < 1e-9, r.hk.get("p_pns_cavity"))
    rc = next(cold.iter_rows())
    check("cold HK 절대열(t_cavity=6173)",
          abs(rc.hk["t_cavity"] - (3000 + 6173) * 0.01) < 1e-9, rc.hk.get("t_cavity"))
    check("bytepack 수식((col0<<16)|col1)",
          rc.bytepack_sec == ((1234 << 16) | 5678) / 100.0, rc.bytepack_sec)
    check("hk_col 이 같은 열을 준다",
          (RP.hk_col(6179, "p_cavity"), RP.hk_col(6181, "p_ans_cavity"), RP.hk_col(6181, "nope"))
          == (6160, 6164, None))

    # 출처: 오프라인 PC 끼리 같은 정의를 쓰는지 대조할 문자열(파일@판#내용해시)
    import re
    from core import run_meta
    prov = RP.layout_for(6181)[0].profile
    check("레이아웃 출처 = 파일@판#해시8",
          re.fullmatch(r"caesar_hot\.example\.json@\d+\.\d+\.\d+#[0-9a-f]{8}", prov or "") is not None, prov)
    lay_in = run_meta.layout_from_input(os.path.join(d, "2026-06-01-001 hot.dat"))
    check("raw 입력 meta 에 profile", (lay_in or {}).get("profile") == prov, lay_in)
    ap = os.path.join(d, "x_alpha_trace.dat")
    with open(ap, "w", encoding="utf-8") as fh:
        fh.write(f"# raw_layout: ncols=6181 campaign=2026-yeosu parser=DataIO-dynamic profile={prov}\n1 2\n")
    check("알파 헤더의 profile= 이 meta 로 왕복", (run_meta.layout_from_input(ap) or {}).get("profile") == prov,
          run_meta.layout_from_input(ap))


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
    check("hk_map 채워짐", p.layout.hk_map is RP.layout_for(6181)[0].hk_map)
    row = next(r for r in p.iter_rows() if r.flag == 500)
    check("HK 값이 실제로 읽힘(oven_ans_setpoint=6151)",
          abs(row.hk["oven_ans_setpoint"] - (3000 + 6151) * 0.01) < 1e-9,
          row.hk.get("oven_ans_setpoint"))
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
          p.layout.kind == "cold" and p.layout.hk_map is RP.layout_for(6174)[0].hk_map,
          (p.layout.kind, list(p.layout.hk_map)))

    # (b) 등록 안 된 폭에서도 같은 보호가 걸려야 한다(헤더 6177 > 데이터 6170, 둘 다 미등록)
    UNREG = 6170
    assert UNREG not in RP.CAMPAIGN_LAYOUTS, "이 검사는 미등록 폭이어야 의미가 있다"
    p2 = RP.RawParser(_write(os.path.join(d, "widehdr_unreg.dat"), 6177, UNREG, 6))
    check("(b) 미등록이어도 최빈(데이터행) 열수로 판정", p2.layout.ncols == UNREG, p2.layout.ncols)
    check("(b) 데이터행을 버리지 않는다", sum(1 for _ in p2.iter_rows()) == 7)
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
    """2026-06-11~06-15 콜드 구성(6174) — HK 선두 5열 결손. 정상 6179 의 모든 HK 열 - 5."""
    print("[2-D] 콜드 6174 구성(HK 선두 5열 결손)")
    lay, lay79 = RP.layout_for(6174)[0], RP.layout_for(6179)[0]
    check("6174가 등록돼 있다", lay is not None)
    if lay is None:
        return
    shared = sorted(set(lay.hk_map) & set(lay79.hk_map))
    check("공통 HK 열이 전부 6179 열 - 5",
          shared and all(lay.hk_map[k][0] == lay79.hk_map[k][0] - 5 for k in shared),
          {k: (lay79.hk_map[k][0], lay.hk_map[k][0]) for k in shared})
    p = RP.RawParser(_synth_row(6174, os.path.join(d, "cold6174.dat"), flag=1))
    row = next(p.iter_rows())
    check("p_cavity를 6155에서 읽는다",
          abs(row.hk["p_cavity"] - (3000 + 6155) * RP.P_SCALE) < 1e-9, row.hk.get("p_cavity"))
    check("t_cavity를 6168에서 읽는다(명목 6173 아님 — 함정의 본체)",
          abs(row.hk["t_cavity"] - (3000 + 6168) * 0.01) < 1e-9
          and abs(row.hk["t_cavity"] - (3000 + 6173) * 0.01) > 1e-6, row.hk.get("t_cavity"))


def test_cold_6174_profile():
    """Vigil이 6174 파일을 배정할 수 있어야 한다 — 없으면 5일치가 감시 사각지대."""
    print("[2-E] Vigil 프로파일이 6174를 라우팅한다")
    from core.profile import ProfileSet

    ps = ProfileSet.load_default()
    got = ps.route(filename="2026-06-11-020.dat", n_columns=6174)
    check("6174 -> 전용 프로파일", got is not None and got.profile_id.endswith("_6174"),
          got.profile_id if got else None)
    g79 = ps.route(filename="2026-06-11-001.dat", n_columns=6179)
    check("6179는 여전히 기본 콜드", g79 is not None and g79.profile_id == "caesar_cold_2026yeosu",
          g79.profile_id if g79 else None)
    g81 = ps.route(filename="2026-05-18-001.dat", n_columns=6181)
    check("6181은 여전히 핫", g81 is not None and g81.profile_id == "caesar_hot_2026yeosu",
          g81.profile_id if g81 else None)


def test_register_guard():
    print("[3] 중복 등록 가드 · 같은 열 수의 날짜별 구성")
    with _saved_registry():
        try:
            RP.register_campaign_layout(6179, "other", {"X": "primary"}, {})
            check("겹치는 날짜 중복 등록은 예외", False, "예외가 안 났다")
        except ValueError as e:
            check("겹치는 날짜 중복 등록은 예외", "replace=True" in str(e), str(e))
        try:
            RP.register_campaign_layout(99991, "x", {"X": "nosuchrole"}, {})
            check("모르는 역할은 예외", False, "예외가 안 났다")
        except ValueError:
            check("모르는 역할은 예외", True)
        # 핫(05-01~08-31)과 안 겹치는 새 핫 배치 — 같은 6181 에 둘 다 산다
        RP.register_campaign_layout(6181, "hot-lab", {"cold": "primary", "ANs": "secondary"}, {},
                                    date_range=("2026-09-01", "2099-12-31"), source="lab.json")
        a, ina = RP.layout_for(6181, "2026-06-01-001.dat")
        b, inb = RP.layout_for(6181, "2026-10-02-001.dat")
        c, inc = RP.layout_for(6181, "2025-01-01-001.dat")
        check("layout_for: 6월 = 여수, 10월 = 새 배치",
              (a.kind, ina, b.kind, inb) == ("hot", True, "hot-lab", True), (a.kind, b.kind))
        check("layout_for: 어느 구간에도 안 들면 첫 구성을 '구간 밖'으로", (c.kind, inc) == ("hot", False))
        check("block_channel_name 이 날짜로 다른 이름",
              RP.block_channel_name(_synth_row(6181, os.path.join(tempfile.mkdtemp(), "2026-10-02-001.dat")),
                                    2053) == "cold")


def test_unit_scales_from_core():
    print("[4] 단위 환산은 core 상수(프로파일의 반올림 scale 아님)")
    for ncols in (6179, 6181):
        lay = RP.layout_for(ncols)[0]
        press = [v for v in lay.hk_map.values() if v[3] == "press"]
        check(f"{ncols}: 압력 scale = core P_SCALE",
              press and all(abs(v[1] - RP.P_SCALE) < 1e-12 for v in press), [v[1] for v in press])


def test_channel_map_matches_profiles():
    print("[5] channel_map ↔ 캠페인 프로파일 매핑 대조")
    from tools import optimize_params as OP

    # 알려진 미결 불일치(2026-10-01) — 지우지 말고 표시한다. 핫 프로파일은 Augur FitSet 이
    # 실제로 쓰는 짝(ANs 블록 2053 ↔ wv_cal/roi1)을 따르고, channel_map.json·판정 문서의 wavecal
    # 열은 9-14 메모(ANs ↔ roi2)를 따른다. roi1/roi2 차이는 전 구간 ≈ 0.034 nm(0.7 px)로 핏 shift
    # 가 흡수한다. 어느 Hg 교정이 어느 CCD 영역 것인지 원자료로 확인되면 한쪽을 고치고 이 집합을
    # 비울 것. **이 집합 밖의 불일치는 그대로 FAIL** 이다.
    pending = {("ans", "roi2", "roi1"), ("pns", "roi1", "roi2")}
    bad = OP.verify_channel_map_against_profiles()
    unexpected = [b for b in bad if tuple(b) not in pending]
    check("두 파일이 일치(알려진 wavecal 미결 제외)", unexpected == [], unexpected)
    if bad:
        print(f"  WARN  wavecal 짝 미결 {len(bad)}건(channel_map vs 프로파일): {bad}")
    agreed = dict(OP.KEY2WLDIR)
    for key, _cm, prof_val in bad:
        agreed[key] = prof_val
    check("프로파일 값으로 맞춘 매핑은 불일치 0",
          OP.verify_channel_map_against_profiles(key2wldir=agreed) == [])
    if "ans" in agreed and "pns" in agreed:
        swapped = dict(agreed)
        swapped["ans"], swapped["pns"] = swapped["pns"], swapped["ans"]
        caught = OP.verify_channel_map_against_profiles(key2wldir=swapped)
        check("뒤바꾼 매핑을 잡아낸다", len(caught) == 2, caught)
    else:
        check("뒤바꾼 매핑을 잡아낸다", False, "ans/pns 키가 없다")


def _profile_dir_with(d, name, edit):
    """기본 프로파일 폴더 사본 + edit(dict) 를 적용한 새 프로파일 하나."""
    pdir = os.path.join(d, name)
    shutil.copytree(os.path.join(_ROOT, "vigil", "profiles"), pdir)
    src = os.path.join(pdir, "caesar_cold.example.json")
    prof = json.load(open(src, encoding="utf-8"))
    edit(prof)
    with open(os.path.join(pdir, f"{name}.json"), "w", encoding="utf-8") as fh:
        json.dump(prof, fh, ensure_ascii=False)
    return pdir


def test_autoload_new_configuration(d):
    print("[6] 새 구성 JSON 자동 등록 — 새 열 수 · 같은 열 수에 채널 추가(날짜)")
    from core.data_io import DataIO

    # (a) 캐비티가 하나 더 켜진 가상의 다음 캠페인 — 열 수가 다르므로 새 구성
    new_ncols = 6179 + 2048

    def more_cols(p):
        p["profile_id"] = "caesar_next_2027demo"
        p["campaign"] = "2027-demo"
        p["match"]["n_columns"] = new_ncols
        p["match"]["filename_glob"] = "*Demo*.dat"
    pdir = _profile_dir_with(d, "next", more_cols)
    with _saved_registry():
        got = RP.autoload_campaign_layouts(pdir, verbose=False)
        check("(a) 새 열 수만 새로 등록", [l.ncols for l in got] == [new_ncols], [l.ncols for l in got])
        check("(a) campaign 기록", RP.layout_for(new_ncols)[0].campaign == "2027-demo")
        pr = RP.RawParser(_synth_row(new_ncols, os.path.join(d, "next.dat")))
        check("(a) 새 구성 raw가 파싱되고 HK가 읽힘", pr.layout.kind == "cold" and bool(next(pr.iter_rows()).hk),
              pr.layout.kind)
        check("(a) 재실행은 무해", RP.autoload_campaign_layouts(pdir, verbose=False) == [])

    # (b) 콜드에 채널 추가 — 같은 6179열, 2026-10-01 부터 블록 4101 도 신호(다른 셀, 다른 센서)
    def add_channel(p):
        p["profile_id"] = "caesar_cold_2ch_demo"
        p["profile_version"] = "1.0.0"
        p["match"]["date_range"] = ["2026-10-01", "2099-12-31"]
        for ch in p["channels"]:
            if ch["id"] == "ch_noise2":
                ch.update({"id": "ch_cell2", "label": "Cell2", "role": "signal",
                           "cavity": {"pressure_hk": ["unknown_rel28"],
                                      "temperature_hk": ["t_spectrometer"]}})
        p["hk"]["fields"] = [dict(f, unit="mbar", scale=0.6895) if f["key"] == "unknown_rel28" else f
                             for f in p["hk"]["fields"]]
    pdir = _profile_dir_with(d, "twoch", add_channel)
    # 여수 콜드 프로파일은 날짜 제한이 없어 새 구성과 겹친다 — 실제로는 여수 프로파일에 끝 날짜를
    # 붙여야 한다(그게 이 기능의 사용법). 사본에서 그렇게 한다.
    yp = os.path.join(pdir, "caesar_cold.example.json")
    y = json.load(open(yp, encoding="utf-8"))
    y["match"]["date_range"] = ["2026-01-01", "2026-09-30"]
    json.dump(y, open(yp, "w", encoding="utf-8"), ensure_ascii=False)
    with _saved_registry():
        RP.CAMPAIGN_LAYOUTS.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            RP.autoload_campaign_layouts(pdir, verbose=False)
        lays = RP.CAMPAIGN_LAYOUTS.get(6179, [])
        check("(b) 6179 에 날짜별 구성 2개", len(lays) == 2, [(l.source, l.date_range) for l in lays])
        old = RP.RawParser(_synth_row(6179, os.path.join(d, "2026-06-02-001.dat"), flag=1))
        new_fp = _synth_row(6179, os.path.join(d, "2026-10-05-001.dat"), flag=1,
                            overrides={6177: 1450})        # Cell2 압력 raw(×P_SCALE ≈ 999.7 mbar)
        new = RP.RawParser(new_fp)
        check("(b) 6월 파일은 1채널(NO2)", old.layout.spec_blocks == {"NO2": RP.SPEC_PRIMARY},
              old.layout.spec_blocks)
        check("(b) 10월 파일은 2채널(NO2 + Cell2)",
              new.layout.spec_blocks == {"NO2": RP.SPEC_PRIMARY, "Cell2": RP.SPEC_SECONDARY},
              new.layout.spec_blocks)
        with contextlib.redirect_stdout(io.StringIO()):
            _, s2, _, t2, p2 = DataIO.load_measurement_with_hk(new_fp, 0, None, 0, 2)
            _, s1, _, t1, p1 = DataIO.load_measurement_with_hk(new_fp, 0, None, 0, 1)
        check("(b) data_io: 새 채널(슬롯 2)은 그 채널의 cavity 센서로 T/P",
              abs(p2 - 1450 * RP.P_SCALE) < 1e-9 and abs(t2 - (3000 + 6174) * 0.01) < 1e-9, (t2, p2))
        check("(b) data_io: 기존 채널(슬롯 1)은 여전히 p_cavity·t_cavity",
              abs(p1 - (3000 + 6160) * RP.P_SCALE) < 1e-9 and abs(t1 - (3000 + 6173) * 0.01) < 1e-9,
              (t1, p1))
        check("(b) data_io: 슬롯 2 스펙트럼 = 블록 4101", float(s2[0]) == 3000 + 4101, s2[0])


def test_data_io_follows_cavity_chain(d):
    print("[7] data_io T/P = 프로파일 채널 cavity 목록(우선순위·결측 폴백)")
    from core.data_io import DataIO

    def tp(fp, ch):
        with contextlib.redirect_stdout(io.StringIO()):
            _, _, _, t, p = DataIO.load_measurement_with_hk(fp, 0, None, 0, ch)
        return t, p

    fp = _synth_row(6181, os.path.join(d, "2026-06-01-010 Hot.dat"), flag=1)
    t1, p1 = tp(fp, 1)
    t2, p2 = tp(fp, 2)
    check("ANs(슬롯 1) = p_ans_cavity(6164)·tempcell1(6174)",
          abs(p1 - (3000 + 6164) * RP.P_SCALE) < 1e-9 and abs(t1 - (3000 + 6174) * 0.01) < 1e-9, (t1, p1))
    check("PNs(슬롯 2) = p_pns_cavity(6162)·tempcell2(6175)",
          abs(p2 - (3000 + 6162) * RP.P_SCALE) < 1e-9 and abs(t2 - (3000 + 6175) * 0.01) < 1e-9, (t2, p2))
    # 첫 센서가 결측(0)이면 목록의 다음
    fp = _synth_row(6181, os.path.join(d, "2026-06-01-011 Hot.dat"), flag=1,
                    overrides={6164: 0, 6174: 65535, 6175: 0})
    t1, p1 = tp(fp, 1)
    check("ANs 압력 결측 → p_pns_cavity, 온도 둘 다 결측 → cell_heater(6155)",
          abs(p1 - (3000 + 6162) * RP.P_SCALE) < 1e-9 and abs(t1 - (3000 + 6155) * 0.01) < 1e-9, (t1, p1))
    # 구간 밖(배치가 바뀐 뒤) — 채널 정의 없음 → 옛 슬롯 규칙: 슬롯 2 = 300 °C 경로 압력(6164)
    fp = _synth_row(6181, os.path.join(d, "2026-09-28-001 Hot.dat"), flag=1)
    with contextlib.redirect_stderr(io.StringIO()):
        t2, p2 = tp(fp, 2)
        t1, p1 = tp(fp, 1)
    check("구간 밖: 슬롯 2 = 6164, 슬롯 1 = 6162 (옛 슬롯 규칙 유지)",
          abs(p2 - (3000 + 6164) * RP.P_SCALE) < 1e-9 and abs(p1 - (3000 + 6162) * RP.P_SCALE) < 1e-9,
          (p1, p2))


def main() -> int:
    d = tempfile.mkdtemp(prefix="raw-layout-")
    test_profile_layouts_match_legacy(d)
    test_unknown_ncols(d)
    test_short_header_row(d)
    test_wide_header_row(d)
    test_cold_6174_layout(d)
    test_cold_6174_profile()
    test_register_guard()
    test_unit_scales_from_core()
    test_channel_map_matches_profiles()
    test_autoload_new_configuration(d)
    test_data_io_follows_cavity_chain(d)
    if _FAIL:
        print("raw layout tests: %d FAIL" % len(_FAIL))
        return 1
    print("raw layout self-check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
