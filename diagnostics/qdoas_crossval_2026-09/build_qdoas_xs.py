"""AUGUR 레퍼런스 단면적(Ref_*_Dynamic-ILS-Applied.dat, 픽셀 도메인 단일컬럼) +
파장보정(Calib_*_Poly2.txt, 픽셀 도메인 단일컬럼) -> QDOAS Molecules 패널이 읽을 수 있는
2컬럼(파장 nm, 단면적 cm^2/molecule) ASCII .xs 파일로 변환한다.

배경: Ref_*.dat는 이미 기기 슬릿함수(Dynamic ILS)로 컨볼루션되고 기기 픽셀 그리드에
얹힌 값이라, QDOAS에 다시 컨볼루션시키면 이중 컨볼루션이 된다. 그래서 QDOAS
Molecules 패널에서 이 파일들은 "convolution: None"(이미 컨볼루션됨)으로 등록해야
한다 -- 이건 QDOAS 설치 후 GUI에서 사용자가 직접 확인/설정할 부분이다.

파일 규격(둘 다 헤더 없는/주석만 있는 단일컬럼, 같은 길이=같은 픽셀그리드):
  Calib_*_Poly2.txt : 줄 번호(1-based)=픽셀, 값=파장(nm)
  Ref_<GAS>_Dynamic-ILS-Applied.dat : "#"로 시작하는 헤더 3줄 + 줄번호=픽셀, 값=단면적

사용:
  python build_qdoas_xs.py --calib <Calib_....txt> --ref-dir <wv_cal/<채널>> --out <출력폴더>
  (--ref-dir 안의 Ref_*.dat 전부를 찾아 각각 변환. 개별 파일 하나만 하려면 --ref 사용)

출력: <out>/<GAS>_augur-conv.xs  (2컬럼, 파장 오름차순 -- QDOAS 요구사항)
"""
import argparse, glob, os, re
import numpy as np


def convert_one(calib_wl: np.ndarray, ref_path: str, out_dir: str) -> str:
    xs = np.loadtxt(ref_path, comments="#")
    if xs.shape[0] != calib_wl.shape[0]:
        raise SystemExit(
            f"{ref_path}: 단면적 {xs.shape[0]}행 vs 파장보정 {calib_wl.shape[0]}행 -- "
            f"같은 채널(픽셀 그리드)의 Calib/Ref 파일인지 확인하세요.")
    m = re.search(r"Ref_(.+?)_Dynamic-ILS-Applied", os.path.basename(ref_path))
    gas_full = m.group(1) if m else os.path.splitext(os.path.basename(ref_path))[0]
    # QDOAS는 "파일명이 기체 심볼로 시작 + 밑줄"을 요구한다. Augur의 REF_PROPS/시나리오는
    # 기체 라벨(예: "H2O")과 실제 레퍼런스 데이터셋 이름(예: "H2O-HITRAN")을 분리해 쓰므로,
    # "-"가 있으면 그 앞부분을 QDOAS 심볼로 쓴다 (H2O-HITRAN -> 심볼 H2O).
    symbol = gas_full.split("-")[0]

    order = np.argsort(calib_wl)  # 이미 오름차순이면 no-op, 방어적으로 항상 정렬
    wl_sorted = calib_wl[order]
    xs_sorted = xs[order]

    os.makedirs(out_dir, exist_ok=True)
    stem = symbol if symbol == gas_full else f"{symbol}_{gas_full}"
    out_path = os.path.join(out_dir, f"{stem}_augur-conv.xs")
    np.savetxt(out_path, np.column_stack([wl_sorted, xs_sorted]), fmt="%.6f\t%.6e")
    print(f"  {os.path.basename(ref_path)} ({symbol}) -> {out_path}  "
          f"[{wl_sorted[0]:.3f}-{wl_sorted[-1]:.3f} nm, {len(wl_sorted)}pt]")
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calib", required=True, help="Calib_*_Poly2.txt (픽셀->파장, 단일컬럼)")
    ap.add_argument("--ref-dir", help="Ref_*_Dynamic-ILS-Applied.dat들이 있는 폴더 (전부 변환)")
    ap.add_argument("--ref", action="append", help="개별 Ref_*.dat 파일 (여러 번 지정 가능)")
    ap.add_argument("--out", required=True, help="출력 폴더")
    args = ap.parse_args()

    calib_wl = np.loadtxt(args.calib)
    print(f"calib: {args.calib} -> {len(calib_wl)}px, {calib_wl[0]:.3f}-{calib_wl[-1]:.3f} nm")

    refs = list(args.ref or [])
    if args.ref_dir:
        refs += sorted(glob.glob(os.path.join(args.ref_dir, "Ref_*_Dynamic-ILS-Applied.dat")))
    if not refs:
        raise SystemExit("변환할 Ref_*.dat가 없습니다 (--ref-dir 또는 --ref 지정).")

    for r in refs:
        convert_one(calib_wl, r, args.out)


if __name__ == "__main__":
    main()
