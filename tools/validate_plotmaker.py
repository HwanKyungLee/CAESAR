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
8. Undo          : 데이터셋·시리즈 제거 복원 · 데이터셋 undo가 그걸 쓰던 시리즈까지(R7)
9. 창 상태 기억   : QSettings 스플리터·탭·테마 저장→복원 왕복(2026-06 UX개편 회귀가드)
10. Batch Publish : 종별 일괄저장 후 원래 시리즈목록/콤보선택 상태 복원되나 ·
    같은 종·다른 데이터셋 파일명이 겹쳐 덮어쓰지 않나(R2, 2026-10-02)
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
28. Publish 폰트 : pdf/ps=Type42(저널 거부 사례 회피)·svg=none(벡터 편집 가능).
    설정만 보지 않고 실제 SVG를 저장해 <text> 유무까지 본다 (2026-09-21)
29. Okabe-Ito 팔레트 : 색각안전 8색이 시리즈 순서대로·8개 넘으면 순환 (2026-09-21)
30. 상관 히트맵 컬러맵 : 음=파랑·양=빨강이 pg·mpl 동일(RdBu를 _r 없이 쓰면 부호가
    조용히 뒤집힌다) + 셀 글자색이 배경 휘도 기준인가 (2026-09-21)
31. Publish 프리셋 + EPS : 논문 폭(Copernicus 8.3/17cm) 프리셋이 figure 크기까지
    반영되고 autosize를 끄나 · EPS에 글리프가 실제로 들어갔나 (2026-09-21)
32. 폰트 폴백 : font.family 목록으로 한글 글리프 폴백(ASCII는 Arial) ·
    한글+수식 혼합 라벨 감지(mathtext 엔진엔 한글이 없어 □가 된다) (2026-09-21)
33. 표시 토글 : 시리즈·주석 체크 해제가 화면·Publish 양쪽에서 숨기되 **삭제하지
    않나** · 곡선에 시리즈 라벨이 태깅돼 클릭→편집이 가능한가 (2026-09-21)
34. Result Lab → Plot Maker 다리 : Hide QC·사후 QC K·구간·시프트가 **경로 + 규칙**으로
    넘어가 Result Lab 선택과 행 단위로 같은 숨김을 만드나 · 끄면 복원 · 원본 불변 ·
    설정 저장/열기 왕복 · 옛 형식 호환 (D0, 2026-10-01)
35. 파생 열 : 단위변환·연쇄·범주형 비교·hour 식이 맞게 계산되나 · 깨진/위험한 식은
    실행 없이 빨갛게 남나 · 원본 열 보호 · **식만** 저장되고 열 때 재계산되나 ·
    Result Lab 계산기와 같은 엔진(core/expr.py) (D1, 2026-10-01)
36. 행 필터 + Flag 색칠 : keep/hide 조건식·파생 열 조건·규칙 개별 on/off(삭제 아님) ·
    깨진 조건은 그 규칙만 무효+✗(데이터셋은 열림) · 설정 왕복 · Flag 점이 pg·mpl 같은 수 ·
    리샘플 중엔 끄고 안내 · 스타일 편집이 숨김을 안 풀어버리나 (D2, 2026-10-01)
37. 정렬·Join : Scatter의 다른 데이터셋 짝짓기가 결손을 가로질러 잇지 않나 · Join(⋈)
    데이터셋이 같은 값을 내나 · 재료 필터 반영 · Join 위 파생 열 · 레시피 저장/왕복 ·
    재료 삭제 시 묵은 값 없이 ✗ (D1+, 2026-10-01)
38. Deming·구간 추세 : x에도 오차가 있을 때 Deming이 OLS 감쇠를 보정하나(합성 참값) ·
    기본 OLS 제목·범례 불변 · λ from 1σ · Result Lab Σ Stats 구간 추세 (2026-10-01)
39. Copernicus 프리셋 : Theme 하나로 Publish 폭·dpi·라벨/눈금 크기·눈금 방향·Okabe-Ito·
    격자 끔이 실제 Publish 그림에 들어가나 · autosize 해제 (2026-10-01)
40. Preview 모덜리스 : 싱글턴 · 무변화면 안 그림 · 바뀐 뒤 한 박자 동안 그대로면 다시 그림 ·
    시리즈 스타일 변경도 감지 · 렌더 오류는 팝업 아닌 창 안 (M-P, 2026-10-01)
41. 패널 계약 : 6개 모드 render_mpl(fig, ax)가 받은 패널 안에만 그리나 · 옆 패널 x 라벨·
    눈금 무손상(autofmt_xdate 류 금지) · 분할 시계열은 패널 칸을 쪼갠다 (M1, 2026-10-01)
42. Composer : 패널 조각으로 그림 · 편집기·화면 무오염 · Edit 연결(추가 직후엔 안 묶임) · inset ·
    룩(눈금 크기) 전 패널 공통·inset은 작게 · x 공유 · 높이 비율 · 설정 왕복 · 끄면 단일 (M2, 2026-10-01)
43. R축(twinx)·컬러바 눈금은 오른쪽에만 — 왼쪽 숫자 옆에 겹쳐 찍히던 버그의 가드 (2026-10-01)
44. 콘솔 : df()=보이는 그대로·push 시각 왕복·입력 기록 부착 · 예외 격리·여러 줄 · 설정 저장은
    기록만 · **설정을 열 때 기록을 자동 실행하지 않나**(센티넬 파일) · rerun()으로만 재생성 (D3, 2026-10-01)
45. 주석 시각 : 연도 생략 값이 서기 1년·UTC가 아니라 데이터 연도·로컬로 · 깨진 주석은
    Publish를 죽이지 않고 건너뛰며 이름이 남나 (R1, 2026-10-02)
46. Export CSV : 시간축 다른 열을 core.align으로 — 끝값 외삽·결손 직선 메움 없이 빈 칸,
    '#' 헤더에 시프트·리샘플 기록, Plot Maker가 다시 읽나 (R3, 2026-10-02)
47. 시간축 시계 : fit .meta.json time_shift_h·time_KST 열로 데이터셋 시계를 알고 x 라벨에
    (UTC)/(KST) · Night를 UTC 시계에 칠하면 경고 (R4, 2026-10-02)
48. Split 축 범위 : Y-left 범위·log는 좌축 시리즈 패널 전부, Y-right는 우축 시리즈 패널에만
    (전엔 axes[0] / axes[1:] 가정이라 Y-right가 둘째 패널에 걸렸다, R5, 2026-10-02)
49. Theme 선 굵기 : 테마 굵기는 기본(직전 테마) 굵기 시리즈에만, 사용자 지정은 보존 (R6, 2026-10-02)
50. 조판 빈 패널 : 데이터셋이 지워진 패널은 'missing: …' + Publish 경고 (R8, 2026-10-02)
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
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series.append(["fixture:CHOCHO", "R", None, None])   # 데이터셋을 쓰던 시리즈(R7)
    ts._refresh_list()
    w._tree.topLevelItem(0).setSelected(True)
    w._remove_data()
    if w.shelf or ts._series:
        return "FAIL", "데이터셋 제거가 안 됨(테스트 전제 실패)"
    w.undo_last()
    if "fixture" not in w.shelf:
        return "FAIL", "데이터셋 undo 복원 실패"
    if [s[0] for s in ts._series] != ["fixture:CHOCHO"]:
        return "FAIL", f"데이터셋 undo가 그걸 쓰던 시리즈를 복원 안 함: {ts._series} (R7)"
    ts._series.clear()

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
        # 같은 종·다른 데이터셋(CH1/CH2 NO2) — 예전엔 둘 다 timeseries_NO2.png라 덮어썼다(R2)
        ds2 = _fixture_dataset("fixture2", seed=3)
        w.shelf[ds2.name] = ds2; w._refresh_tree(); w._notify_modes()
        ts._series.append(["fixture2:NO2", "L", None, None])
        ts._refresh_list()
        orig_series_obj = ts._series

        with tempfile.TemporaryDirectory() as tmp:
            QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: tmp)
            QMessageBox.information = staticmethod(lambda *a, **k: None)   # 모달 차단 방지
            w._batch_publish()
            pngs = sorted(os.path.basename(p) for p in glob.glob(os.path.join(tmp, "*.png")))
            if len(pngs) != 3:
                return "FAIL", f"TimeSeries 배치 파일 개수 이상(같은 종 덮어쓰기?): {pngs}"
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
        return "PASS", "TimeSeries 3파일(같은 종·다른 데이터셋 구분) + Diurnal 콤보(-1) 복원 확인"
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


# ── 29. Okabe-Ito 범주형 팔레트: 순서대로 배색 + 8개 넘으면 순환 ───────────
@check("팔레트: Okabe-Ito 색각안전 배색")
def c_okabe_ito():
    from gui.ui_plot_maker.widget import _CATEGORICAL
    name = "Okabe-Ito (colorblind-safe)"
    pal = _CATEGORICAL.get(name)
    if not pal or len(pal) != 8:
        return "FAIL", f"Okabe-Ito 팔레트가 없거나 8색이 아님: {pal}"
    w = _widget_with_fixture()
    if name not in [w._palette_combo.itemText(i) for i in range(w._palette_combo.count())]:
        return "FAIL", "팔레트 콤보에 Okabe-Ito가 없음"
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    for _ in range(10):                      # 8색보다 많게 → 순환 확인
        ts._series.append(["fixture:NO2", "L", None, None])
    ts._refresh_list()
    w._apply_palette(name)
    got = [s[2] for s in ts._series]
    want = [pal[i % 8] for i in range(10)]
    if got != want:
        return "FAIL", f"배색 불일치: {got[:4]}… (기대 {want[:4]}…)"
    # 계통색(단일 hue 진↔연) 경로가 안 깨졌나
    w._apply_palette("Blue")
    if ts._series[0][2] == pal[0]:
        return "FAIL", "계통색 팔레트가 Okabe-Ito 값을 그대로 둠(분기 오류)"
    return "PASS", f"8색 순서·순환 정확 · 콤보 노출 · 계통색 경로 무사"


