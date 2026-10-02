# -*- coding: utf-8 -*-
"""core/mission_package.py — 미션 패키지: FitSet 하나 + 그 기간의 채널 정체를 **자기완결 폴더**로.

왜: Augur 의 FitSet 은 레퍼런스·wavecal 을 만든 PC 의 **절대경로**로 가리킨다. 측정 PC(인터넷 없음, USB)
에 그대로 옮기면 파일을 못 찾는다. 그리고 FitSet 은 "어느 raw 의 어느 블록이 어느 셀인가"를 모른다
(채널 키는 Augur 탭 번호, `data_label` 은 뒤바뀐 이력이 있다). 그래서 내보낼 때 그 연결을 **사람이 한 번
확정**하고, 필요한 파일을 전부 복사해 패키지 안 **상대경로**로 묶는다 — USB 어디에 두든 열린다.

    <패키지>/
      manifest.json           형식·만든 때·Augur 판·원본 FitSet·파일별 sha1·미션 출처 문자열
      fitset.json             FitSet 사본 — wl_path·refs[].path 가 패키지 상대경로
      wavecal/<wl_dir>/…      wavecal 사본(폴더 이름 = 원래 wl_dir — Vigil 이 그 이름으로 채널을 고른다)
      refs/<채널 키>/…        레퍼런스 사본(채널마다 — 이름이 같아도 내용이 다른 경우가 있다)
      base_*.json             바탕 기본(구조) 프로파일 사본(미션은 이걸로 합쳐진다 — PC 마다 같은 구조)
      mission_<base>.json     미션(셀 정체·센서·FitSet 채널·날짜) — 경로는 패키지 상대

설치: `install_package` 가 폴더째 미션 루트(Augur `vigil/profiles/missions/`, Vigil 은 상태 폴더의
`missions/`)로 복사한다. 원본은 건드리지 않고(무결성 헌장), 같은 이름의 다른 패키지는 지우지 않고
옆으로 옮긴다. 프로파일 로더(core.profile)가 그 아래 미션을 기본 프로파일과 함께 읽는다.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone

FORMAT = "caesar-mission-package"
VERSION = 1
MANIFEST = "manifest.json"
FITSET = "fitset.json"


def missions_root(profile_dir: str | None = None) -> str:
    """Augur 쪽 미션 설치 위치 — 프로파일 폴더 아래 `missions/`(프로그램 폴더째 USB 로 옮기면 같이 간다)."""
    if profile_dir is None:
        from core.profile import DEFAULT_PROFILE_DIR
        profile_dir = DEFAULT_PROFILE_DIR
    return os.path.join(profile_dir, "missions")


def _sha1(path: str) -> str:
    """줄바꿈을 맞춘 텍스트는 CRLF/LF 무관 — 바이너리(npz 등)는 그대로."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if b"\0" not in raw[:4096]:
        raw = raw.replace(b"\r\n", b"\n")
    return hashlib.sha1(raw).hexdigest()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_") or "x"


def wl_dir_of(wl_path: str) -> str:
    """wavecal 경로의 바로 위 폴더 이름(roi1·roi2·cold …) — FitSet 채널을 고르는 토큰."""
    parts = [p for p in re.split(r"[\\/]+", str(wl_path or "")) if p]
    return parts[-2] if len(parts) >= 2 else ""


def resolve(path, base_dir):
    """상대경로면 base_dir 기준 절대경로로(절대경로·빈 값은 그대로)."""
    if not path or os.path.isabs(str(path)) or re.match(r"^[A-Za-z]:[\\/]", str(path)):
        return path
    return os.path.normpath(os.path.join(base_dir, str(path)))


def absolutize_fitset(scen: dict, fitset_dir: str) -> dict:
    """FitSet 안의 상대경로(wl_path·refs[].path)를 fitset_dir 기준으로 푼 사본."""
    out = copy.deepcopy(scen)
    for ch in (out.get("channels") or {}).values():
        if ch.get("wl_path"):
            ch["wl_path"] = resolve(ch["wl_path"], fitset_dir)
        for r in ch.get("refs") or []:
            if isinstance(r, dict) and r.get("path"):
                r["path"] = resolve(r["path"], fitset_dir)
    return out


def absolutize_profile_dict(d: dict, profile_dir: str) -> dict:
    """프로파일(미션) dict 안의 상대경로(concentration.fitset_path·reflectance.wavecal_path)를 푼 사본."""
    out = copy.deepcopy(d)
    for ch in out.get("channels") or []:
        c = ch.get("concentration")
        if isinstance(c, dict) and c.get("fitset_path"):
            c["fitset_path"] = resolve(c["fitset_path"], profile_dir)
        r = ch.get("reflectance")
        if isinstance(r, dict) and r.get("wavecal_path"):
            r["wavecal_path"] = resolve(r["wavecal_path"], profile_dir)
    return out


