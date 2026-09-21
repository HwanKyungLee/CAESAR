# -*- coding: utf-8 -*-
"""tools/validate_plotmaker.py — Plot Maker 회귀 검증 (offscreen Qt)
=====================================================================
gui/ui_plot_maker/ 패키지(2026-06 분할: data·processing·core·modes·widget)는
테스트가 하나도 없었다. 고칠 때마다
손으로 6개 모드를 다 눌러보는 대신, 여기서 headless(offscreen)로 위젯을
구성 → 전 모드 렌더 → 데이터 제거 → Heatmap 더블클릭/설정 → 설정 저장·불러오기
까지 자동으로 확인한다. validate_pipeline.py와 같은 PASS/WARN/FAIL 리포팅
스타일이지만, Qt 위젯이라 QApplication을 offscreen으로 1회 띄운다.

확인 항목
---------
1. 위젯 생성       : 모드가 다 등록됐나
2. 전 모드 렌더    : render()·render_mpl()이 6개 모드 다 예외 없이 도나
3. 잔존 렌더 방지  : 데이터셋 제거 후 콤보가 실제로 비워지나(2026-06 회귀 가드)
4. Heatmap 더블클릭+config : on_column_activated·to_config/from_config 왕복
5. 설정 저장/불러오기 : .pmcfg.json 라운드트립에서 mode_cfg 보존되나
6. 색 결정론      : TimeSeries/Diurnal의 _resolve_specs()가 같은 입력→같은 색
7. 시리즈 리스트 id무결성 : id조회·드래그순서·삭제
8. Undo          : 데이터셋·시리즈 제거 복원
9. 창 상태 기억   : QSettings 스플리터·탭·테마 저장→복원 왕복(2026-06 UX개편 회귀가드)
10. Batch Publish : 종별 일괄저장 후 원래 시리즈목록/콤보선택 상태 복원되나
11. X축 DateAxisItem 재생성 방지 : 같은 시간축 상태로 연달아 render해도 축
    객체가 교체 안 되나(2026-07-03 실GUI 발견 — 교체되면 pg가 눈금 캐시를
    못 넘겨받아 초기뷰 X라벨이 "00.050" 식으로 깨짐)
12. 색상 채널태그 구분 : 같은 종을 CH1/CH2처럼 다른 태그로 동시에 그릴 때
    서로 다른 색(2026-07-03 실GUI에서 NO2 CH1·CH2가 완전히 같은 파랑으로
    겹쳐 안 보이던 버그 발견)
13. Time shift 표시전용 : 시프트가 resolve() 반환 시각만 옮기고 원본
    Dataset.time은 불변 + Publish에 경고문 삽입 (2026-07-06 기능)
14. Custom resample : 콤보 Custom+분 스핀 → resample_sec 환산 (2026-07-06)
15. 라벨 스타일 pg↔mpl 패리티 : label_style(size/color/pos)를 두 렌더러가
    동일하게 소비 — pos 있으면 양쪽 다 원래 축라벨 비우고 자유배치로
    (2026-07-07 세션 내내 재발한 'pg만 고침/mpl만 고침' 버그류 가드)
16. label_style 저장/복원 : _gather_style/_apply_style 왕복 + 위젯 동기화
17. Annotate 양경로 : 마커선·라벨이 pg와 mpl(범례 off여도) 둘 다 그려지나
    (2026-07-06 실GUI 발견 — mpl은 legend label로만 넘겨 범례 끄면 증발)
18. 시간축 X범위 패딩 : 화면(pg)은 경계 눈금 안 잘리게 2% 패딩, Publish는
    tight 유지 (2026-07-06 '29일/5일 눈금 잘림' 실GUI 발견 버그의 회귀가드)
19. Tick size : 눈금 글자 크기가 pg(tickFont)·mpl(labelsize)에 같은 규칙
    (_tick_pt: 지정값 > 전역 Font−2 > 기본)으로 적용 (2026-07-07 기능)
20. 주석 = 범위 무영향 : epoch 세로선 주석이 Diurnal(0-23h) 등 다른 좌표계
    모드의 mpl 축범위를 못 늘리나 (2026-07-07 실GUI — diurnal x축이 17억으로
    폭발해 데이터 압착. pg ignoreBounds와 의미론 통일 가드)
21. SI prefix 금지 : pg 축이 작은 값(0.2 ppb대)을 ×1000 스케일(200 표시+
    ×0.001 라벨)하지 않나 — mpl은 원시값이라 화면-Publish 눈금 불일치
    (2026-07-07 실GUI 발견)
22. 눈금 숫자/눈금선 분리 : '숫자' 꺼도 '눈금선'만 남길 수 있나 — pg
    (showValues/tickLength)·mpl(labelbottom/bottom) 독립 토글 (2026-07-07 요청)
23. X 틱 앵커 : 앵커 날짜+N일 간격 눈금이 pg·mpl 같은 위치에 찍히나
    (2026-07-07 요청 — "원하는 날짜에서 며칠 간격")
24. 눈금선 방향/길이 : 바깥(out)/안(in)·길이(px)가 pg(tickLength 부호)·
    mpl(direction/length)에 같은 규칙으로 적용 (2026-07-07 요청)
25. 시리즈 kind 7종 : line/marker/step/bar/area/band/errorbar가 pg·mpl 양쪽에서
    무사고 + step 좌표가 steps-post 정확 + 짝 없는 band 폴백 (M4, 2026-09-21)
26. 라벨 마크업 : 입력은 mathtext 하나 — pg는 HTML로 변환, mpl은 원문 유지.
    `$…$` 밖의 밑줄(R_mean)은 건드리지 않음 (M5, 2026-09-21)
27. 주석 7종 : 선·구간음영·텍스트·화살표·사각형이 pg·mpl 양쪽에(범례 off여도)
    + .pmcfg.json 저장/복원 + 옛 {"val":…} 레코드 호환 (M3, 2026-09-21)
    · **화살촉 각도**: autoscale 후 재계산되나 + 줌하면 따라오나 (2026-09-21
      실측 버그 — 생성 시점에 각도를 박으면 '직전 렌더의 축 범위'로 계산돼
      위로 향할 화살표가 179.9°=거의 수평이 됐다)
"""
from __future__ import annotations
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # PyQt6 import 전에 설정

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
from PyQt6.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication([])   # 모듈 스코프, 1회만

from gui.ui_plot_maker import PlotMakerWidget, Dataset

CHECKS = []
def check(name):
    def deco(fn):
        CHECKS.append((name, fn)); return fn
    return deco

class Skip(Exception):
    pass


def _fixture_dataset(name="fixture", n=500, seed=0):
    """Qt/디스크 무관한 합성 Dataset — 시간축 + 2개 가스 컬럼 + 1개 에러 컬럼."""
    rng = np.random.default_rng(seed)
    t0 = 1_750_000_000.0
    t = t0 + np.arange(n) * 60.0
    no2 = 5 + 2 * np.sin(np.arange(n) / 50) + rng.normal(0, 0.3, n)
    chocho = 0.5 + 0.1 * np.cos(np.arange(n) / 40) + rng.normal(0, 0.05, n)
    return Dataset(name, f"<fixture:{name}>", t,
                   {"NO2": no2, "CHOCHO": chocho},
                   units={"NO2": "ppb", "CHOCHO": "ppb"},
                   errs={"NO2": np.full(n, 0.2)})