# ── 30. 상관 히트맵 컬러맵: 부호 방향(음=파랑, 양=빨강)이 pg·mpl 동일 ────────
# bwr → RdBu_r 교체(2026-09-21) 때의 함정 가드. RdBu를 `_r` 없이 쓰면 색은 비슷한데
# **상관의 부호가 조용히 뒤집힌다** — 그림이 멀쩡해 보여서 아무도 못 알아챈다.
@check("상관 히트맵 컬러맵: 음=파랑 · 양=빨강 (pg·mpl)")
def c_heatmap_cmap_sign():
    from matplotlib import colormaps
    import pyqtgraph as pg_
    from gui.ui_plot_maker.modes import HeatmapMode
    cm = colormaps[HeatmapMode.CMAP]
    lo = cm(0.0)[:3]            # r = -1
    hi = cm(1.0)[:3]            # r = +1
    if not (lo[2] > lo[0]):
        return "FAIL", f"mpl: r=-1이 파랑이 아님 RGB={tuple(round(v,2) for v in lo)} (RdBu를 _r 없이 쓴 듯)"
    if not (hi[0] > hi[2]):
        return "FAIL", f"mpl: r=+1이 빨강이 아님 RGB={tuple(round(v,2) for v in hi)}"
    try:
        lut = pg_.colormap.getFromMatplotlib(HeatmapMode.CMAP).getLookupTable(0.0, 1.0, 256)
    except Exception as e:
        return "FAIL", f"pg가 {HeatmapMode.CMAP}를 못 읽음: {e}"
    if not (int(lut[0][2]) > int(lut[0][0]) and int(lut[-1][0]) > int(lut[-1][2])):
        return "FAIL", f"pg 부호 방향 불일치: -1={tuple(int(v) for v in lut[0][:3])} +1={tuple(int(v) for v in lut[-1][:3])}"
    # 셀 글자색은 배경 휘도로 정해야 한다 — |r| 문턱을 박으면 컬러맵 바꿀 때 어긋난다
    if HeatmapMode._white_text(0.5) or HeatmapMode._white_text(0.0):
        return "FAIL", "밝은 셀(|r|≤0.5)에 흰 글자 — 배경 휘도 판정이 깨졌다"
    if not (HeatmapMode._white_text(1.0) and HeatmapMode._white_text(-1.0)):
        return "FAIL", "짙은 셀(|r|=1)에 검은 글자 — 배경 휘도 판정이 깨졌다"
    return "PASS", (f"{HeatmapMode.CMAP} · pg/mpl 둘 다 -1=파랑, +1=빨강 · "
                    f"글자색은 배경 휘도 기준(|r|=0.5 검정, 1.0 흰색)")


# ── 31. Publish 프리셋 + EPS 출력 ──────────────────────────────────────────
@check("Publish 프리셋(논문 폭) + EPS 벡터 출력")
def c_publish_preset_eps():
    import tempfile, os as _os, re as _re
    from gui.ui_plot_maker.widget import _PUBLISH_PRESETS
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None]); ts.render()
    name = "Paper, 1 column (8.3 cm)"
    if name not in _PUBLISH_PRESETS:
        return "FAIL", f"프리셋 목록에 '{name}' 없음: {list(_PUBLISH_PRESETS)}"
    w._chk_autosize.setChecked(True)
    w._apply_publish_preset(name)
    ww, hh, dpi = _PUBLISH_PRESETS[name]
    if (round(w._fig_w.value(), 2), round(w._fig_h.value(), 2), w._dpi_spin.value()) != (ww, hh, dpi):
        return "FAIL", f"프리셋 미반영: {w._fig_w.value()}×{w._fig_h.value()} @{w._dpi_spin.value()}"
    if w._chk_autosize.isChecked():
        return "FAIL", "프리셋을 골랐는데 '모드별 권장 크기 자동'이 켜진 채 — 모드 바꾸면 덮인다"
    fig = w._build_publish_fig()
    if tuple(round(v, 2) for v in fig.get_size_inches()) != (ww, hh):
        return "FAIL", f"figure 크기가 프리셋과 다름: {fig.get_size_inches()}"
    # EPS: 실제로 저장되고 텍스트가 글리프로 들어갔나(mpl#27328 = 글자 통째 증발 가드)
    fd, p = tempfile.mkstemp(suffix=".eps"); _os.close(fd)
    try:
        fig.savefig(p)
        raw = open(p, "rb").read()
    finally:
        try:
            _os.remove(p)
        except OSError:
            pass
    if not raw.startswith(b"%!PS-Adobe"):
        return "FAIL", "EPS 헤더가 아님"
    if b"selectfont" not in raw or b"glyphshow" not in raw:
        return "FAIL", "EPS에 텍스트 드로잉이 없음 — 눈금/라벨이 통째로 빠졌다(mpl#27328류)"
    return "PASS", f"{name} {ww}×{hh}in@{dpi} 적용·autosize 해제 · EPS {len(raw)//1024}KB에 글리프 포함"


# ── 32. 폰트: 한글은 글리프 폴백, 한글+수식 혼합은 감지 ─────────────────────
# 예전엔 font.family를 한글 폰트로 통째 바꿔 한글 없는 논문 그림까지 한글 폰트로
# 찍혔다. 이제 family에 목록을 줘 글리프 단위로 폴백한다(font.sans-serif 목록으로는
# 안 된다 — 그건 '하나를 고르는 후보'라 없는 글리프는 □가 된다. 실측함).
@check("폰트: 한글 글리프 폴백 · 한글+수식 혼합 감지")
def c_font_fallback():
    import warnings, tempfile, os as _os, matplotlib
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    w.custom["title"] = "여수 캠페인 한글 제목"      # 한글만
    w.custom["ylabel"] = "NO$_2$ [ppb]"              # 수식만
    ts.render()
    fig = w._build_publish_fig()
    fam = matplotlib.rcParams["font.family"]
    if not isinstance(fam, list) or len(fam) < 2:
        return "FAIL", f"font.family가 목록이 아님({fam}) — 목록이어야 글리프 폴백이 된다"
    fd, p = tempfile.mkstemp(suffix=".png"); _os.close(fd)
    try:
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            fig.savefig(p, dpi=100)
        miss = [str(x.message) for x in ws if "missing from font" in str(x.message)]
    finally:
        try:
            _os.remove(p)
        except OSError:
            pass
    if miss:
        return "FAIL", f"한글/수식 라벨에서 글리프 누락 {len(miss)}건: {miss[0][:60]}"
    if w._mixed_hangul_mathtext():
        return "FAIL", "분리된 라벨을 '혼합'으로 오탐"
    w.custom["title"] = "한글 NO$_2$ 농도"           # 한 라벨에 섞기 → 감지돼야
    if not w._mixed_hangul_mathtext():
        return "FAIL", "한글+수식 혼합 라벨을 감지 못함(한글이 □로 나가는데 조용하다)"
    return "PASS", f"family={fam[:2]}… 폴백 정상 · 누락 0 · 혼합 라벨 감지"


# ── 33. 표시 토글(숨김≠삭제) + 곡선 클릭 → 스타일 편집 ─────────────────────
# Object Manager를 새 패널로 만들지 않고, **이미 있는 두 목록**(시리즈·주석)에
# 체크박스를 달았다. 헌장 ①의 UI판 — 숨기는 것이지 지우는 게 아니다.
@check("표시 토글: 시리즈·주석 숨김(삭제 아님) + 곡선 클릭 대상 태깅")
def c_visibility_and_click():
    import pyqtgraph as pg_
    from PyQt6.QtCore import Qt as Qt_
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._series.append(["fixture:CHOCHO", "L", None, None])
    ts._refresh_list()
    ts.render()
    n_all = len(ts._resolve_specs())
    if n_all != 2:
        return "FAIL", f"시리즈 2개인데 specs {n_all}개"
    # 목록 체크 해제 → 그림에서만 빠지고 _series에는 남아야 한다
    ts._list.item(0).setCheckState(Qt_.CheckState.Unchecked)
    if len(ts._resolve_specs()) != 1:
        return "FAIL", "체크 해제했는데 여전히 그려짐"
    if len(ts._series) != 2:
        return "FAIL", f"숨김이 삭제로 동작함 — _series {len(ts._series)}개 (2 기대)"
    ts._list.item(0).setCheckState(Qt_.CheckState.Checked)
    if len(ts._resolve_specs()) != 2:
        return "FAIL", "다시 체크했는데 안 돌아옴"
    # 주석도 같은 규칙
    t0 = float(w.shelf["fixture"].time[10])
    w._annots = [{"kind": "vline", "x1": t0, "label": "evt", "color": "#d32f2f"}]
    ts.render()
    n_on = sum(isinstance(i, pg_.InfiniteLine) for i in w.p1.items)
    w._annots[0]["visible"] = False
    ts.render()
    n_off = sum(isinstance(i, pg_.InfiniteLine) for i in w.p1.items)
    if n_off != n_on - 1:
        return "FAIL", f"주석 숨김 미동작(선 {n_on}→{n_off})"
    fig = w._build_publish_fig()      # Publish도 같은 규칙이어야 한다
    if any(ln.get_linestyle() == "--" for ln in fig.axes[0].lines):
        return "FAIL", "화면에선 숨겼는데 Publish에는 주석이 남음"
    # 곡선 클릭 → 어느 시리즈인지 찾아갈 수 있게 태깅됐나
    ts.render()
    tagged = [getattr(i, "_pm_label", None) for i in w.p1.items
              if isinstance(i, pg_.PlotDataItem) and getattr(i, "_pm_label", None)]
    if "fixture:NO2" not in tagged:
        return "FAIL", f"곡선에 시리즈 라벨 태그 없음 — 클릭해도 뭘 편집할지 모른다: {tagged}"
    return "PASS", "시리즈·주석 숨김이 화면·Publish 양쪽에 · _series 보존 · 곡선 태깅 확인"


