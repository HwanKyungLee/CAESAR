"""미션 패키지(core/mission_package.py) 자체검증 — 합성 FitSet, 데이터 불필요, Qt offscreen.

  1) 만들기: FitSet 의 wavecal·레퍼런스를 복사하고 경로를 **패키지 상대**로, manifest(sha1·출처)
  2) 옮겨도 열린다: 패키지 폴더를 다른 곳으로 옮겨 로드 → 경로가 새 위치로 풀린다
  3) 변조 감지: 파일 하나를 바꾸면 verify 가 잡고 install 이 거부(아무것도 안 바꿈)
  4) Augur: <profile_dir>/missions/ 에 설치하면 raw_parser 가 그 날짜의 핫 파일을 미션 채널 이름과
     cavity 센서로 읽는다(그 전 날짜는 여수 미션, 미션 없는 날짜는 기본)
  5) Vigil: load_mission → 그 날짜 파일이 미션으로 라우팅, FitSet 채널을 패키지 안에서 연다(fitset_channel 키),
     날짜가 겹치는 미션은 거부
  6) 미션이 구조를 바꾸려 하면(없는 블록) 만들기 단계에서 거부
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_n_pass = _n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _fake_fitset(d):
    """두 채널 FitSet — roi1/roi2 wavecal, 같은 이름·다른 내용의 레퍼런스(패키지가 채널별로 나눠야 한다)."""
    for roi in ("roi1", "roi2"):
        os.makedirs(os.path.join(d, "wv_cal", roi))
        with open(os.path.join(d, "wv_cal", roi, "Calib.txt"), "w") as fh:
            fh.write("\n".join(f"{400 + i * 0.05:.4f}" for i in range(2048)))
        with open(os.path.join(d, "wv_cal", roi, "Ref_NO2.dat"), "w") as fh:
            fh.write(f"# {roi}\n1 2\n")
    fs = {"version": 1, "active": "1", "channels": {
        k: {"wl_path": os.path.join(d, "wv_cal", roi, "Calib.txt").replace("\\", "/"),
            "refs": [{"name": "NO2", "path": os.path.join(d, "wv_cal", roi, "Ref_NO2.dat").replace("\\", "/")}],
            "fit_start_nm": 430.0, "fit_end_nm": 462.0, "cavity_d": 51.8, "rl_factor": 0.933,
            "data_label": "WRONG-LABEL"}                         # 이름표는 안 쓴다
        for k, roi in (("1", "roi1"), ("2", "roi2"))}}
    os.makedirs(os.path.join(d, "fit setting"))
    p = os.path.join(d, "fit setting", "FitSet_demo.json")
    json.dump(fs, open(p, "w", encoding="utf-8"))
    return p


MISSION = {"base": "caesar_hot_base", "profile_id": "lab_hot_2026_10", "date_range": ["2026-10-01", "2099-12-31"],
           "channels": [
               {"block": "ch1", "label": "COLDcell", "fitset_channel": "2",
                "cavity": {"pressure_hk": ["p_pns_cavity"], "temperature_hk": ["tempcell1", "cell_heater"]},
                "concentration": {"alert": {"conc_max_ppb": 100}}, "reflectance": {}},
               {"block": "ch2", "label": "ANs300", "fitset_channel": "1",
                "cavity": {"pressure_hk": ["p_ans_cavity"], "temperature_hk": ["tempcell2", "cell_heater"]},
                "concentration": {}, "reflectance": None}]}


def main():
    from core import mission_package as MP
    from core.profile import ProfileError, load_profile
    d = tempfile.mkdtemp()
    try:
        src = os.path.join(d, "src")
        fp = _fake_fitset(src)
        pkg = os.path.join(d, "pkg")
        man = MP.build_package(pkg, fp, [MISSION], name="lab_hot_2026_10", created_by="test")
        files = set(man["files"])
        check("1) fitset·wavecal·refs·base·mission 복사",
              {"fitset.json", "base_hot_6181.json", "mission_caesar_hot_base.json"} <= files
              and any(f.startswith("wavecal/roi1/") for f in files)
              and {"refs/1/Ref_NO2.dat", "refs/2/Ref_NO2.dat"} <= files, sorted(files))
        fs = json.load(open(os.path.join(pkg, "fitset.json"), encoding="utf-8"))
        check("1) FitSet 안 경로가 패키지 상대", fs["channels"]["2"]["wl_path"] == "wavecal/roi2/Calib.txt"
              and fs["channels"]["2"]["refs"][0]["path"] == "refs/2/Ref_NO2.dat", fs["channels"]["2"])
        md = json.load(open(os.path.join(pkg, "mission_caesar_hot_base.json"), encoding="utf-8"))
        c1 = md["channels"][0]
        check("1) 미션: fitset_path·wavecal 상대, fitset_channel 키, R roi = FitSet 핏 창",
              c1["concentration"]["fitset_path"] == "fitset.json" and c1["concentration"]["fitset_channel"] == "2"
              and c1["reflectance"]["wavecal_path"] == "wavecal/roi2/Calib.txt"
              and c1["reflectance"]["roi_nm"] == [430.0, 462.0], c1)
        check("1) manifest 출처 = 미션+바탕", man["provenance"][0].startswith("mission_caesar_hot_base.json@1.0.0#")
              and "+base_hot_6181.json@" in man["provenance"][0], man["provenance"])
        check("1) verify 깨끗", MP.verify_package(pkg) == [], MP.verify_package(pkg))

        # 2) 옮겨도 열린다
        moved = os.path.join(d, "usb", "somewhere", "pkg")
        shutil.copytree(pkg, moved)
        shutil.rmtree(src)                                    # 원본 FitSet·파일이 없어도
        prof = load_profile(os.path.join(moved, "mission_caesar_hot_base.json"))
        ch1 = prof.channel("ch1")
        check("2) 옮긴 위치로 경로가 풀린다",
              os.path.normpath(ch1.concentration.fitset_path) == os.path.normpath(os.path.join(moved, "fitset.json"))
              and os.path.exists(ch1.reflectance.wavecal_path), ch1.concentration.fitset_path)
        check("2) 미션 = 기본 구조 + 정체", prof.is_mission and [c.label for c in prof.signal_channels()]
              == ["COLDcell", "ANs300"] and ch1.pressure_keys() == ["p_pns_cavity"], prof.profile_id)

        # 3) 변조 감지
        bad = os.path.join(d, "bad")
        shutil.copytree(moved, bad)
        with open(os.path.join(bad, "refs", "1", "Ref_NO2.dat"), "a") as fh:
            fh.write("tampered\n")
        probs = MP.verify_package(bad)
        check("3) 변조 감지", any("changed: refs/1/Ref_NO2.dat" in p for p in probs), probs)
        root = os.path.join(d, "root")
        try:
            MP.install_package(bad, root)
            check("3) 변조 패키지는 설치 거부", False)
        except ValueError:
            check("3) 변조 패키지는 설치 거부(아무것도 안 만듦)", not os.path.exists(root))

        # 4) Augur — 프로파일 폴더 사본 + missions/ 설치
        from core import raw_parser as RP
        pdir = os.path.join(d, "profiles")
        shutil.copytree(os.path.join(_ROOT, "vigil", "profiles"), pdir)
        MP.install_package(moved, MP.missions_root(pdir))
        saved = {k: list(v) for k, v in RP.CAMPAIGN_LAYOUTS.items()}
        try:
            RP.CAMPAIGN_LAYOUTS.clear()
            with contextlib.redirect_stdout(io.StringIO()):
                RP.autoload_campaign_layouts(pdir, verbose=False)
            srcs = [l.source for l in RP.CAMPAIGN_LAYOUTS.get(6181, [])]
            check("4) 설치된 미션 등록(source = 상대경로)",
                  "missions/lab_hot_2026_10/mission_caesar_hot_base.json" in srcs, srcs)
            la, _ = RP.layout_for(6181, "2026-10-05-001 Hot.dat")
            lb, _ = RP.layout_for(6181, "2026-06-05-001 Hot.dat")
            lc, _ = RP.layout_for(6181, "2026-09-10-001 Hot.dat")
            check("4) 10월 = 새 미션(COLDcell/ANs300), 6월 = 여수, 9월 = 기본",
                  list(la.channels) == ["COLDcell", "ANs300"] and list(lb.channels) == ["ANs", "PNs"]
                  and not lc.is_mission, (list(la.channels), list(lb.channels), lc.source))
            check("4) 새 미션 cavity 센서", la.cavity["ANs300"][0] == ("p_ans_cavity",), la.cavity)
        finally:
            RP.CAMPAIGN_LAYOUTS.clear()
            RP.CAMPAIGN_LAYOUTS.update(saved)

        # 5) Vigil — load_mission
        from PyQt6.QtCore import QCoreApplication
        _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        from vigil.run_vigil import VigilApp
        st = os.path.join(d, "vstate")
        core = VigilApp(None, os.path.join(_ROOT, "vigil", "profiles"), st)
        before = core.profiles.route(filename="2026-10-05-001 Hot.dat", n_columns=6181)
        got = core.load_mission(moved)
        after = core.profiles.route(filename="2026-10-05-001 Hot.dat", n_columns=6181)
        check("5) 불러오기 전 = 기본, 후 = 미션", not before.is_mission and after.profile_id == "lab_hot_2026_10",
              (before.profile_id, after.profile_id))
        check("5) 상태 폴더 missions/ 에 설치", os.path.isdir(os.path.join(st, "missions", "lab_hot_2026_10")))
        check("5) 출처 기록", got and got[0].startswith("mission_caesar_hot_base.json@"), got)
        fch = core._get_fitset_channel(after.channel("ch1").concentration)
        check("5) FitSet 채널을 키('2')로, 패키지 안 경로로 연다",
              fch["wl_path"].replace("\\", "/").endswith("missions/lab_hot_2026_10/wavecal/roi2/Calib.txt")
              and os.path.exists(fch["refs"][0]["path"]), fch["wl_path"])
        # 겹치는 미션은 거부
        over = dict(MISSION, profile_id="lab_hot_overlap", date_range=["2026-12-01", "2027-01-31"])
        pkg2 = os.path.join(d, "pkg2")
        src2 = os.path.join(d, "src2")
        MP.build_package(pkg2, _fake_fitset(src2), [over], name="lab_hot_overlap")
        try:
            core.load_mission(pkg2)
            check("5) 날짜 겹치는 미션 거부", False)
        except ValueError as e:
            check("5) 날짜 겹치는 미션 거부", "overlaps" in str(e), str(e))

        # 6) 구조를 바꾸려는 미션
        bad_m = dict(MISSION, channels=[dict(MISSION["channels"][0], block="ch9")])
        try:
            MP.build_package(os.path.join(d, "pkg3"), _fake_fitset(os.path.join(d, "src3")), [bad_m], name="x")
            check("6) 없는 블록 → 만들기 거부", False)
        except ProfileError:
            check("6) 없는 블록 → 만들기 거부", True)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\nmission package tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