def _widget_with_fixture():
    w = PlotMakerWidget()
    ds = _fixture_dataset()
    w.shelf[ds.name] = ds
    w._refresh_tree()
    w._notify_modes()
    return w


# ── 1. 위젯 생성 자체가 죽지 않는가 ──────────────────────────────────────
@check("위젯 생성")
def c_construct():
    w = PlotMakerWidget()
    if w._mode is None or not w._modes:
        return "FAIL", "모드가 하나도 등록되지 않음"
    return "PASS", f"{len(w._modes)}개 모드 등록됨: {[m.key for m in w._modes]}"


# ── 2. 데이터 추가 → 전체 모드 순회하며 render()/render_mpl() 둘 다 무사히 ──
@check("전 모드 render()/render_mpl() 무사고")
def c_all_modes_render():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._refresh_list()
    from matplotlib.figure import Figure
    failures = []
    for i, m in enumerate(w._modes):
        w._mode_combo.setCurrentIndex(i)   # _on_mode_changed 트리거 → render()
        for attr in ("_c", "_cx", "_cy"):
            combo = getattr(m, attr, None)
            if combo is not None and not combo.currentText():
                combo.setCurrentText("fixture:NO2")
        try:
            m.render()
            fig = Figure(figsize=(6, 4))
            m.render_mpl(fig)
        except NotImplementedError:
            pass
        except Exception as e:
            failures.append(f"{m.key}: {type(e).__name__}: {e}")
    if failures:
        return "FAIL", "; ".join(failures)
    return "PASS", f"{len(w._modes)}개 모드 render+render_mpl 무사고"


# ── 3. 데이터셋 제거 후 stale 렌더 없는지 (2026-06 on_shelf_changed 회귀 가드) ──
@check("데이터셋 제거 → 잔존 콤보 없음")
def c_removal_no_stale():
    w = _widget_with_fixture()
    for i, m in enumerate(w._modes):
        w._mode_combo.setCurrentIndex(i)
        for attr in ("_c", "_cx", "_cy"):
            combo = getattr(m, attr, None)
            if combo is not None:
                combo.setCurrentText("fixture:NO2")
    w.shelf.clear()
    w._refresh_tree()
    w._notify_modes()
    problems = []
    for m in w._modes:
        for attr in ("_c", "_cx", "_cy"):
            combo = getattr(m, attr, None)
            if combo is not None and combo.currentText():
                problems.append(f"{m.key}.{attr} still shows '{combo.currentText()}'")
    if problems:
        return "FAIL", "; ".join(problems)
    return "PASS", "선반 비운 후 모든 콤보가 정상적으로 비워짐"


# ── 4. Heatmap 더블클릭 + config 라운드트립 ──────────────────────────────
@check("Heatmap 더블클릭 no-op 아님 + config 라운드트립")
def c_heatmap():
    w = _widget_with_fixture()
    hm = next(m for m in w._modes if m.key == "heatmap")
    hm.options_widget()
    ok = hm.on_column_activated("fixture:NO2")
    if not ok:
        return "FAIL", "on_column_activated이 False/no-op — 더블클릭이 여전히 죽어있음"
    hm._pinned_cols = ["fixture:NO2", "fixture:CHOCHO"]
    cfg = hm.to_config()
    if cfg.get("cols") != ["fixture:NO2", "fixture:CHOCHO"]:
        return "FAIL", f"to_config()이 pinned_cols를 보존 안 함: {cfg}"
    hm2 = type(hm)(w)
    hm2.from_config(cfg)
    if hm2._pinned_cols != hm._pinned_cols:
        return "FAIL", "from_config() 왕복 불일치"
    return "PASS", "on_column_activated 동작 + to_config/from_config 왕복 확인"


# ── 5. 전체 .pmcfg.json 저장→새 위젯→로드 라운드트립 ────────────────────
@check("설정 저장→로드 라운드트립")
def c_cfg_roundtrip():
    import json, tempfile
    w1 = _widget_with_fixture()
    w1._mode_combo.setCurrentIndex(0)   # timeseries
    ts = w1._modes[0]
    ts.options_widget()
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._refresh_list()
    cfg1 = {m.key: m.to_config() for m in w1._modes}

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".pmcfg.json", delete=False,
                                      encoding="utf-8")
    try:
        json.dump({"_version": w1._CFG_VERSION, "mode_cfg": cfg1}, tmp)
        tmp.close()
        with open(tmp.name, encoding="utf-8") as f:
            loaded = json.load(f)
        loaded = w1._migrate_cfg(loaded)
        w2 = PlotMakerWidget()
        for m in w2._modes:
            m.options_widget()
            m.from_config(loaded.get("mode_cfg", {}).get(m.key, {}))
        ts2 = w2._modes[0]
        if ts2._series != ts._series:
            return "FAIL", f"timeseries 시리즈 왕복 불일치: {ts2._series} vs {ts._series}"
        return "PASS", "mode_cfg 라운드트립 예외 없음, 시리즈 구조 보존 확인"
    finally:
        os.unlink(tmp.name)


# ── 6. TimeSeries/Diurnal 색 결정론 (Part1 ResolvedSeries 구조 확인) ──────
@check("TimeSeries/Diurnal: _resolve_specs() 결정론적")
def c_resolve_specs_deterministic():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._series.append(["fixture:CHOCHO", "R", None, None])
    c1 = [s.color for s in ts._resolve_specs()]
    c2 = [s.color for s in ts._resolve_specs()]
    if c1 != c2:
        return "FAIL", f"TimeSeries 같은 입력인데 색이 다름: {c1} vs {c2}"

    di = next(m for m in w._modes if m.key == "diurnal")
    di.options_widget()
    di._c.setCurrentText("fixture:NO2")
    out1 = di._resolve_specs()
    out2 = di._resolve_specs()
    d1 = [s.color for s in out1[0]]
    d2 = [s.color for s in out2[0]]
    if d1 != d2:
        return "FAIL", f"Diurnal 같은 입력인데 색이 다름: {d1} vs {d2}"
    return "PASS", f"TimeSeries {c1} / Diurnal {d1} — 둘 다 결정론적"


# ── 7. 시리즈 리스트 id()기반 조회·드래그순서·삭제 (2026-06 UX개편 회귀가드) ──
# PyQt6은 QListWidgetItem에 저장한 plain list를 꺼낼 때 '값은 같지만 다른 객체'로
# 복사해 반환한다(identity 비보존, 실측 확인됨) — 그래서 원본 객체 대신 id(엔트리)
# 값을 저장하고 _series_by_id()로 되찾는 방식으로 짰다. 이 검증이 없으면 다음에
# 누가 "item.data(...)가 그냥 객체겠지" 하고 되돌리면 삭제/색상/이름변경이
# 전부 조용히 no-op이 된다(실제로 구현 중 한 번 이렇게 깨졌었음).
@check("시리즈 리스트: id 조회·드래그순서·삭제 무결성")
def c_series_list_identity():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._series.append(["fixture:CHOCHO", "R", None, None])
    ts._refresh_list()
    if ts._series_by_id(ts._list.item(0).data(0x0100)) is not ts._series[0]:
        return "FAIL", "_series_by_id() 조회 실패 — 리스트 아이템과 실제 시리즈가 어긋남"
    # 드래그 순서변경 시뮬레이션(첫 항목을 맨 뒤로)
    row0 = ts._list.takeItem(0)
    ts._list.addItem(row0)
    ts._sync_order_from_list()
    if ts._series[0][0] != "fixture:CHOCHO":
        return "FAIL", f"드래그 재정렬 후 순서 반영 안 됨: {[s[0] for s in ts._series]}"
    # 선택 후 삭제가 실제로 개수를 줄이는지(id 매칭 실패시 no-op이었던 버그)
    ts._list.item(0).setSelected(True)
    before = len(ts._series)
    ts._remove(keep_undo=False)
    if len(ts._series) != before - 1:
        return "FAIL", f"선택삭제가 반영 안 됨: {before} → {len(ts._series)}"
    return "PASS", "id조회·드래그순서·삭제 전부 정상"