# ── 34. Result Lab → Plot Maker 다리: 보던 상태가 레시피로 넘어가나 (D0) ─────────
# 전엔 경로만 넘겨서 Hide QC·K·구간·시프트가 증발했다. 이제 경로 + 재계산 가능한
# 규칙을 넘긴다. 숨김은 삭제가 아니다 — 끄면 돌아오고, 설정을 다시 열어도 같다.
def _write_report_fixture(path, n=120, seed=1, offset_s=0.0, step_min=2, skip=()):
    """GUI 리포트 포맷(File\\tChannel\\tTime…) 합성 파일 — 두 채널, 일부 QC·튀는 RMS.
    offset_s·step_min·skip(빠뜨릴 행 번호 = 결손)은 정렬/Join 검증용. 기본값 출력은 그대로."""
    from datetime import datetime, timedelta
    rng = np.random.default_rng(seed)
    t0 = datetime(2026, 5, 20, 0, 0, 0) + timedelta(seconds=offset_s)
    skip = set(skip)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# synthetic report for validate_plotmaker #34\n")
        f.write("File\tChannel\tTime\tRMS\tChi2\tStatus\tNO2\tNO2_Error\tShift\tSqueeze\n")
        for i in range(n):
            if i in skip:
                rng.normal(); rng.normal(); rng.normal()   # 난수열은 그대로 소비(나머지 행 값 불변)
                continue
            ch = "1" if i % 2 == 0 else "2"
            rms = 1e-3 * (1 + 0.05 * rng.normal())
            if i in (7, 30, 31, 90):
                rms *= 8                       # 사후 QC(K)가 잡을 튀는 점
            st = "QC-RMS" if i in (12, 13, 60) else ("Unstable" if i == 44 else "")
            f.write(f"s{i}.txt\t{ch}\t{(t0 + timedelta(minutes=step_min * i)):%Y-%m-%d %H:%M:%S}\t"
                    f"{rms:.6g}\t1.0\t{st}\t{5 + rng.normal():.4f}\t0.2\t{0.1 * rng.normal():.4f}\t1.0001\n")


@check("Result Lab → Plot Maker: QC·구간·시프트가 규칙으로 넘어가고, 끄면 복원·설정 왕복")
def c_resultlab_bridge():
    import json, tempfile
    from PyQt6.QtCore import QDateTime
    from gui.ui_result_viewer import ResultViewerWidget
    from gui.ui_plot_maker import load_dataset
    tmpd = tempfile.mkdtemp()
    p = os.path.join(tmpd, "fixture_report.dat")
    _write_report_fixture(p)

    rv = ResultViewerWidget()
    rv._path = p
    rv._reload()
    if rv._current_kind != "fit":
        return "FAIL", f"리포트 fixture가 fit으로 판별 안 됨: {rv._current_kind}"
    rv._chk_hide_qc.setChecked(True)
    rv._spin_qc_k.setValue(3.0)
    rv._spin_shift.setValue(9.0)          # → _reload, 입력칸은 시프트된 전체 범위로 재초기화
    t = rv._fit_cache
    a, b = float(t["time"][20]), float(t["time"][100])   # 원본 시각
    off = 9 * 3600
    rv._dt_from.setDateTime(QDateTime.fromSecsSinceEpoch(int(a + off)))
    rv._dt_to.setDateTime(QDateTime.fromSecsSinceEpoch(int(b + off)))

    got = []
    rv.send_to_plotmaker.connect(got.append)
    rv._to_plot_maker()
    if not got or not isinstance(got[0][0], dict):
        return "FAIL", f"다리가 레시피(dict)를 안 보냄: {got[:1]}"
    spec = got[0][0]
    kinds = [r["kind"] for r in spec["rules"]]
    if kinds != ["status_qc", "rms_k", "time_range"] or spec["shift_h"] != 9.0:
        return "FAIL", f"규칙 번역 불일치: {kinds}, shift={spec['shift_h']}"

    # Result Lab이 Stats에 쓰는 선택 마스크와 Plot Maker 숨김 마스크가 행 단위로 같아야 한다
    _, sel = rv._stats_arrays()
    w = PlotMakerWidget()
    w.add_specs(got[0])
    ds = next(iter(w.shelf.values()))
    hid = ds.hidden_mask()
    if hid is None or not np.array_equal(hid, ~sel):
        return "FAIL", (f"숨김 마스크 ≠ Result Lab 선택 (PM {0 if hid is None else int(hid.sum())}"
                        f" vs RL {int((~sel).sum())})")
    if not {"Status", "Flag", "Channel"} <= set(ds.cats) or "Shift" not in ds.cols:
        return "FAIL", f"범주형/진단 열 누락: cats={list(ds.cats)} cols={list(ds.cols)}"
    if ds.cats["Flag"][44] != "unstable" or ds.cats["Flag"][12] != "qc":
        return "FAIL", "Flag 열이 flag_of와 다름"

    label = f"{ds.name}:NO2"
    _, _, y, tt = w.resolve(label)
    raw = load_dataset(p).cols["NO2"]
    if not (np.all(np.isnan(y[hid])) and np.array_equal(y[~hid], raw[~hid])):
        return "FAIL", "resolve()가 숨김 행만 NaN으로 내지 않음"
    if not np.allclose(tt, ds.time + off):
        return "FAIL", "데이터셋 시프트가 resolve() 시각에 안 걸림"
    if not np.array_equal(ds.cols["NO2"], raw):
        return "FAIL", "원본 ds.cols가 변조됨 — 숨김은 삭제가 아니다(헌장 ①)"

    w.set_dataset_view(ds.name, rules_on=False)        # 끄면 전부 돌아온다
    _, _, y_off, _ = w.resolve(label)
    if not np.array_equal(y_off, raw, equal_nan=True):
        return "FAIL", "필터를 껐는데 값이 안 돌아옴"
    w.set_dataset_view(ds.name, rules_on=True)

    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append([label, "L", None, None])
    fig = w._build_publish_fig()
    if not any("dataset shift" in tx.get_text() for tx in fig.texts):
        return "FAIL", "Publish에 데이터셋 시프트 표기가 없음(조용한 시각 조작 금지)"

    # 설정 저장 → 새 위젯에서 열기: 같은 마스크·시프트 (파일 다시 읽고 규칙 재적용)
    from unittest import mock
    cfgp = os.path.join(tmpd, "x.pmcfg.json")
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getSaveFileName", return_value=(cfgp, "")):
        w._save_cfg()
    with open(cfgp, encoding="utf-8") as f:
        saved = json.load(f)["datasets"][ds.name]
    if not isinstance(saved, dict) or saved.get("rules") != spec["rules"]:
        return "FAIL", f"설정에 레시피가 안 저장됨: {saved}"
    w2 = PlotMakerWidget()
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getOpenFileName", return_value=(cfgp, "")):
        w2._load_cfg()
    ds2 = w2.shelf.get(ds.name)
    if ds2 is None or not np.array_equal(ds2.hidden_mask(), hid) or ds2.shift_h != 9.0:
        return "FAIL", "설정 왕복 후 숨김 마스크/시프트가 다름"

    # 옛 형식(이름 → 경로 문자열)도 열린다
    with open(cfgp, "w", encoding="utf-8") as f:
        json.dump({"_version": w._CFG_VERSION, "datasets": {"old": p}}, f)
    w3 = PlotMakerWidget()
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getOpenFileName", return_value=(cfgp, "")):
        w3._load_cfg()
    if "old" not in w3.shelf or w3.shelf["old"].hidden_mask() is not None:
        return "FAIL", "옛 형식 설정(경로 문자열)이 안 열리거나 규칙이 생김"
    return "PASS", (f"규칙 3종+9h 전달 · 숨김 {int(hid.sum())}행 = RL 선택과 행 단위 동일 · "
                    "끄면 복원 · 원본 불변 · Publish 표기 · 설정 왕복·옛 형식 호환")


