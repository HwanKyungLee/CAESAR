"""core/run_meta.py — 결과 `.dat` 옆에 쓰는 `.meta.json` 사이드카.

왜: 파일명에는 poly·Sh·gT만 들어가고 **QC(K·RMS·SNR)·settling·Tikhonov λ·Robust·
캘리브 세트(wavecal·R·ILS·dark)는 안 들어간다.** 즉 파일명이 같아도 다른 설정의 결과일
수 있다. `.dat` 헤더 주석에 텍스트로는 있지만 사람만 읽을 수 있어, 버전 비교/설정 diff를
기계가 할 수 없었다.

원칙
----
* **`.dat` 포맷은 한 글자도 안 바뀐다.** meta는 항상 *옆에* 쓴다(추가만, 기존 경로 불변).
* Qt를 임포트하지 않는다(core 규약). 호출부가 평범한 dict를 모아서 넘긴다.
* `runid`는 **설정만**의 해시다 — 데이터 날짜·행수·시각·커밋을 넣으면 "같은 설정으로
  다시 돌렸다"를 식별하지 못해 존재 이유가 사라진다.
* 레퍼런스/캘리브 파일은 **basename**만 해시한다. 절대경로를 넣으면 같은 설정이 머신마다
  다른 runid가 되어 재현성 추적이 깨진다(`core/paths.py`가 존재하는 이유와 같은 문제).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime

from core.provenance import is_reproducible as _reproducible

try:                                  # 패키지로 임포트된 평소 경로
    from core.paths import resolve_ref_path
except ImportError:                   # `python core/run_meta.py` 직접 실행(자기검증)
    from paths import resolve_ref_path

SCHEMA = "augur-run-meta-v1"


def meta_path_for(dat_path: str) -> str:
    """'…/260904_CH1.dat' → '…/260904_CH1.meta.json' (확장자만 교체)."""
    return os.path.splitext(dat_path)[0] + ".meta.json"


def _basename(path):
    """해시·기록용 파일 식별자. 경로가 아니라 이름만 남긴다(머신 독립).

    없으면 `""`가 아니라 `None` — 빈 문자열은 "설정 안 함", None은 "모름"이고
    legacy backfill에서는 후자가 사실이다(둘을 섞으면 소비자가 거짓을 읽는다)."""
    if not path:
        return None
    return os.path.basename(str(path).strip().replace("\\", "/").rstrip("/"))


def _text(value):
    """문자열 필드: 없으면 None(모름), 있으면 str. `str(None)`='None' 방지."""
    return None if value is None else str(value)


def _num(value, default=None):
    """UI에서 온 문자열/None을 수로. 실패하면 default (숨은 예외 대신 명시적 결측)."""
    try:
        if value is None or value == "":
            return default
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return default


def _species(cfg: dict) -> list:
    """refs + ref_props → 종별 정합 정책 한 줄씩. 순서는 refs 순서를 보존한다."""
    props = cfg.get("ref_props") or {}
    out = []
    for ref in cfg.get("refs") or []:
        name = ref.get("name")
        p = props.get(name, {}) if name else {}
        out.append({
            "name": name,
            "xs": _basename(ref.get("path")),
            "mult": _num(ref.get("mult")),
            "sh_mode": _text(p.get("sh_mode")),
            "sh_val": _text(p.get("sh_val")),
            "sq_mode": _text(p.get("sq_mode")),
            "sq_val": _text(p.get("sq_val")),
            "t_ref": _num(p.get("t_ref")),
            "t_coeff": _num(p.get("t_coeff")),
            "active_bands_nm": _text(p.get("active_bands_nm")),
        })
    return out


def build_meta(cfg: dict, *, channel, qc: dict, calibration: dict,
               data_days=(), rows=None, campaign=None, scenario=None,
               code_version=None, app_version=None, created=None,
               meta_source="live", layout=None) -> dict:
    """채널 하나의 설정 스냅샷(`_channel_configs[ch]` 형태) → meta dict.

    `cfg`는 `app_window._capture_config()`가 만드는 dict를 그대로 받는다(새 수집 경로를
    만들지 않는다). `qc`/`calibration`은 그 dict가 담지 않는 나머지를 호출부가 모아 넘긴다.
    `runid`는 마지막에 자기 자신으로부터 계산해 넣는다.
    """
    meta = {
        "schema": SCHEMA,
        "runid": None,
        "created": (created or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "campaign": campaign,
        "data_days": sorted(set(data_days)),
        "channel": _num(channel),
        "label": (cfg.get("data_label") or "").strip(),
        "window": {
            "px": [_num(cfg.get("f_min")), _num(cfg.get("f_max"))],
            "nm": [_num(cfg.get("fit_start_nm")), _num(cfg.get("fit_end_nm"))],
            # ⚠ px 필드가 정본이다. nm 필드는 스테일일 수 있다
            # (docs/fit_optimizer_handoff.md §13-A) — 둘 다 기록하고 unit으로 어느 쪽이
            # 실제로 쓰였는지 남긴다.
            "unit": cfg.get("fit_unit", "nm"),
        },
        "poly_deg": _num(cfg.get("poly_deg")),
        "step_limit": _num(cfg.get("step_limit")),
        "allow_neg": bool(cfg.get("allow_negative_gas")),
        "gas_temp": _num(cfg.get("gas_temp"), 0),
        "time_shift_h": _num(cfg.get("time_shift_h"), 0),
        "species": _species(cfg),
        "calibration": dict(calibration or {}),
        "qc": dict(qc or {}),
        "rows": dict(rows or {}),
        # 이 결과가 **어떤 raw 구성에서** 나왔나(B안). 사람이 친 campaign 라벨과 다를 수
        # 있고, 그건 정보다. runid 해시에는 안 넣는다 — 설정이 아니라 입력의 성질이므로.
        "layout": dict(layout) if layout else None,
        "provenance": {
            "commit": code_version,
            # 이 커밋으로 checkout해서 결과를 재현할 수 있다고 **주장 가능한가**.
            # commit이 'nogit'/'-dirty'/'-unknown'이면 False다. 조용히 넘기면
            # 재현 가능한 파일과 아닌 파일이 섞여 나중에 구별이 안 된다.
            "reproducible": bool(_reproducible(code_version)),
            "augur": app_version,
            "scenario": scenario,
            # "live" = 저장 시점 UI에서 온 전량. "legacy-header" = `.dat` 헤더에서 복원해
            # 일부가 null(설정 전량이 아님) — 소비자가 둘을 구별할 수 있어야 한다.
            "meta_source": meta_source,
        },
    }
    # legacy는 해시 입력에 null 구멍이 있어 서로 다른 런이 충돌할 수 있다. 접두사를 갈라
    # 정상 runid와 절대 섞이지 않게 한다('r…' vs 'L…').
    meta["runid"] = compute_runid(meta, prefix=("r" if meta_source == "live" else "L"))
    return meta


# runid 해시에 들어가는 것 = 숫자를 바꾸는 설정 전부.
# 빠지는 것: created·data_days·rows·provenance (같은 설정을 다른 날/다른 커밋으로 돌려도
# 같은 runid여야 "설정이 같다"를 식별할 수 있다).
_RUNID_KEYS = ("channel", "window", "poly_deg", "step_limit", "allow_neg",
               "gas_temp", "time_shift_h", "species", "calibration", "qc")


def compute_runid(meta: dict, prefix: str = "r") -> str:
    """설정만의 sha1 앞 5자리 → 'r3f8a1'. 같은 설정 = 같은 runid."""
    payload = {k: meta.get(k) for k in _RUNID_KEYS}
    # 종 순서는 설계행렬의 열 순서일 뿐 해를 안 바꾼다 → 순서만 다른 걸 '다른 설정'으로
    # 보고하지 않게 해시에서만 이름순 정렬한다(meta 본문은 표시 순서 그대로 보존).
    if isinstance(payload.get("species"), list):
        payload["species"] = sorted(payload["species"],
                                    key=lambda s: str(s.get("name", "")))
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)
    return prefix + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:5]


def _flatten(value, prefix="", out=None):
    """중첩 dict/list → {'a.b.c': 값}. 종 목록은 **이름으로** 키를 만든다 —
    인덱스로 하면 순서만 바뀌어도 전부 다르다고 나온다."""
    out = {} if out is None else out
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(value, list):
        named = [v for v in value if isinstance(v, dict) and v.get("name")]
        if len(named) == len(value):
            for v in value:
                _flatten({k: x for k, x in v.items() if k != "name"},
                         f"{prefix}.{v['name']}", out)
        else:
            out[prefix] = list(value)
    else:
        out[prefix] = value
    return out


def diff_meta(a: dict, b: dict) -> list:
    """두 meta의 **설정** 차이 → [(key, old, new)]. a=이전, b=이후.

    비교 대상은 `_RUNID_KEYS` — runid 해시에 들어가는 것과 **정확히 같은 집합**이다.
    어긋나면 "runid는 다른데 diff는 비었다"(또는 반대)가 나와 버전 목록이 거짓말을
    한다. 그래서 목록을 따로 두지 않고 한 상수를 공유한다.
    종이 추가/삭제된 쪽은 없는 값이 `None`으로 나온다.
    """
    fa = _flatten({k: a.get(k) for k in _RUNID_KEYS})
    fb = _flatten({k: b.get(k) for k in _RUNID_KEYS})
    return [(k, fa.get(k), fb.get(k))
            for k in sorted(set(fa) | set(fb))
            if fa.get(k) != fb.get(k)]


def summarize_diff(diff: list, limit: int = 3) -> str:
    """diff → 한 줄. 버전 목록의 '전 버전과 뭐가 달라졌나' 칸."""
    if not diff:
        return "no setting change"

    def _short(v):
        if v is None:
            return "-"
        if isinstance(v, float):
            return f"{v:g}"
        s = str(v)
        return s if len(s) <= 18 else s[:17] + "…"

    head = [f"{k.split('.', 1)[-1]} {_short(o)}→{_short(n)}" for k, o, n in diff[:limit]]
    more = f" (+{len(diff) - limit})" if len(diff) > limit else ""
    return ", ".join(head) + more


_DAY_DIR_RE = re.compile(r"^(\d{6}|\d{4}-\d{2}-\d{2})$")


def version_search_root(dat_path: str) -> str:
    """같은 날 버전들이 모여 있는 최상위 폴더.

    날짜처럼 생긴 **가장 가까운 상위 폴더**를 쓴다. A3 배치에선
    `{campaign}/{YYYY-MM-DD}/` 라 `fitting/`을 품고, 레거시
    `{day}/{neg}/{QC}/` 에선 neg·QC 버킷을 가로질러 찾는다 — 옛 구조에서
    QC만 다른 재핏은 다른 폴더에 있으므로 파일 폴더만 보면 놓친다.
    """
    d = os.path.dirname(os.path.abspath(dat_path))
    cur = d
    for _ in range(4):                       # {day}/{neg}/{QC}/file 이 최대 깊이
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            break
        if _DAY_DIR_RE.match(os.path.basename(cur)):
            return cur
        cur = parent
    return d


def find_versions(dat_path: str) -> list:
    """같은 날·같은 채널의 결과 버전들 → [{path, meta}], 저장 시각순.

    `.meta.json`만 읽는다 — 결과 `.dat`을 열지 않으므로 수십 개라도 즉시 끝난다.
    meta 없는 파일은 목록에 안 나온다(`tools/backfill_meta.py`로 만들 수 있다).
    """
    me = read_meta(dat_path)
    root = version_search_root(dat_path)
    want_ch = (me or {}).get("channel")
    want_days = set((me or {}).get("data_days") or [])

    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [x for x in dirnames if not x.startswith("_")]
        for fn in filenames:
            if not fn.endswith(".meta.json"):
                continue
            mp = os.path.join(dirpath, fn)
            m = read_meta(mp)
            if m is None:
                continue
            if want_ch is not None and m.get("channel") != want_ch:
                continue
            if want_days and not (set(m.get("data_days") or []) & want_days):
                continue
            found.append({"path": mp[: -len(".meta.json")] + os.path.splitext(dat_path)[1],
                          "meta_path": mp, "meta": m})
    found.sort(key=lambda r: (str(r["meta"].get("created") or ""), r["meta_path"]))
    return found


def bucket_labels(meta: dict) -> tuple:
    """meta → ('neg_o'|'neg_x', 'QCk8'|'QCmanual'|'QCoff') 표시 라벨.

    A3 전에는 이 어휘가 폴더 이름이었고 `save()`가 인라인으로 만들었다. 이제 폴더가
    아니라 라벨이지만 결과뷰어·날짜로더가 시리즈를 가를 때 여전히 쓴다 —
    **정의는 여기 한 곳**이다(사본을 만들면 어긋난다). 헤더 텍스트에서 뽑는 경로는
    `core.result_io.neg_qc_from_comments`(레거시 파일용)."""
    neg = "neg_o" if meta.get("allow_neg") else "neg_x"
    qc = (meta.get("qc") or {})
    if not qc.get("enabled"):
        return neg, "QCoff"
    k = qc.get("auto_k")
    return neg, (f"QCk{k:g}" if k else "QCmanual")


def write_meta(dat_path: str, meta: dict) -> str:
    """`.dat` 옆에 `.meta.json`을 쓴다. 경로를 반환. `.dat`은 건드리지 않는다."""
    path = meta_path_for(dat_path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2, default=str)
        fh.write("\n")
    return path


def read_meta(dat_path: str) -> dict | None:
    """`.dat` 경로(또는 meta 경로)로 meta를 읽는다. 없거나 깨졌으면 None."""
    path = dat_path if dat_path.endswith(".meta.json") else meta_path_for(dat_path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def layout_from_input(path: str) -> dict | None:
    """이 입력 파일이 **실제로 어떤 raw 구성에서 나왔는지**를 알아낸다(선택은 안 한다).

    B안: 파싱 구성의 **선택은 데이터(열 수)가** 하고, **기록은 여기서** 한다. 사람이 친
    캠페인 라벨(폴더 이름)과 기계가 고른 구성이 다를 수 있는데, 그건 오류가 아니라 정보다
    (예: `yeosu_2026` 폴더에 아라온 raw를 넣어 돌려본 경우 — meta를 보면 바로 보인다).

    * 알파(`*_alpha_trace.dat`): 헤더의 `# raw_layout:` 줄을 읽는다(알파를 만들 때 기록됨).
    * raw `.dat`: 첫 데이터행의 열 수로 레지스트리를 조회한다.
    * 그 외/실패: None — **모르면 안 적는다**(추측한 provenance가 없는 것보다 나쁘다).
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            first_data = None
            for line in fh:
                if line.startswith("# raw_layout:"):
                    out = {}
                    for tok in line.split(":", 1)[1].split():
                        if "=" in tok:
                            k, v = tok.split("=", 1)
                            out[k] = int(v) if v.isdigit() else v
                    return out or None
                if line.startswith("#") or not line.strip():
                    continue
                first_data = line
                break
    except OSError:
        return None
    if not first_data:
        return None
    toks = first_data.split("\t") if "\t" in first_data else first_data.split()
    ncols = len(toks)
    try:
        try:                               # 패키지로 임포트된 평소 경로
            from core.raw_parser import CAMPAIGN_LAYOUTS
        except ImportError:                # `python core/run_meta.py` 직접 실행(자기검증)
            from raw_parser import CAMPAIGN_LAYOUTS
    except Exception:                      # noqa: BLE001
        return {"ncols": ncols}
    lay = CAMPAIGN_LAYOUTS.get(ncols)
    if lay is None:
        return {"ncols": ncols, "campaign": "unregistered"}
    return {"ncols": ncols, "campaign": lay.campaign or lay.kind, "kind": lay.kind,
            "source": lay.source}


