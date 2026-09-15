"""QDOAS 교차검증 — 일치도 통계 보강 (2026-09-14).

기존 `compare_qdoas_augur.py`는 `r²`와 OLS `slope`를 냈다. 그런데 **상관은 일치가
아니다** — 이 대조표 자체가 증거다(Cold CHOCHO r²=0.861인데 slope 0.685 = 31% 차이).

이 스크립트는 같은 데이터에 `core.agreement`로 다음을 추가한다:

  1. **Bland-Altman** — 평균 편향 · 일치한계 · 비례 편향(농도 의존성)
  2. **Deming 회귀** — OLS는 x축 오차로 기울기가 0쪽으로 감쇠한다. 두 방법 다
     불확도가 있으므로 OLS slope는 구조적으로 1에서 멀어진다.
  3. **유효 표본수 + 블록 부트스트랩 CI** — 60초 빈 시계열은 독립이 아니다.
  4. **QC 서브셋 편향 점검** — 기존 비교는 `Status=="OK"` 행만 썼다.

주의 — 두 가지를 일부러 자체 구현했다(기존 스크립트를 임포트하지 않는다):

  · `compare_qdoas_augur.py` / `compare_hot_ans_negshift.py`는 모듈 레벨에서 바로
    실행되는 코드라(임포트 = 전체 실행) 라이브러리로 재사용할 수 없다. 두 스크립트의
    절대경로는 2026-09-15에 폴더 기준으로 고쳤지만, 구조는 그대로라 여전히 임포트 금지.
  · QDOAS 출력은 **파일마다 컬럼 구성이 다르다**. 일반 출력은 8열, `*_negshift.ASC`는
    Chi/RMS/Shift/Stretch가 더 붙은 17열이다. 로더를 잘못 고르면 **조용히 엉뚱한 열을
    집는다** — 실제로 그렇게 읽었더니 Hot ANs CHOCHO r²=0.007이 나왔다(정답 0.960).
    그래서 **열 수로 포맷을 자동 판별**한다. 사람이 고르지 않으면 틀릴 수 없다.

    python diagnostics/qdoas_crossval_2026-09/agreement_report.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from core.agreement import compare, format_compare
from core.physics import air_number_density

GASES = ["CHOCHO", "H2O", "NO2"]

# Augur ppb -> cm^-3 역환산용 명목 조건(스캔별 T/P가 병합파일에 없어 근사).
# 원 비교 스크립트와 같은 가정이며, 상수는 core 단일 출처를 쓴다.
T_NOMINAL_C, P_NOMINAL_MBAR = 25.0, 1013.25
N_AIR_NOMINAL = air_number_density(T_NOMINAL_C, P_NOMINAL_MBAR)

# QDOAS ASCII 컬럼 레이아웃 — 열 수로 구분한다.
#    8열 : compare_qdoas_augur.py 가 쓰던 일반 출력
#   17열 : compare_hot_ans_negshift.py 가 쓰던 부호교정판(진단열 포함)
_LAYOUTS = {
    8: ["dt_raw", "spec_no", "CHOCHO_SlCol", "CHOCHO_SlErr",
        "H2O_SlCol", "H2O_SlErr", "NO2_SlCol", "NO2_SlErr"],
    17: ["dt_raw", "spec_no", "Chi", "RMS", "Ref2Ref1Shift",
         "CHOCHO_SlCol", "CHOCHO_SlErr", "Shift_CHOCHO", "ErrShift",
         "Stretch1", "Stretch2", "ErrStretch1", "ErrStretch2",
         "H2O_SlCol", "H2O_SlErr", "NO2_SlCol", "NO2_SlErr"],
}


def load_qdoas_any(path, K):
    """QDOAS ASCII -> alpha(=SCD/K). **열 수로 레이아웃을 판별**한다."""
    df = pd.read_csv(path, sep="\t", skiprows=2, header=None, engine="python")
    df = df.dropna(axis=1, how="all")
    ncol_raw = int(df.shape[1])
    layout = _LAYOUTS.get(ncol_raw)
    if layout is None:
        raise ValueError(f"{os.path.basename(path)}: 모르는 컬럼 수 {df.shape[1]} "
                         f"(아는 것: {sorted(_LAYOUTS)}) — 레이아웃 확인 후 등록할 것")
    df.columns = layout
    df["dt"] = pd.to_datetime(df["dt_raw"].astype(str).str.strip(), format="%Y%m%d%H%M%S")
    for g in GASES:
        df[f"alpha_qdoas_{g}"] = pd.to_numeric(df[f"{g}_SlCol"], errors="coerce") / K
    return df, ncol_raw          # 원본 열 수(파생열 추가 전)


def load_augur(path):
    df = pd.read_csv(path, sep="\t", comment="#", engine="python")
    df["dt"] = pd.to_datetime(df["Time"])
    for g in GASES:
        df[f"realconc_augur_{g}"] = pd.to_numeric(df[g], errors="coerce") * N_AIR_NOMINAL / 1e9
    return df


CHANNELS = [   # (라벨, QDOAS 출력, Augur 병합결과, K) — README의 최종 확정 조합
    ("Cold",    "qdoas_output/cold/Analysis_clean.html",     "augur_fit/cold_merge.dat", 1e6),
    ("Hot PNs", "qdoas_output/hot_PNs/hot_PNs.ASC",          "augur_fit/pns_merge.dat",  1e7),
    ("Hot ANs", "qdoas_output/hot_ans/hot_ans_negshift.ASC", "augur_fit/ans_merge.dat",  1e7),
]


def run():
    print("QDOAS 교차검증 — 일치도 통계 (Bland-Altman · Deming · 블록 부트스트랩)")
    print("x = Augur realconc, y = QDOAS SCD/K  (둘 다 cm^-3, 같은 물리량)")
    print("=" * 96)
    for name, qrel, arel, K in CHANNELS:
        qp, ap = os.path.join(HERE, qrel), os.path.join(HERE, arel)
        if not (os.path.exists(qp) and os.path.exists(ap)):
            print(f"\n[{name}] 입력 없음 — 건너뜀")
            continue
        try:
            q, ncol = load_qdoas_any(qp, K)
            a = load_augur(ap)
            m = pd.merge(q[["dt"] + [f"alpha_qdoas_{g}" for g in GASES]],
                         a[["dt", "Status"] + [f"realconc_augur_{g}" for g in GASES]],
                         on="dt", how="inner")
        except Exception as e:                       # noqa: BLE001
            print(f"\n[{name}] 로드 실패: {e}")
            continue

        ok = m["Status"].astype(str).str.strip() == "OK"
        print(f"\n{'=' * 96}\n{name}   병합 {len(m):,}행  (Status==OK {int(ok.sum()):,}행"
              f" = {100 * ok.mean():.1f}%)   QDOAS 레이아웃 {ncol}열\n{'=' * 96}")

        for g in GASES:
            x = m.loc[ok, f"realconc_augur_{g}"].to_numpy(float)
            y = m.loc[ok, f"alpha_qdoas_{g}"].to_numpy(float)
            if np.isfinite(x).sum() < 50:
                print(f"\n[{name} {g}] 유효 표본 부족 — 건너뜀")
                continue
            r = compare(x, y, name=f"{name} {g} (Status==OK)", relative=False)
            print()
            print(format_compare(r, unit="cm^-3"))

            xa = m[f"realconc_augur_{g}"].to_numpy(float)
            ya = m[f"alpha_qdoas_{g}"].to_numpy(float)
            n_ok = int(np.isfinite(x).sum())
            if int(np.isfinite(xa).sum()) > n_ok:
                ra = compare(xa, ya, name="전체", relative=False, boot=False)
                d = ra["deming_slope"] - r["deming_slope"]
                print(f"  [QC 편향 점검] 전체 행 n={ra['n']:,}: r²={ra['r2']:.4f} "
                      f"Deming slope={ra['deming_slope']:.4f} (OK만 대비 {d:+.4f})")
                if abs(d) > 0.05:
                    print("     경고: QC 필터가 일치도를 유의하게 바꾼다 — 두 값 다 보고할 것")
            else:
                print("  [QC 편향 점검] 제외행에 유효값이 없어 비교 불가"
                      " (QC 행은 농도가 NaN이라 애초에 빠진다)")

    print("\n" + "=" * 96)
    print("읽는 법")
    print("  · r²는 '같이 오르내리는가'다. '같은 값인가'는 Bland-Altman 편향과 Deming slope가 답한다.")
    print("  · OLS와 Deming이 다르면 그 차이가 감쇠(x축 오차) 몫이다.")
    print("  · 유효 n이 n보다 훨씬 작으면 n 기반 CI/p값은 쓰면 안 된다.")
    print("  · 비례 편향 기울기가 0에서 멀면 '평균 편향' 한 숫자로 요약하면 안 된다.")
    print("  · Deming CI가 1.0을 **포함하지 않으면** 그 차이는 통계적으로 실재한다.")


if __name__ == "__main__":
    run()