# ── 35. 파생 열: 식을 저장하고 값은 다시 계산 (D1) ─────────────────────────────
@check("파생 열: 단위변환·연쇄·범주형·hour · 깨진 식은 빨갛게 · 안전 · 설정 왕복")
def c_derived_columns():
    import json, tempfile
    from unittest import mock
    from gui.ui_plot_maker.data import local_hour
    from gui.ui_plot_maker.derived_dialog import DerivedColumnDialog
    from gui.dlg_calculator import safe_eval as calc_eval
    tmpd = tempfile.mkdtemp()
    p = os.path.join(tmpd, "fixture_report.dat")
    _write_report_fixture(p)
    w = PlotMakerWidget()
    w.add_specs([{"path": p, "rules": [{"kind": "status_qc"}]}])
    name = next(iter(w.shelf))
    ds = w.shelf[name]
    no2 = ds.cols["NO2"].copy()

    for spec in ({"name": "NO2_ugm3", "expr": "NO2 * 1.88", "unit": "µg/m³"},
                 {"name": "anom", "expr": "NO2_ugm3 - mean(NO2_ugm3)"},
                 {"name": "ok_only", "expr": 'where(Flag == "ok", NO2, nan)'},
                 {"name": "daytime", "expr": "(hour >= 9) & (hour < 18)"}):
        err = w.set_derived(name, spec)
        if err:
            return "FAIL", f"{spec['name']} 실패: {err}"
    c = ds.cols
    if not np.allclose(c["NO2_ugm3"], no2 * 1.88) or ds.units.get("NO2_ugm3") != "µg/m³":
        return "FAIL", "단위 변환 값/단위 불일치"
    if not np.allclose(c["anom"], c["NO2_ugm3"] - np.nanmean(c["NO2_ugm3"])):
        return "FAIL", "앞 파생 열을 쓰는 연쇄 식 불일치"
    okm = ds.cats["Flag"] == "ok"
    if not (np.allclose(c["ok_only"][okm], no2[okm]) and np.all(np.isnan(c["ok_only"][~okm]))):
        return "FAIL", "범주형 비교(Flag == \"ok\") 불일치"
    hr = local_hour(ds.time)
    if not np.array_equal(c["daytime"], ((hr >= 9) & (hr < 18)).astype(float)):
        return "FAIL", "hour 변수 불일치"

    # 숨김 규칙은 파생 열에도 같은 행에 걸린다(resolve 한 길목)
    _, _, y, _ = w.resolve(f"{name}:NO2_ugm3")
    hid = ds.hidden_mask()
    if not (hid.any() and np.all(np.isnan(y[hid]))):
        return "FAIL", "숨김 규칙이 파생 열에 안 걸림"

    # 깨진 식: 그 열만 빠지고 오류가 남는다(조용히 사라지지 않음) · 안전: 실행 안 됨
    if not w.set_derived(name, {"name": "bad", "expr": "NO2 * nosuch"}):
        return "FAIL", "모르는 이름이 오류 없이 통과"
    sentinel = os.path.join(tmpd, "pwned")
    evil = f'__import__("os").makedirs(r"{sentinel}")'
    if not w.set_derived(name, {"name": "evil", "expr": evil}) or os.path.exists(sentinel):
        return "FAIL", "위험한 식이 거부되지 않음"
    for bad in ("bad", "evil"):
        if bad in ds.cols or bad not in ds.derived_errors:
            return "FAIL", f"깨진 식 {bad}가 cols에 있거나 오류 기록이 없음"
    top = w._tree.topLevelItem(0)
    kinds = [top.child(j).data(0, 0x0100)[0] for j in range(top.childCount())]
    if kinds.count("bad") != 2:
        return "FAIL", f"트리에 깨진 열 표시가 없음: {kinds}"
    if w.set_derived(name, {"name": "NO2", "expr": "1"}) is None:
        return "FAIL", "원본 열 이름(NO2)을 덮어쓰는 파생 열이 허용됨"
    # 손으로 고친 설정에 원본과 같은 이름이 와도 원본은 산다
    from gui.ui_plot_maker import load_spec
    dsx = load_spec({"path": p, "derived": [{"name": "NO2", "expr": "NO2 * 0"}]})
    if not np.array_equal(dsx.cols["NO2"], no2) or "NO2" not in dsx.derived_errors:
        return "FAIL", "원본과 같은 이름의 파생 식이 원본 열을 덮어씀"
    dsx.apply_derived()
    if "NO2" not in dsx.cols:
        return "FAIL", "재계산이 원본 열을 걷어냄"

    # 그림에 실제로 쓰인다 (화면 + Publish)
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append([f"{name}:NO2_ugm3", "L", None, None])
    ts.render()
    w._build_publish_fig()

    # 설정 저장 → 새 위젯: 식이 저장되고 값은 다시 계산
    cfgp = os.path.join(tmpd, "d.pmcfg.json")
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getSaveFileName", return_value=(cfgp, "")):
        w._save_cfg()
    with open(cfgp, encoding="utf-8") as f:
        saved = json.load(f)["datasets"][name]["derived"]
    if [d["name"] for d in saved] != ["NO2_ugm3", "anom", "ok_only", "daytime", "bad", "evil"]:
        return "FAIL", f"설정에 식 목록이 안 저장됨: {saved}"
    if any("values" in d for d in saved):
        return "FAIL", "값이 설정에 박힘 — 식만 저장해야 한다"
    w2 = PlotMakerWidget()
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getOpenFileName", return_value=(cfgp, "")):
        w2._load_cfg()
    ds2 = w2.shelf[name]
    if not (np.allclose(ds2.cols["anom"], c["anom"]) and set(ds2.derived_errors) == {"bad", "evil"}):
        return "FAIL", "설정 왕복 후 파생 값/오류 상태가 다름"

    # 의존 열 삭제 → 그 열을 쓰던 열은 빨갛게 드러난다
    w.delete_derived(name, "NO2_ugm3")
    if "anom" in ds.cols or "anom" not in ds.derived_errors:
        return "FAIL", "의존 열 삭제 후 연쇄 열이 조용히 남거나 사라짐"

    # 대화상자: 미리보기 평가 + 잘못된 식이면 OK 비활성
    from PyQt6.QtWidgets import QDialogButtonBox
    dlg = DerivedColumnDialog(ds)
    dlg._name.setText("x2"); dlg._expr.setText("NO2 * 2"); dlg._validate()
    okb = dlg._bb.button(QDialogButtonBox.StandardButton.Ok)
    if not okb.isEnabled() or "✓" not in dlg._msg.text():
        return "FAIL", f"대화상자 미리보기 실패: {dlg._msg.text()}"
    dlg._expr.setText("NO2 *"); dlg._validate()
    if okb.isEnabled():
        return "FAIL", "문법 오류인데 OK가 눌림"

    # 계산기(Result Lab)도 같은 엔진 — 예전 식 그대로 동작
    A, B = np.array([1.0, 4.0]), np.array([2.0, 0.0])
    r = calc_eval("(A - B) / B", {"A": A, "B": B})
    if not (r[0] == -0.5 and np.isinf(r[1])):
        return "FAIL", "계산기 식 결과가 바뀜"
    return "PASS", ("4종 식·연쇄·hour·숨김 연동 · 깨진/위험 식은 빨간 표시(실행 안 됨) · "
                    "원본 열 보호 · 식만 저장·재계산 · 의존 삭제 드러남 · 계산기 호환")