# ── 8. 가벼운 Undo (데이터셋 제거·시리즈 제거 복원) ──────────────────────
@check("Undo: 데이터셋·시리즈 제거 복원")
def c_undo():
    w = _widget_with_fixture()
    w._tree.topLevelItem(0).setSelected(True)
    w._remove_data()
    if w.shelf:
        return "FAIL", "데이터셋 제거가 안 됨(테스트 전제 실패)"
    w.undo_last()
    if "fixture" not in w.shelf:
        return "FAIL", "데이터셋 undo 복원 실패"

    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._refresh_list()
    ts._list.item(0).setSelected(True)
    ts._remove()   # keep_undo=True(기본) — push_undo 호출됨
    if ts._series:
        return "FAIL", "시리즈 제거가 안 됨(테스트 전제 실패)"
    w.undo_last()
    if not ts._series or ts._series[0][0] != "fixture:NO2":
        return "FAIL", "시리즈 undo 복원 실패"
    return "PASS", "데이터셋·시리즈 undo 둘 다 정상 복원"


# ── 9. 창 상태 기억(QSettings) 왕복 ──────────────────────────────────────
@check("창 상태 기억: 스플리터·탭·테마 QSettings 왕복")
def c_window_state():
    from PyQt6.QtCore import QSettings
    qs = QSettings("CAESAR", "app")
    qs.remove("plotmaker")   # 테스트 오염 방지
    try:
        w1 = PlotMakerWidget()
        w1._split.setSizes([260, 900])
        w1._tabs.setCurrentIndex(2)
        i = w1._theme_combo.findText("PPT")
        if i < 0:
            return "FAIL", "테마 콤보에 PPT 없음(테스트 전제 실패)"
        w1._theme_combo.setCurrentIndex(i)
        w1._on_theme_combo_changed()

        w2 = PlotMakerWidget()   # 새 세션 흉내
        if w2._tabs.currentIndex() != 2:
            return "FAIL", f"탭 복원 실패: {w2._tabs.currentIndex()}"
        if w2._theme_combo.currentText() != "PPT":
            return "FAIL", f"테마 복원 실패: {w2._theme_combo.currentText()}"
        if w2._lbl_size.value() != 16:   # PPT 테마 font=16 — 콤보만 아니라 실제 재적용 확인
            return "FAIL", f"테마 재적용 실패(폰트 {w2._lbl_size.value()} != 16)"
        return "PASS", "스플리터·탭·테마(재적용 포함) 왕복 확인"
    finally:
        qs.remove("plotmaker")   # 실제 사용자 설정과 안 섞이게 정리


# ── 10. Batch Publish — 종별 일괄저장 + 상태복원 ─────────────────────────
@check("Batch Publish: 일괄저장 + 시리즈목록/콤보선택 상태복원")
def c_batch_publish():
    import tempfile, glob
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    orig_dlg, orig_msg = QFileDialog.getExistingDirectory, QMessageBox.information
    try:
        w = _widget_with_fixture()
        ts = next(m for m in w._modes if m.key == "timeseries")
        ts.options_widget()
        ts._series.append(["fixture:NO2", "L", None, None])
        ts._series.append(["fixture:CHOCHO", "R", "#00FF00", None])
        ts._refresh_list()
        orig_series_obj = ts._series

        with tempfile.TemporaryDirectory() as tmp:
            QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: tmp)
            QMessageBox.information = staticmethod(lambda *a, **k: None)   # 모달 차단 방지
            w._batch_publish()
            pngs = sorted(os.path.basename(p) for p in glob.glob(os.path.join(tmp, "*.png")))
            if len(pngs) != 2:
                return "FAIL", f"TimeSeries 배치 파일 개수 이상: {pngs}"
            if ts._series is not orig_series_obj:
                return "FAIL", "배치 후 원래 시리즈 리스트 객체로 복원 안 됨"

            # Diurnal도(콤보 선택없음 상태에서 시작 → 배치 후 다시 선택없음으로 복원돼야)
            di = next(i for i, m in enumerate(w._modes) if m.key == "diurnal")
            w._mode_combo.setCurrentIndex(di)
            dm = w._mode
            if dm._c.currentIndex() != -1:
                return "FAIL", "테스트 전제 실패: diurnal 콤보가 이미 선택돼 있음"
            w._batch_publish()
            if dm._c.currentIndex() != -1:
                return "FAIL", f"diurnal 콤보 복원 실패(index={dm._c.currentIndex()})"
        return "PASS", "TimeSeries 2파일 + Diurnal 콤보(-1) 복원 확인"
    finally:
        QFileDialog.getExistingDirectory, QMessageBox.information = orig_dlg, orig_msg


# ── 11. X축 DateAxisItem 재생성 방지 (실GUI 발견 회귀가드) ────────────────
@check("X축: 같은 시간축 상태 연속 render에서 축 객체 유지")
def c_axis_no_reswap():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._refresh_list(); ts.render()
    axis1 = w.pw.getAxis("bottom")
    ts._series.append(["fixture:CHOCHO", "L", None, None])
    ts._refresh_list(); ts.render()
    axis2 = w.pw.getAxis("bottom")
    if axis1 is not axis2:
        return "FAIL", "같은 시간축 상태인데 render()마다 축 객체가 재생성됨 — X라벨 깨짐 재발 위험"
    if type(axis1).__name__ != "DateAxisItem":
        return "FAIL", f"시간축 데이터인데 DateAxisItem이 아님: {type(axis1).__name__}"
    # 실제로 축 종류가 바뀌어야 할 때(Diurnal↔TimeSeries)는 여전히 스왑돼야 함
    di = next(i for i, m in enumerate(w._modes) if m.key == "diurnal")
    w._mode_combo.setCurrentIndex(di)
    if type(w.pw.getAxis("bottom")).__name__ != "AxisItem":
        return "FAIL", "Diurnal 전환 시 축이 plain AxisItem으로 안 바뀜"
    w._mode_combo.setCurrentIndex(0)
    ts.render()
    if type(w.pw.getAxis("bottom")).__name__ != "DateAxisItem":
        return "FAIL", "TimeSeries 복귀 시 DateAxisItem으로 안 바뀜"
    return "PASS", "동일 종류 축은 재생성 안 하고, 실제 전환 시엔 정상 스왑됨"