def meta_to_cfg(meta: dict, ref_dir: str | None = None) -> tuple:
    """meta → `_capture_config()` 모양의 cfg + 못 찾은 파일 목록. `build_meta`의 역변환.

    **왜 필요한가**: 저장된 결과의 잔차를 보려면 *그때* 설정으로 엔진을 다시 세워야 한다.
    지금 GUI 설정으로 계산한 잔차는 화면의 농도와 대응하지 않는다 — 조용히 틀린 그림이다.

    `ref_dir`: 레퍼런스·wavecal의 basename을 붙일 디렉터리. meta는 머신 독립을 위해
    **basename만** 갖고 있으므로(runid 계약) 어느 폴더인지는 호출부가 정해 넘긴다.
    같은 이름의 `Ref_NO2_Dynamic-ILS-Applied.dat`가 cold/roi1/roi2에 각각 **다른 내용**
    으로 있으므로, 폴더를 잘못 고르면 다른 채널의 단면으로 핏하게 된다 — 이 함수는
    추측하지 않고, 폴더 결정은 `core.refit.resolve_calibration_dir`가 알파의 파장축과
    대조해서 한다.

    반환: (cfg, unresolved) — unresolved는 실제로 존재하지 않는 경로들의 basename 목록.
    비어있지 않으면 호출부는 **재핏을 포기**해야 한다(있는 것만으로 핏하면 레퍼런스가
    빠진 채 계산돼 농도가 달라진다).
    """
    def _path(name):
        if not name:
            return ""
        if ref_dir:
            cand = os.path.join(ref_dir, name)
            if os.path.exists(cand):
                return cand
        return resolve_ref_path(name)

    unresolved = []
    refs, props = [], {}
    for sp in meta.get("species") or []:
        name = sp.get("name")
        if not name:
            continue
        fp = _path(sp.get("xs"))
        if not fp or not os.path.exists(fp):
            unresolved.append(sp.get("xs") or name)
        refs.append({"name": name, "path": fp, "mult": sp.get("mult") or 0})
        props[name] = {
            "sh_mode": sp.get("sh_mode") or "Free",
            "sh_val": sp.get("sh_val") or "",
            "sq_mode": sp.get("sq_mode") or "Free",
            "sq_val": sp.get("sq_val") or "",
            "t_ref": sp.get("t_ref"),
            "t_coeff": sp.get("t_coeff"),
            "active_bands_nm": sp.get("active_bands_nm") or "",
        }

    calib = meta.get("calibration") or {}
    wl = _path(calib.get("wavecal"))
    if not wl or not os.path.exists(wl):
        unresolved.append(calib.get("wavecal") or "(wavecal 미기록)")

    win = meta.get("window") or {}
    px = win.get("px") or [None, None]
    nm = win.get("nm") or [None, None]
    qc = meta.get("qc") or {}
    cfg = {
        "wl_path": wl,
        "refs": refs,
        "ref_props": props,
        "data_label": meta.get("label") or "",
        "f_min": "" if px[0] is None else str(px[0]),
        "f_max": "" if px[1] is None else str(px[1]),
        "fit_start_nm": nm[0],
        "fit_end_nm": nm[1],
        "fit_unit": win.get("unit") or "nm",
        "poly_deg": meta.get("poly_deg"),
        "step_limit": meta.get("step_limit"),
        "allow_negative_gas": bool(meta.get("allow_neg")),
        "gas_temp": meta.get("gas_temp") or 0,
        "time_shift_h": meta.get("time_shift_h") or 0,
        # 핏 수치를 바꾸는 값이라 반드시 meta에서 가져온다(기본값으로 때우면 안 됨).
        "tikhonov_lambda": qc.get("tikhonov") or 0.0,
        "use_robust": bool(qc.get("robust")),
    }
    return cfg, unresolved


