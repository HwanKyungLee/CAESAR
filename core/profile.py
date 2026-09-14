"""oculus/profile.py — 인스트루먼트 프로파일 로더 (범용 리더의 심장).

설계문서 §2-A. `Cold`/`Hot`/`PNs`/`ANs` 같은 채널 명명·레이아웃은 구성마다
달라지므로 코드에 박지 않고 `oculus/profiles/*.json` 에서 읽는다. 이 모듈은 그
JSON을 타입 있는 파이썬 객체로 바꾸고, raw 파일을 프로파일로 라우팅하고, raw 한
행에서 시각·flag·채널 스펙트럼·HK 물리값을 뽑는 헬퍼를 제공한다.

로직은 절대 채널 label(문자열)에 의존하지 않는다 — `Channel.id`(안정 식별자)나
`Flags.role_of()`(의미 역할) 같은 구조만 본다.

    from oculus.profile import ProfileSet
    ps = ProfileSet.load_default()
    prof = ps.route(filename="2026-05-26-001 Hot.dat", n_columns=6181)
    role = prof.flag_role(int(row[prof.header.state_flag_col]))   # 'atmosphere'|'za'|...
    for ch in prof.signal_channels():
        spec = ch.slice(row)

검증: `python oculus/test_profile.py`
"""
from __future__ import annotations

import fnmatch
import glob
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence

DEFAULT_PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
SCHEMA_PATH = os.path.join(DEFAULT_PROFILE_DIR, "_schema.json")

# 경보 심각도: HK 밴드 평가 결과
SEVERITY_NONE = None
SEVERITY_WARN = "warn"
SEVERITY_ALARM = "alarm"


class ProfileError(ValueError):
    """프로파일 로드/검증 실패."""


# ─────────────────────────────────────────────────────────────────────────
# 값 단위 구성 요소
# ─────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ScaledField:
    """단일 스칼라 열: 물리값 = raw[col] * scale + offset."""
    col: int
    scale: float = 1.0
    offset: float = 0.0
    unit: Optional[str] = None

    def value(self, row: Sequence[float]) -> float:
        return float(row[self.col]) * self.scale + self.offset

    @classmethod
    def from_dict(cls, d: dict) -> "ScaledField":
        return cls(col=int(d["col"]), scale=float(d.get("scale", 1.0)),
                   offset=float(d.get("offset", 0.0)), unit=d.get("unit"))


@dataclass(frozen=True)
class TimeBytepack:
    """행별 시각: bytepack = (raw[hi]<<16)|raw[lo] = 연초 기준 센티초(0.01s)."""
    hi_col: int
    lo_col: int
    epoch: str = "year_start"
    unit: str = "centiseconds"

    def centiseconds(self, row: Sequence[float]) -> int:
        return (int(row[self.hi_col]) << 16) | int(row[self.lo_col])

    def to_datetime(self, row: Sequence[float], year: int) -> datetime:
        """센티초 카운터 → 벽시계. 파일의 연도를 알아야 복원 가능(설계 §1.4)."""
        cs = self.centiseconds(row)
        return datetime(year, 1, 1) + timedelta(seconds=cs / 100.0)

    @classmethod
    def from_dict(cls, d: dict) -> "TimeBytepack":
        return cls(hi_col=int(d["hi_col"]), lo_col=int(d["lo_col"]),
                   epoch=d.get("epoch", "year_start"),
                   unit=d.get("unit", "centiseconds"))


@dataclass(frozen=True)
class Header:
    time_bytepack: TimeBytepack
    state_flag_col: int
    exposure_col: Optional[int] = None
    ccd_temp: Optional[ScaledField] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Header":
        return cls(
            time_bytepack=TimeBytepack.from_dict(d["time_bytepack"]),
            state_flag_col=int(d["state_flag_col"]),
            exposure_col=(int(d["exposure_col"]) if "exposure_col" in d else None),
            ccd_temp=(ScaledField.from_dict(d["ccd_temp"]) if "ccd_temp" in d else None),
        )


