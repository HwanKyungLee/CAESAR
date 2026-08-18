"""tools/bundle_oculus_deps.py — Oculus를 Python 없는 컴퓨터에 USB로 옮길 때 필요한
FitSet 의존 파일(웨이브캘·레퍼런스 스펙트럼)을 한 폴더로 모은다.

Oculus는 레퍼런스·웨이브캘을 자체 생성하지 않고 Augur가 만든 FitSet json을 그대로 읽는다
(oculus/monitors/conc_monitor.py, oculus/profile.py:ConcentrationConfig — 단일 출처 원칙).
문제는 그 FitSet json이 가리키는 wl_path/refs[].path, 그리고 프로파일 json 자체의
reflectance.wavecal_path가 전부 이 개발 컴퓨터의 절대경로라, 그대로 복사하면 대상
컴퓨터에서 파일을 못 찾는다. 이 스크립트는 프로파일 json → (FitSet json →) 실물 파일을
따라가며 한 폴더로 모아 복사하고, 복사본 안의 경로를 --base-dir(대상 컴퓨터에 이 폴더를
놓을 위치) 기준 절대경로로 다시 쓴다.

사용:
    python tools/bundle_oculus_deps.py oculus/profiles/caesar_cold.example.json ^
        --out dist/oculus_deps --base-dir "D:/Oculus"

    # 여러 프로파일(냉/열) 동시에 — FitSet/레퍼런스가 겹치면 한 번만 복사됨
    python tools/bundle_oculus_deps.py oculus/profiles/*.json --out dist/oculus_deps --base-dir D:/Oculus

그 다음 dist/oculus_deps 폴더 전체를 --base-dir로 지정한 그 경로에 그대로 복사하면 된다
(경로가 다르면 --base-dir를 실제 위치로 다시 지정해 재실행 — 복사만 다시 하면 됨, 원본은
안 건드림).

자체 검증: python tools/bundle_oculus_deps.py --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys


def _resolve(path: str, ref_dir: str) -> str | None:
    """path가 상대경로면 그걸 담고 있던 json 파일의 디렉터리(ref_dir) 기준으로 푼다.
    Oculus 런타임은 이런 경로를 CWD 기준으로 그대로 열기 때문에(참고: 원본에도 상대경로가
    섞여 있음), 여기선 "그 json 근처에 있겠거니" 가정하고 최선을 다해 찾는다 — 못 찾으면
    None(호출 쪽에서 missing으로 보고)."""
    if not path:
        return None
    if os.path.isabs(path):
        return path if os.path.exists(path) else None
    candidate = os.path.normpath(os.path.join(ref_dir, path))
    return candidate if os.path.exists(candidate) else None


def _dest_rel(src: str, seen: dict) -> str:
    """wv_cal/ 아래 목적지 상대경로. 부모폴더명+파일명으로 roi1/roi2/cold 같은 원본
    구조를 보존해 동명 레퍼런스 파일(Ref_CHOCHO_...dat가 채널마다 있음) 충돌을 피한다.
    그래도 다른 원본이 같은 이름으로 충돌하면 해시 접미사를 붙인다."""
    rel = os.path.join(os.path.basename(os.path.dirname(src)), os.path.basename(src))
    rel = rel.replace(os.sep, "/")
    prev = seen.get(rel)
    if prev is not None and prev != src:
        digest = hashlib.sha1(src.encode("utf-8")).hexdigest()[:8]
        base, ext = os.path.splitext(rel)
        rel = f"{base}_{digest}{ext}"
    seen[rel] = src
    return rel


def _copy_into(src: str, out_dir: str, base_dir: str, seen: dict, missing: list) -> str | None:
    """src를 out_dir/wv_cal/<rel>로 복사하고, base_dir 기준 절대경로(문자열)를 돌려준다."""
    if src is None:
        missing.append(src)
        return None
    rel = _dest_rel(src, seen)
    dest = os.path.join(out_dir, "wv_cal", rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src, dest)
    return f"{base_dir.rstrip('/')}/wv_cal/{rel}"


def bundle(profile_paths: list[str], out_dir: str, base_dir: str) -> dict:
    """반환: {'copied': n, 'missing': [원본경로,...]} — 요약용."""
    os.makedirs(os.path.join(out_dir, "profiles"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "fit_setting"), exist_ok=True)
    seen_files: dict = {}
    seen_fitsets: dict = {}   # fitset_path(원본) -> base_dir 기준 새 경로
    missing: list = []
    copied = 0

    def copy_file(src):
        nonlocal copied
        r = _copy_into(src, out_dir, base_dir, seen_files, missing)
        if r is not None:
            copied += 1
        return r

    def bundle_fitset(fitset_path: str, ref_dir: str) -> str | None:
        resolved = _resolve(fitset_path, ref_dir)
        if resolved is None:
            missing.append(fitset_path)
            return None
        if resolved in seen_fitsets:
            return seen_fitsets[resolved]
        scen = json.load(open(resolved, encoding="utf-8"))
        fitset_dir = os.path.dirname(resolved)
        for ch in scen.get("channels", {}).values():
            wl = _resolve(ch.get("wl_path", ""), fitset_dir)
            new_wl = copy_file(wl) if wl else (missing.append(ch.get("wl_path")) or None) \
                if ch.get("wl_path") else None
            if wl:
                ch["wl_path"] = new_wl
            for ref in ch.get("refs", []):
                p = ref.get("path", "")
                if not p:
                    continue
                rp = _resolve(p, fitset_dir)
                new_p = copy_file(rp) if rp else (missing.append(p) or None)
                if rp:
                    ref["path"] = new_p
        fname = os.path.basename(resolved)
        dest = os.path.join(out_dir, "fit_setting", fname)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(scen, f, ensure_ascii=False, indent=1)
        new_path = f"{base_dir.rstrip('/')}/fit_setting/{fname}"
        seen_fitsets[resolved] = new_path
        return new_path

    for prof_path in profile_paths:
        prof = json.load(open(prof_path, encoding="utf-8"))
        ref_dir = os.path.dirname(os.path.abspath(prof_path))
        for ch in prof.get("channels", []):
            refl = ch.get("reflectance")
            if refl and refl.get("wavecal_path"):
                wl = _resolve(refl["wavecal_path"], ref_dir)
                new_wl = copy_file(wl) if wl else (missing.append(refl["wavecal_path"]) or None)
                if wl:
                    refl["wavecal_path"] = new_wl
            conc = ch.get("concentration")
            if conc and conc.get("fitset_path"):
                new_fp = bundle_fitset(conc["fitset_path"], ref_dir)
                if new_fp:
                    conc["fitset_path"] = new_fp
        dest = os.path.join(out_dir, "profiles", os.path.basename(prof_path))
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(prof, f, ensure_ascii=False, indent=1)

    return {"copied": copied, "missing": [m for m in missing if m]}


def _selftest():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        roi1 = os.path.join(src, "wv_cal", "roi1")
        os.makedirs(roi1)
        open(os.path.join(roi1, "Calib.txt"), "w").write("wavecal")
        open(os.path.join(roi1, "Ref_NO2.dat"), "w").write("ref")

        fitset = {
            "channels": {
                "1": {
                    "wl_path": os.path.join(roi1, "Calib.txt").replace("\\", "/"),
                    "refs": [{"name": "NO2", "path": os.path.join(roi1, "Ref_NO2.dat").replace("\\", "/")},
                             {"name": "MISSING", "path": os.path.join(roi1, "nope.dat").replace("\\", "/")}],
                }
            }
        }
        fitset_path = os.path.join(src, "FitSet_test.json")
        json.dump(fitset, open(fitset_path, "w"))

        profile = {
            "channels": [
                {"id": "ch1",
                 "reflectance": {"wavecal_path": os.path.join(roi1, "Calib.txt").replace("\\", "/")},
                 "concentration": {"fitset_path": fitset_path.replace("\\", "/"), "wl_dir": "roi1"}}
            ]
        }
        profile_path = os.path.join(src, "profile_test.json")
        json.dump(profile, open(profile_path, "w"))

        out = os.path.join(tmp, "out")
        result = bundle([profile_path], out, "D:/Oculus")

        assert result["copied"] == 3, result           # Calib.txt (x2 uses, 1 copy) + Ref_NO2.dat
        assert result["missing"] == [os.path.join(roi1, "nope.dat").replace("\\", "/")], result

        new_prof = json.load(open(os.path.join(out, "profiles", "profile_test.json")))
        assert new_prof["channels"][0]["reflectance"]["wavecal_path"] == "D:/Oculus/wv_cal/roi1/Calib.txt"
        new_fitset_path = new_prof["channels"][0]["concentration"]["fitset_path"]
        assert new_fitset_path == "D:/Oculus/fit_setting/FitSet_test.json"

        new_fitset = json.load(open(os.path.join(out, "fit_setting", "FitSet_test.json")))
        ch1 = new_fitset["channels"]["1"]
        assert ch1["wl_path"] == "D:/Oculus/wv_cal/roi1/Calib.txt"
        assert ch1["refs"][0]["path"] == "D:/Oculus/wv_cal/roi1/Ref_NO2.dat"
        assert ch1["refs"][1]["path"] == os.path.join(roi1, "nope.dat").replace("\\", "/")  # 못 찾으면 원본 유지

        assert os.path.exists(os.path.join(out, "wv_cal", "roi1", "Calib.txt"))
        assert os.path.exists(os.path.join(out, "wv_cal", "roi1", "Ref_NO2.dat"))

    print("selftest OK")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp949 콘솔에서 — 등 깨지는 것 방지
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profiles", nargs="*", help="oculus/profiles/*.json (실제 사용할 프로파일)")
    ap.add_argument("--out", help="번들을 생성할 로컬 폴더")
    ap.add_argument("--base-dir", help="대상 컴퓨터에서 이 번들 폴더가 놓일 절대경로 "
                                        "(기본: --out의 절대경로 — 같은 경로에 그대로 옮길 거면 생략 가능)")
    ap.add_argument("--selftest", action="store_true", help="자체 검증만 돌리고 종료")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if not args.profiles or not args.out:
        ap.error("profiles와 --out은 --selftest가 아니면 필수")

    base_dir = args.base_dir or os.path.abspath(args.out).replace("\\", "/")
    result = bundle(args.profiles, args.out, base_dir)
    print(f"복사: {result['copied']}개 파일 → {args.out}")
    if result["missing"]:
        print(f"⚠ 못 찾은 파일 {len(result['missing'])}개 (경로 확인 필요):")
        for m in result["missing"]:
            print(f"  - {m}")
    else:
        print("빠진 파일 없음.")
    print(f"\n대상 컴퓨터에 이 폴더 전체를 정확히 '{base_dir}' 위치로 복사하세요.")
    print("(다른 위치라면 --base-dir를 그 경로로 바꿔 재실행 — 원본 파일은 안 건드립니다.)")


if __name__ == "__main__":
    main()
