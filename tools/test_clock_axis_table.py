"""`clock_axis_table` 자체검증 — 합성 데이터라 실측자료 없이 돈다.

무엇을 잡나
  1) 5분 빈 카운트가 지연을 제대로 되찾는가(결손이 있는 날).
  2) 결손 없는 평평한 날은 **동률로 실토**하는가 — 이게 가장 중요하다.
     조용히 아무 값이나 내놓으면 게이트 0 판정이 통째로 거짓이 된다.
  3) 최소 xlsx 리더가 날짜 서식 셀을 datetime 으로 돌려주는가.
"""
import datetime as dt
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clock_axis_table import best_lag, bin5, pick, read_sheet, score_candidates

T0 = dt.datetime(2026, 6, 5)


def _day(gap_bins=(), partial=None):
    """하루치 5분 빈 카운트.

    `gap_bins` 는 빈 자체가 없는 자리(결손), `partial` 은 {빈번호: 스캔수} 로 꽉 차지
    않은 자리. **지연을 가르는 건 partial 이다** — score_candidates 는 양쪽 다 값이
    있는 빈만 세므로, 결손은 한쪽(오른쪽) 커버리지로만 작용하고 값이 5 로 평평하면
    어떤 지연이든 자기 자신과 맞는다. 실측에서도 그래서 무결손일이 동률로 나온다.
    """
    out = {}
    for i in range(288):
        if i in gap_bins:
            continue
        out[T0 + dt.timedelta(minutes=5 * i)] = (partial or {}).get(i, 5)
    return out


PARTIAL = {7: 1, 63: 3, 64: 2, 119: 4, 175: 2, 176: 1, 200: 3, 244: 4,
           245: 2, 260: 1, 270: 3, 280: 4}


def test_best_lag_finds_shift():
    left = _day(gap_bins=tuple(range(30, 40)), partial=PARTIAL)
    for lag_h in (0, 9, -9, 3):
        right = {t + dt.timedelta(hours=lag_h): n for t, n in left.items()}
        lag, hit, tot = best_lag(left, right)
        assert lag == lag_h * 60, (lag_h, lag)
        assert hit == tot > 0


def test_flat_day_is_declared_a_tie():
    """스캔 수가 하루 내내 5 로 평평하면 9 h 를 밀어도 자기 자신과 맞는다.

    이 경우 `pick` 이 조용히 한쪽을 고르면 게이트 0 판정이 통째로 거짓이 된다.
    반드시 '동률'로 실토해야 한다."""
    flat = _day()
    cand = score_candidates(flat, flat)
    assert cand[0][0] == cand[0][1] > 0
    assert cand[-540][0] == cand[-540][1] > 0
    lag, note = pick(cand)
    assert lag is None and "동률" in note


def test_partial_day_resolves_uniquely():
    left = _day(partial=PARTIAL)
    right = {t - dt.timedelta(minutes=540): n for t, n in left.items()}
    cand = score_candidates(left, right)
    lag, note = pick(cand)
    assert lag == -540, (lag, note, cand)
    assert cand[0][0] < cand[0][1]          # 0 h 는 완전일치가 아니어야 한다


def test_pick_marks_weak_evidence():
    """겹치는 빈이 몇 개뿐이면 값은 내되 '(부분)' 으로 표시해 완전일치와 구분한다."""
    lag, note = pick({0: (5, 5), -540: (0, 0)})
    assert "부분" in note, note
    # 완전일치일 때는 그 표시가 없어야 한다
    assert "부분" not in pick({0: (160, 160), -540: (140, 160)})[1]


def test_read_sheet_dates(tmp_path=None):
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.xlsx")
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2" s="1"><v>46173.5</v></c><c r="B2"><v>4</v></c></row>'
             '</sheetData></worksheet>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/workbook.xml",
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
                   ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Data" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml",
                   '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<si><t>time</t></si><si><t>ans_n_valid</t></si></sst>')
        z.writestr("xl/styles.xml",
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<cellXfs><xf numFmtId="0"/><xf numFmtId="22"/></cellXfs></styleSheet>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    idx, rows = read_sheet(p)
    assert idx["time"] == 0 and idx["ans_n_valid"] == 1
    assert isinstance(rows[0][0], dt.datetime) and rows[0][1] == 4.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all passed")