@dataclass(frozen=True)
class Flags:
    """의미 역할('atmosphere','za','he',...) → flag 숫자값 목록."""
    mapping: dict

    def role_of(self, flag: int) -> Optional[str]:
        """flag 숫자 → 역할 이름. 미정의면 None."""
        for role, values in self.mapping.items():
            if flag in values:
                return role
        return None

    def values(self, role: str) -> list:
        return list(self.mapping.get(role, []))

    def is_role(self, flag: int, role: str) -> bool:
        return flag in self.mapping.get(role, [])

    @classmethod
    def from_dict(cls, d: dict) -> "Flags":
        return cls(mapping={k: [int(v) for v in vals] for k, vals in (d or {}).items()})


@dataclass(frozen=True)
class ReflectanceConfig:
    """채널별 R(반사율) 실시간 산출 설정(M2, 선택). 없으면 r_monitor가 SKIP.
    물리 계산 자체는 tools/reflectance_calc.ReflectanceCalculator(단일 출처)가 한다 —
    여기는 그 함수가 필요로 하는 채널별 입력(wavecal·캐비티 HK 필드·ROI·경보 임계)만 서술."""
    wavecal_path: Optional[str] = None
    roi_nm: Optional[tuple] = None          # (lo, hi) nm
    cavity_temp_hk: Optional[str] = None    # hk.fields[].key
    cavity_pressure_hk: Optional[str] = None
    cavity_len_cm: float = 51.8
    rl_factor: float = 0.933
    warn_drop: Optional[float] = None
    alarm_drop: Optional[float] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ReflectanceConfig":
        alert = d.get("alert") or {}
        roi = d.get("roi_nm")
        return cls(
            wavecal_path=d.get("wavecal_path"),
            roi_nm=(tuple(float(v) for v in roi) if roi else None),
            cavity_temp_hk=d.get("cavity_temp_hk"),
            cavity_pressure_hk=d.get("cavity_pressure_hk"),
            cavity_len_cm=float(d.get("cavity_len_cm", 51.8)),
            rl_factor=float(d.get("rl_factor", 0.933)),
            warn_drop=(float(alert["warn_drop"]) if "warn_drop" in alert else None),
            alarm_drop=(float(alert["alarm_drop"]) if "alarm_drop" in alert else None),
        )


@dataclass(frozen=True)
class ConcentrationConfig:
    """채널별 경량 DOAS 농도 피팅 설정(M3, 선택). 없으면 conc_monitor가 SKIP.
    레퍼런스·핏창·poly·ref_props는 여기서 새로 정의하지 않고 Augur FitSet json을
    그대로 가리킨다(fitset_path+wl_dir) — Augur 확정 설정과 갈라지지 않게."""
    fitset_path: str
    wl_dir: str
    allow_negative_gas: bool
    target: str = "NO2"
    cavity_temp_hk: Optional[str] = None
    cavity_pressure_hk: Optional[str] = None
    throttle_sec: float = 10.0
    seed_narrow_px: float = 2.0
    conc_min_ppb: Optional[float] = None
    conc_max_ppb: Optional[float] = None
    spike_ppb: Optional[float] = None
    rms_sig_alarm: Optional[float] = None
    flatline_n: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ConcentrationConfig":
        alert = d.get("alert") or {}
        if not isinstance(d.get("allow_negative_gas"), bool):
            raise ProfileError("concentration.allow_negative_gas must be an explicit boolean")
        return cls(
            fitset_path=d["fitset_path"],
            wl_dir=d["wl_dir"],
            allow_negative_gas=d["allow_negative_gas"],
            target=d.get("target", "NO2"),
            cavity_temp_hk=d.get("cavity_temp_hk"),
            cavity_pressure_hk=d.get("cavity_pressure_hk"),
            throttle_sec=float(d.get("throttle_sec", 10.0)),
            seed_narrow_px=float(d.get("seed_narrow_px", 2.0)),
            conc_min_ppb=(float(alert["conc_min_ppb"]) if "conc_min_ppb" in alert else None),
            conc_max_ppb=(float(alert["conc_max_ppb"]) if "conc_max_ppb" in alert else None),
            spike_ppb=(float(alert["spike_ppb"]) if "spike_ppb" in alert else None),
            rms_sig_alarm=(float(alert["rms_sig_alarm"]) if "rms_sig_alarm" in alert else None),
            flatline_n=(int(alert["flatline_n"]) if "flatline_n" in alert else None),
        )