def _demo():
    """자기검증: runid가 설정에만 반응하는지 (핵심 계약)."""
    cfg = {
        "data_label": "PNs", "f_min": "512", "f_max": "1240",
        "fit_start_nm": 435.0, "fit_end_nm": 480.0, "fit_unit": "nm",
        "poly_deg": 3, "step_limit": 0.5, "allow_negative_gas": True,
        "refs": [{"name": "NO2", "path": r"C:\refs\NO2_298K_ILS062.dat", "mult": 0}],
        "ref_props": {"NO2": {"sh_mode": "Center", "sh_val": "-0.21, 1.9"}},
    }
    qc = {"enabled": False, "auto_k": 8.0, "tikhonov": 0.0, "robust": False}
    calib = {"wavecal": "wv_cal_cold_0723.dat", "r": "R_CH1.npz"}
    kw = dict(channel=1, qc=qc, calibration=calib)

    a = build_meta(cfg, data_days=["2026-09-04"], rows={"total": 10}, **kw)
    # 데이터·시각·커밋이 달라도 설정이 같으면 같은 runid
    b = build_meta(cfg, data_days=["2026-09-05"], rows={"total": 99},
                   code_version="gdeadbee", **kw)
    assert a["runid"] == b["runid"], (a["runid"], b["runid"])

    # 설정이 하나라도 다르면 다른 runid
    for mutate in (
        lambda c: c.update(poly_deg=4),
        lambda c: c.update(allow_negative_gas=False),
        lambda c: c["ref_props"]["NO2"].update(sh_val="-0.21, 2.0"),
        lambda c: c["refs"].append({"name": "O4", "path": "O4.dat", "mult": 0}),
    ):
        import copy
        c2 = copy.deepcopy(cfg)
        mutate(c2)
        assert build_meta(c2, **kw)["runid"] != a["runid"], mutate

    # QC·캘리브도 해시에 든다
    assert build_meta(cfg, channel=1, qc={**qc, "enabled": True},
                      calibration=calib)["runid"] != a["runid"]
    assert build_meta(cfg, channel=1, qc=qc,
                      calibration={**calib, "r": "R_CH2.npz"})["runid"] != a["runid"]

    # 절대경로가 달라도 파일명이 같으면 같은 runid (머신 독립)
    import copy
    c3 = copy.deepcopy(cfg)
    c3["refs"][0]["path"] = "/home/x/NO2_298K_ILS062.dat"
    assert build_meta(c3, **kw)["runid"] == a["runid"]

    # 종 순서만 바뀐 건 같은 설정이다(설계행렬 열 순서는 해를 안 바꾼다)
    c4 = copy.deepcopy(cfg)
    c4["refs"].insert(0, {"name": "H2O", "path": "H2O.dat", "mult": -12})
    c5 = copy.deepcopy(c4)
    c5["refs"].reverse()
    assert build_meta(c4, **kw)["runid"] == build_meta(c5, **kw)["runid"]
    assert [s["name"] for s in build_meta(c5, **kw)["species"]] == ["NO2", "H2O"]  # 표시순 보존

    # 사이드카 왕복 + `.dat` 불변
    import tempfile
    dat = os.path.join(tempfile.mkdtemp(), "260904_CH1.dat")
    with open(dat, "w", encoding="utf-8") as fh:
        fh.write("# data\n")
    assert os.path.basename(write_meta(dat, a)) == "260904_CH1.meta.json"
    assert read_meta(dat)["runid"] == a["runid"]
    with open(dat, encoding="utf-8") as fh:
        assert fh.read() == "# data\n", ".dat must stay byte-identical"

    assert meta_path_for("/o/260904_CH1.dat") == "/o/260904_CH1.meta.json"
    assert read_meta("/nonexistent/nope.dat") is None

    # ── diff (B3) — runid와 반드시 같은 것을 본다 ──────────────────────
    assert diff_meta(a, b) == [], diff_meta(a, b)          # 같은 설정 → 차이 없음
    assert summarize_diff([]) == "no setting change"

    c6 = copy.deepcopy(cfg)
    c6["poly_deg"] = 5
    c6["ref_props"]["NO2"]["sh_val"] = "-0.30, 1.9"
    d6 = diff_meta(a, build_meta(c6, **kw))
    keys = [k for k, _o, _n in d6]
    assert "poly_deg" in keys and "species.NO2.sh_val" in keys, keys
    assert "poly_deg 3→5" in summarize_diff(d6), summarize_diff(d6)

    # ★불변식: runid가 다르다 ⟺ diff가 비어있지 않다.
    # 어긋나면 버전 목록이 "바뀐 게 없는데 새 버전"(또는 반대)을 보여준다.
    for mutate in (lambda c: c.update(poly_deg=7),
                   lambda c: c.update(allow_negative_gas=False),
                   lambda c: c["ref_props"]["NO2"].update(sq_mode="Fix"),
                   lambda c: c["refs"].append({"name": "O4", "path": "O4.dat", "mult": 0})):
        cx = copy.deepcopy(cfg)
        mutate(cx)
        mx = build_meta(cx, **kw)
        assert (mx["runid"] != a["runid"]) == bool(diff_meta(a, mx)), mutate
    same = build_meta(cfg, **kw)
    assert same["runid"] == a["runid"] and diff_meta(a, same) == []
    # 종 순서만 바뀐 건 runid도 diff도 변화 없음(설계행렬 열 순서는 해를 안 바꾼다)
    assert diff_meta(build_meta(c4, **kw), build_meta(c5, **kw)) == []

    # ── find_versions (B3) — 두 배치 모두에서 형제 버전을 찾는다 ────────
    root = tempfile.mkdtemp()
    a3 = os.path.join(root, "yeosu_2026", "2026-09-04", "fitting")
    os.makedirs(a3)
    for poly in (3, 4, 5):
        cx = copy.deepcopy(cfg)
        cx["poly_deg"] = poly
        mx = build_meta(cx, channel=1, qc=qc, calibration=calib,
                        data_days=["2026-09-04"], created=datetime(2026, 9, 4, poly))
        fp = os.path.join(a3, f"260904_CH1_PNs_{mx['runid']}.dat")
        open(fp, "w").close()
        write_meta(fp, mx)
    # 다른 채널은 섞이면 안 된다
    other = build_meta(cfg, channel=2, qc=qc, calibration=calib, data_days=["2026-09-04"])
    fp2 = os.path.join(a3, f"260904_CH2_x_{other['runid']}.dat")
    open(fp2, "w").close()
    write_meta(fp2, other)

    vs = find_versions(fp)
    assert len(vs) == 3, [v["meta"]["runid"] for v in vs]
    assert [v["meta"]["poly_deg"] for v in vs] == [3, 4, 5], "created 순 정렬이 아님"
    assert all(v["meta"]["channel"] == 1 for v in vs)
    assert os.path.exists(vs[0]["path"]), vs[0]["path"]

    # 레거시 {day}/{neg}/{QC}/ — QC 버킷을 가로질러 찾아야 한다
    leg = os.path.join(root, "260905")
    for bucket, k in (("QCoff", None), ("QCk8", 8.0)):
        dd = os.path.join(leg, "neg_o", bucket)
        os.makedirs(dd)
        mx = build_meta(cfg, channel=1, qc={"enabled": bool(k), "auto_k": k},
                        calibration=calib, data_days=["2026-09-05"])
        fp3 = os.path.join(dd, f"260905_cold_{mx['runid']}.dat")
        open(fp3, "w").close()
        write_meta(fp3, mx)
    assert len(find_versions(fp3)) == 2, "legacy: QC 버킷 가로지르기 실패"
    assert os.path.basename(version_search_root(fp3)) == "260905"
    assert os.path.basename(version_search_root(fp)) == "2026-09-04"

    # meta → cfg 왕복: 핏 수치를 바꾸는 값이 하나도 새지 않아야 한다.
    back, missing = meta_to_cfg(a)
    assert back["poly_deg"] == cfg["poly_deg"]
    assert back["allow_negative_gas"] == cfg["allow_negative_gas"]
    assert back["step_limit"] == cfg["step_limit"]
    assert [r["name"] for r in back["refs"]] == [r["name"] for r in cfg["refs"]]
    assert back["ref_props"]["NO2"]["sh_mode"] == "Center"
    assert back["ref_props"]["NO2"]["sh_val"] == "-0.21, 1.9"
    assert back["f_min"] == "512" and back["f_max"] == "1240"
    assert missing, "없는 파일은 unresolved로 보고돼야 한다(조용히 넘어가면 안 됨)"
    # λ·robust는 meta의 qc 블록에 있다 — 기본값으로 때우면 다른 핏이 된다.
    q = build_meta(cfg, channel=1, qc={"enabled": True, "auto_k": 6.0, "tikhonov": 0.02,
                                       "robust": True},
                   calibration=calib, data_days=["2026-09-04"])
    qb, _ = meta_to_cfg(q)
    assert qb["tikhonov_lambda"] == 0.02 and qb["use_robust"] is True

    # layout_from_input — 알파 헤더 / raw 열 수 / 모르면 None
    ap = os.path.join(root, "x_alpha_trace.dat")
    with open(ap, "w", encoding="utf-8") as fh:
        fh.write("# CAESAR Pro Alpha Export\n")
        fh.write("# raw_layout: ncols=6181 campaign=2026-yeosu parser=DataIO-dynamic\n")
        fh.write("row_idx\tT_C\tP_mbar\tpx100\n1\t25\t1013\t1e-7\n")
    lay = layout_from_input(ap)
    assert lay == {"ncols": 6181, "campaign": "2026-yeosu",
                   "parser": "DataIO-dynamic"}, lay

    rp = os.path.join(root, "raw_like.dat")
    with open(rp, "w", encoding="utf-8") as fh:
        fh.write("\t".join(["0"] * 6179) + "\n")
    lay2 = layout_from_input(rp)
    assert lay2 and lay2["ncols"] == 6179, lay2
    assert lay2.get("campaign") in ("2026-yeosu", "unregistered"), lay2

    # layout은 runid 해시에 들어가면 안 된다 — 같은 설정이면 입력이 달라도 같은 runid
    m1 = build_meta(cfg, channel=1, qc={}, calibration=calib, layout=lay)
    m2 = build_meta(cfg, channel=1, qc={}, calibration=calib, layout=lay2)
    assert m1["runid"] == m2["runid"], (m1["runid"], m2["runid"])
    assert m1["layout"] == lay and m2["layout"] == lay2

    print("run_meta self-check OK:", a["runid"])


if __name__ == "__main__":
    _demo()
