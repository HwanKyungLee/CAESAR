"""QDOAS 대조의 절대 스케일을 **스캔별 실측 T/P**로 다시 잰다 (2026-09-17).

왜
--
`compare_qdoas_augur.py`는 Augur merge 파일의 ppb를 cm⁻³로 되돌릴 때 **명목**
n_air(T=25 °C, P=1013.25 mbar)를 쓴다. merge 파일에 스캔별 T/P가 없기 때문이다
(`T_used_C`/`P_used_mbar` 열은 `cadf466`, 2026-09-08에 추가됐는데 merge 파일은
2026-07-09 생성 — 두 달 전이라 열이 없다).

그런데 **워커는 명목값을 쓰지 않았다.** `gui/worker.py:492` / `:1037`가 알파 행의
실측 `env_t`/`env_p`를 그대로 쓰고, `gas_temp_override`는 `gas_temp > 0`일 때만
켜지는데 이 런의 헤더는 `gas_temp=0.0°C`라 꺼져 있었다. 즉

    ppb_merge = real_conc / n_air(T_실측, P_실측) × 1e9

이고, 명목 n_air로 되돌리면 그 비율만큼 계통 오차가 남는다:

    slope(SCD/K ÷ realconc_approx) = n_air(실측) / n_air(명목)

여수 실측 샘플(2026-06-14 첫 스캔)만 봐도 무시할 양이 아니다:
    PNs  T=34.87 °C, P=920.51 mbar   → 비 0.879
    ANs  T=37.86 °C, P=965.26 mbar   → 비 0.913
    cold T=26.22 °C, P=1005.94 mbar  → 비 0.989
핫 채널은 P가 920~965 mbar로 대기압보다 한참 낮다(가열·배기된 셀).

**재핏이 필요 없다.** ppb는 이미 있고, T/P는 알파 트레이스에 스캔별로 들어 있으며,
merge의 `File` 열이 `"<알파파일> [<행번호>]"`라 행 단위로 정확히 되짚을 수 있다.

무엇을 답하나
-------------
slope가 1.0에서 벗어난 것이 **알고리즘 불일치인지 단위 환산 근사인지**를 가른다.
정확한 T/P로 1.0에 붙으면 Augur–QDOAS는 절대 스케일까지 일치하는 것이고,
그래도 남으면 그건 진짜 알고리즘 차이다.

사용:  python recompare_exact_tp.py [--alpha-root <경로>]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from core.physics import air_number_density          # noqa: E402  단일 출처
from compare_qdoas_augur import GASES, load_qdoas, N_AIR_NOMINAL   # noqa: E402

DEFAULT_ALPHA_ROOT = r"C:\GHL\2026 yeosu\Output\alpha\10s"

# merge 파일 ↔ 알파 하위경로 ↔ QDOAS 출력 ↔ K
CHANNELS = [
    dict(name="cold", sub="cold", K=1e6,
         augur="augur_fit/cold_merge.dat",
         qdoas="qdoas_output/cold/Analysis_clean.html"),
    dict(name="hot_ans", sub=os.path.join("hot", "ch1"), K=1e7,
         augur="augur_fit/ans_merge.dat",
         qdoas="qdoas_output/hot_ans/hot_ans_boundfix.ASC"),
    dict(name="hot_pns", sub=os.path.join("hot", "ch2"), K=1e7,
         augur="augur_fit/pns_merge.dat",
         qdoas="qdoas_output/hot_PNs/hot_PNs_boundfix.ASC"),
]

_FILE_RE = re.compile(r"^(?P<fname>\S+\.dat)\s*\[(?P<row>\d+)\]\s*$")
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def alpha_tp_table(path):
    """알파 트레이스 한 파일 → [(T_C, P_mbar), …] **데이터행 순서대로**.

    열 배치는 `row_idx  doy  datetime  T_C  P_mbar  px0 …` 이라 앞 5필드만 자르면
    된다. 2048 픽셀을 파싱할 이유가 없다(파일당 수십 MB).

    ⚠ 키는 파일의 `row_idx` **열 값이 아니라 위치**다. 10 s 평균이라 `row_idx`는
    0, 11, 22 …처럼 건너뛰는데(원시 행 번호), `DataIO._load_alpha_trace_row`는
    `data_rows[row_index]`로 **위치** 인덱싱하고 merge 파일의 `[NNNN]`도 그 위치다.
    열 값으로 맞추면 첫 행만 우연히 맞고 나머지가 전부 어긋난다(실측: 7.8 %만 매칭).
    """
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("row_idx"):
                continue
            f = line.split("\t", 5)
            try:
                out.append((float(f[3]), float(f[4])))
            except (ValueError, IndexError):
                out.append((float("nan"), float("nan")))
    return out


def load_augur_exact(merge_path, alpha_root, sub):
    """merge + 스캔별 실측 T/P → 명목/정확 두 가지 real_conc."""
    df = pd.read_csv(merge_path, sep="\t", comment="#", engine="python",
                     )
    df["dt"] = pd.to_datetime(df["Time"], errors="coerce")
    m = df["File"].astype(str).str.extract(_FILE_RE)
    df["_fname"], df["_row"] = m["fname"], pd.to_numeric(m["row"], errors="coerce")

    cache, miss = {}, 0
    T = np.full(len(df), np.nan)
    P = np.full(len(df), np.nan)
    for i, (fname, row) in enumerate(zip(df["_fname"].to_numpy(),
                                         df["_row"].to_numpy())):
        if not isinstance(fname, str) or not np.isfinite(row):
            miss += 1
            continue
        if fname not in cache:
            d = _DATE_RE.match(fname)
            p = (os.path.join(alpha_root, sub, d.group(1), fname) if d else None)
            cache[fname] = alpha_tp_table(p) if (p and os.path.exists(p)) else []
        tbl, r = cache[fname], int(row)
        if not (0 <= r < len(tbl)):
            miss += 1
            continue
        T[i], P[i] = tbl[r]
    df["_T_C"], df["_P_mbar"] = T, P
    ok = np.isfinite(T) & np.isfinite(P)
    n_air_exact = np.full(len(df), np.nan)
    n_air_exact[ok] = air_number_density(T[ok], P[ok])
    df["_n_air_exact"] = n_air_exact
    for g in GASES:
        ppb = pd.to_numeric(df[g], errors="coerce")
        df[f"realconc_nominal_{g}"] = ppb * N_AIR_NOMINAL / 1e9
        df[f"realconc_exact_{g}"] = ppb * n_air_exact / 1e9
    return df, miss


def slope_through_origin(x, y):
    """y = s·x 의 최소제곱 기울기(절편 없음). 절대 스케일 비교라 원점을 지나야 한다."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    den = float(x @ x)
    return (float(x @ y) / den) if den > 0 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha-root", default=DEFAULT_ALPHA_ROOT)
    args = ap.parse_args()

    rows = []
    for ch in CHANNELS:
        ap_ = os.path.join(HERE, ch["augur"])
        qp_ = os.path.join(HERE, ch["qdoas"])
        if not (os.path.exists(ap_) and os.path.exists(qp_)):
            print(f"[{ch['name']}] SKIP — 입력 없음")
            continue
        print(f"\n{'='*72}\n{ch['name']}\n{'='*72}")
        a, miss = load_augur_exact(ap_, args.alpha_root, ch["sub"])
        q = load_qdoas(qp_, ch["K"])
        got = int(np.isfinite(a["_n_air_exact"]).sum())
        print(f"  Augur {len(a)}행 중 실측 T/P 복원 {got}행 ({100.0*got/len(a):.1f} %), 실패 {miss}")
        if got == 0:
            print("  → 알파 트레이스를 못 찾았다. --alpha-root 확인.")
            continue
        print(f"  T_C  중앙값 {np.nanmedian(a['_T_C']):.2f}  "
              f"P_mbar 중앙값 {np.nanmedian(a['_P_mbar']):.2f}")
        print(f"  n_air 실측/명목 중앙값 = "
              f"{np.nanmedian(a['_n_air_exact'])/N_AIR_NOMINAL:.4f}")

        mg = pd.merge(q[["dt"] + [f"alpha_qdoas_{g}" for g in GASES]],
                      a[["dt"] + [f"realconc_{k}_{g}" for g in GASES
                                  for k in ("nominal", "exact")]],
                      on="dt", how="inner")
        print(f"  타임스탬프 매칭 {len(mg)}건")
        for g in GASES:
            qv = mg[f"alpha_qdoas_{g}"].to_numpy(float)
            nom = mg[f"realconc_nominal_{g}"].to_numpy(float)
            exa = mg[f"realconc_exact_{g}"].to_numpy(float)
            # 두 slope는 **반드시 같은 행 집합**에서 재야 한다. 실측 T/P를 못 찾은
            # 행이 섞이면 근사 개선이 아니라 표본 차이를 보게 된다.
            m = np.isfinite(qv) & np.isfinite(nom) & np.isfinite(exa)
            n_used = int(m.sum())
            if n_used < 100:
                print(f"    {g:7s} SKIP — 공통 표본 {n_used}행")
                continue
            s_nom = slope_through_origin(nom[m], qv[m])
            s_exa = slope_through_origin(exa[m], qv[m])
            r = float(pd.Series(qv[m]).corr(pd.Series(exa[m])))
            # 역변환이 맞는지 **내부 검증**: 명목 n_air는 스캔별 T/P 변동을 무시하므로
            # 그만큼 산포가 남아야 한다. 실측 T/P로 바꿔 산포가 줄면 매핑이 맞은 것이고,
            # 늘면 행 매핑이 틀린 것이다(그때는 slope 개선도 믿으면 안 된다).
            sd_nom = float(np.std(qv[m] - s_nom * nom[m], ddof=1)) / float(np.std(qv[m], ddof=1))
            sd_exa = float(np.std(qv[m] - s_exa * exa[m], ddof=1)) / float(np.std(qv[m], ddof=1))
            print(f"    {g:7s} n={n_used}  r={r:+.4f}   "
                  f"slope 명목={s_nom:.4f} → **실측 T/P={s_exa:.4f}**"
                  f"   (1.0에서 {abs(s_nom-1)*100:.1f}% → {abs(s_exa-1)*100:.1f}%)"
                  f"   잔차산포 {sd_nom:.4f} → {sd_exa:.4f}")
            rows.append(dict(channel=ch["name"], gas=g, n=n_used, r=r,
                             resid_sd_nominal=sd_nom, resid_sd_exact=sd_exa,
                             slope_nominal_tp=s_nom, slope_exact_tp=s_exa,
                             T_C_median=float(np.nanmedian(a["_T_C"])),
                             P_mbar_median=float(np.nanmedian(a["_P_mbar"]))))
    if rows:
        out = os.path.join(HERE, "recompare_exact_tp_summary.csv")
        pd.DataFrame(rows).to_csv(out, index=False)
        print(f"\n요약 -> {out}")


if __name__ == "__main__":
    main()
