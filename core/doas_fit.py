"""core/doas_fit.py — 공유 VarPro DOAS 피터(DoasFitter)
====================================================

CAESAR의 비선형 DOAS 핏(Variable Projection + NNLS + Tikhonov + IRLS)을
worker.AnalysisWorker에서 **그대로 추출**한 단일 구현.

- AnalysisWorker는 기존 메서드명을 유지하되 이 클래스로 위임한다(동작 보존,
  raw 경로 회귀 바이트동일 게이트로 검증). raw·alpha 입력 모두 이 경로로 핏하므로
  raw↔alpha VarPro가 일치한다.

설계 원칙
---------
* DoasFitter는 engine만 보유하고 **나머지는 호출마다 인자로 받는다**(상태 없음).
  Kalman/etalon-한번검출/사전캘리브 캐리오버 등 스캔간 상태는 워커가 소유.
* interpolators는 **픽셀-인덱스**(engine.add_reference가 interp1d(arange,…)로 생성).
  따라서 항상 픽셀 공간에서 평가한다.
"""
import numpy as np
from scipy.linalg import lstsq as scipy_lstsq, solve_triangular
from scipy.optimize import least_squares, lsq_linear
from numpy.polynomial import chebyshev

# etalon–기체 공선성 경고 문턱 |r| — 이 이상이면 두 계수가 얽혀 오차가 부풀 수
# 있음을 보고한다(개선작업지시_2026-07 §B 제안값 0.5). 핏을 막거나 값을 바꾸지
# 않는다 — 검증≠필터.
ETALON_CORR_WARN = 0.5


def policy_floats(gas, kind, mode, raw, n):
    """shift/squeeze 정책 문자열 -> 실수 n개. 못 읽으면 **조용한 기본값 대신 예외**.

    이 파싱의 단일 출처. core.fit_optimizer도 같은 문자열을 읽으므로 여기로 위임한다.

    2026-09-15 이전에는 이 파싱이 실패하면 각 자리에서 하드코딩 기본값으로
    갈아탔다(Center -> 0±3px, Limit -> ±3px, Fix -> 0, sq Limit -> ±0.01,
    sq Fix -> 1.0). 결과 파일 헤더에는 **선언한 세팅**이 그대로 기록되므로,
    오타 하나면 "기록된 세팅"과 "실제로 돈 세팅"이 달라진 채 밤샘 런이 끝난다.
    재현성 원칙(결과 헤더 = 그 결과를 만든 세팅)과 정면으로 어긋나므로, 숫자가
    나오기 전인 셋업 단계에서 멈춘다.

    같은 검사가 이미 `core.fitset_builder.validate_fitset()`에 있다 — 거기는
    FitSet을 내보내기 전에 거르는 문지기이고, 여기는 그걸 안 거친 경로(수동
    ref_properties 등)를 위한 마지막 방어선이다.
    """
    try:
        vals = [float(x) for x in str(raw).split(",")]
    except (TypeError, ValueError):
        vals = None
    if vals is None or len(vals) != n:
        raise ValueError(
            f"{gas}: {kind}_mode={mode} 인데 {kind}_val을 읽을 수 없다 "
            f"({kind}_val={raw!r}, 기대: 콤마로 구분된 실수 {n}개). "
            f"FitSet/레퍼런스 설정을 고칠 것 — 예전에는 여기서 조용히 기본값으로 "
            f"갈아타서 '기록된 세팅'과 '실제 세팅'이 어긋났다."
        )
    return vals


