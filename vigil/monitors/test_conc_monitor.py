"""vigil/monitors/conc_monitor.py 단위테스트.

Real alpha from `Output/alpha/60s/cold` is turned back into intensities with the exact
inverse of core.physics.bbceas_alpha (_spectrum_for_alpha) and fitted with the real FitSet.

Until 2026-10-02 this file used `spectrum = I0*exp(-alpha)`, which the monitor's old
`-log(I/I0)` undid exactly -- a circular test that could never see that the monitor fed
optical density as alpha [cm^-1] (concentrations L_eff ~1e6 too high, 32/32 PASS).
The inverse now needs (1-R)/d, so a unit error breaks it; plus test_real_raw_end_to_end
replays a real raw file through RMonitor -> ConcMonitor (SKIP if the raw is not local).

커버:
  1) I0 버퍼링(za_inject 윈도우 완결) + throttle
  2) 첫 핏 후 seed narrowing(Center 모드로 전환)
  3) 경보 판정(_classify) — OK/물리불가(P1)/rms낮음(P1)/스파이크(P2)/평탄선(P2)
  4) 연속 실패 → P0 격상
  5) pick_fitset_channel — wl_dir 매칭
  6) no R -> SKIP (no OD fallback)
  7) real raw end to end -- concentration in the physical range

사용: python vigil/monitors/test_conc_monitor.py → 전부 PASS면 exit 0
"""
import glob
import json
import os
import sys
import warnings

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import dataclasses
from datetime import datetime, timedelta

from core.physics import RayleighPhysics
from vigil.alert_engine import OK, P0, P1, P2, SKIP
from vigil.monitors.conc_monitor import PURGE_SETTLE_SEC, ConcMonitor, pick_fitset_channel
from vigil.profile import ConcentrationConfig
from tools import optimize_params as OP
from tools.residual_compare import load_alpha

# (1-R)/d [cm^-1] of a real cold R (R=0.999949, L_eff ~10 km).
OMR_D_COLD = 9.79e-7
RL_COLD = 0.933
# Calibration rows in the unit tests are stamped long ago, so the purge-settle window
# (PURGE_SETTLE_SEC after the last ZA/He row) is over when 'sampling' rows arrive at now().
CAL_T = datetime(2000, 1, 1)


def _spectrum_for_alpha(alpha, i0, omr_d, t_c, p_mbar, wave, rl=RL_COLD):
    """Exact inverse of bbceas_alpha with equal ZA/sample T/P:
    I = I0 / (1 + alpha / (omr_d + rl*alpha_ZA))."""
    a_za = RayleighPhysics.get_alpha_rayleigh(wave, t_c, p_mbar, "zero_air")
    return np.asarray(i0, float) / (1.0 + np.asarray(alpha, float) / (omr_d + rl * a_za))


_n_pass = 0
_n_fail = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def _real_cold_alpha():
    files = sorted(glob.glob(
        r"C:\Doasis_Work\Output\alpha\60s\cold\2026-05-26\*_cold_alpha_trace.dat"))
    if not files:
        return None
    return load_alpha(files[0])   # (wave, alpha, T, P)


def _make_monitor(**cfg_overrides):
    scen = json.load(open(OP.FITSET, encoding="utf-8"))
    fit_ch = pick_fitset_channel(scen, "cold")
    cfg_kwargs = dict(fitset_path=OP.FITSET, wl_dir="cold", target="NO2",
                      allow_negative_gas=False,
                      throttle_sec=0.0, seed_narrow_px=2.0,
                      conc_min_ppb=-20, conc_max_ppb=50, spike_ppb=20,
                      rms_sig_alarm=0.15, flatline_n=5)
    cfg_kwargs.update(cfg_overrides)
    cfg = ConcentrationConfig(**cfg_kwargs)
    return ConcMonitor(fit_ch, cfg)


def test_pick_fitset_channel():
    print("[5] pick_fitset_channel — wl_dir 매칭")
    scen = json.load(open(OP.FITSET, encoding="utf-8"))
    for wl_dir in ("cold", "roi1", "roi2"):
        ch = pick_fitset_channel(scen, wl_dir)
        check(f"'{wl_dir}' 매칭됨", wl_dir in str(ch.get("wl_path", "")).replace("\\", "/"))
    try:
        pick_fitset_channel(scen, "roi99")
        check("없는 wl_dir는 예외", False, "예외 안 남")
    except ValueError:
        check("없는 wl_dir는 예외", True)


