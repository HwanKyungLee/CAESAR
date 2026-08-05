"""R(t)/I₀(t) 계단 변화 가드 (step-change guard) — 단일 구현.

문제: R(t)·I₀(t)는 knot들을 PCHIP으로 보간한다. 거울 청소·재정렬·급오염 같은
**계단형 변화**가 knot 사이에서 일어나면 PCHIP이 이를 램프(경사)로 뭉개서 그
구간의 α가 계통적으로 틀어진다. 이 모듈은
  1) '계단 후보'를 감지하고 (detect_step_candidates)
  2) 계단 경계에서 PCHIP을 **분절**하는 보간기를 제공하며 (SegmentedPchip)
  3) 운영자가 아는 이벤트(청소/재정렬 시각)를 수동 분절로 강제할 수 있게 한다.

데이터 무결성 헌장: knot을 지우지 않는다 — 보간이 계단을 관통하지 않도록 분절
경계만 바꾼다. 감지 결과는 항상 **보고(경고)** 되고, 어떤 knot도 자동 배제하지
않는다.

감지 설계 (실데이터 근거: docs/step_guard_threshold_2026-07.md, 2026-07-16)
---------------------------------------------------------------------------
계단 점수 score(i) = min( pair_rel(i), persist_rel(i) )
  pair_rel    = 인접 knot 상대 변화 |Δm|/m̄
  persist_rel = 앞뒤 k-knot **중앙값** 레벨 차의 상대값 — 진짜 계단(청소/오염)은
                레벨이 지속 이동하고, 인젝션 불량 스파이크는 다음 knot에서
                복귀하므로 지속 조건에서 탈락한다(콜드 큰 점프의 절반이 비지속).
문턱 threshold = max( REL_FLOOR, ADAPT_FACTOR × p95(pair_rel) )
  REL_FLOOR    = 0.15 — 핫 채널 정상 drift p99.5(0.06~0.08)의 약 2배 위.
  ADAPT_FACTOR × p95 = 채널 자신의 시간당 변동성의 2배 — 콜드처럼 인젝션 노이즈가
                큰 채널에서 '노이즈 수준의 점프'를 계단으로 오인해 과분절하는 것을
                막는다(과분절 = 과가공). 그런 채널은 수동 분절이 주 수단.
"""
import numpy as np

# 문턱 상수 — 산정 근거·실측 분포는 docs/step_guard_threshold_2026-07.md
REL_FLOOR = 0.15        # 절대 바닥: 핫 정상 drift p99.5의 ~2배 (2026 여수 실측)
ADAPT_FACTOR = 2.0      # 채널 자기 변동성(p95 pair_rel) 대비 배수
ADAPT_PCTL = 95.0       # 자기 변동성 백분위
PERSIST_K = 5           # 지속성 판단 창(앞뒤 knot 수)


def resolve_time_axis(idx_values, sec_values):
    """PCHIP 보간축으로 스캔 인덱스 대신 실측 절대시각(초)을 쓸 수 있는지 결정한다.

    배경: I₀(t)/R(t) 보간은 원래 global scan index(카운터) 위에서 이뤄졌다 — 정상
    운영 중엔 스캔 간격이 거의 균일(≈0.97초)해 인덱스가 시간의 좋은 대리(proxy)지만,
    파일 유실·장비 정지로 실제 경과시간과 스캔 카운트가 어긋나는 구간에서는 물리적
    시간축(램프 감쇠·캐비티 상태는 초 단위 시간에 비례)과 인덱스축이 갈라진다.

    sec_values(각 knot의 bytepack 실측 초)가 전부 유한하고 2개 이상이면 그것을 쓰고,
    아니면(HK 파싱 실패 등 드문 경우) 기존 인덱스 축으로 안전하게 폴백한다 — 두 축을
    섞으면 PCHIP이 단조성을 잃으므로 항상 한쪽만 전부 쓴다.

    반환: (x_axis: ndarray, is_real_time: bool)."""
    sec = np.asarray(sec_values, dtype=float)
    idx = np.asarray(idx_values, dtype=float)
    if sec.size >= 2 and sec.size == idx.size and np.isfinite(sec).all():
        return sec, True
    return idx, False