# ── 36. 행 필터(조건식) + Flag 색칠 (D2) ───────────────────────────────────
@check("행 필터: keep/hide 조건식·개별 on/off·깨진 규칙 표시 · Flag 색칠 pg↔mpl")
def c_filters_and_flag_colors():
    import json, tempfile
    from unittest import mock
    from PyQt6.QtCore import Qt as Qt_
    from gui.ui_plot_maker import load_spec
    from gui.ui_plot_maker.filters_dialog import FiltersDialog
    tmpd = tempfile.mkdtemp()
    p = os.path.join(tmpd, "fixture_report.dat")
    _write_report_fixture(p)

    # ── 필터 ──
    w = PlotMakerWidget()
    w.add_specs([{"path": p, "rules": [{"kind": "status_qc"}]}])
    name = next(iter(w.shelf)); ds = w.shelf[name]
    w.set_derived(name, {"name": "NO2x2", "expr": "NO2 * 2"})
    flag, rms = ds.cats["Flag"], ds.cols["RMS"]
    qc = np.array([str(s).startswith("QC") for s in ds.cats["Status"]])

    dlg = FiltersDialog(ds)
    dlg._mode.setCurrentIndex(0); dlg._expr.setText('Flag != "unstable"'); dlg._update_preview()
    if "hides 1 of" not in dlg._preview.text():
        return "FAIL", f"미리보기 개수 틀림: {dlg._preview.text()}"
    dlg._commit(new=True)
    dlg._mode.setCurrentIndex(1); dlg._expr.setText("NO2x2 > 2 * median(NO2)"); dlg._update_preview()
    dlg._commit(new=True)                                  # 파생 열을 쓰는 hide 규칙
    dlg._expr.setText("nosuch > 1"); dlg._update_preview()
    if dlg._btn_add.isEnabled():
        return "FAIL", "깨진 조건인데 Add가 눌림"
    rules, on = dlg.chosen()
    w.set_dataset_view(name, rules=rules, rules_on=on)
    want = qc | (flag == "unstable") | (ds.cols["NO2x2"] > 2 * np.nanmedian(ds.cols["NO2"]))
    if not np.array_equal(ds.hidden_mask(), want):
        return "FAIL", "keep/hide 조건식 마스크 불일치"

    # 규칙 하나만 끄기 (지우지 않고)
    dlg2 = FiltersDialog(ds)
    dlg2._list.item(0).setCheckState(Qt_.CheckState.Unchecked)   # status_qc 끔
    rules2, _ = dlg2.chosen()
    if len(rules2) != 3 or rules2[0].get("on") is not False:
        return "FAIL", "개별 끄기가 삭제로 동작하거나 저장 안 됨"
    w.set_dataset_view(name, rules=rules2)
    want2 = (flag == "unstable") | (ds.cols["NO2x2"] > 2 * np.nanmedian(ds.cols["NO2"]))
    if not np.array_equal(ds.hidden_mask(), want2) or np.array_equal(want2, want):
        return "FAIL", "끈 규칙이 여전히 숨기고 있음"

    # 깨진 조건식 규칙: 그 규칙만 아무것도 안 숨기고 ✗ — 데이터셋은 열린다
    bad_rules = rules2 + [{"kind": "expr", "expr": "nosuch > 1", "mode": "hide"}]
    w.set_dataset_view(name, rules=bad_rules)
    if 3 not in ds.rule_errors or "broken filter" not in w._tree.topLevelItem(0).text(0):
        return "FAIL", "깨진 규칙이 표시되지 않음"
    dsb = load_spec({"path": p, "rules": bad_rules})
    if 3 not in dsb.rule_errors:
        return "FAIL", "깨진 규칙이 있는 레시피를 못 열거나 오류가 안 남음"
    try:
        load_spec({"path": p, "rules": [{"kind": "nosuchkind"}]})
        return "FAIL", "모르는 규칙 kind가 조용히 통과"
    except ValueError:
        pass

    # 설정 왕복 — expr 규칙·개별 off 상태 보존
    cfgp = os.path.join(tmpd, "f.pmcfg.json")
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getSaveFileName", return_value=(cfgp, "")):
        w._save_cfg()
    w2 = PlotMakerWidget()
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getOpenFileName", return_value=(cfgp, "")):
        w2._load_cfg()
    if not np.array_equal(w2.shelf[name].hidden_mask(), ds.hidden_mask()):
        return "FAIL", "설정 왕복 후 필터 마스크 다름"

    # ── Flag 색칠 ──
    w3 = PlotMakerWidget()
    w3.add_specs([p])                                       # 규칙 없음 → qc 점도 보인다
    n3 = next(iter(w3.shelf)); lab = f"{n3}:NO2"
    ts = next(m for m in w3._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append([lab, "L", None, None]); ts._refresh_list()
    ts._styles[lab] = {"color_by": "Flag"}
    ts.render()
    import pyqtgraph as pg_
    pg_flag = {it.opts.get("name"): len(it.xData) for it in w3.p1.items
               if isinstance(it, pg_.PlotDataItem) and str(it.opts.get("name") or "").startswith("flag:")}
    if pg_flag != {"flag: unstable": 1, "flag: qc": 3}:
        return "FAIL", f"화면 flag 점 불일치: {pg_flag}"
    fig = w3._build_publish_fig()
    leg = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
    # 범례 핸들은 범례용 복제본이라 점 개수가 다르다 → 축에 그려진 실제 선을 색으로 센다
    from matplotlib.colors import to_hex
    from gui.result_viewer_io import flag_color
    by_col = {to_hex(flag_color(k)).lower(): f"flag: {k}" for k in ("unstable", "settling", "qc", "cal")}
    mpl_n = {}
    for ln in fig.axes[0].lines:
        lb = by_col.get(to_hex(ln.get_color()).lower())
        if lb and ln.get_linestyle() == "None":
            mpl_n[lb] = mpl_n.get(lb, 0) + len(ln.get_xdata())
    if not {"flag: unstable", "flag: qc"} <= set(leg):
        return "FAIL", f"Publish 범례에 flag 항목이 없음: {leg}"
    if mpl_n != pg_flag:
        return "FAIL", f"Publish flag 점 ≠ 화면: {mpl_n} vs {pg_flag}"
    if w3.p1.items and any(it.opts.get("symbolBrush") is None for it in w3.p1.items
                           if isinstance(it, pg_.PlotDataItem) and str(it.opts.get("name") or "").startswith("flag:")):
        return "FAIL", "flag 점에 색이 없음"
    w3._res_combo.setCurrentText("5 min")                   # 리샘플 → 끄고 이유를 말한다
    ts.render()
    if any(str(getattr(it, "opts", {}).get("name") or "").startswith("flag:") for it in w3.p1.items):
        return "FAIL", "리샘플 중에도 flag 색이 칠해짐(평균 점엔 flag가 없다)"
    if "flag colours off" not in w3._status.text():
        return "FAIL", "리샘플로 꺼졌다는 안내가 없음"
    # 스타일 창에서 OK → 숨겨둔 시리즈가 다시 나타나면 안 된다(전엔 dict 통째 덮어써서 풀렸다)
    from PyQt6.QtWidgets import QDialog
    ts._styles[lab]["visible"] = False
    ts._list.setCurrentRow(0)
    with mock.patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
        ts._edit_style()
    if ts._style_of(lab)["visible"] or ts._style_of(lab)["color_by"] != "Flag":
        return "FAIL", "스타일 편집이 숨김/색칠 설정을 풀어버림"
    return "PASS", ("keep/hide·파생 열 조건·개별 off·깨진 규칙 ✗(데이터셋은 열림)·설정 왕복 · "
                    "Flag 점 pg=mpl {unstable 1, qc 3} · 리샘플 시 끄고 안내")


# ── 37. 데이터셋 간 정렬: 결손 가드 + Join 데이터셋 (D1+) ─────────────────────
@check("정렬: Scatter 결손 가드 · Join(⋈) 데이터셋 — 재료 필터 반영·파생 열·설정 왕복·재료 삭제 ✗")
def c_alignment_and_join():
    import json, tempfile
    from unittest import mock
    from gui.ui_plot_maker.join_dialog import JoinDialog
    tmpd = tempfile.mkdtemp()
    pa = os.path.join(tmpd, "chA.dat")
    pb = os.path.join(tmpd, "chB.dat")
    _write_report_fixture(pa)                                   # 2분 간격 120행
    _write_report_fixture(pb, seed=7, offset_s=30, skip=range(40, 80))   # +30 s, 80분 결손
    w = PlotMakerWidget()
    w.add_specs([pa, pb])
    A, B = w.shelf["chA"], w.shelf["chB"]
    hole = (A.time > B.time[39]) & (A.time < B.time[40])         # B 결손 안에 있는 A 시각

    # Scatter: 다른 데이터셋 짝짓기 — 결손을 가로질러 잇지 않는다
    sc = next(m for m in w._modes if m.key == "scatter")
    sc.options_widget()
    sc._cx.setCurrentText("chA:NO2"); sc._cy.setCurrentText("chB:NO2")
    xv, yv, _ = sc._xy()
    if not (np.all(np.isnan(yv[hole])) and np.isfinite(yv[~hole][1:-1]).all()):
        return "FAIL", "Scatter가 결손 구간을 보간으로 메움(또는 정상 구간을 버림)"
    w._mode_combo.setCurrentIndex([m.key for m in w._modes].index("scatter"))
    sc.render()
    if "left unpaired" not in w._status.text():
        return "FAIL", f"짝 못 지은 점 안내 없음: {w._status.text()}"

    # Join 대화상자 미리보기 → Join 데이터셋
    dlg = JoinDialog("chA", w.shelf)
    dlg._other.setCurrentText("chB"); dlg._preview()
    if "✓" not in dlg._msg.text():
        return "FAIL", f"Join 미리보기 실패: {dlg._msg.text()}"
    jn = w.add_join(dlg.spec())
    J = w.shelf.get(jn)
    if J is None or "NO2_B" not in J.cols or not np.array_equal(J.cols["NO2"], A.cols["NO2"]):
        return "FAIL", f"Join 열 구성 이상: {None if J is None else list(J.cols)}"
    if not np.all(np.isnan(J.cols["NO2_B"][hole])) or J.join_info["n_gap"] != int(hole.sum()):
        return "FAIL", f"Join이 결손을 메움 / n_gap {J.join_info['n_gap']} ≠ {int(hole.sum())}"
    if not np.allclose(J.cols["NO2_B"][~hole][1:-1], yv[~hole][1:-1]):
        return "FAIL", "Join 값 ≠ Scatter 짝 값(같은 정렬 함수여야)"
    if w.set_derived(jn, {"name": "dNO2", "expr": "NO2 - NO2_B"}):
        return "FAIL", "Join 위 파생 열(데이터셋 간 차이) 실패"

    # 재료 필터를 바꾸면 Join이 다시 만들어진다(보이는 그대로)
    w.set_dataset_view("chB", rules=[{"kind": "expr", "expr": "NO2 < 5", "mode": "keep"}])
    if np.isfinite(J.cols["NO2_B"]).sum() >= np.isfinite(yv).sum() or "dNO2" not in J.cols:
        return "FAIL", "재료 필터 변경이 Join에 반영 안 됨(또는 파생 열이 사라짐)"
    w.set_dataset_view("chB", rules=[])

    # 설정 왕복 — Join은 재료 다음에, 레시피로
    cfgp = os.path.join(tmpd, "j.pmcfg.json")
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getSaveFileName", return_value=(cfgp, "")):
        w._save_cfg()
    with open(cfgp, encoding="utf-8") as f:
        saved = json.load(f)["datasets"][jn]
    if "join" not in saved or "path" in saved:
        return "FAIL", f"Join이 레시피로 저장 안 됨: {list(saved)}"
    w2 = PlotMakerWidget()
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getOpenFileName", return_value=(cfgp, "")):
        w2._load_cfg()
    J2 = w2.shelf.get(jn)
    if J2 is None or not np.allclose(J2.cols["dNO2"], J.cols["dNO2"], equal_nan=True):
        return "FAIL", "설정 왕복 후 Join/파생 값 다름"

    # 재료 삭제 → 묵은 값 없이 ✗
    w2.shelf.pop("chB"); w2._refresh_tree()
    J2 = w2.shelf[jn]
    if J2.cols or "error" not in J2.join_info:
        return "FAIL", "재료가 사라졌는데 Join에 묵은 값이 남음"
    top = [w2._tree.topLevelItem(i).text(0) for i in range(w2._tree.topLevelItemCount())]
    if not any("⋈ ✗" in t for t in top):
        return "FAIL", f"트리에 Join 오류 표시 없음: {top}"
    return "PASS", (f"결손 {int(hole.sum())}점 안 메움(Scatter·Join 같은 값) · 안내 · Join 위 파생 열 · "
                    "재료 필터 반영 · 레시피 저장·왕복 · 재료 삭제 시 ✗")


# ── 38. Scatter Deming 회귀 + Result Lab 구간 추세 ─────────────────────────
@check("Deming 회귀(x 오차 편향 보정) · OLS 기본 불변 · λ from 1σ · Result Lab 구간 추세")
def c_deming_and_trend():
    from gui.ui_plot_maker.processing import regress, regress_deming, trend_per_hour
    rng = np.random.default_rng(3)
    true = rng.uniform(0, 20, 4000)
    x = true + rng.normal(0, 2.0, true.size)        # x에도 오차 → OLS 기울기 감쇠
    y = 1.5 * true + 1.0 + rng.normal(0, 2.0 * 1.5, true.size)
    s_ols = regress(x, y)[0]
    s_dem = regress_deming(x, y, lam=1.5 ** 2)[0]
    if not (s_ols < 1.45 and abs(s_dem - 1.5) < 0.03):
        return "FAIL", f"Deming 편향 보정 실패: OLS {s_ols:.3f} / Deming {s_dem:.3f} (참 1.5)"
    tt = 1_750_000_000.0 + np.arange(200) * 120.0
    tr = trend_per_hour(tt, 3.0 + 0.25 * (tt - tt[0]) / 3600 + rng.normal(0, 0.01, 200))
    if not (abs(tr[0] - 0.25) < 0.002 and tr[1] > 0):
        return "FAIL", f"구간 추세 틀림: {tr}"

    # 모드: 기본 OLS 제목은 예전 그대로, Deming 선택 시 표기 + Publish + 설정 왕복
    w = PlotMakerWidget()
    from gui.ui_plot_maker import Dataset
    n = true.size
    ds = Dataset("dm", "<fixture:dm>", 1_750_000_000.0 + np.arange(n) * 60.0,
                 {"A": x, "B": y}, errs={"A": np.full(n, 2.0), "B": np.full(n, 3.0)})
    w.shelf["dm"] = ds; w._refresh_tree(); w._notify_modes()
    sc = next(m for m in w._modes if m.key == "scatter")
    sc.options_widget()
    w._mode_combo.setCurrentIndex([m.key for m in w._modes].index("scatter"))
    sc._cx.setCurrentText("dm:A"); sc._cy.setCurrentText("dm:B")
    sc.render()
    t_ols = sc._fit_title(sc._fit(*sc._xy()[:2]))
    if "[" in t_ols or not t_ols.startswith("y = "):
        return "FAIL", f"OLS 기본 제목이 바뀜: {t_ols}"
    sc._fit_combo.setCurrentText("Deming (λ from 1σ errors)")
    r = sc._fit(*sc._xy()[:2])
    if "λ=2.25 from 1σ" not in r[4] or abs(r[0] - 1.5) > 0.03:
        return "FAIL", f"λ from 1σ 실패: {r}"
    if "Deming" not in w._status.text():
        return "FAIL", "상태줄에 적합 방법 표기 없음"
    fig = w._build_publish_fig()
    if "Deming" not in fig.axes[0].get_title():
        return "FAIL", "Publish 제목에 방법 표기 없음"
    cfg = sc.to_config()
    sc2 = type(sc)(w); sc2.options_widget(); sc2.from_config(cfg)
    if sc2._fit_combo.currentText() != cfg["fit"]:
        return "FAIL", "적합 방법 설정 왕복 실패"

    # Result Lab Σ Stats 에 추세 열
    import tempfile
    from gui.ui_result_viewer import ResultViewerWidget
    from PyQt6.QtWidgets import QPlainTextEdit
    p = os.path.join(tempfile.mkdtemp(), "fixture_report.dat")
    _write_report_fixture(p)
    rv = ResultViewerWidget(); rv._path = p; rv._reload()
    rv._show_stats()
    eds = rv.findChildren(QPlainTextEdit)
    if not eds or "trend /h" not in eds[-1].toPlainText():
        return "FAIL", "Result Lab Stats에 구간 추세가 없음"
    return "PASS", (f"OLS {s_ols:.3f} → Deming {s_dem:.3f} (참 1.5) · 추세 {tr[0]:.4f}/h (참 0.25) · "
                    "OLS 제목 불변 · λ from 1σ · Publish 표기 · 설정 왕복 · Stats 추세 열")


# ── 39. Copernicus 저널 프리셋 ───────────────────────────────────────────
@check("Copernicus 프리셋: 폭·dpi·글자/눈금 크기·눈금 방향·Okabe-Ito가 Publish에 한 번에")
def c_copernicus_preset():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._series.append(["fixture:CHOCHO", "L", None, None])
    ts._refresh_list()
    name = "Copernicus (ACP/AMT) — 1 column"
    w._theme_combo.setCurrentText(name)
    w._apply_theme(name)
    fig = w._build_publish_fig()
    wi, hi = fig.get_size_inches()
    if (round(wi, 2), round(hi, 2)) != (3.27, 2.45) or w._dpi_spin.value() != 300:
        return "FAIL", f"크기/dpi 불일치: {wi:.2f}×{hi:.2f} @ {w._dpi_spin.value()}"
    if w._chk_autosize.isChecked():
        return "FAIL", "모드별 자동 크기가 안 꺼짐(모드 바꾸면 논문 폭이 덮인다)"
    ax = fig.axes[0]
    tl = ax.get_xticklabels() + ax.get_yticklabels()
    sizes = {round(t.get_fontsize()) for t in tl if t.get_text()}
    if sizes and sizes != {7}:
        return "FAIL", f"눈금 글자 크기 ≠ 7 pt: {sizes}"
    if round(ax.yaxis.label.get_fontsize()) != 8:
        return "FAIL", f"축 라벨 크기 ≠ 8 pt: {ax.yaxis.label.get_fontsize()}"
    tdir = ax.xaxis.get_major_ticks()[0]._tickdir if ax.xaxis.get_major_ticks() else "in"
    if tdir != "in":
        return "FAIL", f"눈금 방향이 안쪽이 아님: {tdir}"
    from matplotlib.colors import to_hex
    cols = [to_hex(l.get_color()).lower() for l in ax.get_lines()[:2]]
    if cols != ["#000000", "#e69f00"]:
        return "FAIL", f"Okabe-Ito 순서 색이 아님: {cols}"
    if ax.xaxis._major_tick_kw.get("gridOn", False):
        return "FAIL", "격자가 켜져 있음"
    return "PASS", "3.27×2.45 in @300 · autosize 끔 · 8 pt 라벨/7 pt 눈금 · 눈금 안쪽 · Okabe-Ito · 격자 끔"


# ── 40. Preview 모덜리스 + 자동 갱신 (M-P) ─────────────────────────────────
@check("Preview: 모덜리스·싱글턴 · 설정 바뀌면 한 박자 뒤 다시 그림 · 그대로면 안 그림 · 오류는 창 안에")
def c_preview_modeless():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None]); ts._refresh_list()
    w._preview_publish()
    dlg = w._preview_dlg
    if dlg.isModal() or not dlg.isVisible() or dlg._lbl.pixmap().isNull():
        return "FAIL", "Preview가 모덜이거나 안 보이거나 그림이 없음"
    n0 = dlg.n_renders
    w._preview_publish()                         # 다시 눌러도 창은 하나
    if w._preview_dlg is not dlg or dlg.n_renders != n0 + 1:
        return "FAIL", "Preview 창이 여러 개 생기거나 즉시 갱신 안 됨"
    n1 = dlg.n_renders
    dlg._tick(); dlg._tick()                     # 아무것도 안 바뀜 → 다시 그리지 않는다
    if dlg.n_renders != n1:
        return "FAIL", "변화가 없는데 다시 그림(헛수고)"
    w._ed_title.setText("Changed title"); w.custom["title"] = "Changed title"
    dlg._tick()                                  # 바뀐 직후 — 한 박자 기다림
    if dlg.n_renders != n1:
        return "FAIL", "바뀐 직후 바로 그림(타이핑 중 렌더 폭탄)"
    dlg._tick()                                  # 그대로 → 이제 그린다
    if dlg.n_renders != n1 + 1:
        return "FAIL", "설정이 바뀌었는데 자동 갱신 안 됨"
    ts._styles["fixture:NO2"] = {"kind": "bar"}  # 시리즈 스타일 변경도 지문에 잡혀야
    dlg._tick(); dlg._tick()
    if dlg.n_renders != n1 + 2:
        return "FAIL", "시리즈 스타일 변경이 자동 갱신을 못 깨움"
    # 렌더 오류는 팝업이 아니라 창 안에 (자동 갱신 중 메시지박스 폭탄 금지)
    from unittest import mock
    with mock.patch.object(type(w), "_build_publish_fig", side_effect=RuntimeError("boom")):
        dlg.refresh()
    if "boom" not in dlg._info.text():
        return "FAIL", "렌더 오류가 창 안에 표시 안 됨"
    dlg.close()
    return "PASS", "모덜리스·싱글턴 · 무변화 시 안 그림 · 변화 후 한 박자 뒤 갱신 · 스타일 변경 감지 · 오류는 창 안"


