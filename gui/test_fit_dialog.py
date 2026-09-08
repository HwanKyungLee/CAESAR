"""gui/test_fit_dialog.py — Test Fit 다이얼로그: 탭1 자동 파라미터 최적화 + 탭2 1스캔 미리보기.

기존 app_window.py의 _test_fit(1스캔 즉석검산)을 대체하지 않고 탭2로 보존한 채,
core/param_optimizer.py·core/fit_physics.py(둘 다 순수·Qt무관, tools/optimize_params.py로
이미 검증된 헤드리스 최적화 파이프라인)를 12스캔 표본에 돌려 파라미터(poly·shift·squeeze·
step_limit·Link)를 추천하는 탭1을 추가한다. 추천은 표시만 — [Apply]를 사람이 눌러야
실제 ref_props/스핀박스에 반영된다(자동 적용 금지, docs/fit_optimizer_handoff.md §15-E 불변식4).

핵심 주의점(§15-E 불변식1): target의 shift Limit 추천을 그대로 쓰면 0을 안 품는 범위가
나올 수 있어 실제 RUN의 첫 스캔(last_valid_shift=0에서 시작)이 죽는다 — 반드시 Center
모드(실측 중심에 앵커)로 변환한다. core/fitset_builder.py의 build_fitset 조립 로직(247-283행)과
동일한 규칙을 여기서도 그대로 따른다.
"""
from __future__ import annotations

import json
import os
import sys
import traceback

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
    QPushButton, QProgressBar, QComboBox, QMessageBox, QTextEdit, QFileDialog,
)