def test_gas_policy_source_and_legacy_migration():
    print("[6] gas policy source + legacy migration")
    scen = json.load(open(OP.FITSET, encoding="utf-8"))
    legacy = dict(pick_fitset_channel(scen, "cold"))
    legacy.pop("allow_negative_gas", None)
    cfg = ConcentrationConfig(fitset_path=OP.FITSET, wl_dir="cold",
                              allow_negative_gas=False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cm = ConcMonitor(legacy, cfg)
    check("legacy FitSet은 profile fallback을 경고", bool(caught))
    check("legacy provenance 기록", cm.gas_policy_provenance.startswith("legacy"))

    current = dict(legacy, allow_negative_gas=False)
    cm = ConcMonitor(current, cfg)
    check("현재 FitSet이 정책 단일 출처", cm.gas_policy_provenance == "FitSet")
    try:
        ConcMonitor(dict(current, allow_negative_gas=True), cfg)
        check("FitSet/profile 불일치 거부", False)
    except ValueError:
        check("FitSet/profile 불일치 거부", True)


def test_i0_buffer_and_fit_and_throttle():
    print("[1]+[2] I0 버퍼링 + throttle + seed narrowing")
    real = _real_cold_alpha()
    if real is None:
        print("  SKIP  실측 알파 없음(로컬 데이터 없음) — 이 블록 건너뜀")
        return
    wave, alpha_real, T, P = real
    i0 = np.full_like(wave, 40000.0)
    omr_d = np.full_like(wave, OMR_D_COLD)
    spectrum = _spectrum_for_alpha(alpha_real, i0, omr_d, T, P, wave)
    kw = dict(omr_d=omr_d, rl=RL_COLD)

    cm = _make_monitor(throttle_sec=0.0)
    r_za = cm.observe("za_inject", i0, T, P, **kw, row_time=CAL_T)
    check("za_inject 중엔 결과 없음", r_za is None)
    check("I0 아직 없음(za 윈도우 안 끝남)", cm._i0 is None)

    r0 = cm.observe("sampling", spectrum, T, P, **kw)
    check("za 윈도우 종료 후 I0 채워짐", cm._i0 is not None)
    check("첫 sampling 행에서 핏 실행됨", r0 is not None)
    status, msg, metrics = r0
    check("농도값이 유한", np.isfinite(metrics["conc_ppb"]), metrics)
    check("cold 콘텍스트에서 그럴듯한 농도(-20~50ppb)",
          -20 <= metrics["conc_ppb"] <= 50, metrics["conc_ppb"])
    check("첫 핏 후 seed(_last_shift) 저장됨", cm._last_shift is not None)
    rp2 = cm._seeded_ref_props()
    check("두번째부턴 Center 모드로 좁힘", rp2["NO2"]["sh_mode"] == "Center", rp2["NO2"])

    # throttle=0이라 즉시 재핏 가능 — 되는지만 확인(느려도 됨, 값 검증은 위에서 끝)
    r1 = cm.observe("sampling", spectrum, T, P, **kw)
    check("throttle=0이면 바로 재핏", r1 is not None)

    # The same spectrum read as OD (old bug) is L_eff times larger than alpha.
    ratio = float(np.nanmedian(np.abs(-np.log(spectrum / i0))) / np.nanmedian(np.abs(alpha_real)))
    check("OD/alpha ratio is L_eff scale (1e5..1e7)", 1e5 < ratio < 1e7, f"ratio={ratio:.3e}")


def test_throttle_blocks_immediate_refit():
    print("[1] throttle_sec 큰 값이면 바로 다음 행은 스킵")
    real = _real_cold_alpha()
    if real is None:
        print("  SKIP  실측 알파 없음")
        return
    wave, alpha_real, T, P = real
    i0 = np.full_like(wave, 40000.0)
    omr_d = np.full_like(wave, OMR_D_COLD)
    spectrum = _spectrum_for_alpha(alpha_real, i0, omr_d, T, P, wave)
    kw = dict(omr_d=omr_d, rl=RL_COLD)
    cm = _make_monitor(throttle_sec=9999.0)
    cm.observe("za_inject", i0, T, P, **kw, row_time=CAL_T)
    r0 = cm.observe("sampling", spectrum, T, P, **kw)
    check("첫 핏은 즉시 실행", r0 is not None)
    r1 = cm.observe("sampling", spectrum, T, P, **kw)
    check("throttle 안 지났으면 None", r1 is None)


def test_no_r_yields_skip_not_garbage():
    print("[6] no R -> SKIP (no OD fallback)")
    cm = _make_monitor(throttle_sec=0.0)
    i0 = np.full(2048, 40000.0)
    spectrum = i0 * 0.98
    cm.observe("za_inject", i0, 25.0, 1013.25, row_time=CAL_T)
    r = cm.observe("sampling", spectrum, 25.0, 1013.25)          # no omr_d
    check("no omr_d -> SKIP", r is not None and r[0] == SKIP, f"got {r}")
    check("no omr_d -> no concentration value", r is not None and "conc_ppb" not in r[2], f"got {r}")

    cm2 = _make_monitor(throttle_sec=0.0)
    cm2.observe("za_inject", i0, 25.0, 1013.25, row_time=CAL_T)
    r2 = cm2.observe("sampling", spectrum, 25.0, 1013.25, omr_d=np.full(512, OMR_D_COLD))
    check("omr_d axis mismatch -> failure", r2 is not None and r2[0] in (P1, P0), f"got {r2}")

    cm3 = _make_monitor(throttle_sec=0.0)
    cm3.observe("za_inject", i0, 25.0, 1013.25, row_time=CAL_T)
    r3 = cm3.observe("sampling", spectrum, 25.0, 1013.25, omr_d=np.full(2048, np.nan))
    check("omr_d NaN in fit window (outside R ROI) -> failure, not a value",
          r3 is not None and r3[0] in (P1, P0) and "conc_ppb" not in r3[2], f"got {r3}")


def test_purge_settle():
    print("[8] purge settle -- no fit within PURGE_SETTLE_SEC after a ZA/He block (Augur default)")
    check("same value as Augur alpha generation (60 s)", PURGE_SETTLE_SEC == 60.0, PURGE_SETTLE_SEC)
    cm = _make_monitor(throttle_sec=0.0)
    i0 = np.zeros(2048)                       # bad I0: any fit that runs reports a failure
    kw = dict(omr_d=np.full(2048, OMR_D_COLD), rl=RL_COLD)
    t0 = datetime(2026, 5, 20, 3, 0, 0)
    cm.observe("za_inject", i0, 25.0, 1013.25, row_time=t0, **kw)
    cm.observe("za_wait_after", i0, 25.0, 1013.25, row_time=t0 + timedelta(seconds=20), **kw)
    end = t0 + timedelta(seconds=20)          # settle counts from the END of the block
    r = cm.observe("sampling", i0, 25.0, 1013.25, row_time=end + timedelta(seconds=6), **kw)
    check("6 s after the block: no fit", r is None, f"got {r}")
    r = cm.observe("sampling", i0, 25.0, 1013.25,
                   row_time=end + timedelta(seconds=PURGE_SETTLE_SEC - 1), **kw)
    check("settle-1 s: still no fit", r is None, f"got {r}")
    r = cm.observe("sampling", i0, 25.0, 1013.25,
                   row_time=end + timedelta(seconds=PURGE_SETTLE_SEC), **kw)
    check("settle elapsed: fit runs", r is not None, f"got {r}")
    r = cm.observe("sampling", i0, 25.0, 1013.25, row_time=t0 - timedelta(minutes=5), **kw)
    check("row older than the block (out-of-order catch-up) is not held back", r is not None)
    cm.observe("he_inject", i0, 25.0, 1013.25, row_time=t0 + timedelta(hours=1), **kw)
    r = cm.observe("sampling", i0, 25.0, 1013.25, row_time=t0 + timedelta(hours=1, seconds=30), **kw)
    check("He block also starts a settle window", r is None, f"got {r}")


def test_classify():
    print("[3] _classify — 경보 등급")
    cm = _make_monitor(conc_min_ppb=-20, conc_max_ppb=50, spike_ppb=20,
                       rms_sig_alarm=0.15, flatline_n=3)

    def _res(conc, rms_sig=0.05, perr_rel=0.05, rms=3e-9):
        return dict(conc=conc, rms_sig=rms_sig, perr_rel=perr_rel, rms=rms,
                    conc_all={"NO2": conc})

    status, msg, m = cm._classify(_res(3.5))
    check("정상 범위 → OK", status == OK, f"{status}: {msg}")

    status, msg, m = cm._classify(_res(80.0))
    check("너무 높음 → P1", status == P1, f"{status}: {msg}")

    cm2 = _make_monitor(conc_min_ppb=-20, conc_max_ppb=50, rms_sig_alarm=0.15)
    status, msg, m = cm2._classify(_res(-30.0))
    check("너무 낮음 → P1", status == P1, f"{status}: {msg}")

    cm3 = _make_monitor(rms_sig_alarm=0.15)
    status, msg, m = cm3._classify(_res(3.0, rms_sig=0.30))
    check("rms/sig 높음 → P1", status == P1, f"{status}: {msg}")

    cm4 = _make_monitor(spike_ppb=5.0)
    cm4._classify(_res(3.0))            # 이력에 3.0 심음
    status, msg, m = cm4._classify(_res(30.0))
    check("직전 대비 급변 → P2", status == P2, f"{status}: {msg}")

    cm5 = _make_monitor(flatline_n=3)
    cm5._classify(_res(4.0))
    cm5._classify(_res(4.0))
    status, msg, m = cm5._classify(_res(4.0))
    check("N회 연속 동일값 → 평탄선 P2", status == P2, f"{status}: {msg}")

    # rms_alarm — 저농도 채널용 절대 잔차 문턱(rms_sig는 신호가 작으면 폭발해서 못 씀).
    cm6 = _make_monitor(rms_sig_alarm=None, rms_alarm=5e-8)
    check("rms 정상(3e-9) → OK", cm6._classify(_res(1.0, rms=3e-9))[0] == OK)
    st6, msg6, _ = cm6._classify(_res(1.0, rms=2e-7))
    check("rms 큼(2e-7) → P1", st6 == P1, f"{st6}: {msg6}")
    # 실측 근거: cold 748스캔에서 rms_sig>0.15가 56%에 걸렸고 그 대부분이 저농도(중앙
    # 1.1ppb)였다 — 같은 스캔들이 rms 기준으론 정상으로 남아야 한다.
    cm7 = _make_monitor(rms_sig_alarm=None, rms_alarm=5e-8)
    check("저농도+높은 rms_sig라도 rms 정상이면 OK",
          cm7._classify(_res(0.5, rms_sig=0.67, rms=3.5e-9))[0] == OK)

    status, msg, m = cm5._classify(dict(conc=float("nan"), rms_sig=0.05, perr_rel=0.05,
                                        rms=3e-9, conc_all={}))
    check("농도 NaN → P1", status == P1, f"{status}: {msg}")


def test_fail_streak_to_p0():
    print("[4] 연속 실패 → P0")
    cm = _make_monitor(throttle_sec=0.0)
    bad_i0 = np.zeros(2048)          # I0 <= 0 -> NaN alpha in the window
    bad_spec = np.full(2048, 1.0)
    kw = dict(omr_d=np.full(2048, OMR_D_COLD), rl=RL_COLD)
    r_za = cm.observe("za_inject", bad_i0, 25.0, 1013.25, **kw, row_time=CAL_T)
    r1 = cm.observe("sampling", bad_spec, 25.0, 1013.25, **kw)
    check("1회 실패 → P1", r1[0] == P1, f"got {r1[0]}: {r1[1]}")
    r2 = cm.observe("sampling", bad_spec, 25.0, 1013.25, **kw)
    check("2회 연속 실패 → 아직 P1", r2[0] == P1, f"got {r2[0]}: {r2[1]}")
    r3 = cm.observe("sampling", bad_spec, 25.0, 1013.25, **kw)
    check("3회 연속 실패 → P0", r3[0] == P0, f"got {r3[0]}: {r3[1]}")


# Hot 05-20-003 opens with a He (510) then ZA (500) block in its first 190 rows.
RAW_CANDIDATES = (
    r"C:\GHL\2026 yeosu\RAW\hot\05\2026-05-20-003.dat",
    r"E:\Yeosu_2026\CAESAR_Hot\2026-05\2026-05-20-003.dat",
)


def test_real_raw_end_to_end():
    """[7] Real raw -> RMonitor -> ConcMonitor, same order as VigilApp._tick (R first).
    No synthesis or inversion: instrument counts go straight in. The test that was missing
    when the OD bug shipped."""
    print("[7] real raw end to end (raw -> R -> alpha -> concentration)")
    raw = next((p for p in RAW_CANDIDATES if os.path.isfile(p)), None)
    if raw is None:
        print("  SKIP  raw not local")
        return
    from vigil.monitors.r_monitor import RMonitor
    from vigil.profile import DEFAULT_PROFILE_DIR, ProfileSet

    rows = []
    with open(raw, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            toks = line.rstrip("\n").split("\t")
            if len(toks) < 100:
                continue
            try:
                rows.append([float(t) for t in toks])
            except ValueError:
                continue
            if len(rows) >= 400:
                break
    prof = ProfileSet.load(DEFAULT_PROFILE_DIR).route(raw, len(rows[-1]))
    if prof is None:
        print(f"  SKIP  no profile for ncols={len(rows[-1])}")
        return
    for ch in prof.signal_channels():
        if ch.concentration is None or ch.reflectance is None:
            continue
        cc, rc = ch.concentration, ch.reflectance
        try:
            scen = json.load(open(cc.fitset_path, encoding="utf-8"))
            cfg = dataclasses.replace(cc, throttle_sec=0.0)
            cm = ConcMonitor(pick_fitset_channel(scen, cc.wl_dir), cfg)
            wave = OP.load_wavecal(rc.wavecal_path)
        except Exception as e:                       # noqa: BLE001
            print(f"  SKIP  {ch.id}: FitSet/wavecal not local ({type(e).__name__}: {e})")
            continue
        rm = RMonitor(wave_nm=wave, cavity_len_cm=rc.cavity_len_cm, rl_factor=rc.rl_factor,
                      roi_nm=rc.roi_nm)

        def hk(row, keys):
            return prof.hk.first_valid(row, keys)

        concs, conc_without_r = [], 0
        year = int(os.path.basename(raw)[:4])
        last_cal, min_since_cal = None, float("inf")
        for row in rows:
            role = prof.flag_role(int(row[prof.header.state_flag_col]))
            row_time = prof.header.time_bytepack.to_datetime(row, year)
            if role not in ("sampling", "header", None):
                last_cal = row_time
            spec = ch.slice(row)
            rm.observe(role, spec, hk(row, ch.temp_keys(rc)), hk(row, ch.pressure_keys(rc)))
            had_r = rm.omr_d is not None
            out = cm.observe(role, spec, hk(row, ch.temp_keys(cc)), hk(row, ch.pressure_keys(cc)),
                             omr_d=rm.omr_d, rl=rc.rl_factor, row_time=row_time)
            if out is not None and "conc_ppb" in out[2]:
                concs.append(out[2]["conc_ppb"])
                conc_without_r += 0 if had_r else 1
                min_since_cal = min(min_since_cal, (row_time - last_cal).total_seconds())
            if len(concs) >= 8:
                break
        check(f"{ch.label}: R computed from the raw ZA/He blocks", rm.omr_d is not None)
        check(f"{ch.label}: never a concentration without R", conc_without_r == 0, f"{conc_without_r}")
        check(f"{ch.label}: concentrations produced", bool(concs))
        check(f"{ch.label}: no fit inside the purge-settle window",
              min_since_cal >= PURGE_SETTLE_SEC, f"first fit {min_since_cal:.0f} s after calibration")
        if concs:
            med = float(np.median(concs))
            print(f"  ({ch.label}: {len(concs)} scans, NO2 median {med:.2f} ppb)")
            # OD bug gave 1e6 ppb here.
            check(f"{ch.label}: NO2 median in 0..200 ppb", 0.0 <= med <= 200.0, f"{med:.4g}")


def main():
    if not os.path.isfile(OP.FITSET):
        # 실 FitSet(이 PC 의 Output/)이 있어야 하는 테스트다 — CI·다른 PC 에선 건너뛴다.
        print(f"conc_monitor tests: SKIP — FitSet 없음 ({OP.FITSET})")
        return 0
    for t in (test_pick_fitset_channel, test_gas_policy_source_and_legacy_migration,
              test_i0_buffer_and_fit_and_throttle,
              test_throttle_blocks_immediate_refit, test_classify, test_fail_streak_to_p0,
              test_no_r_yields_skip_not_garbage, test_purge_settle, test_real_raw_end_to_end):
        t()
    print(f"\nconc_monitor tests: {_n_pass} PASS · {_n_fail} FAIL")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
