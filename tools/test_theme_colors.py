"""Augur 그래프 색 단일 출처(gui/theme.py, 2026-10-01) — 창마다 팔레트가 다시 갈라지지 않게.

예전엔 같은 CH1 이 모니터 #1f77b4(tab10) · R 대화상자/결과 뷰어 #2196F3(Material)였고, 결과 뷰어
농도 그래프는 기체 순서로 색을 돌려 써 NO₂ 가 창마다 달랐다. 지키는 것:
1. 모니터·R 대화상자·결과 뷰어·Plot Maker 가 theme 의 값을 그대로 쓴다.
2. Plot Maker 자동 배색(validate_plotmaker 가 고정한 확정색)이 theme 의 기체 색과 같다.
3. 모르는 기체의 해시 배색은 이름 있는 기체 색을 피한다.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])

from gui import theme

_n_pass = _n_fail = 0


def check(label, ok, detail=""):
    global _n_pass, _n_fail
    if ok:
        _n_pass += 1
        print(f"  PASS  {label}")
    else:
        _n_fail += 1
        print(f"  FAIL  {label}  {detail}")


def main():
    print("[1] 채널 색 — 창마다 같은 값")
    from gui import monitor_widget, ui_dialogs_r
    check("모니터 농도 탭 CH1..3 = theme",
          monitor_widget.MonitorWidget._CONC_CH_COLORS == {c: theme.channel_color(c) for c in (1, 2, 3)},
          str(monitor_widget.MonitorWidget._CONC_CH_COLORS))
    check("R 대화상자 채널 목록 = theme.CHANNELS", list(ui_dialogs_r._CH_COLORS) == list(theme.CHANNELS))
    check("channel_color 순환", theme.channel_color(len(theme.CHANNELS) + 1) == theme.channel_color(1))

    print("[2] 기체 색 — Plot Maker 자동 배색과 같은 출처")
    from gui.ui_plot_maker import core as pm_core
    from gui import ui_result_viewer
    check("Plot Maker 범용 팔레트 = theme.SERIES", list(pm_core._PALETTE) == list(theme.SERIES))
    check("결과 뷰어 팔레트 = theme.SERIES", list(ui_result_viewer._PALETTE) == list(theme.SERIES))
    sp = {k: v for k, v in theme.SPECIES.items() if k != "no2"}
    found = [v for v in vars(pm_core).values() if isinstance(v, type) and hasattr(v, "_SPECIES_COLORS")]
    check("Plot Maker 종 색 = theme.SPECIES", bool(found) and all(c._SPECIES_COLORS == sp for c in found),
          f"{len(found)} classes")
    for name in ("NO2", "NO2 (CH1)", "chocho", "H2O", "O4", "O3"):
        base = name.lower().split("(")[0].strip()
        check(f"species_color({name!r})", theme.species_color(name) == theme.SPECIES[base])

    print("[3] 모르는 기체는 이름 있는 기체 색을 피한다")
    for name in ("IO", "HONO", "SO2", "BrO", "HCHO", "OClO"):
        c = theme.species_color(name)
        check(f"{name} → {c}", c not in theme.SPECIES.values() and theme.species_color(name) == c)

    print(f"\n{_n_pass} PASS · {_n_fail} FAIL")
    sys.exit(1 if _n_fail else 0)


if __name__ == "__main__":
    main()
