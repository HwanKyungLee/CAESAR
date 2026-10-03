"""Setup 탭 Vigil 그룹 'Export Mission…' 미션 내보내기 대화상자 자체검증 — 합성 FitSet·raw, Qt offscreen.

  1) FitSet 을 열면 채널마다 한 줄, 기본값(여수 미션의 같은 블록 센서)이 채워진다
  2) Check with raw: 밝은 블록 = lit + 핏 창이 LED 반치 구간 안 ✓, 어두운 블록 = DARK
  3) 이름을 안 적으면 내보내기 거부, 같은 블록 두 번도 거부
  4) build → 패키지(미션 하나 = 기본 프로파일 하나), cavity 체인에 cell_heater 폴백
"""
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


def _raw(path, n=6):
    """핫 6181열: 블록 2053 에 px 400–1400 평탄 LED(9000), 4101 은 어두움(600)."""
    with open(path, "w") as fh:
        for k in range(n):
            v = ["600"] * 6181
            v[4] = "1"
            for i in range(2048):
                v[2053 + i] = "9000" if 400 <= i <= 1400 else "1500"
            fh.write("\t".join(v) + "\n")
    return path


def main():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])   # noqa: F841
    from tools.test_mission_package import _fake_fitset
    from gui.dlg_mission_export import MissionExportDialog
    d = tempfile.mkdtemp()
    try:
        fp = _fake_fitset(os.path.join(d, "src"))
        dlg = MissionExportDialog(None, fitset_path=fp)
        t = dlg.table
        check("1) FitSet 채널마다 한 줄", t.rowCount() == 2, t.rowCount())
        # 2026-10-03: 블록은 기본값 없음(예전엔 모든 행이 ch1) — 사람이 LED 스펙트럼을 보고 고른다
        check("1) 블록 기본값은 비어 있음",
              all(t.cellWidget(r, 3).currentData() is None for r in range(2)),
              [t.cellWidget(r, 3).currentData() for r in range(2)])
        for r in range(2):
            t.cellWidget(r, 4).setText(f"cell{r}")
        try:
            dlg.collect()
            check("1) 블록을 안 고르면 거부", False, "collect() accepted an unset block")
        except ValueError as e:
            check("1) 블록을 안 고르면 거부", "choose the raw block" in str(e), str(e))
        for r in range(2):
            t.cellWidget(r, 4).setText("")
        # 행 0 = FitSet 채널 '1' → 핫 블록 ch1, 행 1 = '2' → 핫 블록 ch2
        for r, blk in ((0, "ch1"), (1, "ch2")):
            cb = t.cellWidget(r, 2)
            cb.setCurrentIndex(cb.findText("hot 6181"))
            cbb = t.cellWidget(r, 3)
            cbb.setCurrentIndex(cbb.findData(blk))
        check("1) 기본값: 핫 ch1 압력 = 여수 ANs 와 같은 p_ans_cavity, 온도 tempcell1",
              t.cellWidget(0, 5).currentData() == "p_ans_cavity" and t.cellWidget(0, 6).currentData() == "tempcell1",
              (t.cellWidget(0, 5).currentData(), t.cellWidget(0, 6).currentData()))
        check("1) 이름 칸은 비어 있고 힌트만(사람이 정한다)",
              t.cellWidget(0, 4).text() == "" and t.cellWidget(0, 4).placeholderText() == "ANs",
              t.cellWidget(0, 4).placeholderText())

        dlg._check_raw(_raw(os.path.join(d, "2026-10-05-001 Hot.dat")))
        c0, c1 = t.cellWidget(0, 9).text(), t.cellWidget(1, 9).text()
        check("2) 밝은 블록: lit + 창 안 ✓", c0.startswith("lit") and "window inside ✓" in c0, c0)
        check("2) 어두운 블록: DARK", c1.startswith("DARK"), c1)

        try:
            dlg.collect()
            check("3) 이름 없으면 거부", False)
        except ValueError as e:
            check("3) 이름 없으면 거부", "cell name" in str(e), str(e))
        t.cellWidget(0, 4).setText("ANs")
        t.cellWidget(1, 4).setText("Cold")
        t.cellWidget(1, 3).setCurrentIndex(t.cellWidget(1, 3).findData("ch1"))
        try:
            dlg.collect()
            check("3) 같은 블록 두 번 거부", False)
        except ValueError as e:
            check("3) 같은 블록 두 번 거부", "twice" in str(e), str(e))
        t.cellWidget(1, 3).setCurrentIndex(t.cellWidget(1, 3).findData("ch2"))
        t.cellWidget(1, 8).setChecked(False)                     # ch2 는 R 안 함

        dlg.ed_name.setText("lab_test")
        dlg.dt_from.setDate(dlg.dt_from.date().fromString("2026-10-01", "yyyy-MM-dd"))
        ms = dlg.collect()
        check("4) 기본 프로파일 하나 = 미션 하나", len(ms) == 1 and ms[0]["base"] == "caesar_hot_base", ms)
        ch = ms[0]["channels"][0]
        check("4) cavity 온도 체인에 cell_heater 폴백", ch["cavity"]["temperature_hk"] == ["tempcell1", "cell_heater"],
              ch["cavity"])
        check("4) R 끈 채널은 reflectance 없음", ms[0]["channels"][1]["reflectance"] is None)
        man = dlg.build(os.path.join(d, "out"))
        check("4) 패키지 생성 + 출처", man["missions"] == ["mission_caesar_hot_base.json"] and man["provenance"],
              man.get("missions"))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\nmission export dialog tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