def knot_scalar_metric(omr_d, wave_nm=None, fit_window_nm=None):
    """knot별 (N, npix) omr_d → 스칼라 시계열 m[N].

    m = 신뢰 창(fit_window_nm) 내 omr_d 평균 (∝ 1/Leff — |Δm|/m̄ 는 |ΔLeff|/Leff
    와 동일 스케일). 창이 없으면 전 픽셀 평균. 1-D 입력(스칼라 knot, 예: I₀
    평균강도)은 그대로 반환한다."""
    a = np.asarray(omr_d, dtype=float)
    if a.ndim == 1:
        return a
    if wave_nm is not None and fit_window_nm:
        wv = np.asarray(wave_nm, dtype=float)
        lo, hi = float(fit_window_nm[0]), float(fit_window_nm[1])
        sel = (wv >= lo) & (wv <= hi)
        if sel.sum() >= 4:
            a = a[:, sel]
    return np.nanmean(a, axis=1)


def relative_changes(metric):
    """인접 knot 상대 변화율 pair_rel = |Δm|/m̄ (m̄ = 두 knot 절대값 평균).
    반환 shape (N-1,). 비유한/0-분모는 0으로."""
    m = np.asarray(metric, dtype=float)
    if m.size < 2:
        return np.zeros(0)
    denom = 0.5 * (np.abs(m[1:]) + np.abs(m[:-1]))
    denom = np.where(denom > 0, denom, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = np.abs(np.diff(m)) / denom
    return np.where(np.isfinite(rel), rel, 0.0)


def persistent_changes(metric, k=PERSIST_K):
    """지속 변화율 persist_rel[i] = |median(m[i+1..i+k]) − median(m[i-k+1..i])| / m̄.
    스파이크(다음 knot에서 복귀)는 중앙값에 눌려 작게 나온다."""
    m = np.asarray(metric, dtype=float)
    n = m.size
    if n < 2:
        return np.zeros(0)
    out = np.zeros(n - 1)
    for i in range(n - 1):
        lo = np.nanmedian(m[max(0, i - k + 1):i + 1])
        hi = np.nanmedian(m[i + 1:min(n, i + 1 + k)])
        den = 0.5 * (abs(lo) + abs(hi))
        out[i] = abs(hi - lo) / den if (np.isfinite(den) and den > 0) else 0.0
    return out


def step_threshold(metric):
    """채널 적응 문턱 = max(REL_FLOOR, ADAPT_FACTOR × p95(pair_rel)).
    조용한 채널(핫)은 바닥 0.15가, 노이즈 큰 채널(콜드)은 자기 변동성 항이 지배."""
    rel = relative_changes(metric)
    if rel.size == 0:
        return REL_FLOOR
    return float(max(REL_FLOOR, ADAPT_FACTOR * np.percentile(rel, ADAPT_PCTL)))


def detect_step_candidates(knot_x, metric, rel_threshold=None, k_persist=PERSIST_K):
    """계단 후보 감지. 반환: (candidates, threshold_used)

    candidates: list of dict
      {"i": 왼쪽 knot 인덱스, "x_left","x_right": 두 knot 시각,
       "x_break": 분절 경계(두 knot 중점),
       "pair_rel","persist_rel","score": 변화율(진단용)}
    rel_threshold=None 이면 step_threshold(metric) 자동 산정.
    감지는 보고용 — 자동 배제/삭제 없음. 분절 적용 여부는 호출부가 정한다."""
    x = np.asarray(knot_x, dtype=float)
    m = np.asarray(metric, dtype=float)
    thr = float(rel_threshold) if rel_threshold is not None else step_threshold(m)
    pair = relative_changes(m)
    pers = persistent_changes(m, k=k_persist)
    score = np.minimum(pair, pers)
    out = []
    for i in np.flatnonzero(score > thr):
        out.append({
            "i": int(i),
            "x_left": float(x[i]),
            "x_right": float(x[i + 1]),
            "x_break": float(0.5 * (x[i] + x[i + 1])),
            "pair_rel": float(pair[i]),
            "persist_rel": float(pers[i]),
            "score": float(score[i]),
        })
    return out, thr


def _segment_slices(knot_x, break_x):
    """분절 경계 break_x 로 knot 배열을 세그먼트 인덱스 구간으로 나눈다.
    경계와 정확히 같은 knot 은 오른쪽 세그먼트에 들어간다."""
    x = np.asarray(knot_x, dtype=float)
    bx = sorted(float(b) for b in (break_x or [])
                if np.isfinite(b) and x[0] < b < x[-1])
    if not bx:
        return [(0, len(x))], []
    segs, used, start = [], [], 0
    for b in bx:
        cut = int(np.searchsorted(x, b, side="left"))
        if cut <= start or cut >= len(x):
            continue   # 이 경계로는 knot이 갈리지 않음(중복/범위 밖) → 무시
        segs.append((start, cut))
        used.append(b)
        start = cut
    segs.append((start, len(x)))
    return segs, used


class SegmentedPchip:
    """분절 PCHIP 보간기 — 계단 경계를 관통하지 않는 R(t)/I₀(t) 보간.

    plain PchipInterpolator(extrapolate=False) + '경계 밖 최근접 상수' 정책의
    드롭인 대체. break 가 없으면(세그먼트 1개) 기존 PCHIP과 **동일 출력**(무회귀).

    분절 정책: 각 세그먼트는 자기 knot 들로만 PCHIP을 만든다. 질의 시각이
    세그먼트 경계~인접 knot 사이(=knot 없는 계단 구간)면 그 세그먼트의 최근접
    knot 값을 상수로 쓴다. 세그먼트 knot 이 1개면 상수. 전체 범위 밖도 최근접
    상수(기존 정책과 동일).

    y 는 (N,) 스칼라 또는 (N, npix) 벡터 knot 모두 지원."""

    def __init__(self, knot_x, knot_y, break_x=None):
        from scipy.interpolate import PchipInterpolator
        x = np.asarray(knot_x, dtype=float)
        y = np.asarray(knot_y, dtype=float)
        if x.ndim != 1 or len(x) < 1 or len(x) != len(y):
            raise ValueError("knot_x/knot_y size mismatch or empty")
        self.x = x
        self.y = y
        segs, used = _segment_slices(x, break_x)
        self.break_x = used           # 실제 적용된 분절 경계(오름차순)
        self._segs = []               # (x0, x1, interp|None, y_first, y_last)
        for (a, b) in segs:
            xs, ys = x[a:b], y[a:b]
            itp = PchipInterpolator(xs, ys, extrapolate=False) if len(xs) >= 2 else None
            self._segs.append((xs[0], xs[-1], itp, ys[0], ys[-1]))

    @property
    def n_segments(self):
        return len(self._segs)

    def _seg_for(self, xv):
        """질의 시각이 속한 세그먼트 인덱스 — 분절 경계 기준(경계=오른쪽)."""
        k = int(np.searchsorted(self.break_x, xv, side="right"))
        return min(k, len(self._segs) - 1)

    def __call__(self, xv):
        xv = float(xv)
        if not np.isfinite(xv):
            return None
        x0, x1, itp, y0, y1 = self._segs[self._seg_for(xv)]
        if xv <= x0 or itp is None:
            return np.asarray(y0, dtype=float) if np.ndim(y0) else float(y0)
        if xv >= x1:
            return np.asarray(y1, dtype=float) if np.ndim(y1) else float(y1)
        v = itp(xv)
        return np.asarray(v, dtype=float) if np.ndim(v) else float(v)


def format_step_report(candidates, threshold=None, x_to_str=None, kind="R(t)",
                       segmented=True):
    """계단 후보 목록 → 로그/헤더용 경고 문자열 목록.
    x_to_str: knot 시각(float) → 사람이 읽을 문자열 (없으면 숫자 그대로)."""
    if not candidates:
        return []
    f = x_to_str or (lambda v: f"{v:.0f}")
    thr_s = f" (threshold {threshold * 100:.0f}%)" if threshold is not None else ""
    act = ("interpolation segmented at these boundaries"
           if segmented else "reported only — interpolation unchanged")
    lines = [f"[STEP GUARD] {kind}: {len(candidates)} step candidate(s){thr_s} "
             f"— {act}; no data removed:"]
    for c in candidates:
        lines.append(
            f"  • {f(c['x_left'])} → {f(c['x_right'])}  "
            f"jump {c['pair_rel'] * 100:.1f}%, persists {c['persist_rel'] * 100:.1f}%")
    return lines