@dataclass(frozen=True)
class Channel:
    """스펙트럼 블록. id=로직이 참조하는 안정 식별자, label=표시용 문자열(로직 의존 금지)."""
    id: str
    role: str  # 'signal' | 'noise'
    label: Optional[str] = None
    columns: Optional[tuple] = None  # (start, end) 절대 열, 양끝 포함
    reflectance: Optional[ReflectanceConfig] = None
    concentration: Optional[ConcentrationConfig] = None

    @property
    def is_signal(self) -> bool:
        return self.role == "signal"

    def slice(self, row: Sequence[float]):
        """이 채널의 스펙트럼 절편 반환(양끝 포함). columns 미지정이면 오류."""
        if self.columns is None:
            raise ProfileError(f"channel '{self.id}' has no columns (autodetect 필요)")
        s, e = self.columns
        return row[s:e + 1]

    @classmethod
    def from_dict(cls, d: dict) -> "Channel":
        cols = d.get("columns")
        return cls(id=d["id"], role=d["role"], label=d.get("label"),
                   columns=(tuple(int(c) for c in cols) if cols else None),
                   reflectance=(ReflectanceConfig.from_dict(d["reflectance"])
                               if "reflectance" in d else None),
                   concentration=(ConcentrationConfig.from_dict(d["concentration"])
                                 if "concentration" in d else None))


def _band_check(value: float, band: Optional[Sequence]) -> bool:
    """value가 [lo, hi] 밴드 안이면 True. None 끝값은 한쪽 무제한. band 자체 None이면 True."""
    if band is None:
        return True
    lo, hi = band
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


@dataclass(frozen=True)
class HKField:
    """Housekeeping 열: 물리값 = raw[start_col+rel]*scale + offset. 밴드는 선택."""
    key: str
    rel: int
    scale: float = 1.0
    offset: float = 0.0
    unit: Optional[str] = None
    label: Optional[str] = None
    nominal: Optional[float] = None
    warn: Optional[tuple] = None   # (lo, hi)
    alarm: Optional[tuple] = None  # (lo, hi)
    phases: Optional[tuple] = None  # 밴드가 유효한 flag 역할들 (None=전 구간)

    def value(self, row: Sequence[float], hk_start: int) -> float:
        return float(row[hk_start + self.rel]) * self.scale + self.offset

    def applies_to(self, phase: Optional[str]) -> bool:
        """이 필드의 밴드를 주어진 측정 구간(flag 역할)에서 평가해야 하는지.

        `phases`가 지정된 필드는 그 구간에서만 경보한다 — 교정 중에는 장비가 의도적으로
        off-nominal이 되므로(He 주입 시 캐비티압 상승 등) 대기 측정용 밴드를 그대로 적용하면
        매 교정 사이클마다 오경보가 난다. phase를 모르면(None) 보수적으로 평가한다."""
        if self.phases is None or phase is None:
            return True
        return phase in self.phases

    def evaluate(self, phys_value: float, phase: Optional[str] = None):
        """물리값의 경보 심각도. alarm 밴드 이탈=SEVERITY_ALARM, warn 이탈=SEVERITY_WARN,
        아니면 None. 밴드가 없거나 이 구간에 해당하지 않으면 None(표시만)."""
        if not self.applies_to(phase):
            return SEVERITY_NONE
        if self.alarm is not None and not _band_check(phys_value, self.alarm):
            return SEVERITY_ALARM
        if self.warn is not None and not _band_check(phys_value, self.warn):
            return SEVERITY_WARN
        return SEVERITY_NONE

    @classmethod
    def from_dict(cls, d: dict) -> "HKField":
        alert = d.get("alert") or {}
        warn = tuple(alert["warn"]) if "warn" in alert else None
        alarm = tuple(alert["alarm"]) if "alarm" in alert else None
        phases = tuple(alert["phases"]) if "phases" in alert else None
        return cls(key=d["key"], rel=int(d["rel"]),
                   scale=float(d.get("scale", 1.0)), offset=float(d.get("offset", 0.0)),
                   unit=d.get("unit"), label=d.get("label"),
                   nominal=(float(d["nominal"]) if "nominal" in d else None),
                   warn=warn, alarm=alarm, phases=phases)