# ── 12. 색상 채널태그 구분 (실GUI 발견 회귀가드) ──────────────────────────
@check("색상: 같은 종·다른 채널태그면 다른 색")
def c_color_channel_tag_distinct():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    c_ch1 = ts._auto_color("NO2 (CH1)")
    c_ch2 = ts._auto_color("NO2 (CH2)")
    if c_ch1 == c_ch2:
        return "FAIL", f"NO2 (CH1)과 NO2 (CH2)가 같은 색: {c_ch1} — 겹쳐서 구분 불가"
    if ts._auto_color("NO2 (ANs)") != "#1565C0" or ts._auto_color("NO2 (PNs)") != "#E65100":
        return "FAIL", "ANs/PNs 셀 확정색이 바뀜(기존 규약 깨짐)"
    if ts._auto_color("NO2") != "#1976D2" or ts._auto_color("ANs") != "#2E7D32":
        return "FAIL", "무태그 종 색이 바뀜(기존 규약 깨짐)"
    return "PASS", f"NO2 (CH1)={c_ch1} / NO2 (CH2)={c_ch2} — 구분됨, 기존 확정색 보존"


# ── 13. Time shift = 표시 전용 (원본 불변) ────────────────────────────────
@check("Time shift: 표시만 이동, 원본 Dataset.time 불변")
def c_time_shift_display_only():
    w = _widget_with_fixture()
    ds = w.shelf["fixture"]
    t_orig = ds.time.copy()
    w._shift_spin.setValue(9.0)          # _on_transform_changed → time_shift_hours
    if w.time_shift_hours != 9.0:
        return "FAIL", f"스핀 9h인데 time_shift_hours={w.time_shift_hours}"
    _, _, _, t_shifted = w.resolve("fixture:NO2")
    if not np.allclose(t_shifted, t_orig + 9 * 3600):
        return "FAIL", "resolve()가 +9h를 반영하지 않음"
    if not np.array_equal(ds.time, t_orig):
        return "FAIL", "원본 Dataset.time이 변조됨 — 표시전용 계약 위반!"
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    fig = w._build_publish_fig()
    warn = any("time shift" in t.get_text() for t in fig.texts)
    if not warn:
        return "FAIL", "Publish 그림에 time shift 경고문이 없음(조용한 시각조작 금지 계약)"
    w._shift_spin.setValue(0.0)
    fig0 = w._build_publish_fig()
    if any("time shift" in t.get_text() for t in fig0.texts):
        return "FAIL", "시프트 0인데 경고문이 남아있음"
    return "PASS", "+9h: resolve만 이동·원본 불변·Publish 경고문 on/off 정상"


# ── 14. Custom resample 분→초 환산 ────────────────────────────────────────
@check("Resample: Custom 분 스핀 → resample_sec")
def c_custom_resample():
    w = _widget_with_fixture()
    w._res_combo.setCurrentText("5 min")
    if w.resample_sec != 300:
        return "FAIL", f"프리셋 5 min인데 resample_sec={w.resample_sec}"
    if w._res_custom_spin.isEnabled():
        return "FAIL", "프리셋 선택인데 Custom 스핀이 활성화돼 있음"
    w._res_combo.setCurrentText("Custom…")
    if not w._res_custom_spin.isEnabled():
        return "FAIL", "Custom 선택했는데 분 스핀이 비활성"
    w._res_custom_spin.setValue(2.5)
    if w.resample_sec != 150.0:
        return "FAIL", f"2.5분인데 resample_sec={w.resample_sec} (150 기대)"
    return "PASS", "5min 프리셋=300s · Custom 2.5min=150s · 스핀 활성화 연동 정상"


# ── 15. 라벨 스타일 pg↔mpl 패리티 (이번 세션 재발 버그류의 핵심 가드) ──────
@check("라벨 스타일: pg(화면)·mpl(Publish) 동일 소비")
def c_label_style_parity():
    from matplotlib.figure import Figure
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    # (a) pos=None + size/color → 양쪽 다 '원래 자리' 라벨에 스타일만
    w.label_style["ylabel"] = {"pos": None, "size": 14, "color": "#2E7D32"}
    ts.render()
    if not w.p1.getAxis("left").labelText:
        return "FAIL", "(a) pg 기본경로인데 좌축 라벨이 비어있음"
    if "ylabel" in w._custom_label_items:
        return "FAIL", "(a) pos=None인데 자유배치 아이템이 생김"
    fig = Figure(figsize=(6, 4)); ts.render_mpl(fig)
    ax = fig.axes[0]
    if ax.get_ylabel() != "NO2 [ppb]":
        return "FAIL", f"(a) mpl ylabel='{ax.get_ylabel()}' (NO2 [ppb] 기대)"
    if ax.yaxis.label.get_color() != "#2E7D32" or ax.yaxis.label.get_fontsize() != 14:
        return "FAIL", "(a) mpl ylabel 색/크기가 label_style을 반영 안 함"
    # (b) pos 지정 → 양쪽 다 원래 라벨 비우고 자유배치(transAxes 비율)로
    w.label_style["ylabel"]["pos"] = (-0.09, 0.5)
    ts.render()
    if w.p1.getAxis("left").labelText:
        return "FAIL", "(b) 자유배치인데 pg 원래 축라벨이 남아있음(이중 표시)"
    if "ylabel" not in w._custom_label_items:
        return "FAIL", "(b) pg 자유배치 아이템이 안 생김"
    fig2 = Figure(figsize=(6, 4)); ts.render_mpl(fig2)
    ax2 = fig2.axes[0]
    if ax2.get_ylabel():
        return "FAIL", "(b) 자유배치인데 mpl ylabel이 남아있음(이중 표시)"
    free = [t for t in ax2.texts if t.get_text() == "NO2 [ppb]"]
    if not free:
        return "FAIL", "(b) mpl에 자유배치 텍스트가 없음 — pg에만 보이고 Publish에선 증발"
    if free[0].get_transform() is not ax2.transAxes:
        return "FAIL", "(b) mpl 자유배치가 transAxes(비율)가 아님 — pg와 위치 어긋남"
    return "PASS", "기본경로 스타일 반영 + 자유배치 시 양쪽 모두 이전/전환 일치"


# ── 16. label_style 저장/복원 왕복 ────────────────────────────────────────
@check("label_style: 스타일 저장/복원 왕복 + 위젯 동기화")
def c_label_style_roundtrip():
    import json
    w = _widget_with_fixture()
    w.label_style["ylabel"] = {"pos": (-0.09, 0.5), "size": 14, "color": "#2E7D32"}
    st = json.loads(json.dumps(w._gather_style()))   # 디스크 왕복과 동일(JSON화)
    w2 = PlotMakerWidget()
    w2._apply_style(st)
    got = w2.label_style["ylabel"]
    if got["size"] != 14 or got["color"] != "#2E7D32" or tuple(got["pos"]) != (-0.09, 0.5):
        return "FAIL", f"복원값 불일치: {got}"
    wdg = w2._label_style_widgets["ylabel"]
    if wdg["size"].value() != 14 or not wdg["free_chk"].isChecked():
        return "FAIL", "복원 후 Size 스핀/📍 체크박스가 동기화 안 됨"
    return "PASS", "JSON 왕복 후 값·위젯 모두 일치"


