"""C1 회귀 검사 — 종 정책 테이블을 위젯으로 추출해도 계약이 그대로인가.

지키는 것:
  1. `RefPropertiesTable.get_properties()`가 넣은 정책을 **그대로** 돌려준다
     (Free/Limit/Fix/Link/Center 다섯 모드 전부). 여기가 틀리면 shift 정책이
     조용히 바뀌어 핏 결과가 달라진다.
  2. `RefPropertiesDialog.get_properties()`가 위젯과 **같은 값**을 준다 —
     기존 호출부(`app_window.open_ref_properties`)의 계약 불변.
  3. `set_gases()`로 가스 목록이 바뀌어도(레퍼런스 재락) 깨지지 않는다.
  4. Center 모드가 살아있다 — 0을 안 품는 Limit이 첫 스캔에서 죽는 문제의 해법이라
     (`fit_optimizer_handoff.md` §16) 추출 과정에서 빠뜨리면 안 된다.

    python tools/test_ref_properties_table.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # 헤드리스

from PyQt6.QtWidgets import QApplication

from gui.ref_properties_dialog import RefPropertiesDialog, RefPropertiesTable

GASES = ["NO2", "CHOCHO", "H2O", "O4"]
PROPS = {
    # 논문 방식: NO2를 맞추고 나머지는 그 값에 link
    "NO2":    {"sh_mode": "Center", "sh_val": "-5.25, 1.9", "sq_mode": "Fix",
               "sq_val": "1.0", "t_ref": 25.0, "t_coeff": 0.0, "active_bands_nm": ""},
    "CHOCHO": {"sh_mode": "Link", "sh_val": "NO2", "sq_mode": "Link", "sq_val": "NO2",
               "t_ref": 20.0, "t_coeff": 0.05, "active_bands_nm": "430,460"},
    "H2O":    {"sh_mode": "Limit", "sh_val": "-1.0, 1.0", "sq_mode": "Free",
               "sq_val": "Free", "t_ref": 25.0, "t_coeff": 0.0, "active_bands_nm": ""},
    "O4":     {"sh_mode": "Fix", "sh_val": "0.0", "sq_mode": "Fix", "sq_val": "1.0",
               "t_ref": 25.0, "t_coeff": 0.0, "active_bands_nm": "460,495"},
}


def _same(got, want, who):
    for gas, w in want.items():
        g = got[gas]
        for k, v in w.items():
            assert g[k] == v, f"{who}: {gas}.{k} = {g[k]!r}, expected {v!r}"


def test_widget_roundtrip():
    t = RefPropertiesTable(GASES, PROPS)
    _same(t.get_properties(), PROPS, "widget")
    assert t.table.rowCount() == 4 and t.table.columnCount() == 8


def test_center_mode_survives():
    """Center는 shift에만 있고 squeeze엔 없다(1.0 기준이라 불필요)."""
    t = RefPropertiesTable(GASES, PROPS)
    w = t.param_widgets["NO2"]
    assert [w["sh_cmb"].itemText(i) for i in range(w["sh_cmb"].count())] \
        == ["Free", "Limit", "Fix", "Link", "Center"]
    assert [w["sq_cmb"].itemText(i) for i in range(w["sq_cmb"].count())] \
        == ["Free", "Limit", "Fix", "Link"]
    assert t.get_properties()["NO2"]["sh_val"] == "-5.25, 1.9"


def test_link_excludes_self():
    """Link 콤보에 자기 자신이 있으면 안 된다(자기참조 무한루프)."""
    t = RefPropertiesTable(GASES, PROPS)
    for gas in GASES:
        c = t.param_widgets[gas]["sh_lnk"]
        assert gas not in [c.itemText(i) for i in range(c.count())], gas


def test_dialog_matches_widget():
    """다이얼로그는 위젯을 감싸기만 한다 — 값이 같아야 계약 불변."""
    d = RefPropertiesDialog(None, GASES, PROPS)
    _same(d.get_properties(), PROPS, "dialog")
    assert d.gas_list == GASES                 # 하위호환 프로퍼티
    assert d.table.rowCount() == 4
    assert set(d.param_widgets) == set(GASES)


def test_set_gases_rebuild():
    """레퍼런스를 다시 락하면 가스 목록이 바뀐다 — 재구성이 깨지면 안 된다."""
    t = RefPropertiesTable(GASES, PROPS)
    t.set_gases(["NO2", "H2O"], PROPS)
    got = t.get_properties()
    assert set(got) == {"NO2", "H2O"}, set(got)
    assert t.table.rowCount() == 2
    assert got["NO2"]["sh_mode"] == "Center"
    # 늘어나는 방향도
    t.set_gases(GASES, PROPS)
    assert set(t.get_properties()) == set(GASES)
    _same(t.get_properties(), PROPS, "after rebuild")


def test_unknown_gas_defaults():
    """props에 없는 가스는 DOASIS 기본값으로 — 빈 값이나 예외가 아니라."""
    t = RefPropertiesTable(["XX"], {})
    p = t.get_properties()["XX"]
    assert p["sh_mode"] == "Limit" and p["sq_mode"] == "Fix", p


def test_summary_line_shows_center():
    """한 줄 요약이 Center를 'Free'로 뭉개면 안 된다.

    예전 사다리는 Link/Limit/Fix가 아니면 전부 Free로 떨어져서 `Center -5.25, 1.9`가
    'Free'로 보였다 — 의미가 정확히 반대다(Free=제약 없음, Center=선언 중심에 앵커).
    RUN 직전 확인 다이얼로그도 이 함수를 쓰므로 밤샘 런의 마지막 검문이 거짓이 된다.
    """
    from gui.app_window import CAESARAnalyzer as A
    txt = A._shsq_text(GASES, PROPS)
    assert "Free" not in txt.split("H2O")[0], txt      # NO2·CHOCHO 구간에 Free가 없어야
    assert "NO2 Sh@-5.25,1.9" in txt, txt              # Center는 @중심,반폭
    assert "CHOCHO Sh→NO2" in txt, txt                 # Link는 →대상
    assert "H2O Sh[-1.0,1.0]" in txt, txt              # Limit는 [범위]
    assert "O4 Sh=0.0" in txt, txt                     # Fix는 =값
    assert "SqFree" in txt, txt                        # 진짜 Free는 Free
    # 모르는 모드는 Free로 속이지 않는다
    odd = A._shsq_text(["X"], {"X": {"sh_mode": "Wobble", "sh_val": "1"}})
    assert "?Wobble" in odd, odd


def main() -> int:
    # 반드시 참조를 붙잡아 둔다 — 표현식으로만 만들면 GC되어 프로세스가 죽는다.
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    for fn in (test_widget_roundtrip, test_center_mode_survives,
               test_link_excludes_self, test_dialog_matches_widget,
               test_set_gases_rebuild, test_unknown_gas_defaults,
               test_summary_line_shows_center):
        fn()
        print(f"  PASS  {fn.__name__}")
    print("ref properties table self-check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