@dataclass(frozen=True)
class HK:
    start_col: int
    fields: tuple  # tuple[HKField]

    def field(self, key: str) -> Optional[HKField]:
        for f in self.fields:
            if f.key == key:
                return f
        return None

    def read(self, row: Sequence[float], phase: Optional[str] = None) -> dict:
        """{key: (물리값, 심각도)} 한 번에. 대시보드·경보 공통 입력.

        `phase`(= 그 행의 flag 역할)를 넘기면 구간 한정 밴드가 올바르게 적용된다.
        교정 구간에서 대기용 밴드가 오경보를 내지 않도록 **항상 넘기는 것을 권장**한다."""
        out = {}
        for f in self.fields:
            v = f.value(row, self.start_col)
            out[f.key] = (v, f.evaluate(v, phase))
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "HK":
        return cls(start_col=int(d["start_col"]),
                   fields=tuple(HKField.from_dict(x) for x in d["fields"]))


@dataclass(frozen=True)
class Cadence:
    scan_interval_sec: float
    file_rollover_sec: Optional[float] = None
    liveness_grace_sec: Optional[float] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Cadence":
        return cls(scan_interval_sec=float(d["scan_interval_sec"]),
                   file_rollover_sec=(float(d["file_rollover_sec"]) if "file_rollover_sec" in d else None),
                   liveness_grace_sec=(float(d["liveness_grace_sec"]) if "liveness_grace_sec" in d else None))


@dataclass(frozen=True)
class Autodetect:
    first_spectrum_col: int
    signal_min_max: float
    warmup_scans: int = 5

    @classmethod
    def from_dict(cls, d: dict) -> "Autodetect":
        return cls(first_spectrum_col=int(d["first_spectrum_col"]),
                   signal_min_max=float(d["signal_min_max"]),
                   warmup_scans=int(d.get("warmup_scans", 5)))


@dataclass(frozen=True)
class Match:
    n_columns: Optional[int] = None
    filename_glob: Optional[str] = None

    def col_match(self, n_columns: Optional[int]) -> bool:
        """이 프로파일이 주어진 열수를 정확히 요구하면 True."""
        return (self.n_columns is not None and n_columns is not None
                and self.n_columns == n_columns)

    def col_compatible(self, n_columns: Optional[int]) -> bool:
        """열수와 모순되지 않으면 True(열수 제약이 없거나 정확히 일치). filename은 보지 않음."""
        if n_columns is None or self.n_columns is None:
            return True
        return self.n_columns == n_columns

    def name_match(self, filename: Optional[str]) -> bool:
        """파일명 glob이 있고 일치하면 True."""
        return (self.filename_glob is not None and filename is not None
                and fnmatch.fnmatch(os.path.basename(filename), self.filename_glob))

    @classmethod
    def from_dict(cls, d: dict) -> "Match":
        return cls(n_columns=(int(d["n_columns"]) if "n_columns" in d else None),
                   filename_glob=d.get("filename_glob"))