# ── 블록 확인(사람이 정체를 판단할 근거) ─────────────────────────────────────────
def block_check(raw_path: str, block_start: int, wl_path: str | None = None,
                fit_window_nm=None, max_rows: int = 200) -> dict:
    """raw 한 파일에서 블록 하나의 밝기 — 정체 판단과 '핏 창이 빛 들어오는 구간 안인가' 검사용.

    반환: {'n_rows', 'max', 'lit'(≥5000, data_io 와 같은 문턱), 'peak_px', 'halfmax_px'(lo,hi),
          'median' (np.ndarray, 대기 측정 행 중앙값 스펙트럼), 그리고 wl_path 가 있으면 'peak_nm',
          'halfmax_nm', fit_window_nm 이 있으면 'window_inside'(창 양끝이 반치 구간 안)}."""
    import numpy as np
    from core.raw_parser import CH_PIXELS, COL_FLAG, FLAG_AMBIENT
    rows = []
    with open(raw_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            t = line.rstrip("\n").split("\t")
            if len(t) < block_start + CH_PIXELS:
                continue
            try:
                if int(float(t[COL_FLAG])) != FLAG_AMBIENT:
                    continue
                rows.append([float(x) for x in t[block_start:block_start + CH_PIXELS]])
            except ValueError:
                continue
            if len(rows) >= max_rows:
                break
    out = {"n_rows": len(rows)}
    if not rows:
        return out
    med = np.median(np.asarray(rows), axis=0)
    pk = int(np.argmax(med))
    half = med > (med.min() + (med.max() - med.min()) / 2.0)
    idx = np.flatnonzero(half)
    out.update(median=med, max=float(med.max()), lit=bool(med.max() >= 5000.0), peak_px=pk,
               halfmax_px=(int(idx[0]), int(idx[-1])) if idx.size else None)
    if wl_path and os.path.exists(wl_path):
        try:
            from tools.optimize_params import load_wavecal
            wave = np.asarray(load_wavecal(wl_path), float).ravel()
            if wave.size >= CH_PIXELS:
                out["peak_nm"] = float(wave[pk])
                if out["halfmax_px"]:
                    lo, hi = out["halfmax_px"]
                    out["halfmax_nm"] = (float(wave[lo]), float(wave[hi]))
                    if fit_window_nm:
                        a, b = sorted(float(v) for v in fit_window_nm)
                        out["window_inside"] = bool(out["halfmax_nm"][0] <= a and b <= out["halfmax_nm"][1])
        except Exception as e:                    # noqa: BLE001 — 검사 실패가 내보내기를 막지 않는다
            out["wavecal_error"] = f"{type(e).__name__}: {e}"
    return out


# ── 만들기 ───────────────────────────────────────────────────────────────────
def build_package(out_dir: str, fitset_path: str, missions: list, *, name: str,
                  profile_dir: str | None = None, created_by: str = "") -> dict:
    """미션 패키지 폴더를 만든다(out_dir 은 비어 있거나 없어야 한다) → manifest dict.

    missions: [{'base': 기본 id, 'profile_id', 'profile_version'(기본 1.0.0), 'description',
                'campaign', 'date_range': [lo, hi],
                'channels': [{'block': 'ch1', 'label': 'ANs', 'fitset_channel': '1',
                              'cavity': {'pressure_hk': [...], 'temperature_hk': [...]},
                              'concentration': {...추가 설정(target·alert…)} | None(농도 안 함),
                              'reflectance': {...추가 설정(roi_nm·alert…)} | None(R 안 함)}]}]
    FitSet 채널의 wavecal·레퍼런스를 복사하고, 미션의 concentration.fitset_path·wl_dir·fitset_channel,
    reflectance.wavecal_path 를 패키지 상대경로로 채운다. 원본은 읽기만 한다."""
    from core.profile import DEFAULT_PROFILE_DIR, load_profiles, merge_mission, validate_profile_dict
    profile_dir = profile_dir or DEFAULT_PROFILE_DIR
    if os.path.exists(out_dir) and os.listdir(out_dir):
        raise FileExistsError(f"package folder is not empty: {out_dir}")
    os.makedirs(out_dir, exist_ok=True)
    scen = json.load(open(fitset_path, encoding="utf-8"))
    src_dir = os.path.dirname(os.path.abspath(fitset_path))
    scen_abs = absolutize_fitset(scen, src_dir)
    pkg_scen = copy.deepcopy(scen_abs)
    missing = []

    def _copy(src, rel):
        dst = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
        return rel.replace("\\", "/")

    used = sorted({c["fitset_channel"] for m in missions for c in m["channels"] if c.get("fitset_channel")})
    for key in used:
        ch = pkg_scen["channels"].get(str(key))
        if ch is None:
            raise KeyError(f"FitSet has no channel '{key}' (has {sorted(pkg_scen['channels'])})")
        wl = ch.get("wl_path")
        if wl and os.path.exists(wl):
            ch["wl_path"] = _copy(wl, os.path.join("wavecal", _safe(wl_dir_of(wl)), os.path.basename(wl)))
        elif wl:
            missing.append(wl)
        for r in ch.get("refs") or []:
            p = r.get("path") if isinstance(r, dict) else None
            if p and os.path.exists(p):
                r["path"] = _copy(p, os.path.join("refs", _safe(key), os.path.basename(p)))
            elif p:
                missing.append(p)
    if missing:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise FileNotFoundError("FitSet files not found (nothing written): " + "; ".join(missing))
    # 쓰지 않는 채널은 빼지 않는다 — FitSet 사본은 원본 그대로가 맞다(채널 키 유지). 단 경로는 못 쓰는 절대
    # 경로로 남으니, 안 쓰는 채널의 경로는 손대지 않는다(Vigil 은 미션이 가리키는 채널만 연다).
    with open(os.path.join(out_dir, FITSET), "w", encoding="utf-8") as fh:
        json.dump(pkg_scen, fh, ensure_ascii=False, indent=1)

    bases = {p.profile_id: p for p in load_profiles(profile_dir, validate=False) if not p.is_mission}
    mission_files = []
    for m in missions:
        base = bases.get(m["base"])
        if base is None:
            raise KeyError(f"base profile '{m['base']}' not found (have {sorted(bases)})")
        bname = os.path.basename(base.source_path)
        shutil.copy2(base.source_path, os.path.join(out_dir, bname))
        md = {"profile_id": m["profile_id"], "profile_version": m.get("profile_version", "1.0.0"),
              "base": m["base"],
              "description": m.get("description") or f"mission {name} — exported from FitSet "
                                                     f"{os.path.basename(fitset_path)}",
              "kind": base.kind, "campaign": m.get("campaign") or name,
              "match": {"date_range": list(m["date_range"])}, "channels": []}
        for c in m["channels"]:
            fch = pkg_scen["channels"][str(c["fitset_channel"])] if c.get("fitset_channel") else None
            oc = {"id": c["block"], "label": c["label"], "role": "signal"}
            if c.get("cavity"):
                oc["cavity"] = c["cavity"]
            if fch is not None and c.get("concentration") is not None:
                conc = {"allow_negative_gas": False, "target": "NO2", "throttle_sec": 10,
                        "seed_narrow_px": 2.0}
                conc.update(c["concentration"])
                conc.update({"fitset_path": FITSET, "wl_dir": wl_dir_of(fch.get("wl_path")),
                             "fitset_channel": str(c["fitset_channel"])})
                # The ±Neg policy is the FitSet's (single source): ConcMonitor refuses to start when
                # the profile disagrees with it, so a False default here switched concentration off
                # for every FitSet fitted with ±Neg on (2026-10-02, first real export: "init failed").
                if isinstance(fch.get("allow_negative_gas"), bool):
                    conc["allow_negative_gas"] = fch["allow_negative_gas"]
                oc["concentration"] = conc
            if fch is not None and c.get("reflectance") is not None:
                refl = {"cavity_len_cm": float(fch.get("cavity_d", 51.8)),
                        "rl_factor": float(fch.get("rl_factor", 0.933))}
                if fch.get("fit_start_nm") is not None and fch.get("fit_end_nm") is not None:
                    refl["roi_nm"] = [float(fch["fit_start_nm"]), float(fch["fit_end_nm"])]
                refl.update(c["reflectance"])
                refl["wavecal_path"] = fch.get("wl_path")
                oc["reflectance"] = refl
            md["channels"].append(oc)
        validate_profile_dict(md)
        bd = json.load(open(base.source_path, encoding="utf-8"))
        merge_mission(bd, md)                    # 구조를 바꾸려 하면 여기서 ProfileError
        fn = f"mission_{_safe(m['base'])}.json"
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as fh:
            json.dump(md, fh, ensure_ascii=False, indent=2)
        mission_files.append(fn)

    files = {}
    for root, _dirs, fnames in os.walk(out_dir):
        for f in fnames:
            rel = os.path.relpath(os.path.join(root, f), out_dir).replace("\\", "/")
            if rel != MANIFEST:
                files[rel] = _sha1(os.path.join(root, f))
    manifest = {"format": FORMAT, "version": VERSION, "name": name,
                "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "created_by": created_by, "source_fitset": os.path.abspath(fitset_path),
                "missions": mission_files, "files": files}
    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    # 출처 문자열(로더가 만드는 것과 같은 값)을 기록 — 설치한 PC 의 로그와 바로 대조
    from core.profile import load_profile
    manifest["provenance"] = [load_profile(os.path.join(out_dir, f), validate=False).provenance
                              for f in mission_files]
    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    return manifest


# ── 검사·설치 ────────────────────────────────────────────────────────────────
def read_manifest(pkg_dir: str) -> dict:
    p = os.path.join(pkg_dir, MANIFEST)
    with open(p, encoding="utf-8") as fh:
        m = json.load(fh)
    if m.get("format") != FORMAT:
        raise ValueError(f"not a mission package (manifest format={m.get('format')!r}): {pkg_dir}")
    return m


def verify_package(pkg_dir: str) -> list:
    """문제 목록(빈 목록 = 온전). 파일 누락·내용 변경(sha1)·미션 로드 실패를 잡는다."""
    try:
        m = read_manifest(pkg_dir)
    except (OSError, ValueError) as e:
        return [str(e)]
    bad = []
    for rel, sha in (m.get("files") or {}).items():
        p = os.path.join(pkg_dir, rel)
        if not os.path.exists(p):
            bad.append(f"missing: {rel}")
        elif _sha1(p) != sha:
            bad.append(f"changed: {rel}")
    from core.profile import load_profile
    for fn in m.get("missions") or []:
        try:
            load_profile(os.path.join(pkg_dir, fn), validate=False)
        except Exception as e:                    # noqa: BLE001
            bad.append(f"mission {fn}: {type(e).__name__}: {e}")
    return bad


def overlap_problems(pkg_dir: str, profile_dir: str, root: str) -> list:
    """이 패키지를 root 에 설치하면 생길 **날짜 겹침**(같은 열 수의 미션끼리) — 설치 전에 본다. 겹치면 그
    날짜의 파일을 어느 정체로 읽을지 정할 수 없다. 같은 이름 패키지(다시 불러오기 = 교체)는 빼고 본다."""
    from core.profile import load_profiles
    man = read_manifest(pkg_dir)
    same = os.path.abspath(os.path.join(root, _safe(man["name"])))
    installed = [f for f in installed_mission_files(root) if os.path.dirname(os.path.abspath(f)) != same]
    new = [os.path.join(pkg_dir, f) for f in man.get("missions") or []]
    allp = load_profiles(profile_dir, extra_paths=installed + new, validate=False)
    newd = os.path.abspath(pkg_dir)
    mine = [p for p in allp if p.source_path and os.path.dirname(os.path.abspath(p.source_path)) == newd]
    others = [p for p in allp if p.is_mission and p not in mine]
    out = []
    for q in mine:
        for p in others:
            if p.match.n_columns != q.match.n_columns:
                continue
            a, b = p.match.date_range, q.match.date_range
            if a is None or b is None or not (a[1] < b[0] or b[1] < a[0]):
                out.append(f"mission {q.profile_id} {b} overlaps {p.profile_id} {a} ({p.source_path}) "
                           f"— end the old mission first")
    return out


def install_package(pkg_dir: str, root: str) -> str:
    """패키지를 root/<이름>/ 으로 복사 → 설치 경로. 검사 실패면 ValueError(아무것도 안 바꿈).
    같은 이름이 이미 있으면: 내용이 같으면 그대로, 다르면 지우지 않고 `<이름>.replaced-<시각>` 으로 옮긴다."""
    problems = verify_package(pkg_dir)
    if problems:
        raise ValueError("mission package failed verification: " + "; ".join(problems))
    m = read_manifest(pkg_dir)
    dst = os.path.join(root, _safe(m["name"]))
    if os.path.abspath(dst) == os.path.abspath(pkg_dir):
        return dst
    if os.path.exists(dst):
        try:
            if read_manifest(dst).get("files") == m.get("files"):
                return dst
        except (OSError, ValueError):
            pass
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        os.replace(dst, f"{dst}.replaced-{stamp}")
    os.makedirs(root, exist_ok=True)
    shutil.copytree(pkg_dir, dst)
    return dst


def installed_mission_files(root: str) -> list:
    """root/<패키지>/ 아래 미션 파일들(manifest 의 missions) — 프로파일 로더가 읽을 것."""
    out = []
    if not root or not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d) or ".replaced-" in name:
            continue
        try:
            m = read_manifest(d)
        except (OSError, ValueError):
            continue
        out.extend(os.path.join(d, f) for f in (m.get("missions") or []))
    return out