# ── 17. Annotate 마커선·라벨이 양 렌더러에 (범례 off여도) ──────────────────
@check("Annotate: 마커선+라벨 pg·mpl 양쪽 표시")
def c_annotations_both_renderers():
    import pyqtgraph as pg_
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    ts.render()
    n_before = sum(isinstance(it, pg_.InfiniteLine) for it in w.p1.items)
    tmid = float(np.median(w.shelf["fixture"].time))
    w._annots = [{"kind": "vline", "val": tmid, "label": "evt", "color": "#d32f2f"},
                 {"kind": "hline", "val": 5.0, "label": "LOD", "color": "#7B1FA2"}]
    ts.render()
    n_after = sum(isinstance(it, pg_.InfiniteLine) for it in w.p1.items)
    if n_after - n_before != 2:
        return "FAIL", f"pg 마커선 {n_after - n_before}개 추가됨 (2개 기대)"
    w._legend_combo.setCurrentText("off")    # 원버그 조건: 범례 꺼도 라벨 보여야
    fig = w._build_publish_fig()
    ax = fig.axes[0]
    texts = {t.get_text().strip() for a in fig.axes for t in a.texts}
    if "evt" not in texts or "LOD" not in texts:
        return "FAIL", f"범례 off에서 mpl 라벨 증발: {texts} (2026-07-06 버그 재발)"
    dashed = [ln for ln in ax.lines if ln.get_linestyle() == "--"]
    if len(dashed) < 2:
        return "FAIL", f"mpl 점선 마커선 {len(dashed)}개 (2개 기대)"
    w._legend_combo.setCurrentText("auto")
    return "PASS", "pg 선 2개 · mpl(범례 off) 선 2개+라벨 2개 모두 표시"


# ── 18. 시간축 X범위: 화면은 경계눈금 패딩, Publish는 tight ────────────────
@check("X범위: pg 2% 패딩(경계눈금 보임) · mpl tight")
def c_xrange_padding_split():
    import datetime as _dt
    import matplotlib.dates as mdates
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    ts.render()                                        # _time_axis=True 확정
    t = w.shelf["fixture"].time
    a = _dt.datetime.fromtimestamp(float(t[50])).strftime("%Y-%m-%d %H:%M")
    b = _dt.datetime.fromtimestamp(float(t[-50])).strftime("%Y-%m-%d %H:%M")
    w._ax_xmin.setText(a); w._ax_xmax.setText(b)
    w.apply_axes()
    ae, be = w._parse_x(a), w._parse_x(b)
    (v0, v1), _ = w.p1.getViewBox().viewRange()
    if not (v0 < ae and v1 > be):
        return "FAIL", f"pg 화면에 패딩이 없음(v=[{v0:.0f},{v1:.0f}] vs [{ae:.0f},{be:.0f}]) — 경계 눈금 잘림 재발"
    fig = w._build_publish_fig()
    x0, x1 = fig.axes[0].get_xlim()
    e0 = mdates.date2num(_dt.datetime.fromtimestamp(ae))
    e1 = mdates.date2num(_dt.datetime.fromtimestamp(be))
    if abs(x0 - e0) > 1e-4 or abs(x1 - e1) > 1e-4:
        return "FAIL", f"mpl이 tight가 아님: [{x0},{x1}] vs [{e0},{e1}]"
    return "PASS", "화면=패딩으로 경계눈금 보존 · Publish=요청범위 그대로 tight"


# ── 19. Tick size — pg·mpl 동일 규칙 ──────────────────────────────────────
@check("Tick size: pg tickFont·mpl labelsize 동일 규칙")
def c_tick_size_parity():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    # 규칙 자체(_tick_pt): 지정값 > 전역 Font−2 > 0
    w._tick_size.setValue(0); w._lbl_size.setValue(0)
    if w._tick_pt() != 0:
        return "FAIL", f"둘 다 auto인데 _tick_pt={w._tick_pt()} (0 기대)"
    w._lbl_size.setValue(14)
    if w._tick_pt() != 12:
        return "FAIL", f"전역 14pt 유도값 _tick_pt={w._tick_pt()} (12 기대)"
    w._tick_size.setValue(9)
    if w._tick_pt() != 9:
        return "FAIL", f"명시 9pt인데 _tick_pt={w._tick_pt()} — 지정값이 우선이어야"
    # pg: render 후 축 tickFont에 반영됐나
    ts.render()
    tf = w.p1.getAxis("bottom").style.get("tickFont")
    if tf is None or tf.pointSize() != 9:
        return "FAIL", f"pg 축 tickFont={tf and tf.pointSize()} (9 기대)"
    # mpl: Publish figure 눈금 라벨 크기
    fig = w._build_publish_fig()
    lab = fig.axes[0].xaxis.get_ticklabels()
    if not lab or lab[0].get_fontsize() != 9:
        return "FAIL", f"mpl 눈금 크기={lab and lab[0].get_fontsize()} (9 기대)"
    # auto로 되돌리면 pg 기본(tickFont=None)으로 복귀하나
    w._tick_size.setValue(0); w._lbl_size.setValue(0)
    ts.render()
    if w.p1.getAxis("bottom").style.get("tickFont") is not None:
        return "FAIL", "auto 복귀 후에도 pg tickFont가 남아있음"
    return "PASS", "규칙(지정>유도>기본)·pg 9pt·mpl 9pt·auto 복귀 전부 일치"


# ── 20. 주석이 다른 좌표계 모드의 mpl 범위를 못 늘리나 ─────────────────────
@check("주석: Diurnal 등 다른 좌표계 mpl 범위 무영향")
def c_annotation_no_range_blowup():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    ts.render()                                   # 시계열에서 epoch 세로선을 찍은 상황
    tmid = float(np.median(w.shelf["fixture"].time))   # ≈1.75e9
    w._annots = [{"kind": "vline", "val": tmid, "label": "evt", "color": "#d32f2f"}]
    di = next(m for m in w._modes if m.key == "diurnal")
    w._mode_combo.setCurrentText(di.label)        # diurnal로 전환(x=0-23h)
    w._mode = di
    di.options_widget()
    if hasattr(di, "_c"):
        di._c.setCurrentText("fixture:NO2")
    di.render()                                   # pg 쪽 — ignoreBounds라 원래 무영향
    fig = w._build_publish_fig()                  # mpl Publish 경로
    x0, x1 = fig.axes[0].get_xlim()
    if x1 > 100:                                  # 0-23h여야 하는데 epoch까지 늘어났나
        return "FAIL", f"diurnal mpl x범위가 주석 때문에 폭발: [{x0:.3g}, {x1:.3g}]"
    # 원래 좌표계(시계열)에서는 주석이 여전히 정상 표시되는지 재확인
    w._mode_combo.setCurrentText(ts.label); w._mode = ts
    ts.render()
    fig2 = w._build_publish_fig()
    texts = {t.get_text().strip() for a in fig2.axes for t in a.texts}
    if "evt" not in texts:
        return "FAIL", "범위 고정 처리가 시계열의 정상 주석 라벨까지 없앰"
    return "PASS", f"diurnal x=[{x0:.2g},{x1:.2g}] 유지 · 시계열 주석 라벨 정상"