from core.doas_fit import DoasFitter
import core.param_optimizer as PO
import core.fit_physics as FP
from core.fitset_builder import validate_fitset
from core.param_optimizer import AC1_DEGENERATE_THRESHOLD as _AC1_DEGENERATE_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────
# alpha 파일 읽기 (px_start 인지) — tools/residual_compare.py::load_alpha 확장.
# _test_fit이 이미 하던 것과 동일하게 pxNNN 헤더에서 시작 픽셀을 뽑는다.
# load_alpha는 이걸 안 하므로(파일이 항상 px0부터 시작한다고 가정) 재사용하지 않고
# 여기서 다시 구현한다 — "Gen px" 좁은 범위로 생성된 알파에서 조용히 틀린 창을
# 최적화하는 사고를 막기 위함(자세한 근거는 계획 문서 Context 참조).
# ─────────────────────────────────────────────────────────────────────────
def _load_alpha_rows(fp: str, max_rows: int = 1):
    """알파 파일에서 (wave, px_start, rows) 반환. rows = [(alpha, T_C, P_mbar), ...] 최대 max_rows개
    (헤더 직후 첫 데이터행부터 연속으로). 파싱 실패 시 (None, 0, [])."""
    wave = None
    alpha_start = None
    px_start = 0
    idx = {}
    rows = []
    try:
        with open(fp, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("# wavelength_nm"):
                    wave = np.array([float(x) for x in line.split(":", 1)[1].split()])
                    continue
                if line.startswith("#"):
                    continue
                cols = line.rstrip("\n").split("\t")
                if not cols:
                    continue
                if alpha_start is None:
                    if cols[0] == "row_idx":
                        idx = {c: i for i, c in enumerate(cols)}
                        alpha_start = next((i for i, c in enumerate(cols) if c.startswith("px")), None)
                        if alpha_start is None:
                            return None, 0, []
                        try:
                            px_start = int(cols[alpha_start][2:])
                        except ValueError:
                            px_start = 0
                    continue
                if wave is None:
                    continue
                n = len(wave)
                if len(cols) < alpha_start + n:
                    continue
                try:
                    alpha = np.array([float(v) for v in cols[alpha_start:alpha_start + n]], dtype=float)
                    iT, iP = idx.get("T_C"), idx.get("P_mbar")
                    T_C = float(cols[iT]) if iT is not None and iT < len(cols) else 25.0
                    P_mbar = float(cols[iP]) if iP is not None and iP < len(cols) else 1013.0
                except ValueError:
                    continue
                rows.append((alpha, T_C, P_mbar))
                if len(rows) >= max_rows:
                    break
    except OSError:
        return None, 0, []
    if wave is None or not rows:
        return None, 0, []
    return wave, px_start, rows


def _resolve_px_bounds(unit: str, lo, hi, wave: np.ndarray, px_start: int) -> tuple[int, int]:
    """(unit, lo, hi)(app_window._current_fit_px_window 원시값) → (px_min, px_max) 배열 인덱스
    (fit_scan의 slice(px_min, px_max+1) 관례에 맞춘 포함구간). unit='px'면 lo/hi가 검출기
    픽셀 번호라 px_start를 빼야 하고, unit='nm'이면 이 파일의 wave 축에서 직접 argmin해
    이미 배열 인덱스이므로 추가 보정이 없다(_test_fit과 동일한 두 갈래 처리)."""
    if unit == "px":
        pmin = max(0, int(lo) - px_start)
        pmax = min(len(wave) - 1, int(hi) - px_start)
    else:
        i0 = int(np.abs(wave - float(lo)).argmin())
        i1 = int(np.abs(wave - float(hi)).argmin())
        pmin, pmax = min(i0, i1), max(i0, i1)
    return pmin, pmax


def _alpha_px_to_engine_px(wave_alpha: np.ndarray, px_min: int, px_max: int, eng) -> tuple[int, int]:
    """`_resolve_px_bounds`가 반환하는 px_min/px_max는 **그 알파 파일 자신의** wave/alpha
    배열 인덱스다(파일마다 px_start 오프셋이 다를 수 있음). 반면
    `fit_physics.differential_collinearity`는 `eng.raw_references[name][px_min:px_max+1]`로
    **엔진 자체의 wave axis**(`eng._wave_axis`) 인덱스를 기대한다 — 둘은 다른 좌표계라
    그대로 넘기면 조용히 엉뚱한 파장 구간을 비교하게 된다. 파장(nm)을 거쳐 변환한다
    (window_designer.scan_windows의 nm2px와 동일 패턴)."""
    wl_lo, wl_hi = float(wave_alpha[px_min]), float(wave_alpha[px_max])
    wax = np.asarray(eng._wave_axis, float).flatten()
    return int(np.argmin(np.abs(wax - wl_lo))), int(np.argmin(np.abs(wax - wl_hi)))


def _assemble_ref_props(ref_props_live: dict, gas_list, target: str, sh: dict, sq: dict, links: list):
    """core/fitset_builder.py build_fitset의 ref_props 조립(247-283행)과 동일 규칙 복제.
    target: shift Limit→Center(실측 중심 앵커, §15-E 불변식1) / 아니면 Fix. squeeze도 동일 정책.
    secondary: Independent→Limit(그 결정의 lb/ub 그대로)+squeeze Link, 아니면 shift/squeeze 둘 다 Link.
    t_ref/t_coeff/active_bands_nm은 기존값 보존(§15-D "사용자 몫" — 자동화 대상 아님)."""
    out = {}
    for g in gas_list:
        old = ref_props_live.get(g, {})
        if g == target:
            if sh.get("policy") == "Limit":
                lo, hi = float(sh["lb"]), float(sh["ub"])
                c_val = float(sh.get("median", 0.0))
                half = max(abs(hi - c_val), abs(c_val - lo))
                sh_mode, sh_val = "Center", f"{round(c_val, 2)}, {round(half, 2)}"
            else:
                sh_mode, sh_val = "Fix", str(sh.get("value", 0.0))
            if sq.get("policy") == "Limit":
                sq_mode, sq_val = "Limit", f"{sq['lo']}, {sq['hi']}"
            else:
                sq_mode, sq_val = "Fix", str(sq.get("value", 1.0))
        else:
            d = next((l for l in links if l.get("secondary") == g), None)
            if d and d.get("decision") == "Independent":
                sh_mode, sh_val = "Limit", f"{d['lb']}, {d['ub']}"
                sq_mode, sq_val = "Link", target
            else:
                sh_mode, sh_val, sq_mode, sq_val = "Link", target, "Link", target
        out[g] = {
            "sh_mode": sh_mode, "sh_val": sh_val,
            "sq_mode": sq_mode, "sq_val": sq_val,
            "t_ref": old.get("t_ref", 25.0),
            "t_coeff": old.get("t_coeff", 0.0),
            "active_bands_nm": old.get("active_bands_nm", ""),
        }
    return out


def _rp_with_recommended_shift(ref_props: dict, target: str, sh: dict) -> dict:
    """squeeze/step_limit/link 단계가 shift 추천 **이전의 stale 값**(예: 경계에 잘린 Fix)이
    아니라 방금 나온 추천값을 기준으로 평가되도록 target의 shift만 갈아끼운다. 최종 출력용
    Center 변환(_assemble_ref_props)과 달리 이건 파이프라인 내부 평가용이라 Limit/Fix 그대로 둔다."""
    out = {g: dict(p) for g, p in ref_props.items()}
    old = out.get(target, {})
    if sh.get("policy") == "Limit":
        out[target] = dict(old, sh_mode="Limit", sh_val=f"{sh['lb']}, {sh['ub']}")
    elif sh.get("policy") == "Fix":
        out[target] = dict(old, sh_mode="Fix", sh_val=str(sh.get("value", 0.0)))
    # policy == "Link"(측정불가)면 원래 설정 유지
    return out


class _TestFitOptimizerWorker(QThread):
    """12스캔 표본 위에서 param_optimizer/fit_physics 파이프라인을 실행(무거운 부분,
    수십 초) — 메인 스레드를 막지 않는다. 위젯을 직접 만지지 않고 순수 데이터만 받는다."""

    progress = pyqtSignal(int, int, str)   # (done, total=9, stage label)
    finished = pyqtSignal(object)          # 성공: result dict / 실패: {"error","traceback"}

    def __init__(self, files: list[str], eng, ref_props: dict,
                 px_unit: str, px_lo, px_hi,
                 poly0: int, step_limit: float, target: str,
                 allow_negative_gas: bool):
        super().__init__()
        self.files = files
        self.eng = eng
        self.ref_props = ref_props
        self.px_unit, self.px_lo, self.px_hi = px_unit, px_lo, px_hi
        self.poly0 = poly0
        self.step_limit = step_limit
        self.target = target
        if not isinstance(allow_negative_gas, bool):
            raise TypeError("Test Fit requires boolean allow_negative_gas")
        self.allow_negative_gas = allow_negative_gas

    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            self.finished.emit({"error": str(e), "traceback": traceback.format_exc()})

    def _run_inner(self):
        TOTAL = 9
        self.progress.emit(0, TOTAL, "표본 스캔 로딩…")

        # ── 24개 균등표본(파일당 첫 행) + 최대 40개 연속표본(첫 파일들에서 연속 행) ──
        n_files = len(self.files)
        n_sample = min(24, n_files)
        idxs = sorted(set(int(round(k * (n_files - 1) / max(n_sample - 1, 1)))
                          for k in range(n_sample))) if n_files else []
        scans = []
        px_start = 0
        wave_ref = None
        for i in idxs:
            wave, ps, rows = _load_alpha_rows(self.files[i], max_rows=1)
            if wave is None:
                continue
            if wave_ref is None:
                wave_ref, px_start = wave, ps
            alpha, T_C, P_mbar = rows[0]
            scans.append((wave, alpha, T_C, P_mbar))
        if not scans:
            self.finished.emit({"error": "표본 스캔을 하나도 읽지 못했습니다(알파 파일 형식 확인)."})
            return

        consec = []
        for fp in self.files:
            if len(consec) >= 40:
                break
            wave, ps, rows = _load_alpha_rows(fp, max_rows=40 - len(consec))
            if wave is None:
                continue
            for alpha, T_C, P_mbar in rows:
                consec.append((wave, alpha, T_C, P_mbar))

        px_min, px_max = _resolve_px_bounds(self.px_unit, self.px_lo, self.px_hi, wave_ref, px_start)
        if px_max - px_min < 10:
            self.finished.emit({"error": f"핏창이 너무 좁습니다(px {px_min}-{px_max}) — "
                                         "현재 채널의 fit range 설정을 확인하세요."})
            return

        eng, rp, target = self.eng, self.ref_props, self.target
        fitter = DoasFitter(eng)
        step_limit = float(self.step_limit)
        poly0 = int(self.poly0)
        # differential_collinearity(T2 게이트)는 엔진 wave-axis 도메인을 기대한다 — px_min/px_max는
        # 이 알파 파일 로컬 도메인이라 별도로 변환해서 넘긴다(_alpha_px_to_engine_px 참조).
        eng_px_min, eng_px_max = _alpha_px_to_engine_px(wave_ref, px_min, px_max, eng)

        self.progress.emit(1, TOTAL, "기준선 평가…")
        base = PO.evaluate(scans, eng, fitter, rp, px_min, px_max, poly0, step_limit,
                           target, allow_negative_gas=self.allow_negative_gas)

        self.progress.emit(2, TOTAL, "다항식 차수 탐색… (차수마다 shift 재탐색, 가장 오래 걸리는 단계)")
        POLYS = [2, 3, 4, 5, 6, 8]
        rec_poly, ladder = PO.optimize_poly_joint(scans, eng, fitter, rp, px_min, px_max,
                                                  POLYS, step_limit, target,
                                                  eng_px_min=eng_px_min, eng_px_max=eng_px_max,
                                                  allow_negative_gas=self.allow_negative_gas)
        poly_for_rest = rec_poly if rec_poly is not None else poly0

        self.progress.emit(3, TOTAL, "Shift 범위 추천…")
        sh = PO.recommend_shift(scans, eng, fitter, rp, px_min, px_max, poly_for_rest,
                                target, allow_negative_gas=self.allow_negative_gas)
        # squeeze/step_limit/link/health는 shift 추천 **이전**의 stale 값(예: 경계에 잘린
        # Fix -0.5)이 아니라 방금 나온 추천을 기준으로 평가해야 한다 — 안 그러면 이 단계들이
        # 전부 틀렸을지 모르는 shift 위에서 평가되어 자기 결과도 같이 오염된다.
        rp_after_shift = _rp_with_recommended_shift(rp, target, sh)

        self.progress.emit(4, TOTAL, "Squeeze 범위 추천…")
        sq = PO.recommend_squeeze(scans, eng, fitter, rp_after_shift, px_min, px_max, poly_for_rest,
                                  target, step_limit=step_limit,
                                  allow_negative_gas=self.allow_negative_gas)

        self.progress.emit(5, TOTAL, "step_limit 추천…")
        if consec:
            st = PO.recommend_step_limit(consec, eng, fitter, rp_after_shift, px_min, px_max,
                                         poly_for_rest, target,
                                         allow_negative_gas=self.allow_negative_gas)
        else:
            st = dict(value=None, reason="연속 스캔 표본 부족(파일이 1개뿐이거나 행이 없음)")

        self.progress.emit(6, TOTAL, "보조 레퍼런스 Link/Independent 판정…")
        links = []
        for g in eng.gas_list:
            if g == target:
                continue
            links.append(PO.recommend_secondary_link(
                scans, eng, fitter, rp_after_shift, px_min, px_max, poly_for_rest,
                secondary=g, allow_negative_gas=self.allow_negative_gas,
                target=target, step_limit=step_limit,
                eng_px_min=eng_px_min, eng_px_max=eng_px_max))

        self.progress.emit(7, TOTAL, "물리 건전성 점검(상수종)…")
        try:
            health = FP.fitted_amount_health(scans, eng, fitter, rp_after_shift, px_min, px_max,
                                             poly_for_rest, step_limit, target=target,
                                             allow_negative_gas=self.allow_negative_gas)
        except Exception as e:
            health = {"error": str(e)}
        has_theoretical_anchor = FP.theoretical_amount(target, scans[0][2], scans[0][3]) is not None

        self.progress.emit(8, TOTAL, "조립 및 검증…")
        proposed_ref_props = _assemble_ref_props(rp, eng.gas_list, target, sh, sq, links)
        proposed_step_limit = float(st["value"]) if st.get("value") else None
        cfg_check = {
            "f_min": px_min, "f_max": px_max,
            "step_limit": proposed_step_limit if proposed_step_limit is not None else step_limit,
            "ref_props": proposed_ref_props,
        }
        validate_problems = validate_fitset(cfg_check, target)

        self.progress.emit(TOTAL, TOTAL, "완료")
        self.finished.emit({
            "base": base, "poly": {"rec": rec_poly, "ladder": ladder},
            "shift": sh, "squeeze": sq, "step_limit": st, "secondary": links,
            "health": health,
            "has_theoretical_anchor": has_theoretical_anchor,
            "proposed_ref_props": proposed_ref_props,
            "proposed_poly_deg": poly_for_rest,
            "proposed_step_limit": proposed_step_limit,
            "validate_problems": validate_problems,
            "n_scans_used": len(scans), "n_scans_total": n_files,
            "n_consec_used": len(consec),
            "target": target,
        })


def _format_explorer_review(review: dict) -> str:
    """Render the small, public human-review contract without changing a FitSet."""
    if not isinstance(review, dict) or review.get("schema") != "fit-explorer-human-review-v1":
        raise ValueError("not a fit-explorer-human-review-v1 report")
    verdict = review.get("verdict")
    if verdict not in {"RECOMMENDABLE_INTERNAL", "MISSION_LOCAL_ONLY",
                       "NON_IDENTIFIABLE_OR_ABSTAIN"}:
        raise ValueError("unknown Explorer verdict")
    if review.get("apply") != "FORBIDDEN_REQUIRES_EXPLICIT_HUMAN_ACTION":
        raise ValueError("Explorer report must explicitly forbid automatic Apply")

    def _summary(label: str, value: dict | None) -> str:
        if value is None:
            return f"<b>{label}:</b> 없음"
        needed = ("candidate_id", "attempts", "boundary_attempts", "median_ppb", "seed_max_delta_ppb")
        if not isinstance(value, dict) or any(key not in value for key in needed):
            raise ValueError(f"{label} summary is incomplete")
        return (f"<b>{label}:</b> 후보 {value['candidate_id']} · {value['attempts']} attempts · "
                f"median {float(value['median_ppb']):.4g} ppb · boundary "
                f"{value['boundary_attempts']} · seed Δmax "
                f"{float(value['seed_max_delta_ppb']):.3g} ppb")

    reason = str(review.get("reason", "")).replace("&", "&amp;").replace("<", "&lt;")
    return (f"<h3>Explorer verdict: {verdict}</h3>"
            f"<p><b>Reason:</b> {reason}</p>"
            f"<p>{_summary('Stage 2', review.get('stage2'))}<br>"
            f"{_summary('Holdout', review.get('holdout'))}</p>"
            "<p style='color:#C62828; font-weight:bold;'>"
            "이 카드는 증거를 표시할 뿐이며 현재 FitSet·채널 설정을 자동 변경하지 않습니다. "
            "현재 데이터가 이 보고서의 mission/data와 일치하는지는 사용자가 확인해야 합니다.</p>")


class TestFitDialog(QDialog):
    """탭1(⚙️ Optimize, 새로 추가) + 탭2(🧪 Preview, 기존 _show_test_fit_popup 이식).
    비모달(기존 Test Fit 팝업과 동일 — show(), exec() 아님)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._app = parent
        self._worker: _TestFitOptimizerWorker | None = None
        self.setWindowTitle("🧪 Test Fit")
        _s = getattr(parent, "_s", 1.0)
        self.resize(int(920 * _s), int(760 * _s))

        root = QVBoxLayout(self)
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        self._build_optimize_tab()
        self._build_preview_tab()
        self._build_explorer_review_tab()

    # ══════════════════════════════════════════════════════════════
    # 탭1 — 최적화
    # ══════════════════════════════════════════════════════════════
    def _build_optimize_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Target gas:"))
        self._cb_target = QComboBox()
        gas_list = list(self._app.engine.gas_list)
        self._cb_target.addItems(gas_list)
        default = "NO2" if "NO2" in gas_list else (gas_list[0] if gas_list else "")
        if default:
            self._cb_target.setCurrentText(default)
        bar.addWidget(self._cb_target)
        self._btn_run = QPushButton("▶ Run Optimizer (24-scan sample, joint poly×shift search)")
        self._btn_run.setStyleSheet("font-weight: bold; padding: 6px; border: 1px solid #A5D6A7;")
        self._btn_run.clicked.connect(self._run_optimizer)
        bar.addWidget(self._btn_run)
        bar.addStretch(1)
        lay.addLayout(bar)

        self._progress = QProgressBar()
        self._progress.setRange(0, 9)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color:#1565C0;")
        lay.addWidget(self._lbl_status)

        self._results_html = []
        self._results_edit = QTextEdit()
        self._results_edit.setReadOnly(True)
        self._results_edit.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._results_edit, 1)

        self._btn_apply = QPushButton("✅ Apply Recommendations")
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._on_apply)
        lay.addWidget(self._btn_apply)

        self._last_result = None
        self._tabs.addTab(page, "⚙️ Optimize")

    def _clear_results(self):
        self._results_html = []
        self._results_edit.clear()

    def _add_result_label(self, html: str, warn: bool = False, err: bool = False):
        if err:
            color = "#C62828; font-weight:bold"
        elif warn:
            color = "#E65100; font-weight:bold"
        else:
            color = "#333"
        self._results_html.append(f"<div style='color:{color}; margin-bottom:8px;'>{html}</div>")
        self._results_edit.setHtml("".join(self._results_html))

    def _poly_ladder_table(self, ladder: list[dict], rec_poly, target: str) -> str:
        """poly 후보 비교표. §16-B(퇴화 분기는 잔차가 5배 나쁘다)에 따라 |ac1|가 최선 대비
        2배 이상이면 ⚠로 표시 — 사용자가 알고리즘을 맹신하지 않고 직접 눈으로 걸러낼 수 있게."""
        if not ladder:
            return "<b>poly ladder:</b> (no candidates evaluated)"
        best_ac1 = min(abs(r["autocorr1"]) for r in ladder if np.isfinite(r.get("autocorr1", np.nan)))
        rows = ["<tr><th align=left>poly</th><th align=left>n_ok</th>"
                f"<th align=left>{target}</th><th align=left>conc CV</th>"
                "<th align=left>RMS/sig</th><th align=left>|ac1|</th>"
                "<th align=left>multi-R</th>"
                f"<th align=left>{target} shift</th></tr>"]
        for r in ladder:
            ac1 = abs(r.get("autocorr1", float("nan")))
            degenerate = np.isfinite(ac1) and np.isfinite(best_ac1) and ac1 > 2 * best_ac1 and ac1 > 0.15
            multi_r = r.get("multi_R_target", float("nan"))
            sh_med, sh_sig = r.get("shift_dist", {}).get(target, (float("nan"), float("nan")))
            # |ac1| 퇴화(§16-B, NLLS 탐색이 alias 골짜기에 빠짐)와 multi-R 공선성(T2, 핏 없이도
            # 계산되는 기하학적 퇴화)은 서로 다른 원인이라 마크를 분리한다 — 둘 다 나쁘면 구조적
            # 문제, |ac1|만 나쁘면 탐색 문제일 가능성이 높다는 진단 힌트가 된다.
            collinear = np.isfinite(multi_r) and multi_r > PO.POLY_COLLIN_R_MAX
            marks = ("⚠퇴화?" if degenerate else "") + ("⚠공선성?" if collinear else "")
            mark = f" {marks}" if marks else (" ✅" if r["poly"] == rec_poly else "")
            style = "color:#E65100;font-weight:bold" if (degenerate or collinear) else (
                "font-weight:bold" if r["poly"] == rec_poly else "")
            rows.append(
                f"<tr style='{style}'><td>{r['poly']}{mark}</td><td>{r['n_ok']}</td>"
                f"<td>{r['conc']:.3g}</td><td>{r['conc_cv']*100:.0f}%</td>"
                f"<td>{r['rms_sig']:.3g}</td><td>{ac1:.2f}</td>"
                f"<td>{multi_r:.2f}</td>"
                f"<td>{sh_med:+.2f}±{sh_sig:.2f}px</td></tr>")
        return "<table cellpadding=3 style='border-collapse:collapse'>" + "".join(rows) + "</table>"

    def _run_optimizer(self):
        files = self._app._channel_files.get(self._app._active_channel) or self._app.file_list
        if not files:
            QMessageBox.warning(self, "Test Fit", "Load data first.")
            return
        paths = [self._app._entry_filepath(f) for f in files]
        n_files = len(paths)
        if n_files < 3:
            self._lbl_status.setText(
                f"⚠ only {n_files} file(s) available — recommendations may be unstable.")
        unit, lo, hi = self._app._current_fit_px_window()
        self._clear_results()
        self._btn_apply.setEnabled(False)
        self._btn_apply.setText("✅ Apply Recommendations")
        self._btn_run.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)

        self._worker = _TestFitOptimizerWorker(
            paths, self._app.engine, dict(self._app.ref_props),
            unit, lo, hi,
            self._app.spin_poly_deg.value(), self._app.spin_step_limit.value(),
            self._cb_target.currentText(), self._app.chk_allow_neg.isChecked())
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, done, total, label):
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._lbl_status.setText(label)

    def _on_finished(self, result):
        self._btn_run.setEnabled(True)
        self._progress.setVisible(False)
        self._last_result = result
        self._clear_results()

        if "error" in result:
            self._lbl_status.setText("❌ Failed")
            self._add_result_label(f"<b>Optimizer failed:</b> {result['error']}", err=True)
            return

        self._lbl_status.setText(
            f"✅ Done — {result['n_scans_used']}/{result['n_scans_total']} scans used "
            f"({result['n_consec_used']} consecutive for step_limit)")

        target = result["target"]
        base = result["base"]
        if base.get("n_ok", 0) == 0:
            self._add_result_label(
                f"<b>All sample scans failed to fit</b> (n_fail={base.get('n_fail')}) — "
                "check engine/window/references.", err=True)
            return
        self._add_result_label(
            f"<b>Baseline</b> (poly={self._app.spin_poly_deg.value()}): "
            f"{target}={base.get('conc', float('nan')):.3g} ppb, "
            f"RMS/sig={base.get('rms_sig', float('nan')):.3g}, "
            f"|ac1|={abs(base.get('autocorr1', float('nan'))):.2f}")

        poly = result["poly"]
        self._add_result_label(
            f"<b>Poly degree:</b> current {self._app.spin_poly_deg.value()} → "
            f"recommended <b>{poly['rec']}</b> (knee of the ladder — higher degree "
            "doesn't reduce residual structure enough to justify the extra freedom)<br>"
            "<i>each degree below was scored with its own freely-refit shift "
            "(not the current possibly-clipped setting), so degrees aren't penalized "
            "for a stale shift value</i>")
        self._add_result_label(self._poly_ladder_table(poly["ladder"], poly["rec"], target))

        # §16-B: 진짜 해는 |ac1| ~0.03-0.08, 퇴화 분기(통계적으로만 좋아 보이는 가짜 해)는
        # ~1.0. 모든 poly 후보가 그 문턱을 넘으면 이 표본에선 shift 탐색이 통째로 퇴화 분기에
        # 빠진 것 — 어느 poly를 골라도 결과가 신뢰 불가라는 뜻이므로 절대 문턱으로 잡아야 한다
        # (poly끼리 상대비교만으론 전부 나쁠 때 아무것도 걸러내지 못함).
        ladder_ac1 = [abs(r["autocorr1"]) for r in poly["ladder"] if np.isfinite(r.get("autocorr1", np.nan))]
        best_ac1 = min(ladder_ac1) if ladder_ac1 else float("nan")
        degenerate_all = np.isfinite(best_ac1) and best_ac1 > _AC1_DEGENERATE_THRESHOLD
        if degenerate_all:
            self._add_result_label(
                "<b>⚠ 모든 poly 후보의 잔차가 백색이 아닙니다</b> (최선도 |ac1|="
                f"{best_ac1:.2f}, 진짜 핏은 보통 0.03~0.08) — §16-B에서 확인된 "
                "<b>퇴화 분기</b>(통계적으로만 좋아 보이는 가짜 해, 실제 O4 오염 사례에서도 "
                "동일 패턴)와 일치합니다. 이 표본에서 나온 농도·shift 추천은 <b>신뢰하지 말 것</b> "
                "— shift 탐색 범위를 좁히거나(현재 설정된 물리적으로 타당한 범위 근처로), 핏창/레퍼런스를 "
                "재검토한 뒤 다시 시도하세요.", err=True)

        sh = result["shift"]
        cur_sh = self._app.ref_props.get(target, {})
        self._add_result_label(
            f"<b>{target} shift:</b> current {cur_sh.get('sh_mode','?')} "
            f"{cur_sh.get('sh_val','')} → recommended {sh.get('policy')} "
            f"{result['proposed_ref_props'][target]['sh_val']}<br>"
            f"<i>{sh.get('reason','')}</i>",
            warn=bool(sh.get("undetermined")), err=bool(sh.get("degenerate")))

        sq = result["squeeze"]
        self._add_result_label(
            f"<b>{target} squeeze:</b> current {cur_sh.get('sq_mode','?')} "
            f"{cur_sh.get('sq_val','')} → recommended {sq.get('policy')} "
            f"{result['proposed_ref_props'][target]['sq_val']}<br>"
            f"<i>{sq.get('reason','')}</i>")

        st = result["step_limit"]
        if st.get("value") is not None:
            self._add_result_label(
                f"<b>step_limit:</b> current {self._app.spin_step_limit.value():.2f} → "
                f"recommended <b>{st['value']:.2f}</b><br><i>{st.get('reason','')}</i>",
                err=bool(st.get("degenerate")))
        else:
            self._add_result_label(
                f"<b>step_limit:</b> keeping current ({self._app.spin_step_limit.value():.2f}) "
                f"— <i>{st.get('reason','')}</i>", err=bool(st.get("degenerate")))

        for d in result["secondary"]:
            g = d["secondary"]
            self._add_result_label(
                f"<b>{g}:</b> {d.get('decision')} vs {target} — <i>{d.get('reason','')}</i>",
                err=bool(d.get("blocked_by_collinearity")))

        health = result.get("health") or {}
        if "error" not in health and health.get("cv"):
            cv_txt = ", ".join(f"{g}={v*100:.0f}%" for g, v in health["cv"].items())
            self._add_result_label(f"<b>Physical health (coefficient CV):</b> {cv_txt}")
        if not result.get("has_theoretical_anchor", True):
            self._add_result_label(
                f"<i>Note: {target}엔 절대량 물리 앵커가 없습니다(O4만 [O2]²로 있음) — 가장 강한 "
                "T2 게이트(절대량 기각)는 여기서 작동하지 않고, 공선성·CV 게이트만 적용됩니다.</i>")

        # poly 사다리 전체 판정(degenerate_all)뿐 아니라, 그 이후 shift/step_limit 각자의
        # 자체 판정(§16-B 문턱)도 있다 — poly는 통과했지만 shift 추천 자체가 퇴화 분기에
        # 빠지는 경우(예: poly 사다리와 다른 시딩 경로)까지 잡으려면 OR로 합쳐야 한다.
        any_degenerate = degenerate_all or bool(sh.get("degenerate")) or bool(st.get("degenerate"))
        problems = result["validate_problems"]
        if problems:
            self._add_result_label(
                "<b>⚠ Cannot Apply — would break the fit engine:</b><br>" +
                "<br>".join(f"• {p}" for p in problems), err=True)
            self._btn_apply.setEnabled(False)
            self._btn_apply.setToolTip("Fix the problems above (usually: widen step_limit or "
                                       "the window) before applying.")
        elif any_degenerate:
            self._btn_apply.setEnabled(False)
            self._btn_apply.setToolTip("잔차가 백색이 아님(|ac1| 높음) — 퇴화 분기로 의심되어 "
                                       "Apply 비활성화. 위 경고 참조.")
        else:
            self._btn_apply.setEnabled(True)
            self._btn_apply.setToolTip("")

    def _on_apply(self):
        if not self._last_result or "error" in self._last_result:
            return
        self._app._apply_test_fit_recommendations(self._last_result)
        self._btn_apply.setText("Applied ✓")
        self._btn_apply.setEnabled(False)

    # ══════════════════════════════════════════════════════════════
    # 탭3 — Fit Explorer의 사람 검토 카드 (읽기 전용, Apply 없음)
    # ══════════════════════════════════════════════════════════════
    def _build_explorer_review_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        note = QLabel(
            "Fit Explorer가 실제 피팅으로 만든 Stage 2/holdout 증거를 읽기 전용으로 표시합니다. "
            "이 탭은 추천 파라미터를 자동 적용하지 않으며, 보고서의 mission·채널·입력이 현재 설정과 "
            "같은지는 사람이 확인해야 합니다.")
        note.setWordWrap(True)
        lay.addWidget(note)
        bar = QHBoxLayout()
        btn = QPushButton("Load Explorer Review JSON…")
        btn.clicked.connect(self._load_explorer_review)
        bar.addWidget(btn)
        bar.addStretch(1)
        lay.addLayout(bar)
        self._explorer_review_edit = QTextEdit()
        self._explorer_review_edit.setReadOnly(True)
        self._explorer_review_edit.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._explorer_review_edit.setHtml(
            "<i>Review JSON을 불러오면 여기 표시됩니다. "
            "tools/fit_explorer_review.py --output REPORT.json 으로 만들 수 있습니다.</i>")
        lay.addWidget(self._explorer_review_edit, 1)
        self._tabs.addTab(page, "🧭 Explorer Review")

    def _load_explorer_review(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Fit Explorer review", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                review = json.load(fh)
            self._explorer_review_edit.setHtml(_format_explorer_review(review))
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Explorer Review", f"Cannot load review: {exc}")

    # ══════════════════════════════════════════════════════════════
    # 탭2 — 1스캔 미리보기 (기존 _show_test_fit_popup 이식, 로직 불변)
    # ══════════════════════════════════════════════════════════════
    def _build_preview_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        try:
            preview = self._app._compute_1scan_preview()
        except Exception as e:
            lay.addWidget(QLabel(f"Preview failed: {e}"))
            self._tabs.addTab(page, "🧪 Preview (1 scan)")
            return
        if preview is None:
            lay.addWidget(QLabel("Preview unavailable."))
            self._tabs.addTab(page, "🧪 Preview (1 scan)")
            return

        (fp, wl, data, model, resid, gas_models, ppb, shifts, squeezes,
         rms, T_C, P_mbar, collin) = preview

        gtxt = "  ".join(f"{g}={ppb[g]:.2f}" for g in ppb)
        _hdr = QLabel(
            f"<b>{os.path.basename(fp)}</b><br>"
            f"<b>ppb:</b> {gtxt}    <b>RMS:</b> {rms:.2e}    "
            f"<b>Shift:</b> {shifts[0]:+.2f}px  <b>Squeeze:</b> {squeezes[0]:.4f}    "
            f"T={T_C:.1f}°C P={P_mbar:.0f}mb")
        _hdr.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(_hdr)

        if collin is not None:
            from core.doas_fit import DoasFitter as _DF
            _cl = QLabel(_DF.format_etalon_collinearity(collin))
            _cl.setStyleSheet("color:#E65100;font-weight:bold;" if collin.get("warn") else "color:#555;")
            _cl.setWordWrap(True)
            _cl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(_cl)

        _pal = ["#388E3C", "#7B1FA2", "#0097A7", "#C2185B", "#5D4037"]
        gms = [(gi, nm, gas_models[gi]) for gi, nm in enumerate(self._app.engine.gas_list)
               if gas_models and gi < len(gas_models) and gas_models[gi] is not None
               and len(gas_models[gi]) == len(wl)]
        sum_gas = np.sum([g for _, _, g in gms], axis=0) if gms else np.zeros_like(wl)
        diff_data = resid + sum_gas

        pw1 = pg.PlotWidget(); pw1.setBackground('w'); pw1.showGrid(x=True, y=True, alpha=0.3)
        pw1.addLegend(offset=(10, 6))
        pw1.plot(wl, diff_data, pen=pg.mkPen('#1976D2', width=2), name='measured (baseline removed)')
        pw1.plot(wl, sum_gas, pen=pg.mkPen('#D32F2F', width=1.5), name='fitted gases (Σ)')
        pw1.setLabel('left', 'Diff α (cm⁻¹)')
        pw1.setTitle('Measured vs fitted gases')
        lay.addWidget(pw1, 2)

        pw2 = pg.PlotWidget(); pw2.setBackground('w'); pw2.showGrid(x=True, y=True, alpha=0.3)
        pw2.addLegend(offset=(10, 6))
        for gi, nm, gm in gms:
            pw2.plot(wl, gm, pen=pg.mkPen(_pal[gi % len(_pal)], width=1.5),
                     name=f'{nm}  ({ppb.get(nm, float("nan")):.2f} ppb)')
        pw2.setLabel('left', 'Diff α (cm⁻¹)')
        pw2.setTitle('Reference contributions (per gas)')
        lay.addWidget(pw2, 2)

        pw3 = pg.PlotWidget(); pw3.setBackground('w'); pw3.showGrid(x=True, y=True, alpha=0.3)
        pw3.plot(wl, resid, pen=pg.mkPen('#455A64', width=1))
        pw3.setLabel('left', 'Residual'); pw3.setLabel('bottom', 'Wavelength (nm)')
        pw3.setTitle(f"Residual (RMS={rms:.2e})")
        lay.addWidget(pw3, 1)

        self._tabs.addTab(page, "🧪 Preview (1 scan)")

    # ══════════════════════════════════════════════════════════════
    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()
            if not self._worker.wait(3000):
                self._worker.terminate()
                self._worker.wait()
        super().closeEvent(event)