# ── 41. 모드는 받은 패널 안에만 그린다 (M1) ─────────────────────────────────
@check("M1: 6개 모드 render_mpl(fig, ax) — 받은 패널 안에만, 옆 패널 무손상 (분할 시계열 포함)")
def c_render_into_panel():
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series.append(["fixture:NO2", "L", None, None])
    ts._series.append(["fixture:CHOCHO", "L", None, None])
    ts._refresh_list()
    bad = []
    for split in (False, True):
        ts._chk_split.setChecked(split)
        for i, m in enumerate(w._modes):
            if split and m.key != "timeseries":
                continue
            w._mode_combo.setCurrentIndex(i)
            for attr in ("_c", "_cx", "_cy"):
                c = getattr(m, attr, None)
                if c is not None and not c.currentText():
                    c.setCurrentText("fixture:NO2")
            # 위 = 남의 패널, 아래 = 모드 패널. autofmt_xdate는 '아래 행이 아닌' 축의 x 라벨을
            # 숨기므로 이 배치에서 그림 전체 호출이 있으면 위 패널이 망가져 걸린다.
            fig = Figure(figsize=(6, 8)); FigureCanvasAgg(fig)
            other, panel = fig.subplots(2, 1)
            other.set_xlabel("keep me"); other.plot([0, 1], [0, 1])
            cell = panel.get_position()
            try:
                m.render_mpl(fig, panel)
            except NotImplementedError:
                continue
            fig.canvas.draw()
            tag = m.key + ("_split" if split else "")
            if other.get_xlabel() != "keep me" or not other.xaxis.label.get_visible():
                bad.append(f"{tag}: 옆 패널 x 라벨이 사라짐")
            if not any(t.get_visible() and t.get_text() for t in other.get_xticklabels()):
                bad.append(f"{tag}: 옆 패널 눈금 숫자가 숨겨짐(autofmt_xdate 류)")
            for a in fig.axes:
                if a is other:
                    continue
                p = a.get_position()
                if p.y1 > cell.y1 + 0.02:      # 패널 칸 위로 삐져나옴 = 그림 전체 축(add_subplot(111) 류)
                    bad.append(f"{tag}: 모드가 패널 밖에 축을 만듦 (y1 {p.y1:.2f} > {cell.y1:.2f})")
            if split and len([a for a in fig.axes if a is not other]) != 2:
                bad.append(f"{tag}: 분할이 패널 안에서 2칸으로 안 쪼개짐 ({len(fig.axes) - 1})")
    if bad:
        return "FAIL", "; ".join(bad)
    return "PASS", "6개 모드 + 분할 시계열이 받은 패널 안에만 · 옆 패널 라벨·눈금 무손상"