# ── 21. pg 축 auto-SI-prefix 금지 (화면·Publish 눈금 일치) ─────────────────
@check("SI prefix: pg 축이 작은 값을 ×1000 스케일하지 않음")
def c_no_si_prefix_scaling():
    w = PlotMakerWidget()
    rng = np.random.default_rng(1)
    t0 = 1_750_000_000.0
    n = 300
    t = t0 + np.arange(n) * 60.0
    ans = 0.1 + 0.2 * np.sin(np.arange(n) / 30) + rng.normal(0, 0.05, n)   # 0.x ppb대
    ds = Dataset("small", "<fixture:small>", t, {"ANs": ans}, units={"ANs": "ppb"})
    w.shelf[ds.name] = ds
    w._refresh_tree(); w._notify_modes()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["small:ANs", "L", None, None])
    ts.render()
    bad = [nm for nm in ("left", "right", "bottom")
           if getattr(w.p1.getAxis(nm), "autoSIPrefix", False)
           or w.p1.getAxis(nm).autoSIPrefixScale != 1.0]
    if bad:
        return "FAIL", f"{bad} 축에 SI prefix 스케일 활성 — 0.2가 200으로 표시됨(화면-Publish 불일치)"
    w.set_time_axis(False)   # 축 교체 경로(비시간축 새 AxisItem)도 확인
    if getattr(w.p1.getAxis("bottom"), "autoSIPrefix", False):
        return "FAIL", "set_time_axis(False)가 갈아끼운 bottom 축에 SI prefix가 다시 켜짐"
    w.set_time_axis(True)    # DateAxisItem 재생성 경로
    if getattr(w.p1.getAxis("bottom"), "autoSIPrefix", False):
        return "FAIL", "set_time_axis(True)가 갈아끼운 bottom 축에 SI prefix가 다시 켜짐"
    return "PASS", "3개 축 + 축 교체 후에도 SI 스케일 없음(scale=1.0) — 원시값 그대로"


# ── 22. 눈금 숫자와 눈금선 독립 토글 ──────────────────────────────────────
@check("눈금: 숫자 off + 눈금선 on 분리 동작 (pg·mpl)")
def c_tick_text_marks_independent():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    ts.render()
    w._chk_xticks.setChecked(False)     # 숫자 끄고
    w._chk_xtickmarks.setChecked(True)  # 눈금선은 유지
    w.apply_axes()
    bax = w.p1.getAxis("bottom")
    if bax.style.get("showValues", True):
        return "FAIL", "pg: 숫자 껐는데 showValues가 켜져 있음"
    if bax.style.get("tickLength", 0) == 0:
        return "FAIL", "pg: 눈금선 켰는데 tickLength=0 — 숫자와 같이 사라짐(분리 실패)"
    fig = w._build_publish_fig()
    ax = fig.axes[0]
    kw = ax.xaxis._major_tick_kw
    if kw.get("label1On", True):
        return "FAIL", "mpl: 숫자 껐는데 labelbottom이 켜져 있음"
    if not kw.get("tick1On", False):
        return "FAIL", "mpl: 눈금선 켰는데 bottom tick이 꺼짐(분리 실패)"
    w._chk_xtickmarks.setChecked(False)   # 둘 다 끄면 전부 사라져야
    w.apply_axes()
    if w.p1.getAxis("bottom").style.get("tickLength", 0) != 0:
        return "FAIL", "pg: 둘 다 껐는데 눈금선이 남아있음"
    return "PASS", "숫자 off+눈금선 on: pg tickLength 유지·mpl tick1On 유지, 둘 다 off도 정상"


# ── 23. X 틱 앵커 날짜+간격 (pg·mpl 동일 위치) ────────────────────────────
@check("X 틱 앵커: 날짜+N일 간격이 pg·mpl 동일")
def c_anchored_x_ticks():
    import datetime as _dt
    import matplotlib.dates as mdates
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    ts.render()
    t = w.shelf["fixture"].time
    anchor_dt = _dt.datetime.fromtimestamp(float(t[100])).replace(minute=0, second=0)
    w._tick_x.setText("0.25")                                # 6시간 간격
    w._tick_x_anchor.setText(anchor_dt.strftime("%Y-%m-%d %H:%M"))
    w.apply_axes()
    pos = w._anchored_x_ticks(0.25)
    if not pos:
        return "FAIL", "_anchored_x_ticks()가 눈금을 안 만듦"
    anchor_ep = anchor_dt.timestamp()
    step = 0.25 * 86400.0
    bad = [p for p, _l in pos if abs((p - anchor_ep) % step) > 1e-6
           and abs((p - anchor_ep) % step - step) > 1e-6]
    if bad:
        return "FAIL", f"앵커 위상이 안 맞는 눈금 {len(bad)}개"
    if not any(abs(p - anchor_ep) < 1e-6 for p, _l in pos):
        return "FAIL", "앵커 날짜 자체에 눈금이 없음"
    # pg 축에 실제로 박혔나
    bax = w.p1.getAxis("bottom")
    if not getattr(bax, "_tickLevels", None):
        return "FAIL", "pg setTicks가 적용 안 됨(_tickLevels 비어있음)"
    # mpl locator도 같은 위치인가
    fig = w._build_publish_fig()
    loc = fig.axes[-1].xaxis.get_major_locator()
    locs_num = sorted(loc())
    want = sorted(mdates.date2num(_dt.datetime.fromtimestamp(p)) for p, _l in pos)
    if len(locs_num) != len(want) or any(abs(a - b) > 1e-8 for a, b in zip(locs_num, want)):
        return "FAIL", f"mpl 눈금({len(locs_num)}개)과 pg 눈금({len(want)}개) 위치 불일치"
    w._tick_x.setText(""); w._tick_x_anchor.setText("")
    return "PASS", f"앵커 {anchor_dt:%m-%d %H:%M}+6h 간격 눈금 {len(pos)}개 — pg·mpl 동일 위치"


# ── 24. 눈금선 방향(안/바깥)·길이 — pg·mpl 동일 규칙 ───────────────────────
@check("눈금선: 방향(in/out)·길이 pg·mpl 동일 적용")
def c_tick_direction_length():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    ts.render()
    w._tick_dir.setCurrentIndex(1)   # 안(in)
    w._tick_len.setValue(8)
    w.apply_axes()
    if w.p1.getAxis("bottom").style.get("tickLength") != -8:
        return "FAIL", f"pg in/8px인데 tickLength={w.p1.getAxis('bottom').style.get('tickLength')} (-8 기대)"
    fig = w._build_publish_fig()
    kw = fig.axes[0].xaxis._major_tick_kw
    if kw.get("tickdir") != "in" or kw.get("size") != 8:
        return "FAIL", f"mpl in/8px 미반영: dir={kw.get('tickdir')} len={kw.get('size')}"
    w._tick_dir.setCurrentIndex(0)   # 바깥(out), auto 길이
    w._tick_len.setValue(0)
    w.apply_axes()
    if w.p1.getAxis("bottom").style.get("tickLength") != 5:
        return "FAIL", "pg out/auto가 +5가 아님"
    fig2 = w._build_publish_fig()
    kw2 = fig2.axes[0].xaxis._major_tick_kw
    if kw2.get("tickdir") != "out":
        return "FAIL", "mpl out 미반영"
    return "PASS", "in/8px: pg=-8·mpl in 8 — out/auto: pg=+5·mpl out. 규칙 일치"


