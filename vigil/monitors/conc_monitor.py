"""vigil/monitors/conc_monitor.py — 기체 농도 경량 DOAS 피팅 (설계문서 §1.1, M3).

`core/param_optimizer.fit_scan()`(단일 스캔 핏 → 지표, 이 세션의 옵티마이저 CLI들과
같은 단일 출처)을 그대로 재사용한다. 이 모듈이 얹는 건 딱 세 가지:
  1. **I0 관리** — ZA 윈도우가 완결될 때마다 평균(과 그 블록의 T/P)을 갱신
     (r_monitor.py의 윈도우 완결 감지와 같은 패턴). (1-R)/d 는 같은 채널
     RMonitor.omr_d 를 호출부가 넘겨준다.
  2. **속도 우선 자유도 축소**(§1.1 "shift/squeeze 자유도를 줄이거나 고정") — 첫 핏은
     원본 FitSet ref_props(보통 Limit, 넓은 격자탐색 포함)로 정직하게 돌리고, 그 다음부턴
     타깃 shift를 직전 핏값 중심 Center 모드로 좁힌다. `_seed_shift`는 Limit/Free에서만
     격자탐색을 하므로(param_optimizer.py) Center로 바꾸는 것 자체가 탐색을 건너뛴다 —
     fit_scan을 고치지 않고 설정만으로 속도를 얻는다.
  3. **경보 판정** — 물리불가 범위·스파이크·평탄선(센서고착)·핏 신뢰도(rms/sig)·연속
     실패를 P0/P1/P2로. 정확값이 필요한 게 아니라 "추세·자릿수를 믿을 수 있나"만 본다
     (§0-A.4) — 진짜 검증은 Augur 확정 분석과 사후 대조(state_log가 그 근거를 남긴다).

레퍼런스·핏창·poly·ref_props는 여기서 새로 정의하지 않고 Augur FitSet json을 그대로
읽는다(ConcentrationConfig.fitset_path) — 사용자가 Augur에서 이미 검증한 세팅과
갈라지지 않는다.

Alpha is the BBCEAS extinction alpha [cm^-1], not the optical density (fixed 2026-10-02,
first written 2026-09-23 but never committed). The old `alpha = -log(I/I0)` fed OD ~ alpha*L_eff
to fit_scan, which assumes cm^-1, so every concentration came out L_eff (~1e6 cm) too high and
the monitor sat in P1 permanently (diagnostics/ux_audit_2026-10-02/vigil_v2_monitors.md §1).
Now alpha comes from core.physics.bbceas_alpha (the same function as Augur's alpha generation)
with (1-R)/d from RMonitor.omr_d. Without R there is no concentration (SKIP) -- never an OD
fallback.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Optional
import warnings

import numpy as np

from core.doas_fit import DoasFitter
from core.physics import RayleighPhysics, bbceas_alpha
from core import param_optimizer as PO
from vigil.alert_engine import OK, P0, P1, P2, SKIP, worse
from vigil.monitors.running_mean import RunningMean
from tools import optimize_params as OP

FAIL_STREAK_FOR_P0 = 3   # 연속 이 이상 핏 실패하면 P0로 격상(r_monitor.py와 같은 관례)
HISTORY_WINDOW = 20       # 스파이크/평탄선 판단용 최근 농도 이력 길이


def pick_fitset_channel(scen: dict, wl_dir: str) -> dict:
    """FitSet json에서 wl_path에 wl_dir(roi1/roi2/cold 등)를 쓰는 채널을 찾는다.
    data_label은 안 본다 — FitSet json에서 라벨이 실제 채널과 뒤바뀐 사례가 있다
    (fit_optimizer_handoff.md §14-D, tools/optimize_params.pick_channel과 같은 이유)."""
    for ch in scen["channels"].values():
        if wl_dir in str(ch.get("wl_path", "")).replace("\\", "/").split("/"):
            return ch
    raise ValueError(f"FitSet has no channel with wl_path '{wl_dir}'")


class ConcMonitor:
    """채널 하나의 경량 농도 감시 상태 컨테이너.

        fit_ch = pick_fitset_channel(scen, cfg.wl_dir)
        cm = ConcMonitor(fit_ch, cfg)
        result = cm.observe(role, spectrum, temp_c, press_mbar, omr_d=rm.omr_d, rl=rl)  # 매 행 호출
        if result is not None:
            status, msg, metrics = result   # 이번 행에서 새 핏이 돌았음(throttle 통과 + I0 있음)
    """

    def __init__(self, fit_ch: dict, cfg):
        self.cfg = cfg
        self.eng = OP.build_engine_from_config(fit_ch)
        self.fitter = DoasFitter(self.eng)
        self.wave = np.asarray(self.eng._wave_axis, dtype=float).flatten()
        # ⚠️ FitSet json은 f_min/f_max(px)와 fit_start_nm/fit_end_nm이 불일치한다 —
        # px 필드가 진짜(§13-A, fit_optimizer_handoff.md). nm 필드는 스테일.
        self.px_min, self.px_max = int(fit_ch["f_min"]), int(fit_ch["f_max"])
        self.poly_deg = int(fit_ch["poly_deg"])
        self.step_limit = float(fit_ch.get("step_limit", 0.5))
        self.ref_props = dict(fit_ch["ref_props"])   # 원본 보존 — narrow 사본은 매 핏마다 새로
        if "allow_negative_gas" in fit_ch:
            fitset_policy = fit_ch["allow_negative_gas"]
            if not isinstance(fitset_policy, bool):
                raise TypeError("FitSet allow_negative_gas must be bool")
            if cfg.allow_negative_gas != fitset_policy:
                raise ValueError("Vigil profile allow_negative_gas disagrees with FitSet")
            self.allow_negative_gas = fitset_policy
            self.gas_policy_provenance = "FitSet"
        else:
            warnings.warn("legacy FitSet has no allow_negative_gas; using explicit Vigil profile policy",
                          RuntimeWarning, stacklevel=2)
            self.allow_negative_gas = cfg.allow_negative_gas
            self.gas_policy_provenance = "legacy FitSet fallback: Vigil profile"

        self._za_buf = RunningMean()   # I0 누적 평균 — 행을 쌓지 않는다(running_mean 참조)
        self._za_t, self._za_p = RunningMean(), RunningMean()   # I0 block T/P (alpha_ZA Rayleigh term)
        self._i0: Optional[np.ndarray] = None
        self._i0_tp: Optional[tuple] = None
        self._last_fit_time: Optional[datetime] = None
        self._last_shift: Optional[float] = None
        self._history: deque = deque(maxlen=HISTORY_WINDOW)
        self._fail_streak = 0

    def _seeded_ref_props(self) -> dict:
        rp = {g: dict(v) for g, v in self.ref_props.items()}
        if self._last_shift is not None and self.cfg.target in rp:
            rp[self.cfg.target]["sh_mode"] = "Center"
            rp[self.cfg.target]["sh_val"] = f"{self._last_shift},{self.cfg.seed_narrow_px}"
        return rp

    def observe(self, role: Optional[str], spectrum, temp_c: float, press_mbar: float,
                omr_d=None, rl: float = 1.0):
        """새 행 한 개 관측. za_inject 구간 동안 I0 버퍼링, sampling 구간이면
        (throttle 통과 + I0 있을 때) 경량 핏을 돌려 (status, msg, metrics)를 반환.
        핏이 안 돌면 None(호출부는 이전 상태를 유지하면 된다).

        omr_d : (1-R)/d [cm^-1] per pixel, normally the same channel's RMonitor.omr_d.
                None (no ZA/He cycle completed yet) -> SKIP, no concentration.
        rl    : purge length ratio; already in omr_d, applied to alpha_ZA only
                (same convention as gui/worker.py)."""
        if role == "za_inject":
            self._za_buf.add(spectrum)
            self._za_t.add(temp_c)
            self._za_p.add(press_mbar)
            return None
        if self._za_buf:   # za 윈도우가 방금 끝남 — I0 갱신
            self._i0 = self._za_buf.mean()
            self._i0_tp = (float(self._za_t.mean()), float(self._za_p.mean()))
            self._za_buf, self._za_t, self._za_p = RunningMean(), RunningMean(), RunningMean()

        if role != "sampling" or self._i0 is None:
            return None
        now = datetime.now()
        if (self._last_fit_time is not None
                and (now - self._last_fit_time).total_seconds() < self.cfg.throttle_sec):
            return None
        self._last_fit_time = now

        if omr_d is None:
            # No R -> no alpha in cm^-1. A wrong number is worse than none (the old OD path
            # was L_eff ~1e6 too high). He cycles are 3 h apart, so this is normal after start-up.
            return SKIP, f"{self.cfg.target} waiting for R (needs one ZA/He calibration)", {}
        omr_d = np.asarray(omr_d, dtype=float)
        if omr_d.shape != self.wave.shape:
            self._fail_streak += 1
            return self._fail_status(
                f"R wavelength axis mismatch (omr_d {omr_d.shape} vs fit axis {self.wave.shape})")
        # RMonitor sets omr_d to NaN outside its ROI (extrapolated R can clip to 1 -> omr_d 0,
        # which would fake 'no absorption'). A fit window outside the ROI is a profile error.
        n_bad_r = int(np.count_nonzero(~np.isfinite(omr_d[self.px_min:self.px_max + 1])))
        if n_bad_r:
            self._fail_streak += 1
            return self._fail_status(
                f"{n_bad_r}/{self.px_max - self.px_min + 1} fit-window px outside the R ROI "
                "(profile reflectance.roi_nm does not cover this channel's fit window)")

        t_za, p_za = self._i0_tp
        alpha_za = RayleighPhysics.get_alpha_rayleigh(self.wave, t_za, p_za, "zero_air")
        alpha_sample = RayleighPhysics.get_alpha_rayleigh(self.wave, temp_c, press_mbar, "zero_air")
        i_meas = np.asarray(spectrum, dtype=float)
        # I <= 0 is unphysical (dead pixel / over-subtraction): NaN, not a clamp, so the
        # finiteness check below drops the scan instead of fitting a fake value.
        bad = (i_meas <= 0) | (self._i0 <= 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            alpha = bbceas_alpha(i_meas, self._i0, omr_d, alpha_za, alpha_sample, rl)
        alpha = np.where(bad, np.nan, alpha)
        window = alpha[self.px_min:self.px_max + 1]
        if not np.all(np.isfinite(window)):
            self._fail_streak += 1
            return self._fail_status("alpha computation failed (zero/negative intensity or T/P missing)")

        try:
            result = PO.fit_scan(self.eng, self.fitter, self._seeded_ref_props(), self.wave,
                                 alpha, temp_c, press_mbar, self.px_min, self.px_max,
                                 self.poly_deg, self.step_limit, self.cfg.target,
                                 allow_negative_gas=self.allow_negative_gas)
        except Exception as e:                # noqa: BLE001
            self._fail_streak += 1
            return self._fail_status(str(e))
        self._fail_streak = 0
        self._last_shift = result["shifts"].get(self.cfg.target)
        return self._classify(result)

    def _classify(self, result: dict):
        conc, rms_sig = result["conc"], result["rms_sig"]
        metrics = {"conc_ppb": conc, "rms_sig": rms_sig, "rms": result["rms"],
                   "perr_rel": result["perr_rel"], "conc_all_ppb": result["conc_all"]}
        if not np.isfinite(conc):
            return P1, f"{self.cfg.target} fit failed (concentration NaN)", metrics

        issues: list = []
        worst = OK
        c = self.cfg
        if c.conc_min_ppb is not None and conc < c.conc_min_ppb:
            issues.append(f"unphysical (too low) {conc:.1f}<{c.conc_min_ppb}ppb")
            worst = worse(worst, P1)
        if c.conc_max_ppb is not None and conc > c.conc_max_ppb:
            issues.append(f"unphysical (too high) {conc:.1f}>{c.conc_max_ppb}ppb")
            worst = worse(worst, P1)
        if c.rms_sig_alarm is not None and rms_sig > c.rms_sig_alarm:
            issues.append(f"low fit confidence rms/sig={rms_sig*100:.1f}%")
            worst = worse(worst, P1)
        if c.rms_alarm is not None and result["rms"] > c.rms_alarm:
            issues.append(f"large fit residual rms={result['rms']:.2e}")
            worst = worse(worst, P1)
        if (c.spike_ppb is not None and self._history
                and np.isfinite(self._history[-1])
                and abs(conc - self._history[-1]) > c.spike_ppb):
            issues.append(f"sudden change Δ{abs(conc - self._history[-1]):.1f}ppb")
            worst = worse(worst, P2)

        self._history.append(conc)
        if c.flatline_n and len(self._history) >= c.flatline_n:
            recent = list(self._history)[-c.flatline_n:]
            if len({round(v, 6) for v in recent}) == 1:
                issues.append(f"flatline (stuck sensor?) last {c.flatline_n} identical")
                worst = worse(worst, P2)

        msg = f"{c.target}={conc:.1f}ppb" + (" · " + "; ".join(issues) if issues else " (normal)")
        return worst, msg, metrics

    def _fail_status(self, reason: str):
        status = P0 if self._fail_streak >= FAIL_STREAK_FOR_P0 else P1
        return status, f"{self.cfg.target} fit failed ({self._fail_streak} in a row): {reason}", \
            {"fail_streak": self._fail_streak}