# ── 42. Composer: 다중 패널 조판 (M2) ──────────────────────────────────────
@check("Composer: 패널 조각으로 그림·편집기 무오염·편집 연결·inset·x 공유·비율·룩 공통·설정 왕복")
def c_composer():
    import json
    w = _widget_with_fixture()
    keys = [m.key for m in w._modes]
    ts = w._modes[keys.index("timeseries")]
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None]); ts._refresh_list()
    w._mode_combo.setCurrentIndex(keys.index("timeseries"))
    w._ed_title.setText("TS panel"); w.custom["title"] = "TS panel"
    comp = w.composer
    comp.add_current()                                           # (a)
    sc = w._modes[keys.index("scatter")]
    w._mode_combo.setCurrentIndex(keys.index("scatter"))
    sc._cx.setCurrentText("fixture:NO2"); sc._cy.setCurrentText("fixture:CHOCHO")
    w._ed_title.setText("SC panel"); w.custom["title"] = "SC panel"
    comp.add_current()                                           # (b)
    if [p["cell"] for p in comp.panels] != [[0, 0, 1, 1], [0, 1, 1, 1]] or not comp.active():
        return "FAIL", f"빈 칸 배치 이상: {[p.get('cell') for p in comp.panels]}"
    if comp.editing is not None:
        return "FAIL", "추가 직후 편집기가 패널에 묶임 — 다음 화면 변경이 그 패널을 덮어쓴다"

    n_screen = len(w.p1.items)
    axes_before = w._axes_state()
    fig = w._build_publish_fig()
    main = [a for a in fig.axes if a.get_label() != "<colorbar>" and getattr(a, "_colorbar", None) is None]
    titles = sorted(a.get_title() for a in main)
    if titles != ["SC panel", "TS panel"]:
        return "FAIL", f"패널 제목이 자기 조각을 안 따름: {titles}"
    letters = sorted(a.get_title(loc="left") for a in main if a.get_title(loc="left"))
    if letters != ["(a)", "(b)"]:
        return "FAIL", f"패널 글자 이상: {letters}"
    if w._mode is not sc or w.custom["title"] != "SC panel" or w._axes_state() != axes_before:
        return "FAIL", "조판 그리기가 편집기 상태(모드·라벨·축)를 바꿔 놓음"
    if len(w.p1.items) != n_screen:
        return "FAIL", "조판 그리기가 화면(pg)을 건드림"

    comp.edit(0)                                                  # (a) 편집 → 편집기가 시계열로
    if w._mode is not ts or w.custom["title"] != "TS panel":
        return "FAIL", "Edit이 패널을 편집기에 안 실음"
    w._ed_title.setText("TS v2"); w.custom["title"] = "TS v2"
    titles = sorted(a.get_title() for a in w._build_publish_fig().axes if a.get_title())
    if titles != ["SC panel", "TS v2"]:
        return "FAIL", f"편집 중 변경이 그 패널로 안 들어감: {titles}"

    # inset: (c)를 (a) 안에
    comp.add_current()
    comp.set_position(2, inset={"in": 0, "rect": [0.6, 0.6, 0.35, 0.35]})
    fig = w._build_publish_fig(); fig.canvas.draw()
    every = list(fig.axes) + [c for a in fig.axes for c in getattr(a, "child_axes", [])]
    tsx = [a for a in every if a.get_title() == "TS v2"]
    if len(tsx) != 2:
        return "FAIL", f"inset 패널이 안 그려짐 ({len(tsx)})"
    big, small = sorted(tsx, key=lambda a: a.get_position().width, reverse=True)
    bb, sb = big.get_position(), small.get_position()
    if not (bb.x0 <= sb.x0 and sb.x1 <= bb.x1 + 1e-6 and bb.y0 <= sb.y0 and sb.y1 <= bb.y1 + 1e-6):
        return "FAIL", "inset이 꽂힌 패널 밖에 있음"

    # 룩(눈금 크기)은 그림 전체 — 패널을 찍은 뒤 바꿔도 모든 패널에
    w._tick_size.setValue(7)
    fig = w._build_publish_fig()
    sizes = {round(t.get_fontsize()) for a in fig.axes for t in a.get_yticklabels() if t.get_text()}
    if sizes != {7}:
        return "FAIL", f"룩(눈금 7 pt)이 전 패널에 안 먹음: {sizes}"
    ins = [c for a in fig.axes for c in getattr(a, "child_axes", [])]
    isz = {round(t.get_fontsize()) for a in ins for t in a.get_yticklabels() if t.get_text()}
    if not ins or not isz or max(isz) >= 7:
        return "FAIL", f"inset 눈금 글자가 주 패널보다 작지 않음: {isz}"

    # x 공유 + 높이 비율: 시계열 두 개를 위아래로
    w2 = _widget_with_fixture()
    ts2 = w2._modes[[m.key for m in w2._modes].index("timeseries")]
    ts2.options_widget()
    c2 = w2.composer
    c2.rows, c2.cols, c2.sharex, c2.hratios = 2, 1, True, "2,1"
    for col in ("NO2", "CHOCHO"):
        ts2._series[:] = [[f"fixture:{col}", "L", None, None]]; ts2._refresh_list()
        c2.add_current()
    fig = w2._build_publish_fig(); fig.canvas.draw()
    ax_top, ax_bot = sorted([a for a in fig.axes], key=lambda a: -a.get_position().y1)[:2]
    if ax_top.get_xlim() != ax_bot.get_xlim():
        return "FAIL", "x 공유가 안 됨"
    if any(t.get_visible() and t.get_text() for t in ax_top.get_xticklabels()):
        return "FAIL", "x 공유인데 위 패널 x 눈금 숫자가 남음"
    hr = ax_top.get_position().height / ax_bot.get_position().height
    if not 1.6 < hr < 2.4:
        return "FAIL", f"높이 비율 2:1 아님 ({hr:.2f})"

    # 설정 왕복
    cfg = json.loads(json.dumps(w.config_dict(), default=str))
    w3 = _widget_with_fixture()
    w3.composer.from_config(cfg["compose"])
    f3 = w3._build_publish_fig()
    t3 = sorted(a.get_title() for a in list(f3.axes) + [c for a in f3.axes for c in a.child_axes]
                if a.get_title())
    if t3 != ["SC panel", "TS v2", "TS v2"] or w3.composer.editing != comp.editing:
        return "FAIL", f"조판 설정 왕복 실패: {t3}"
    # 끄면 예전 단일 그림
    comp.on = False
    if len([a for a in w._build_publish_fig().axes if a.get_label() != "<colorbar>"]) != 1:
        return "FAIL", "조판을 껐는데 단일 그림으로 안 돌아옴"
    return "PASS", ("2패널+inset · 제목·(a)(b) · 편집기/화면 무오염 · Edit 연결·변경 반영 · inset 위치 · "
                    f"룩 공통 · x 공유·높이 {hr:.2f}:1 · 설정 왕복 · 끄면 단일")


# ── 43. 오른쪽 축(twinx) 눈금이 왼쪽에 겹쳐 찍히지 않는다 ─────────────────────
@check("R축 눈금은 오른쪽에만 — 왼쪽 축 숫자 옆에 겹쳐 찍히지 않음 (Publish)")
def c_twin_ticks_right_only():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series[:] = [["fixture:NO2", "L", None, None], ["fixture:CHOCHO", "R", None, None]]
    ts._refresh_list()
    fig = w._build_publish_fig(); fig.canvas.draw()
    right = [a for a in fig.axes if a.yaxis.get_label_position() == "right"]
    if len(right) != 1:
        return "FAIL", f"R축이 안 생김 ({len(right)})"
    t = right[0].yaxis.get_major_ticks()[0]
    if t.label1.get_visible() or not t.label2.get_visible():
        return "FAIL", "R축 눈금 숫자가 왼쪽에 찍힘(또는 오른쪽에 없음) — 왼쪽 축 숫자와 겹친다"
    w._chk_yticks.setChecked(False)              # 숫자 끄기도 R축에 같은 규칙
    fig = w._build_publish_fig(); fig.canvas.draw()
    right = [a for a in fig.axes if a.yaxis.get_label_position() == "right"][0]
    if right.yaxis.get_major_ticks()[0].label2.get_visible():
        return "FAIL", "Y 숫자 끄기가 R축에 안 먹음"
    return "PASS", "R축 눈금은 오른쪽에만 · 숫자 끄기도 R축에 적용"


# ── 44. 내장 콘솔 (D3) ────────────────────────────────────────────────────
@check("콘솔: df/push 왕복·보이는 그대로·오류 격리·여러 줄 · 기록 저장 · 설정 열 때 자동 실행 금지 · rerun")
def c_console():
    import json, tempfile
    from unittest import mock
    tmpd = tempfile.mkdtemp()
    p = os.path.join(tmpd, "fixture_report.dat")
    _write_report_fixture(p)
    w = PlotMakerWidget()
    w.add_specs([{"path": p, "rules": [{"kind": "status_qc"}]}])
    name = next(iter(w.shelf)); src = w.shelf[name]
    w._open_console()
    con = w._console_dlg
    con.execute(f"x = df({name!r})")
    x = con.ns["x"]
    hid = src.hidden_mask()
    if not (np.all(np.isnan(x["NO2"].to_numpy()[hid])) and "Flag" in x.columns):
        return "FAIL", "df()가 보이는 그대로(숨김 NaN·범주형 열)가 아님"
    con.execute("y = x[['NO2']] * 2")
    con.execute("push(y, 'dbl')")
    d = w.shelf.get("dbl")
    if d is None or not np.allclose(d.cols["NO2"], np.where(hid, np.nan, src.cols["NO2"]) * 2,
                                    equal_nan=True):
        return "FAIL", "push()가 선반에 맞는 값을 안 올림"
    if not np.allclose(d.time, src.time):
        return "FAIL", "push()가 시각을 잃음(DatetimeIndex 왕복)"
    if d.origin is None or "push(y, 'dbl')" not in d.origin["history"]:
        return "FAIL", "push한 데이터셋에 입력 기록이 안 붙음"
    con.execute("1/0")
    if "ZeroDivisionError" not in con.out.toPlainText():
        return "FAIL", "예외가 창에 안 찍힘"
    if not (con.execute("for i in range(3):") and con.execute("    z = i")) or con.execute(""):
        return "FAIL", "여러 줄 블록 처리 이상"
    if con.ns.get("z") != 2:
        return "FAIL", "여러 줄 블록이 실행 안 됨"

    # 기록에 '부작용 있는 코드'를 넣고 저장 → 설정을 열 때 자동 실행되면 안 된다
    sentinel = os.path.join(tmpd, "ran_on_load.txt")
    con.execute(f"open(r'{sentinel}', 'w').close()")
    con.execute("push(y + 1, 'evil')")
    os.remove(sentinel)
    cfgp = os.path.join(tmpd, "c.pmcfg.json")
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getSaveFileName", return_value=(cfgp, "")):
        w._save_cfg()
    with open(cfgp, encoding="utf-8") as f:
        saved = json.load(f)["datasets"]
    if "console" not in saved.get("evil", {}) or "path" in saved["evil"]:
        return "FAIL", f"콘솔 데이터셋이 기록으로 저장 안 됨: {saved.get('evil')}"
    w2 = PlotMakerWidget()
    with mock.patch("gui.ui_plot_maker.widget.QFileDialog.getOpenFileName", return_value=(cfgp, "")):
        w2._load_cfg()
    if os.path.exists(sentinel):
        return "FAIL", "설정을 열자 콘솔 기록이 자동 실행됨 — 공유 설정이 임의 코드를 돌린다!"
    if "evil" in w2.shelf or "evil" not in w2._console_pending or "rerun" not in w2._status.text():
        return "FAIL", "콘솔 데이터셋이 대기·안내 없이 사라지거나 몰래 만들어짐"
    w2._open_console()
    w2._console_dlg.execute("rerun('dbl')")              # 사람이 직접 칠 때만 다시 만든다
    if "dbl" not in w2.shelf or not np.allclose(w2.shelf["dbl"].cols["NO2"], d.cols["NO2"],
                                                  equal_nan=True):
        return "FAIL", f"rerun()이 데이터셋을 못 되살림: {w2._console_dlg.out.toPlainText()[-300:]}"
    return "PASS", ("df 보이는 그대로·push 시각 왕복·기록 부착 · 예외 격리·여러 줄 · 설정 저장=기록만 · "
                    "열 때 자동 실행 안 함(센티넬) · rerun으로만 재생성")