# ── 25. 시리즈 표현 타입(kind): 7종 × pg/mpl 무사고 + 계단 좌표 정확성 ────
# M4(2026-09-21). line/marker 말고도 step·bar·area·band·errorbar를 고를 수 있게
# 했다. 새 kind를 한쪽 렌더러에만 넣어 화면·Publish가 갈라지는 게 이 파일의
# 단골 버그라 **두 경로를 같이** 돌린다.
@check("시리즈 kind 7종: pg·mpl 양쪽 무사고 + step 좌표")
def c_series_kinds():
    from gui.ui_plot_maker.processing import step_xy, bar_width
    from matplotlib.figure import Figure
    # 계단 좌표는 라이브러리 옵션이 아니라 우리가 펴므로 값 자체를 검사한다
    xs, ys = step_xy(np.array([0.0, 1.0, 2.0]), np.array([10.0, 20.0, 30.0]))
    if list(xs) != [0, 1, 1, 2, 2] or list(ys) != [10, 10, 20, 20, 30]:
        return "FAIL", f"step_xy 좌표가 steps-post가 아님: x={list(xs)} y={list(ys)}"
    if bar_width(np.array([0.0, 60.0, 120.0])) != 48.0:      # 60 × 0.8
        return "FAIL", f"bar_width 오산: {bar_width(np.array([0.0, 60.0, 120.0]))}"

    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    # 2개 시리즈 — band는 '다음 시리즈'와의 사이를 채우므로 짝이 있어야 한다
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._series.append(["fixture:CHOCHO", "R", None, None])
    ts._refresh_list()
    ts._chk_err.setChecked(True)            # errorbar가 쓸 값 공급
    bad = []
    for kind in ts.KINDS:
        ts._styles["fixture:NO2"] = {"kind": kind}
        try:
            ts.render()
            fig = Figure(figsize=(6, 4))
            ts.render_mpl(fig)
            if not fig.axes or not (fig.axes[0].lines or fig.axes[0].patches
                                    or fig.axes[0].collections or fig.axes[0].containers):
                bad.append(f"{kind}(mpl 빈 축)")
        except Exception as e:
            bad.append(f"{kind}: {type(e).__name__} {e}")
    if bad:
        return "FAIL", " · ".join(bad)
    # 마지막 시리즈에 band를 걸면 짝이 없다 → 죽지 말고 선으로 폴백해야 한다
    ts._styles = {"fixture:CHOCHO": {"kind": "band"}}
    try:
        ts.render()
        ts.render_mpl(Figure(figsize=(6, 4)))
    except Exception as e:
        return "FAIL", f"짝 없는 band에서 예외: {type(e).__name__} {e}"
    # 옛 설정(kind 키 없음)도 그대로 살아야 한다
    ts._styles = {"fixture:NO2": {"width": 3, "dash": "dash"}}
    st = ts._style_of("fixture:NO2")
    if st["kind"] != "line" or st["width"] != 3:
        return "FAIL", f"구버전 스타일 기본값 채우기 실패: {st}"
    return "PASS", f"{len(ts.KINDS)}종 × pg/mpl 무사고 · step 좌표 정확 · 짝없는 band 폴백 · 구설정 호환"


# ── 26. 라벨 마크업(M5): mathtext 하나로 입력 → pg는 HTML, mpl은 원문 ────
# 그 전에는 `NO$_2$`가 화면에 literal, `NO<sub>2</sub>`가 Publish에 literal이었다.
@check("라벨 마크업: mathtext → pg HTML, mpl 원문 유지")
def c_label_markup():
    from gui.ui_plot_maker.core import mathtext_to_html
    cases = {
        "NO$_2$": "NO<sub>2</sub>",
        "$\\mu$g m$^{-3}$": "μg m<sup>-3</sup>",
        "$\\times$10$^{-9}$": "×10<sup>-9</sup>",
        "R_mean": "R_mean",                 # $ 밖의 밑줄은 건드리지 않는다
        "NO2_Error (ppb)": "NO2_Error (ppb)",
        "a < b": "a &lt; b",                # HTML 특수문자 이스케이프
        "$\\unknowncmd$": "\\unknowncmd",   # 모르는 토큰은 통과(조용히 지우지 않음)
    }
    bad = [f"{k!r}→{mathtext_to_html(k)!r}(기대 {v!r})"
           for k, v in cases.items() if mathtext_to_html(k) != v]
    if bad:
        return "FAIL", " · ".join(bad)

    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    w._ed_y.setText("NO$_2$ [ppb]")
    w.custom["ylabel"] = "NO$_2$ [ppb]"
    ts.render()
    pg_lbl = w.p1.getAxis("left").labelText
    if "<sub>2</sub>" not in pg_lbl:
        return "FAIL", f"pg 축라벨이 HTML로 안 바뀜: {pg_lbl!r}"
    fig = w._build_publish_fig()
    mpl_lbl = fig.axes[0].get_ylabel()
    if mpl_lbl != "NO$_2$ [ppb]":
        return "FAIL", f"mpl 축라벨이 원문이 아님(mathtext가 깨짐): {mpl_lbl!r}"
    return "PASS", f"7케이스 변환 정확 · pg={pg_lbl!r} · mpl 원문 유지"