# ─────────────────────────────────────────────────────────────────────────
# 프로파일
# ─────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Profile:
    profile_id: str
    profile_version: str
    match: Match
    header: Header
    flags: Flags
    channels: tuple  # tuple[Channel]
    hk: HK
    cadence: Cadence
    description: Optional[str] = None
    instrument: Optional[str] = None
    spectrum_block_width: Optional[int] = None
    autodetect: Optional[Autodetect] = None
    saturation_adc_max: Optional[float] = None
    source_path: Optional[str] = None

    # ── 편의 접근 ────────────────────────────────────────────────
    def signal_channels(self) -> list:
        return [c for c in self.channels if c.is_signal]

    def channel(self, channel_id: str) -> Optional[Channel]:
        for c in self.channels:
            if c.id == channel_id:
                return c
        return None

    def flag_role(self, flag: int) -> Optional[str]:
        return self.flags.role_of(int(flag))

    def is_saturated(self, spectrum: Sequence[float]) -> bool:
        """스펙트럼에 포화 픽셀이 있으면 True. saturation 미정의면 항상 False."""
        if self.saturation_adc_max is None:
            return False
        return any(float(v) > self.saturation_adc_max for v in spectrum)

    def autodetect_channels(self, rows: Sequence[Sequence[float]]) -> list:
        """columns를 비운 채널 구성을, 첫 몇 스캔의 블록별 최대값으로 signal/noise 분류.
        근거: raw_parser VALUE-INSPECTION(신호≈3~5만, 노이즈≈700~900). autodetect·
        spectrum_block_width가 있어야 한다. 반환: 새 Channel 목록(ch0,ch1,...)."""
        if self.autodetect is None or self.spectrum_block_width is None:
            raise ProfileError("autodetect/spectrum_block_width 미설정 — 자동탐지 불가")
        ad = self.autodetect
        width = self.spectrum_block_width
        start = ad.first_spectrum_col
        end = self.hk.start_col  # HK 직전까지가 스펙트럼 영역
        use = list(rows)[:max(1, ad.warmup_scans)]
        detected = []
        idx = 0
        col = start
        while col + width <= end:
            block_max = 0.0
            for r in use:
                seg = r[col:col + width]
                m = max((float(v) for v in seg), default=0.0)
                if m > block_max:
                    block_max = m
            role = "signal" if block_max >= ad.signal_min_max else "noise"
            detected.append(Channel(id=f"ch{idx}", role=role, label=None,
                                    columns=(col, col + width - 1)))
            idx += 1
            col += width
        return detected

    @classmethod
    def from_dict(cls, d: dict, source_path: Optional[str] = None) -> "Profile":
        try:
            return cls(
                profile_id=d["profile_id"],
                profile_version=d["profile_version"],
                match=Match.from_dict(d["match"]),
                header=Header.from_dict(d["header"]),
                flags=Flags.from_dict(d["flags"]),
                channels=tuple(Channel.from_dict(c) for c in d["channels"]),
                hk=HK.from_dict(d["hk"]),
                cadence=Cadence.from_dict(d["cadence"]),
                description=d.get("description"),
                instrument=d.get("instrument"),
                spectrum_block_width=(int(d["spectrum_block_width"])
                                      if "spectrum_block_width" in d else None),
                autodetect=(Autodetect.from_dict(d["autodetect"])
                            if "autodetect" in d else None),
                saturation_adc_max=(float(d["saturation"]["adc_max"])
                                    if d.get("saturation", {}).get("adc_max") is not None
                                    else None),
                source_path=source_path,
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ProfileError(f"프로파일 파싱 실패 ({source_path or d.get('profile_id')}): {e}") from e


# ─────────────────────────────────────────────────────────────────────────
# 검증 · 로딩 · 라우팅
# ─────────────────────────────────────────────────────────────────────────
def _load_schema() -> Optional[dict]:
    try:
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def validate_profile_dict(d: dict, schema: Optional[dict] = None) -> None:
    """프로파일 dict 검증. jsonschema가 있으면 스키마로, 없으면 최소 구조 검사.
    실패 시 ProfileError."""
    if schema is None:
        schema = _load_schema()
    try:
        import jsonschema  # optional dep — DAQ PC에 없을 수 있음
    except ImportError:
        jsonschema = None
    if jsonschema is not None and schema is not None:
        try:
            jsonschema.validate(d, schema)
        except jsonschema.ValidationError as e:  # type: ignore[attr-defined]
            raise ProfileError(f"스키마 검증 실패: {e.message} (at {list(e.path)})") from e
        return
    # 폴백: 최소 필수 키 구조 검사
    required = ["profile_id", "profile_version", "match", "header", "flags",
                "channels", "hk", "cadence"]
    missing = [k for k in required if k not in d]
    if missing:
        raise ProfileError(f"필수 키 누락: {missing}")
    if not d.get("channels"):
        raise ProfileError("channels 가 비어 있음")


def load_profile(path: str, validate: bool = True,
                 schema: Optional[dict] = None) -> Profile:
    """단일 프로파일 JSON 로드(+검증) → Profile."""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    if validate:
        validate_profile_dict(d, schema)
    return Profile.from_dict(d, source_path=path)


def load_profiles(profile_dir: str = DEFAULT_PROFILE_DIR,
                  validate: bool = True) -> list:
    """폴더의 모든 프로파일 로드. '_'로 시작하는 파일(_schema.json 등)은 건너뛴다."""
    schema = _load_schema() if validate else None
    profiles = []
    for path in sorted(glob.glob(os.path.join(profile_dir, "*.json"))):
        if os.path.basename(path).startswith("_"):
            continue
        profiles.append(load_profile(path, validate=validate, schema=schema))
    # 중복 profile_id 방지 — by_id/route가 조용히 첫 번째만 쓰는 footgun 차단
    # (열수 중복은 정당할 수 있어 막지 않는다: filename_glob로 구분 가능)
    seen: dict = {}
    for p in profiles:
        if p.profile_id in seen:
            raise ProfileError(
                f"중복 profile_id '{p.profile_id}': {seen[p.profile_id]} vs {p.source_path}")
        seen[p.profile_id] = p.source_path
    return profiles


class ProfileSet:
    """로드된 프로파일 묶음 + 파일→프로파일 라우팅. 한 인스턴스가 Cold·Hot 등
    여러 레이아웃을 동시에 처리(설계 §0-A.5)."""

    def __init__(self, profiles: Sequence[Profile]):
        self.profiles = list(profiles)

    @classmethod
    def load(cls, profile_dir: str = DEFAULT_PROFILE_DIR, validate: bool = True) -> "ProfileSet":
        return cls(load_profiles(profile_dir, validate=validate))

    # 기본 프로파일 폴더 로드(별칭)
    load_default = load

    def __len__(self) -> int:
        return len(self.profiles)

    def by_id(self, profile_id: str) -> Optional[Profile]:
        for p in self.profiles:
            if p.profile_id == profile_id:
                return p
        return None

    def route(self, filename: Optional[str] = None,
              n_columns: Optional[int] = None) -> Optional[Profile]:
        """파일(이름/열수)에 맞는 프로파일 반환. 없으면 None.

        규칙(설계 §2-A: n_columns 1차, filename 보조):
          1. 열수와 **양립 가능**한 프로파일만 후보로 남긴다(열수가 어긋나면 파싱이
             깨지므로 파일명이 맞아도 배제). 열수 정확 일치가 있으면 그쪽만.
          2. 후보가 여럿이면 filename glob으로 동점 해소.
          3. 그래도 하나로 못 좁히면 첫 후보. 후보가 없으면 None.
        filename은 후보를 **좁히기만** 하고, 열수 매치를 무효화하지 못한다."""
        pool = [p for p in self.profiles if p.match.col_compatible(n_columns)]
        if n_columns is not None:
            exact = [p for p in pool if p.match.col_match(n_columns)]
            if exact:
                pool = exact
        if filename is not None:
            named = [p for p in pool if p.match.name_match(filename)]
            if named:
                return named[0]
        if len(pool) == 1:
            return pool[0]
        if pool and n_columns is not None:
            return pool[0]   # 열수 양립 후보 중 최선(best-effort)
        return None


if __name__ == "__main__":
    # 빠른 수동 점검: 기본 폴더 로드 요약
    ps = ProfileSet.load_default()
    print(f"loaded {len(ps)} profile(s) from {DEFAULT_PROFILE_DIR}")
    for p in ps.profiles:
        sig = [c.id for c in p.signal_channels()]
        print(f"  {p.profile_id}  n_columns={p.match.n_columns}  "
              f"signal={sig}  hk_fields={len(p.hk.fields)}")