class DoasFitter:
    def __init__(self, engine):
        self.engine = engine

    # ──────────────────────────────────────────────────────────────────
    def gas_active_in_window(self, ref_properties, gas_name, pixel_idx):
        """현재 핏 윈도우에서 gas_name을 포함할지. 'active_bands_nm'이 비면 항상 활성."""
        props = ref_properties.get(gas_name, {})
        bands_str = props.get("active_bands_nm", "").strip()
        if not bands_str:
            return True

        wave_nm = self.engine.pixel_to_wavelength(pixel_idx)
        win_lo, win_hi = float(wave_nm.min()), float(wave_nm.max())

        for seg in bands_str.split("|"):
            parts = seg.strip().split(",")
            if len(parts) == 2:
                try:
                    b_lo, b_hi = float(parts[0]), float(parts[1])
                    if win_hi >= b_lo and win_lo <= b_hi:
                        return True
                except ValueError:
                    pass
        return False

    # ──────────────────────────────────────────────────────────────────
    def pre_calibrate(self, pixel_idx, optical_depth, poly_order, init_shift):
        """격자탐색으로 초기 shift/squeeze 추정. init_shift = 기존 self.params[0]."""
        best_rms = np.inf
        best_shift = float(init_shift)
        best_squeeze = 1.0

        shifts = np.arange(best_shift - 0.5, best_shift + 0.51, 0.1)
        squeezes = np.arange(0.999, 1.002, 0.001)

        for sh in shifts:
            for sq in squeezes:
                try:
                    A = self.engine.get_basis_matrix(pixel_idx, sh, sq, poly_order)
                    coeffs, _, _, _ = scipy_lstsq(A, optical_depth, lapack_driver='gelsy')
                    y_fit = A @ coeffs
                    rms = np.sqrt(np.mean((optical_depth - y_fit) ** 2))
                    if rms < best_rms:
                        best_rms = rms
                        best_shift = sh
                        best_squeeze = sq
                except Exception:
                    pass
        return best_shift, best_squeeze

    # ──────────────────────────────────────────────────────────────────
    def detect_etalon_frequency(self, pixel_idx, optical_depth, poly_order,
                                freq_min, freq_max):
        """FFT로 지배적 etalon fringe 각주파수(rad/pixel) 검출."""
        x_mapped_temp = np.linspace(-1, 1, len(pixel_idx))
        p_coeffs = np.polyfit(x_mapped_temp, optical_depth, poly_order)
        poly_bg = np.polyval(p_coeffs, x_mapped_temp)

        rough_residual = optical_depth - poly_bg
        fft_vals = np.fft.rfft(rough_residual)
        fft_freqs = np.fft.rfftfreq(len(rough_residual), d=1.0)

        valid_mask = (fft_freqs > freq_min) & (fft_freqs < freq_max)
        if np.any(valid_mask):
            peak_f = fft_freqs[valid_mask][np.argmax(np.abs(fft_vals[valid_mask]))]
            return 2.0 * np.pi * peak_f
        return 0.50

    # ──────────────────────────────────────────────────────────────────
    def etalon_collinearity(self, pixel_idx, fixed_e_f, poly_order, ref_properties,
                            temperature=25.0, fit_sign=1.0,
                            opt_shifts=None, opt_squeezes=None, absolute_center=None):
        """Etalon–기체 공선성 진단 — **보고 전용, 핏 불변**(검증≠필터).

        etalon 제거는 sin(f·x)/cos(f·x) 두 열을 핏 기저에 추가하는 방식(필터 아님·
        신호 삭제 없음)이지만, 핏 창 안에서 어떤 기체 지문이 우연히 주파수 f 성분과
        닮으면 두 계수가 공선성으로 얽혀 오차가 부풀고 농도가 흔들릴 수 있다.
        이 함수는 그 정도를 정량 보고한다.

        방법 (differential 공간 — 완만한 성분은 poly가 흡수하므로 poly 사영 제거
        후 비교해야 의미가 있다):
          1) 최종 설계행렬과 동일한 기체 열(shift/squeeze/T보정/활성창 반영)과
             etalon sin/cos 열을 만든다.
          2) 모든 열에서 Chebyshev 배경(poly_order)을 최소제곱 사영으로 제거.
          3) r  = 각 기체 열과 etalon 2차원 부분공간의 **다중 상관계수**
                  (0~1; 위상 자유 사인파라 부호는 무의미).
          4) VIF = 잔차공간 [기체들+etalon] 상관행렬 역행렬 대각(분산팽창계수).
             vif_no_etalon(etalon 열 제외)과의 비가 'etalon이 유발한 팽창'이다.

        반환 dict:
          per_gas: {gas: {"r": float, "vif": float, "vif_no_etalon": float}}
          e_f: 사용한 각주파수, warn: |r| > ETALON_CORR_WARN 인 기체 목록
        비활성/영-노름 열은 NaN. 실패해도 예외를 밖으로 던지지 않는 건 호출부 책임."""
        pixel_idx = np.asarray(pixel_idx, dtype=float)
        n = len(pixel_idx)
        gases = list(self.engine.gas_list)
        if absolute_center is None:
            absolute_center = pixel_idx[len(pixel_idx) // 2]
        if opt_shifts is None:
            opt_shifts = [0.0] * len(gases)
        if opt_squeezes is None:
            opt_squeezes = [1.0] * len(gases)

        # 기체 열 — execute_varpro_fit 최종 설계행렬과 동일 구성
        t_corr = {}
        for name in gases:
            props = ref_properties.get(name, {})
            t_ref = float(props.get("t_ref", 25.0))
            t_coeff = float(props.get("t_coeff", 0.0))
            t_corr[name] = 1.0 + t_coeff * (temperature - t_ref) / 100.0
        gas_cols = []
        for i, name in enumerate(gases):
            if not self.gas_active_in_window(ref_properties, name, pixel_idx):
                gas_cols.append(np.zeros(n))
                continue
            px_sh = (pixel_idx - absolute_center) * opt_squeezes[i] + absolute_center + opt_shifts[i]
            col = fit_sign * self.engine.interpolators[name](px_sh) / self.engine.scaling_factors[name]
            gas_cols.append(np.asarray(col, dtype=float) * t_corr[name])

        x_min, x_max = pixel_idx[0], pixel_idx[-1]
        x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
        T = (chebyshev.chebvander(x_mapped, poly_order)
             if poly_order >= 0 else np.zeros((n, 0)))
        et_cols = [np.sin(fixed_e_f * pixel_idx), np.cos(fixed_e_f * pixel_idx)]

        def _depoly(v):
            """poly 사영 제거 → differential 성분."""
            if T.shape[1] == 0:
                return v.copy()
            coef, *_ = np.linalg.lstsq(T, v, rcond=None)
            return v - T @ coef

        g_res = [_depoly(g) for g in gas_cols]
        e_res = [_depoly(e) for e in et_cols]

        def _unit(v, ref_norm=None):
            """단위노름 정규화. differential 노름이 원래 노름 대비 1e-8 미만이면
            'poly에 전부 흡수됨'(퇴화) — 진단 무의미 → 무효 처리."""
            nv = float(np.linalg.norm(v))
            base = float(ref_norm) if ref_norm is not None else 1.0
            if nv <= 1e-300 or (ref_norm is not None and nv < 1e-8 * max(base, 1e-300)):
                return np.zeros_like(v), 0.0
            return v / nv, nv

        # etalon 잔차 부분공간의 정규직교기저
        E = np.column_stack(e_res)
        Q, R_ = np.linalg.qr(E)
        rank = int(np.sum(np.abs(np.diag(R_)) > 1e-12 * max(1.0, np.abs(R_[0, 0]))))
        Q = Q[:, :rank]

        per_gas = {}
        unit_cols, unit_ok = [], []
        for g, g0 in zip(g_res, gas_cols):
            u, nv = _unit(g, ref_norm=np.linalg.norm(g0))
            unit_cols.append(u)
            unit_ok.append(nv > 0)
        eu = [_unit(e)[0] for e in e_res if _unit(e)[1] > 0]

        def _vif(target_u, others_u):
            """VIF = 1/(1−R²), R² = target(단위노름)을 others로 회귀한 설명력.
            (상관행렬 pinv는 특이행렬에서 null-space를 잘라 VIF를 과소평가 —
            완전 공선일수록 작아지는 역설이 있어 직접 회귀로 계산한다.)"""
            if not others_u:
                return 1.0
            A = np.column_stack(others_u)
            beta, *_ = np.linalg.lstsq(A, target_u, rcond=None)
            resid = target_u - A @ beta
            r2 = min(max(1.0 - float(resid @ resid), 0.0), 1.0)
            return float(1.0 / max(1.0 - r2, 1e-12))

        for i, name in enumerate(gases):
            if not unit_ok[i] or rank == 0:
                per_gas[name] = {"r": float("nan"), "vif": float("nan"),
                                 "vif_no_etalon": float("nan")}
                continue
            u = unit_cols[i]
            r = float(np.linalg.norm(Q.T @ u))          # 다중 상관계수 (0~1)
            others = [unit_cols[k] for k in range(len(gases))
                      if k != i and unit_ok[k]]
            per_gas[name] = {"r": min(r, 1.0),
                             "vif": _vif(u, others + eu),
                             "vif_no_etalon": _vif(u, others)}

        warn = [g for g, d in per_gas.items()
                if np.isfinite(d["r"]) and d["r"] > ETALON_CORR_WARN]
        return {"per_gas": per_gas, "e_f": float(fixed_e_f), "warn": warn}

    @staticmethod
    def format_etalon_collinearity(diag):
        """진단 dict → 한 줄 문자열 (Test Fit 팝업·결과 헤더 공용)."""
        if not diag or not diag.get("per_gas"):
            return "etalon-gas collinearity: n/a"
        parts = []
        for g, d in diag["per_gas"].items():
            if not np.isfinite(d["r"]):
                parts.append(f"{g} r=n/a")
                continue
            s = f"{g} r={d['r']:.2f}"
            if np.isfinite(d["vif"]):
                s += f" (VIF {d['vif']:.1f})"
            if g in diag.get("warn", []):
                s += " ⚠"
            parts.append(s)
        line = (f"etalon-gas collinearity (f={diag['e_f']:.3f} rad/px): "
                + ",  ".join(parts))
        if diag.get("warn"):
            line += (f"  [⚠ |r|>{ETALON_CORR_WARN:g}: coefficients entangled — "
                     f"errors inflate; fit NOT modified]")
        return line

    # ──────────────────────────────────────────────────────────────────
    def setup_fit_parameters(self, ref_properties, initial_shift_center,
                             current_params, step_limit, initial_values=None):
        """least_squares용 비선형 파라미터 리스트(shift/squeeze 모드별) 구성."""
        initial_values = initial_values or {}
        active_vars, fixed_vars, linked_vars = [], {}, {}
        theta0, theta_lb, theta_ub = [], [], []

        for gas in self.engine.gas_list:
            props = ref_properties.get(gas, {"sh_mode": "Limit", "sh_val": "-0.5, 0.5",
                                             "sq_mode": "Fix", "sq_val": "1.0"})

            sh_name = f"{gas}_sh"
            if props["sh_mode"] in ("Limit", "Center"):
                active_vars.append(sh_name)
                if props["sh_mode"] == "Center":
                    # Center 모드: sh_val = "중심, 반폭". 허용창을 **선언된 중심**에 앵커한다.
                    # Limit은 언제나 0에서 출발해 step_limit씩 걸어 들어가야 하므로, 0에서 먼
                    # 실제 shift(예: 핫 -5.25px)를 쓰려면 범위가 0을 품어야 했고 그만큼 느슨해졌다.
                    # Center는 첫 스캔부터 중심에서 시작하므로 범위를 실측만큼 좁게 줄 수 있다.
                    c_val, half = policy_floats(gas, "sh", "Center",
                                                 props.get("sh_val"), 2)
                    half = abs(half)
                    global_lb, global_ub = c_val - half, c_val + half
                    # 스캔간 연속성은 유지: 이전 shift가 이미 창 안이면 그걸 중심으로 이어가고,
                    # 창 밖(첫 스캔의 0 등)이면 선언된 중심에서 시작한다.
                    anchor = (initial_shift_center
                              if global_lb <= initial_shift_center <= global_ub else c_val)
                else:
                    global_lb, global_ub = policy_floats(gas, "sh", "Limit",
                                                          props.get("sh_val"), 2)
                    if global_ub < global_lb:
                        global_lb, global_ub = global_ub, global_lb
                    anchor = initial_shift_center
                window_lb, window_ub = anchor - step_limit, anchor + step_limit
                sh_lb, sh_ub = max(global_lb, window_lb), min(global_ub, window_ub)
                if sh_lb >= sh_ub:
                    # 교집합이 비었다 = 허용범위가 현재 중심에서 step_limit 밖(예: sh_val
                    # "-9,-1.5"인데 중심 0·step 0.5 → [-0.5,-1.5]). 예전엔 여기서 least_squares가
                    # "lower bound must be strictly less than upper bound"로 **죽었다**.
                    # 이제는 허용범위 쪽으로 한 스텝 다가간 창을 주어 걸어 들어가게 한다(비파괴).
                    near = min(max(anchor, global_lb), global_ub)   # 허용범위 내 최근접점
                    step_toward = max(min(near, anchor + step_limit), anchor - step_limit)
                    sh_lb = max(global_lb, min(step_toward, near))
                    sh_ub = min(global_ub, max(step_toward, near))
                    if sh_lb >= sh_ub:                              # 여전히 퇴화면 미세폭 부여
                        sh_lb, sh_ub = near - 1e-4, near + 1e-4
                theta_lb.append(sh_lb); theta_ub.append(sh_ub)
                start = initial_values.get(sh_name, current_params[0])
                theta0.append(max(sh_lb + 1e-5, min(sh_ub - 1e-5, start)))
            elif props["sh_mode"] == "Free":
                active_vars.append(sh_name)
                theta_lb.append(-np.inf); theta_ub.append(np.inf)
                theta0.append(initial_values.get(sh_name, initial_shift_center))
            elif props["sh_mode"] == "Fix":
                # Fix = hold the shift at the ABSOLUTE value (same units as the Limit
                # window). Previously this was `initial_shift_center + val`, which —
                # because initial_shift_center carries last_valid_shift across scans —
                # made any non-zero Fix value drift by `val` every scan (e.g. Fix -0.5
                # ran away to -120). Fix 0 happened to be safe (no accumulation).
                (val,) = policy_floats(gas, "sh", "Fix", props.get("sh_val"), 1)
                fixed_vars[sh_name] = val
            elif props["sh_mode"] == "Link":
                linked_vars[sh_name] = f"{props['sh_val'].strip()}_sh"

            sq_name = f"{gas}_sq"
            if props["sq_mode"] == "Limit":
                active_vars.append(sq_name)
                v_min, v_max = policy_floats(gas, "sq", "Limit",
                                              props.get("sq_val"), 2)
                sq_lb = 1.0 + v_min if abs(v_min) < 0.5 else v_min
                sq_ub = 1.0 + v_max if abs(v_max) < 0.5 else v_max
                theta_lb.append(sq_lb); theta_ub.append(sq_ub)
                start = initial_values.get(sq_name, 1.0)
                theta0.append(max(sq_lb + 1e-5, min(sq_ub - 1e-5, start)))
            elif props["sq_mode"] == "Free":
                active_vars.append(sq_name)
                theta_lb.append(0.1); theta_ub.append(10.0); theta0.append(1.0)
            elif props["sq_mode"] == "Fix":
                (val,) = policy_floats(gas, "sq", "Fix", props.get("sq_val"), 1)
                fixed_vars[sq_name] = 1.0 + val if abs(val) < 0.5 else val
            elif props["sq_mode"] == "Link":
                linked_vars[sq_name] = f"{props['sq_val'].strip()}_sq"

        return active_vars, fixed_vars, linked_vars, theta0, theta_lb, theta_ub

    # ──────────────────────────────────────────────────────────────────
    def execute_varpro_fit(self, pixel_idx, optical_depth, W_initial,
                           active_vars, fixed_vars, linked_vars,
                           theta0, theta_lb, theta_ub, poly_order, fixed_e_f,
                           absolute_center, fit_sign, ref_properties, temperature,
                           tikhonov_lambda, use_robust,
                           override_lam=None, override_robust=None, allow_negative_gas=False,
                           custom_basis=None, return_diagnostics=False):
        """VarPro + NNLS + Tikhonov + Robust(IRLS) 엔진. AnalysisWorker에서 verbatim 이식.
        W_initial: 픽셀별 가중. 길이 n 벡터(권장) 또는 밀집 n×n 대각행렬(구 호출부 호환)
          — 밀집으로 주면 대각만 꺼내 쓴다. 결과는 두 형태가 비트동일.
        allow_negative_gas=True면 가스 계수 하한을 0→−∞로 풀어 음수 농도 허용(0근처 비편향).
        custom_basis: (n_pix, k) 외부 선형 베이스(Ring·fixed-pattern 고유벡터 등). None이면
          컬럼 0개라 기존과 바이트동일. 컬럼은 poly 뒤·etalon 앞에 삽입돼 etalon이 마지막
          열로 유지되므로 반환 인덱싱이 보존되고 gas 계수(c_opt[0:num_gases])도 불변."""
        gas_lb = -np.inf if allow_negative_gas else 0.0
        x_min, x_max = pixel_idx[0], pixel_idx[-1]
        x_mapped = (2.0 * (pixel_idx - x_min) / (x_max - x_min)) - 1.0
        T = chebyshev.chebvander(x_mapped, poly_order) if poly_order >= 0 else np.zeros((len(pixel_idx), 0))

        lam = override_lam if override_lam is not None else tikhonov_lambda
        use_robust = override_robust if override_robust is not None else use_robust

        # 가스별 온도보정: σ_eff(T) = σ_ref × (1 + t_coeff·(T-T_ref)/100)
        t_corr = {}
        for name in self.engine.gas_list:
            props = ref_properties.get(name, {})
            t_ref = float(props.get("t_ref", 25.0))
            t_coeff = float(props.get("t_coeff", 0.0))
            t_corr[name] = 1.0 + t_coeff * (temperature - t_ref) / 100.0

        gas_active = {
            name: self.gas_active_in_window(ref_properties, name, pixel_idx)
            for name in self.engine.gas_list
        }

        # W는 항상 대각(픽셀별 가중)이다. 밀집 n×n 행렬로 받으면 대각만 꺼내
        # 벡터로 쓴다 — `W @ A`(O(n²k))와 `w[:,None]*A`(O(nk))는 대각행렬에선
        # 수학적으로 동치이고 부동소수점으로도 비트동일(off-diagonal이 정확히 0).
        # n=775px 기준 그 곱 하나가 objective 호출 비용의 62%였다.
        w_initial = np.diag(W_initial) if np.ndim(W_initial) == 2 else np.asarray(W_initial, dtype=float)
        w_current = w_initial.copy()
        max_iters = 10 if use_robust else 1
        prev_weights = w_current.copy()
        num_gases = len(self.engine.gas_list)

        # custom_basis 정규화: None이면 컬럼 0개(=기존 동작). poly 뒤·etalon 앞에 들어간다.
        CB = None if custom_basis is None else np.asarray(custom_basis, dtype=float).reshape(len(pixel_idx), -1)

        # Tikhonov 패널티 대각: 다항식(Chebyshev) 배경 열은 절대 수축하지 않는다.
        # (λ>0일 때 배경모양 왜곡·gas 과소편향 방지 — 표준 DOAS. gas·custom·etalon만 능형화.)
        def _penalty(ncols):
            pen = np.full(ncols, lam, dtype=float)
            pen[num_gases:num_gases + (poly_order + 1)] = 0.0
            return np.diag(pen)

        y_w_current = optical_depth * w_current

        # theta에 안 걸리는 열(poly·custom_basis·etalon sin/cos)은 상수다. 목적함수
        # 호출마다 다시 만들 이유가 없어 여기서 한 번만 조립한다. 열 순서는 종전과
        # 동일(gas → poly → custom → sin → cos)이라 하류 인덱싱·반환값이 불변.
        # etalon: sin·cos 두 선형열 — 진폭/위상을 선형으로 흡수(비선형 위상 e_p 제거).
        # A·sin(f·x+φ)=A·cosφ·sin(f·x)+A·sinφ·cos(f·x) 라 같은 모델공간이며 전역 선형해.
        const_cols = [T[:, j] for j in range(poly_order + 1)]
        if CB is not None:
            const_cols += [CB[:, kk] for kk in range(CB.shape[1])]
        const_cols += [np.sin(fixed_e_f * pixel_idx), np.cos(fixed_e_f * pixel_idx)]
        CONST = np.column_stack(const_cols)

        # ── 해석적(Golub–Pereyra) 자코비안 준비 ─────────────────────
        # 쓸 수 있는 조건: 선형 단계가 **무제약**일 때만. gas_lb=0(±Neg OFF)이면 해가
        # 0 경계에 붙는 순간 투영이 미분 불가능해져 해석해가 틀린 값을 준다 → 그때는
        # scipy 유한차분(기존 동작)으로 떨어진다.
        # engine은 덕타이핑으로 들어올 수 있다(테스트 대역 등) → getattr로 본다.
        _ref_deriv = getattr(self.engine, "ref_derivatives", {})
        use_analytic_jac = (gas_lb == -np.inf) and bool(self.engine.gas_list) and all(
            name in _ref_deriv for name in self.engine.gas_list)

        # θ_k가 어느 기체 열에 어떤 형태로 걸리는지. Link면 한 θ가 여러 기체를 움직인다.
        jac_targets = {v: [] for v in active_vars}
        for _i, _name in enumerate(self.engine.gas_list):
            if not gas_active[_name]:
                continue
            for _kind, _is_sq in (("sh", False), ("sq", True)):
                _var = f"{_name}_{_kind}"
                _src = linked_vars.get(_var, _var)
                if _src in jac_targets:
                    jac_targets[_src].append((_i, _is_sq))
        # 창 밖 기체 열은 항상 0 → A가 랭크부족이라 QR이 깨진다. 그 열을 빼고 풀고
        # 계수는 0으로 되돌린다(현 lsq_linear의 최소노름 해와 같은 값).
        keep_mask = np.array([gas_active[n] for n in self.engine.gas_list]
                             + [True] * CONST.shape[1])
        # 남긴 열 목록에서 기체 i가 몇 번째인지(자코비안 2항이 쓴다)
        keep_pos = {gi: k for k, gi in enumerate(
            [i for i, n in enumerate(self.engine.gas_list) if gas_active[n]])}
        dpx_dsq = (pixel_idx - absolute_center).astype(float)

        def _gas_dcolumns(val_dict):
            """∂(기체 열)/∂px. shift 미분은 이것, squeeze 미분은 여기에 (px−center)를 곱한 것."""
            D = np.zeros((len(pixel_idx), num_gases))
            for i, name in enumerate(self.engine.gas_list):
                if not gas_active[name]:
                    continue
                sh_i, sq_i = val_dict[f"{name}_sh"], val_dict[f"{name}_sq"]
                pixel_shifted = (pixel_idx - absolute_center) * sq_i + absolute_center + sh_i
                d = fit_sign * _ref_deriv[name](pixel_shifted) / self.engine.scaling_factors[name]
                D[:, i] = np.asarray(d).ravel() * t_corr[name]
            return D

        def _gas_columns(val_dict):
            """shift/squeeze가 걸리는 기체 열만. 창 밖 기체는 어차피 0으로 덮이므로
            보간 자체를 건너뛴다(결과 동일, 스플라인 평가 1회 절약)."""
            G = np.empty((len(pixel_idx), num_gases))
            for i, name in enumerate(self.engine.gas_list):
                if not gas_active[name]:
                    G[:, i] = 0.0
                    continue
                sh_i, sq_i = val_dict[f"{name}_sh"], val_dict[f"{name}_sq"]
                pixel_shifted = (pixel_idx - absolute_center) * sq_i + absolute_center + sh_i
                raw_ref = fit_sign * self.engine.interpolators[name](pixel_shifted) / self.engine.scaling_factors[name]
                G[:, i] = raw_ref * t_corr[name]
            return G

        solver_runs = []
        for iteration in range(max_iters):
            jac_state = {}   # objective ↔ jacobian 사이 (같은 θ일 때만) A·Q·c 재활용

            def _theta_to_vals(theta):
                val_dict = {v: theta[i] for i, v in enumerate(active_vars)}
                val_dict.update(fixed_vars)
                for v, t in linked_vars.items():
                    val_dict[v] = val_dict.get(t, 0.0)
                return val_dict

            def _augment(val_dict):
                A_weighted = np.hstack((_gas_columns(val_dict), CONST)) * w_current[:, None]
                num_cols = A_weighted.shape[1]
                if lam > 0:
                    return (np.vstack((A_weighted, _penalty(num_cols))),
                            np.concatenate((y_w_current, np.zeros(num_cols))))
                return A_weighted, y_w_current

            def _solve_qr(theta):
                """무제약 선형 단계를 QR로 푼다. Q는 자코비안의 투영 P⊥=I−QQᵀ에 그대로 쓴다."""
                val_dict = _theta_to_vals(theta)
                A_aug, y_aug = _augment(val_dict)
                A_keep = A_aug[:, keep_mask]
                Q, R = np.linalg.qr(A_keep)
                c_keep = solve_triangular(R, Q.T @ y_aug, lower=False)
                c = np.zeros(A_aug.shape[1])
                c[keep_mask] = c_keep
                st = {"theta": np.array(theta, dtype=float), "val_dict": val_dict,
                      "Q": Q, "R": R, "c": c, "resid": y_aug - A_keep @ c_keep}
                jac_state.clear(); jac_state.update(st)
                return st

            def objective_varpro(theta):
                if use_analytic_jac:
                    return _solve_qr(theta)["resid"]

                val_dict = _theta_to_vals(theta)
                A_aug, y_aug = _augment(val_dict)
                num_cols = A_aug.shape[1]
                lb_inner = [gas_lb] * num_gases + [-np.inf] * (num_cols - num_gases)
                ub_inner = [np.inf] * num_cols
                res_temp = lsq_linear(A_aug, y_aug, bounds=(lb_inner, ub_inner))
                return y_aug - A_aug @ res_temp.x

            def jacobian_varpro(theta):
                """Golub–Pereyra 완전 자코비안 (Kaufman 근사가 아님 — 2항 모두):

                    J_k = −[ P⊥ D_k c  +  A⁺ᵀ D_kᵀ r ],   P⊥ = I − QQᵀ,  A⁺ᵀ = Q R⁻ᵀ

                D_k = ∂A/∂θ_k는 기체 열만 0이 아니다(poly·etalon·Tikhonov 행은 θ 불변).
                2항은 k-벡터 삼각해 하나 + Q 곱 하나라 거의 공짜인데, 이게 있어야
                유한차분과 일치해 검증을 게이트로 쓸 수 있다.

                least_squares는 보통 fun(x) 직후 같은 x에서 jac(x)를 부르므로 그때
                만든 A·Q·R·c를 재활용하고, 어긋나면 다시 푼다(결과는 같고 느릴 뿐)."""
                st = jac_state if (jac_state and np.array_equal(jac_state["theta"], theta))                      else _solve_qr(theta)
                Q, R, c, val_dict, resid = st["Q"], st["R"], st["c"], st["val_dict"], st["resid"]
                D = _gas_dcolumns(val_dict)
                n_pix = len(pixel_idx)
                n_pen = Q.shape[0] - n_pix          # Tikhonov 증강 행 수(없으면 0)
                r_top = resid[:n_pix]
                J = np.empty((Q.shape[0], len(active_vars)))
                for k, var in enumerate(active_vars):
                    v = np.zeros(n_pix)
                    g = np.zeros(Q.shape[1])
                    for gi, is_sq in jac_targets[var]:
                        dcol = (D[:, gi] * dpx_dsq if is_sq else D[:, gi]) * w_current
                        v += dcol * c[gi]
                        g[keep_pos[gi]] = dcol @ r_top
                    if n_pen:
                        v = np.concatenate((v, np.zeros(n_pen)))
                    term1 = v - Q @ (Q.T @ v)
                    term2 = Q @ solve_triangular(R, g, trans='T', lower=False)
                    J[:, k] = -(term1 + term2)
                return J

            if len(theta0) > 0:
                try:
                    res_nonlin = least_squares(objective_varpro, x0=theta0, bounds=(theta_lb, theta_ub),
                                               jac=(jacobian_varpro if use_analytic_jac else '2-point'),
                                               max_nfev=1500)
                except np.linalg.LinAlgError:
                    # A가 정확히 랭크부족(중복 레퍼런스 등) → QR 경로가 못 푼다.
                    # 이 핏은 예전처럼 lsq_linear + 유한차분으로 간다(동작 보존).
                    use_analytic_jac = False
                    jac_state.clear()
                    res_nonlin = least_squares(objective_varpro, x0=theta0, bounds=(theta_lb, theta_ub),
                                               jac='2-point', max_nfev=1500)
                theta_opt = res_nonlin.x
                solver_runs.append({"status": int(res_nonlin.status),
                                    "success": bool(res_nonlin.success),
                                    "nfev": int(res_nonlin.nfev)})
            else:
                # 비선형 파라미터 없음(모든 shift/squeeze가 Fix; etalon은 이제 선형 sin·cos).
                # least_squares는 빈 x0에서 에러나므로 선형해만 1회. (콜드 shift Fix 0 시나리오)
                theta_opt = np.asarray([], dtype=float)

            val_dict_opt = {v: theta_opt[i] for i, v in enumerate(active_vars)}
            val_dict_opt.update(fixed_vars)
            for v, t in linked_vars.items():
                val_dict_opt[v] = val_dict_opt.get(t, 0.0)

            opt_shifts = [val_dict_opt[f"{g}_sh"] for g in self.engine.gas_list]
            opt_squeezes = [val_dict_opt[f"{g}_sq"] for g in self.engine.gas_list]

            A_final = np.hstack((_gas_columns(val_dict_opt), CONST))
            A_f_w = A_final * w_current[:, None]
            y_w = y_w_current

            num_cols_final = A_f_w.shape[1]

            if lam > 0:
                A_aug = np.vstack((A_f_w, _penalty(num_cols_final)))
                y_aug = np.concatenate((y_w, np.zeros(num_cols_final)))
            else:
                A_aug, y_aug = A_f_w, y_w

            lb_final = [gas_lb] * num_gases + [-np.inf] * (num_cols_final - num_gases)
            res_lin_final = lsq_linear(A_aug, y_aug, bounds=(lb_final, [np.inf] * num_cols_final))
            c_opt = res_lin_final.x

            if use_robust and iteration < max_iters - 1:
                residuals = np.abs(optical_depth - A_final @ c_opt)
                raw_mad = np.median(residuals)
                mad = raw_mad if raw_mad > 0 else np.mean(residuals)
                sigma_hat = mad / 0.6745
                k = 4.685 * (sigma_hat + 1e-9)
                new_weights = np.where(residuals < k, (1 - (residuals / k) ** 2) ** 2, 0.0) * w_initial
                if iteration > 0 and np.max(np.abs(new_weights - prev_weights)) < 1e-6:
                    break
                prev_weights = new_weights.copy()
                w_current = new_weights
                y_w_current = optical_depth * w_current
            else:
                break

        resid_w = y_w - A_f_w @ c_opt
        mse = np.mean(resid_w ** 2)
        try:
            # 공분산은 **핏이 실제로 푼 계**의 정규방정식에서 나와야 한다.
            # 예전엔 세 군데가 핏과 어긋나 있었다(λ=0이라 드러나지 않았을 뿐):
            #   ① `lam = tikhonov_lambda` 로 되돌려 override_lam 을 버렸다
            #      → 정규화 A로 핏해놓고 오차는 정규화 B로 계산하는 셈
            #   ② 증강이 `diag(lam)` 이라 **실효 릿지 파라미터는 λ²**인데
            #      (`[A; diag(λ)]c≈[y;0]` → `(AᵀA+λ²I)c=Aᵀy`, 수치검증 완료)
            #      공분산은 `AtWA + λ·I` 로 λ를 썼다
            #   ③ `_penalty()`는 Chebyshev 배경열을 **일부러 0으로 두는데**
            #      (표준 DOAS: 배경은 수축시키지 않는다) 공분산은 `λ·eye` 로
            #      전 열을 균일 수축시켰다
            # 이제 핏이 쓴 페널티 행렬 P를 그대로 받아 `M = AᵀA + PᵀP` 로 만든다 —
            # 증강계 `[A; P]` 의 정규방정식과 정의상 동일하다. λ=0이면 P=0이라
            # 기존과 **바이트동일**. 회귀: `tools/test_covariance_lambda.py`
            AtWA = A_f_w.T @ A_f_w
            n_cols = AtWA.shape[0]
            P = _penalty(n_cols) if lam > 0 else None
            M = AtWA + (P.T @ P if P is not None else 0.0)
            M_inv = np.linalg.pinv(M)
            if P is not None:
                cov = M_inv @ AtWA @ M_inv * mse
            else:
                cov = M_inv * mse
            perr_lin = np.sqrt(np.maximum(np.diag(cov), 0.0))
        except Exception:
            # 0이 아니라 NaN이다. perr는 결과 파일의 <gas>_Error 이자
            # MDL = 3*Error 의 재료이고, fit_optimizer의 1순위 순위축
            # perr_rel(=perr/|coeff|)이기도 하다. 0으로 채우면 "오차 0, 검출한계 0,
            # 최적 세팅"이라는 **가장 방어 불가능한 주장**이 조용히 파일에 박힌다.
            # NaN은 '모른다'이고, 하류(fit_optimizer)가 이미 쓰는 센티넬이다.
            perr_lin = np.full_like(c_opt, np.nan)

        c_gas = c_opt[0:num_gases].copy()
        c_perr = perr_lin[0:num_gases].copy()
        for i, name in enumerate(self.engine.gas_list):
            if not gas_active[name]:
                c_gas[i] = 0.0
                c_perr[i] = 0.0

        # etalon: 마지막 두 열 = a·sin + b·cos → 진폭/위상으로 환산해 반환(하류의
        # `amp·sin(f·x + phase)` 재구성과 정확히 동일: a=A·cosφ, b=A·sinφ).
        a_et, b_et = float(c_opt[-2]), float(c_opt[-1])
        etalon_amp = float(np.hypot(a_et, b_et))
        etalon_phase = float(np.arctan2(b_et, a_et))
        poly_coeffs = c_opt[num_gases:-2]

        result = (opt_shifts, opt_squeezes, c_gas, poly_coeffs,
                  etalon_amp, etalon_phase, c_perr)
        if not return_diagnostics:
            return result
        # ``objective_varpro`` now closes over the final IRLS weight matrix.
        # Evaluate each endpoint once here so robust and non-robust diagnostics
        # are directly comparable.  An earlier scipy ``fun`` may use an older
        # IRLS matrix and therefore is deliberately not reused.
        objective_initial, objective_final = _endpoint_objectives(
            objective_varpro, theta0, theta_opt)
        termination = _aggregate_solver_termination(solver_runs)
        diagnostics = {"objective_initial": float(objective_initial),
                       "objective_final": float(objective_final),
                       "objective_convention": "sum_squared_weighted_varpro_residual",
                       "solver_termination": termination}
        return result, diagnostics


def _aggregate_solver_termination(solver_runs):
    """Conservatively aggregate scipy statuses across IRLS solves."""
    if not solver_runs:
        return {"status": "TERMINATED", "success": True, "nfev": 0}
    codes = [run["status"] for run in solver_runs]
    status = ("FAILED" if any(code < 0 for code in codes)
              else "MAX_NFEV" if any(code == 0 for code in codes)
              else "CONVERGED")
    return {"status": status,
            "success": all(run["success"] for run in solver_runs),
            "nfev": sum(run["nfev"] for run in solver_runs)}


def _endpoint_objectives(objective, theta_initial, theta_final):
    """Evaluate both endpoints once through the same current objective closure."""
    initial = np.asarray(objective(np.asarray(theta_initial, dtype=float)), dtype=float)
    final = np.asarray(objective(np.asarray(theta_final, dtype=float)), dtype=float)
    return float(np.dot(initial, initial)), float(np.dot(final, final))