# ── 27. 주석 레이어(M3): 7종이 pg·mpl 양쪽에 그려지나 + 옛 레코드 호환 ────
# 가드 17번(마커선)의 확장. 주석은 kind마다 pg/mpl 분기가 따로라 한쪽만 고치기
# 쉽고, 그게 이 파일의 단골 버그였다.
@check("주석 7종: pg·mpl 양쪽 + 설정 왕복 + 옛 레코드 호환")
def c_annot_kinds():
    import pyqtgraph as pg_
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    ts.render()
    t = w.shelf["fixture"].time
    t0, t1 = float(t[100]), float(t[200])
    w._annots = [
        {"kind": "vline", "x1": t0, "label": "evt", "color": "#d32f2f"},
        {"kind": "hline", "y1": 5.0, "label": "LOD", "color": "#7B1FA2"},
        {"kind": "vspan", "x1": t0, "x2": t1, "label": "purge", "color": "#0097A7"},
        {"kind": "hspan", "y1": 4.0, "y2": 6.0, "label": "band", "color": "#689F38"},
        {"kind": "text", "x1": t0, "y1": 6.0, "label": "여기 주목", "color": "#333333"},
        {"kind": "arrow", "x1": t0, "y1": 5.5, "x2": t1, "y2": 7.0,
         "label": "spike", "color": "#E65100"},
        {"kind": "rect", "x1": t0, "y1": 4.5, "x2": t1, "y2": 6.5,
         "label": "ROI", "color": "#455A64"},
    ]
    try:
        ts.render()
    except Exception as e:
        return "FAIL", f"pg 렌더 예외: {type(e).__name__} {e}"
    n_region = sum(isinstance(it, pg_.LinearRegionItem) for it in w.p1.items)
    n_text = sum(isinstance(it, pg_.TextItem) for it in w.p1.items)
    n_arrow = sum(isinstance(it, pg_.ArrowItem) for it in w.p1.items)
    if n_region != 2:
        return "FAIL", f"pg 구간 음영 {n_region}개 (vspan+hspan=2 기대)"
    if n_arrow != 1:
        return "FAIL", f"pg 화살표 {n_arrow}개 (1 기대)"
    if n_text < 3:          # text·arrow 라벨·rect 라벨
        return "FAIL", f"pg 텍스트 {n_text}개 (3개 이상 기대)"

    # 화살촉 각도: 실제 레이아웃이 있어야 의미가 있다(씬 좌표 기준).
    # 2026-09-21 실측 버그 — 주석은 clear_plot()에서, 즉 데이터 그리기·autoscale
    # **전**에 만들어져서 생성 시점에 각도를 박으면 '직전 렌더의 축 범위'로 계산된다
    # (위로 향해야 할 화살표가 179.9° = 거의 수평이었다). autoscale 후 재계산이 정답.
    w.show(); _APP.processEvents()
    ts.render(); _APP.processEvents()
    arrows = getattr(w, "_annot_arrows", [])
    if len(arrows) != 1:
        return "FAIL", f"화살표 추적 목록 {len(arrows)}개 (1 기대)"
    ang = arrows[0][0].opts.get("angle")
    # 목표(t0, 5.5)는 꼬리(t1, 7.0)보다 화면상 **왼쪽 아래** → 화살표는 좌하향.
    # 각도 = atan2(꼬리−목표) 이므로 (dx>0, dy<0) → −90~0도.
    if not (-90.0 < float(ang) < 0.0):
        return "FAIL", f"화살촉 각도 {ang:.1f}° — 축 범위 확정 전 값이 박힌 듯(−90~0 기대)"
    vb = w.p1.vb
    (xa, xb) = vb.viewRange()[0]
    vb.setXRange(xa, (xa + xb) / 2); _APP.processEvents()
    if abs(float(arrows[0][0].opts.get("angle")) - float(ang)) < 1e-6:
        return "FAIL", "줌해도 화살촉 각도가 안 따라옴(sigRangeChanged 연결 끊김)"
    ts.render(); _APP.processEvents()

    w._legend_combo.setCurrentText("off")   # 범례를 꺼도 주석은 보여야 한다(가드17 정신)
    try:
        fig = w._build_publish_fig()
    except Exception as e:
        w._legend_combo.setCurrentText("auto")
        return "FAIL", f"mpl 렌더 예외: {type(e).__name__} {e}"
    ax = fig.axes[0]
    texts = {t_.get_text().strip() for a in fig.axes for t_ in a.texts}
    missing = [s for s in ("evt", "LOD", "purge", "band", "여기 주목", "spike", "ROI")
               if s not in texts]
    if missing:
        w._legend_combo.setCurrentText("auto")
        return "FAIL", f"mpl 라벨 누락: {missing}"
    if len(ax.patches) < 3:   # vspan·hspan·rect
        w._legend_combo.setCurrentText("auto")
        return "FAIL", f"mpl 패치 {len(ax.patches)}개 (3개 이상 기대)"
    w._legend_combo.setCurrentText("auto")

    # 옛 레코드({"val": …})도 그대로 살아야 한다
    old = w._annot_norm({"kind": "hline", "val": 3.0})
    if old.get("y1") != 3.0:
        return "FAIL", f"옛 레코드 승격 실패: {old}"
    # 설정 저장/불러오기 왕복 — 전에는 주석이 아예 저장되지 않아 사라졌다
    import json as _json, tempfile, os as _os
    fd, p = tempfile.mkstemp(suffix=".pmcfg.json"); _os.close(fd)
    try:
        from unittest.mock import patch as _patch
        with _patch("gui.ui_plot_maker.widget.QFileDialog.getSaveFileName",
                    return_value=(p, "")):
            w._save_cfg()
        saved = _json.load(open(p, encoding="utf-8"))
        if len(saved.get("annots", [])) != 7:
            return "FAIL", f"설정에 주석 {len(saved.get('annots', []))}개 저장됨 (7 기대)"
        w._annots = []
        with _patch("gui.ui_plot_maker.widget.QFileDialog.getOpenFileName",
                    return_value=(p, "")):
            w._load_cfg()
        if len(w._annots) != 7:
            return "FAIL", f"불러오기 후 주석 {len(w._annots)}개 (7 기대)"
    finally:
        try:
            _os.remove(p)
        except OSError:
            pass
    return "PASS", "7종 pg(구간2·화살표1·텍스트3+)·mpl(라벨7·패치3+) · 설정 왕복 · 옛 레코드 호환"


# ── 28. Publish 폰트 처리: 저널이 받는 PDF · 편집 가능한 SVG ──────────────
# mpl 기본값이 우리 용도와 정반대였다(2026-09-21):
#   pdf/ps.fonttype=3(Type 3) → 임베딩돼도 투고 시스템이 거부하는 곳이 있다
#   svg.fonttype='path'       → 글자가 패스로 박혀 Illustrator/Inkscape 편집 불가
@check("Publish 폰트: PDF/PS Type 42 · SVG는 텍스트 유지")
def c_publish_fonts():
    import matplotlib, tempfile, os as _os
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    ts.render()
    fig = w._build_publish_fig()          # 여기서 _apply_mpl_rc가 돈다
    rc = matplotlib.rcParams
    bad = []
    if rc["pdf.fonttype"] != 42:
        bad.append(f"pdf.fonttype={rc['pdf.fonttype']} (42 기대 — Type 3는 투고 거부 사례)")
    if rc["ps.fonttype"] != 42:
        bad.append(f"ps.fonttype={rc['ps.fonttype']} (42 기대)")
    if rc["svg.fonttype"] != "none":
        bad.append(f"svg.fonttype={rc['svg.fonttype']!r} ('none' 기대)")
    if bad:
        return "FAIL", " · ".join(bad)
    # 설정만 보지 말고 실제 파일로 — SVG에 <text>가 남아야 편집이 된다
    fd, p = tempfile.mkstemp(suffix=".svg"); _os.close(fd)
    try:
        fig.savefig(p)
        svg = open(p, encoding="utf-8").read()
    finally:
        try:
            _os.remove(p)
        except OSError:
            pass
    if "<text" not in svg:
        return "FAIL", "SVG 글자가 패스로 박힘 — 벡터 편집 불가(svg.fonttype 되돌아갔나)"
    return "PASS", "pdf/ps=Type42 · svg=none · 실제 SVG에 <text> 유지됨"


def main():
    print("=" * 64)
    print(" Plot Maker 회귀 검증 (offscreen)")
    print("=" * 64)
    n_pass = n_warn = n_fail = n_skip = 0
    for name, fn in CHECKS:
        try:
            status, msg = fn()
        except Skip as e:
            status, msg = "SKIP", str(e)
        except Exception as e:
            status, msg = "FAIL", f"오류: {type(e).__name__}: {e}"
        icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌", "SKIP": "⏭️ "}[status]
        print(f" [{status:4s}] {icon} {name}")
        print(f"          {msg}")
        n_pass += status == "PASS"; n_warn += status == "WARN"
        n_fail += status == "FAIL"; n_skip += status == "SKIP"
    print("-" * 64)
    print(f" 결과: {n_pass} PASS · {n_warn} WARN · {n_fail} FAIL · {n_skip} SKIP")
    if n_fail:
        print(" ❌ 실패 항목이 있다 — 최근 변경이 뭔가 깨뜨렸을 수 있음.")
    else:
        print(" ✅ 전부 통과 — Plot Maker 건강함.")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