# ── 45. 주석 시각 파서 = _parse_x · 깨진 주석은 건너뛰고 지목 (R1, 2026-10-02) ──
@check("주석 시각: 'MM-DD HH:MM'=데이터 연도·로컬 · 깨진 주석이 Publish를 안 죽이고 지목됨")
def c_annot_time_parse():
    import datetime as _dt
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None])
    ts.render()                                        # _time_axis=True
    yr = _dt.datetime.fromtimestamp(float(w.shelf["fixture"].time[0])).year
    want = _dt.datetime(yr, 5, 20, 12, 0).timestamp()
    for txt in ("05-20 12:00", f"{yr}-05-20 12:00"):
        got = w._parse_annot_x(txt)
        if got != want:
            return "FAIL", f"{txt!r} → {got} (기대 {want}: 데이터 연도·로컬 시각)"
    w._annots = [{"kind": "vline", "x1": -6.2e10, "label": "bad", "color": "#d32f2f"},
                 {"kind": "vline", "x1": float(np.median(w.shelf["fixture"].time)),
                  "label": "good", "color": "#d32f2f"}]
    fig = w._build_publish_fig()
    if fig is None:
        return "FAIL", "깨진 주석 하나로 Publish 실패"
    import io
    fig.savefig(io.BytesIO(), format="png")
    if len(w._publish_warnings) != 1 or "bad" not in w._publish_warnings[0]:
        return "FAIL", f"건너뛴 주석 지목 안 됨: {w._publish_warnings}"
    texts = {t.get_text().strip() for a in fig.axes for t in a.texts}
    if "good" not in texts:
        return "FAIL", f"정상 주석까지 사라짐: {texts}"
    return "PASS", "연도 생략·포함 모두 로컬 같은 시각 · 깨진 주석만 건너뛰고 이름 남김"


# ── 46. Export CSV: 다른 시간축은 core.align — 외삽·결손 메움 금지 + 헤더 기록 (R3) ──
@check("Export CSV: 다른 시간축 외삽·결손 메움 없음 · '#' 헤더에 시프트·리샘플 · 다시 읽힘")
def c_csv_no_fabrication():
    import tempfile
    from PyQt6.QtWidgets import QFileDialog
    from gui.ui_plot_maker.data import load_dataset
    w = _widget_with_fixture()
    a = w.shelf["fixture"]
    # 뒤 절반만 겹치고, 가운데 2시간 결손이 있는 두 번째 데이터셋
    t2 = np.concatenate([a.time[250:350], a.time[-30:] + 600.0])
    b = Dataset("fx2", "<fixture:fx2>", t2, {"NO2": np.arange(len(t2), dtype=float)})
    w.shelf["fx2"] = b; w._refresh_tree(); w._notify_modes()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series += [["fixture:NO2", "L", None, None], ["fx2:NO2", "L", None, None]]
    headers, rows = ts.csv_table()
    col = [r[2] for r in rows]
    if any(col[i] for i in range(0, 250)):
        return "FAIL", "앞쪽 범위 밖 행에 값이 채워짐(끝값 외삽)"
    if any(col[i] for i in range(360, 460)):
        return "FAIL", "결손 구간을 직선으로 메움"
    if not all(col[i] for i in range(250, 350)):
        return "FAIL", "겹치는 구간 값이 비었음"
    orig = QFileDialog.getSaveFileName
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "x.csv")
            QFileDialog.getSaveFileName = staticmethod(lambda *a_, **k: (out, ""))
            w._export_csv()
            txt = open(out, encoding="utf-8").read()
            if not txt.startswith("# Augur Plot Maker export") or "resample" not in txt or "time shift" not in txt:
                return "FAIL", f"CSV 헤더 기록 없음: {txt[:120]!r}"
            ds = load_dataset(out)
            if ds.time is None or len(ds.time) != len(rows):
                return "FAIL", "'#' 헤더가 붙은 CSV를 Plot Maker가 다시 못 읽음"
    finally:
        QFileDialog.getSaveFileName = orig
    return "PASS", "범위 밖·결손은 빈 칸 · 겹친 구간만 값 · 헤더에 시프트/리샘플 · 재로드 정상"


# ── 47. 시간축 시계(tz) 표기 + UTC 위 Night 경고 (R4, 2026-10-02) ─────────────
@check("시간축 시계: fit meta→UTC 표기 · +9h면 KST · time_KST 열 인식 · UTC 위 Night 경고")
def c_time_basis_night():
    import tempfile, json
    from gui.ui_plot_maker.data import load_dataset
    from core.run_meta import meta_path_for
    with tempfile.TemporaryDirectory() as tmp:
        fp = os.path.join(tmp, "rep.dat")
        _write_report_fixture(fp)
        if load_dataset(fp).tz_h is not None:
            return "FAIL", "meta 없는 fit 파일인데 시계를 추측함"
        with open(meta_path_for(fp), "w", encoding="utf-8") as f:
            json.dump({"time_shift_h": 0}, f)
        ds = load_dataset(fp)
        if ds.tz_h != 0.0:
            return "FAIL", f"meta time_shift_h=0인데 tz_h={ds.tz_h}"
        cp = os.path.join(tmp, "sig.csv")
        with open(cp, "w", encoding="utf-8") as f:
            f.write("time_KST,SigmaANs\n2026-05-20 00:00,1\n2026-05-20 00:05,2\n")
        cs = load_dataset(cp)
        if cs.time is None or cs.tz_h != 9.0:
            return "FAIL", f"time_KST 열: time={cs.time is not None} tz_h={cs.tz_h}"
    w = PlotMakerWidget()
    w.shelf[ds.name] = ds; w._refresh_tree(); w._notify_modes()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget(); ts._series.append([f"{ds.name}:NO2", "L", None, None])
    ts._chk_night.setChecked(True)
    ts.render()
    xl = w.p1.getAxis("bottom").labelText
    if "UTC" not in xl:
        return "FAIL", f"화면 x 라벨에 UTC 없음: {xl!r}"
    if "Night is shaded on a UTC clock" not in w._status.text():
        return "FAIL", f"UTC 위 Night 경고 없음: {w._status.text()!r}"
    fig = w._build_publish_fig()
    if "UTC" not in fig.axes[0].get_xlabel():
        return "FAIL", f"Publish x 라벨에 UTC 없음: {fig.axes[0].get_xlabel()!r}"
    w._shift_spin.setValue(9.0); w._on_transform_changed()
    ts.render()
    if "KST" not in w.p1.getAxis("bottom").labelText or "UTC clock" in w._status.text():
        return "FAIL", f"+9h 뒤: {w.p1.getAxis('bottom').labelText!r} / {w._status.text()!r}"
    return "PASS", "meta 없으면 모름 · UTC/KST 라벨(화면·Publish) · time_KST 인식 · 시프트 0+Night 경고, +9h면 해제"


# ── 48. Split 패널: Y-left/Y-right 범위·log가 자기 축 시리즈 패널에 (R5, 2026-10-02) ──
@check("Split: Y-left 범위·log는 좌축 시리즈 패널 전부, Y-right는 우축 시리즈 패널에만")
def c_split_axis_ranges():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series += [["fixture:NO2", "L", None, None], ["fixture:CHOCHO", "R", None, None],
                   ["fixture:NO2", "L", "#000000", None]]
    ts._chk_split.setChecked(True)
    w._ax_ymin.setText("1"); w._ax_ymax.setText("10")
    w._ax_rmin.setText("0"); w._ax_rmax.setText("1")
    w._chk_logy.setChecked(True)
    fig = w._build_publish_fig()
    ax = [a for a in fig.axes if hasattr(a, "_pm_axis")]
    if len(ax) != 3:
        return "FAIL", f"분할 패널 {len(ax)}개 (3 기대)"
    got = [(a._pm_axis, tuple(round(v, 3) for v in a.get_ylim()), a.get_yscale()) for a in ax]
    want = [("L", (1.0, 10.0), "log"), ("R", (0.0, 1.0), "linear"), ("L", (1.0, 10.0), "log")]
    if got != want:
        return "FAIL", f"패널별 (축, ylim, scale) {got} ≠ {want}"
    return "PASS", "좌축 패널 2개 = Y-left+log · 우축 패널 = Y-right"


# ── 49. Theme이 사용자가 정한 선 굵기를 보존 (R6, 2026-10-02) ───────────────
@check("Theme: 기본 굵기 시리즈는 테마를 따르고, 사용자가 정한 굵기는 보존")
def c_theme_keeps_user_width():
    w = _widget_with_fixture()
    ts = next(m for m in w._modes if m.key == "timeseries")
    ts.options_widget()
    ts._series += [["fixture:NO2", "L", None, None], ["fixture:CHOCHO", "L", None, None]]
    ts._styles.setdefault("fixture:CHOCHO", {})["width"] = 5
    w._apply_theme("Paper")
    a = ts._styles.get("fixture:NO2", {}).get("width"); b = ts._styles["fixture:CHOCHO"]["width"]
    if (a, b) != (1, 5):
        return "FAIL", f"Paper 뒤 (기본, 사용자) 굵기 = {(a, b)} (1, 5 기대)"
    w._apply_theme("PPT")
    a = ts._styles["fixture:NO2"]["width"]; b = ts._styles["fixture:CHOCHO"]["width"]
    if (a, b) != (3, 5):
        return "FAIL", f"PPT 뒤 (기본, 사용자) 굵기 = {(a, b)} (3, 5 기대)"
    return "PASS", "테마 굵기는 기본 시리즈에만 · 사용자 5 보존"


# ── 50. 조판: 데이터셋이 사라진 패널은 'missing: …' + 경고 (R8, 2026-10-02) ──────
@check("Composer: 데이터셋이 지워진 패널은 빈 축 대신 'missing: …' + Publish 경고")
def c_composer_missing_dataset():
    w = _widget_with_fixture()
    ds2 = _fixture_dataset("fx2", seed=5)
    w.shelf["fx2"] = ds2; w._refresh_tree(); w._notify_modes()
    keys = [m.key for m in w._modes]
    ts = w._modes[keys.index("timeseries")]
    ts.options_widget(); ts._series.append(["fixture:NO2", "L", None, None]); ts._refresh_list()
    w._mode_combo.setCurrentIndex(keys.index("timeseries"))
    comp = w.composer
    comp.add_current()                                            # (a) fixture
    ts._series[:] = [["fx2:NO2", "L", None, None]]; ts._refresh_list()
    comp.add_current()                                            # (b) fx2
    fig = w._build_publish_fig()
    if w._publish_warnings:
        return "FAIL", f"재료가 다 있는데 경고: {w._publish_warnings}"
    w.shelf.pop("fx2"); w._refresh_tree(); w._notify_modes()
    fig = w._build_publish_fig()
    texts = [t.get_text() for a in fig.axes for t in a.texts]
    if "missing: fx2" not in texts:
        return "FAIL", f"빈 패널에 missing 표시 없음: {texts}"
    if not any("(b)" in m and "fx2" in m for m in w._publish_warnings):
        return "FAIL", f"Publish 경고에 패널·데이터셋 없음: {w._publish_warnings}"
    return "PASS", "지워진 데이터셋 패널 = 'missing: fx2' 표시 + '(b) missing dataset(s): fx2' 경고"


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
