"""core/raw_parser.py
====================

CAESAR Araon Mega-Matrix raw .dat parser.

This module is the **single source of truth** for column layout. Every other
module that reads raw data should go through here rather than hardcoding
column indices.

Layout (verified against 2026-05 Yeosu campaign data + 박사님
`read_data_CAESAR_Araon_2025_3ch.m`):

::

  col  0      : LabVIEW timestamp byte-pack HIGH 16 bits (uint16) — bytepack=(col0<<16)|col1
  col  1      : LabVIEW timestamp byte-pack LOW 16 bits (uint16)
                (필드/상수명 time_lo·COL_TIME_LO 등은 역사적 오명 — 수식이 정본이며
                 기준 .mat doy와 std=0.0000s 일치 검증됨. 이름만 보고 순서 바꾸지 말 것)
  col  2      : exposure (centiseconds? unit unclear, MATLAB calls it 'ms')
  col  3      : tempccd (CCD temp, ÷100 = °C)
  col  4      : state flag (1=Atmosphere, 500=ZA, 510=He, 502/512=wait, 503/513=end)
  col  5–2052 : ** EMPTY / NOISE in 2026 ** (was ch3 in 박사님 2025 3-channel build)
  col 2053–4100: PRIMARY spectrum  — Cold: NO2 cell.   Hot(2026 여수): **ANs 300 °C** cell (청색 LED)
  col 4101–6148: SECONDARY spectrum — Hot(2026 여수): **PNs 180 °C** cell (469 nm LED). Cold: noise.
                 ※ 2026-09-27 인젝션으로 판정(아래 register_campaign_layout 주석). 과거 주석의
                   'PNs=좌측=primary'는 틀렸다. 캠페인 이후 광섬유 배치가 바뀌면 다시 판정할 것.
  col 6149+   : HK block (housekeeping). Cold: 30 cols. Hot: 32 cols.

Verified by VALUE-INSPECTION (2026-05-25-001 Cold, 2026-05-26-001 Hot):
  * Cold block (5:2053): max ≈ 758  → noise (dark floor ~713)
  * Cold block (2053:4101): max ≈ 35839 → SIGNAL (Cold cavity NO2)
  * Cold block (4101:6149): max ≈ 839  → noise
  * Hot block (5:2053): max ≈ 981   → noise (dark floor ~922)
  * Hot block (2053:4101): max ≈ 50608 → SIGNAL (PNs cavity, 박사님 "좌측")
  * Hot block (4101:6149): max ≈ 38024 → SIGNAL (ANs cavity, 박사님 "우측")

HK relative offsets (within the 6149+ block; verified by VALUE-INSPECTION on
2026-05-26-001 Hot + 2026-05-25-001 Cold):

  Hot file (6181 cols total):
    rel  0 (col 6149) : templed1            ÷100 = °C
    rel  1 (col 6150) : templed2            ÷100
    rel  2 (col 6151) : ANs oven setpoint   ÷100 ≈ 300 °C  [MATLAB:'templed3']
    rel  4 (col 6153) : preheater temp      ÷100 ≈ 38 °C   [MATLAB:'temppreh']
    rel  5 (col 6154) : PNs oven setpoint   ÷100 ≈ 180 °C  [MATLAB:'tempcellh']
    rel  6 (col 6155) : cell heater (=cavity gas T setpoint) ÷100 ≈ 75 °C
                                                            [MATLAB:'tempoptbx']
    rel 13 (col 6162) : PNs cavity P        raw × 0.6895 ≈ 965 mbar
    rel 15 (col 6164) : ANs cavity P        raw × 0.6895 ≈ 915 mbar
    rel 25 (col 6174) : tempcell1           ÷100 = °C (always working)
    rel 26 (col 6175) : tempcell2           ÷100 = °C (broken until 5/27 10:56)
    rel 27 (col 6176) : tempcell3           ÷100 = °C
    rel 28 (col 6177) : tempsptrm (spectrometer housing) ÷100 = °C

  Cold file (6179 cols total):
    rel  6 (col 6155) : ??                  raw 15000-15500 (sentinel?)
    rel 11 (col 6160) : cavity pressure     raw × 0.6895 ≈ 1000 mbar
    rel 24 (col 6173) : cavity temperature  ÷100 ≈ 24 °C
    rel 25 (col 6174) : spectrometer T      ÷100

NOTE on MATLAB labels: 박사님 MATLAB variable names (e.g. ``tempcellh``,
``tempoptbx``) appear to drift from the physical role by one or two columns
compared to our 2026 Yeosu data values. The mapping here reflects what the
**data** actually shows, not necessarily the MATLAB label. Where the two
disagree the MATLAB label is recorded as a comment for reference.

캠페인별 레이아웃 — 채널 정의는 vigil/profiles/*.json 한 곳 (2026-10-02~)
---------------------------------------------------------------------
위 컬럼 표는 **2026 여수 구성**의 설명이다. 실제로 쓰는 표는 코드가 아니라 **프로파일 JSON**에
산다 — 블록 이름·HK 열·채널별 압력/온도 센서(`channels[].cavity`)·유효 날짜(`match.date_range`).
Augur(이 모듈·core/data_io)와 Vigil 이 같은 파일을 읽는다(vigil/profiles/README.md).

* import 때 ``autoload_campaign_layouts()`` 가 프로파일 폴더를 읽어 ``CAMPAIGN_LAYOUTS``
  (열 수 → 구성 **목록**)를 만든다. 같은 열 수라도 날짜 구간이 다른 구성이 여럿일 수 있다.
* ``layout_for(ncols, path)`` — 열 수 + 파일명 날짜로 구성을 고른다(어느 구간에도 안 들면
  '구간 밖' — 블록·HK 는 쓰고 채널 이름은 주장하지 않는다).
* ``register_campaign_layout(...)`` — 같은 열 수·**겹치는 날짜**는 조용히 덮지 않는다.
* ``hk_col(ncols, key)`` — 도구가 HK 열 번호를 따로 적지 않게.
* 단위 환산(°C ÷100, mbar ×P_SCALE)은 **core가 단일 출처**이고, 프로파일이 다른 scale을
  적어두면 0.1% 초과일 때 경고한다.

즉 **채널을 추가하거나 배치가 바뀌어도 이 파일을 고치지 않는다** — 프로파일 JSON 을 고친다.
검사: ``python tools/test_raw_layout.py`` (옛 내장 표 재현 + 날짜별 구성 + 채널 추가 시나리오).

State flag conventions
----------------------
::

Authoritative semantics (from the LabVIEW DAQ side). The calibration families
share one rule: **5xx = Zero Air, 51x = Helium**, and the last digit is the
step within that family.

::

  flag = 0     header / file-start marker
  flag = 1     sampling (atmosphere)
  flag = 100   shutdown

  ── x00 injecting · x01 setflow · x02 wait-before · x03 wait-after ──
  flag = 500   ZA injecting     ← measurement window (R uses this)
  flag = 501   ZA setflow
  flag = 502   ZA wait-before
  flag = 503   ZA wait-after
  flag = 510   He injecting     ← measurement window (R uses this)
  flag = 511   He setflow
  flag = 512   He wait-before
  flag = 513   He wait-after

Observed cycle (2026-06-02 Hot, one full calibration ≈ 2 min 15 s, ~30 s/step)::

  1 → 512 → 510 → 513 → 501 → 502 → 500 → 503 → 1

R calculation must use **500 / 510** (the injecting = measurement window),
NOT the setflow/wait steps.

**Why (settled, do not re-litigate).** ``502`` / ``512`` are *wait-before*: the
cell is still being filled, so the gas column is not yet the pure ZA/He the
Rayleigh extinction equation assumes. Measured intensity there differs from the
injecting window by ~5 % (Cold: 42184 at 500 vs 40068 at 502), which propagates
straight into R and inflates its noise.

``tools/r_batch_calculator.py`` once hardcoded ``FLAG_ZA = [502]``; that bug is
**already fixed** — it now imports ``FLAG_ZA``/``FLAG_HE`` from this module, so
500/510 is the single source of truth. Nothing left to migrate.

.. note::
   ``501`` / ``511`` / ``100`` were absent from this file's earlier flag table and
   were added after ``501`` turned up in real 2026-06 data; the older
   "ZA-end (one-row marker)" reading of ``503`` was a guess — it is *wait-after*.

Time decoding
-------------
``col0`` (low 16 bits) and ``col1`` (high 16 bits) byte-pack to a LabVIEW
timestamp in centiseconds since the start of the year:

::

  bytepack = (col0 << 16) | col1
  this_year_sec = bytepack / 100
  date_local = datenum(1904, 1, 2) + (ref_sec + this_year_sec) / 86400

The 2026 ``ref_sec`` per 박사님 MATLAB code is **3 723 840 000**. For
practical use the file mtime is usually a good enough start-of-file
timestamp; we expose both. NOTE: the absolute ``ref_sec`` offset has been
seen to be wrong by hours on 2026 Yeosu files, but the *relative* row-to-row
bytepack spacing is reliable (~0.97 s/row) — see ``ParsedRow.bytepack_sec``.
"""
from __future__ import annotations

import re
import sys
import os
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────────
# Constants — single source of truth
# ──────────────────────────────────────────────────────────────────────────────────

META_COLS = 2053            # 0..2052 inclusive
CH_PIXELS = 2048            # 2048 pixels per spectral channel

# Absolute spectrum slices (start, end_exclusive)
SPEC_BLOCK_A = (5,         5 + CH_PIXELS)            # 5..2053  — empty / legacy 3-ch
# 블록이 어느 셀인지는 캠페인 레이아웃이 정한다(아래 register_campaign_layout). 2026 여수 핫은
# primary = ANs(300 °C), secondary = PNs(180 °C) — docs/채널정체_판정_2026-09-27.md.
SPEC_PRIMARY = (META_COLS, META_COLS + CH_PIXELS)    # 2053..4101 — Cold NO2 / 여수 Hot ANs
SPEC_SECONDARY = (META_COLS + CH_PIXELS,             # 4101..6149 — 여수 Hot PNs (hot only)
                  META_COLS + 2 * CH_PIXELS)
# Legacy aliases for code expecting the MATLAB nomenclature
SPEC_CH1_NO2 = SPEC_PRIMARY        # MATLAB "ch1"
SPEC_CH2_UV  = SPEC_SECONDARY      # MATLAB "ch2"

HK_START = META_COLS + 2 * CH_PIXELS                  # 6149


def spec_blocks_for_ncols(ncols: int) -> dict[str, tuple[int, int]]:
    """등록 안 된(cold/hot 둘 다 아닌) raw 구성을 위한 구조적 폴백.

    CAESAR는 캐비티 수가 재구성될 수 있다(2025년엔 실제로 3채널 빌드가 있었다 —
    이 파일 위 SPEC_BLOCK_A 주석 참조; 2026 cold/hot는 그 중 1~2개만 씀).
    `_detect_layout`이 아는 두 ncols(6179/6181) 중 어느 쪽도 아니면, 여기서
    META_COLS 이후를 CH_PIXELS 폭으로 순서대로 채널 블록을 추론한다 —
    `core/data_io.py`의 `_detect_n_channels_from_row`/동적 슬롯 계산과 같은 트릭
    (HK 블록 폭이 CH_PIXELS보다 훨씬 작다는 전제, 현재 30~32컬럼이라 성립).

    HK 맵은 여기서 못 만든다 — 실제 센서 배치는 열 수만으론 안 나온다(추측하면
    조용히 틀린 HK를 만드는 게 더 위험). 새 구성의 HK 레이아웃이 확인되면
    `_detect_layout`에 그 ncols 항목을 추가할 것. 어떤 블록이 실제 신호를 담고
    있는지(신호 vs 노이즈)도 이 함수는 모른다 — 그건 `DataIO._detect_n_channels_from_row`가
    이미 하는 일이라 여기서 중복 구현하지 않는다."""
    n_slots = max(0, (ncols - META_COLS) // CH_PIXELS)
    return {f"ch{i}": (META_COLS + (i - 1) * CH_PIXELS, META_COLS + i * CH_PIXELS)
            for i in range(1, n_slots + 1)}

# Standard meta columns
COL_TIME_LO = 0
COL_TIME_HI = 1
COL_EXPOSURE = 2
COL_TEMP_CCD = 3
COL_FLAG = 4

# 레이아웃 판정 시 훑어볼 최대 데이터행 수. 헤더행(flag=0)은 1행뿐이라 2면 충분하지만
# 여유를 둔다 — 등록 레이아웃과 맞는 행을 만나면 즉시 멈추므로 보통 1~2행만 읽는다.
LAYOUT_PROBE_ROWS = 5

# State flag categories.
# Family rule: 5xx = Zero Air, 51x = Helium;
#              x00 injecting · x01 setflow · x02 wait-before · x03 wait-after.
FLAG_HEADER   = 0
FLAG_AMBIENT  = 1        # LabVIEW calls this "sampling"
FLAG_SHUTDOWN = 100
FLAG_ZA      = 500       # ZA injecting = measurement window
FLAG_ZA_SETFLOW = 501
FLAG_ZA_WAIT = 502       # wait-before
FLAG_ZA_END  = 503       # wait-after (historical name kept for compatibility)
FLAG_HE      = 510       # He injecting = measurement window
FLAG_HE_SETFLOW = 511
FLAG_HE_WAIT = 512       # wait-before
FLAG_HE_END  = 513       # wait-after (historical name kept for compatibility)

# Accurate aliases (prefer these in new code; values are identical)
FLAG_ZA_WAIT_BEFORE = FLAG_ZA_WAIT
FLAG_ZA_WAIT_AFTER  = FLAG_ZA_END
FLAG_HE_WAIT_BEFORE = FLAG_HE_WAIT
FLAG_HE_WAIT_AFTER  = FLAG_HE_END

FLAG_STABLE = {FLAG_ZA, FLAG_HE}              # actual measurement windows

# Ambient rows within this many seconds after a calibration (ZA/He) block ends still hold purge
# gas in the cavity (2026-09-17: the hourly concentration spike; 60 s measured on Yeosu cold).
# Single source for Augur alpha generation (worker default, Alpha Generator, headless CLI) and
# Vigil's concentration monitor.
PURGE_SETTLE_SEC = 60.0
FLAG_TRANSITIONAL = {FLAG_ZA_SETFLOW, FLAG_ZA_WAIT, FLAG_ZA_END,
                     FLAG_HE_SETFLOW, FLAG_HE_WAIT, FLAG_HE_END}

FLAG_NAMES: dict[int, str] = {
    FLAG_HEADER:     "header",
    FLAG_AMBIENT:    "sampling",
    FLAG_SHUTDOWN:   "shutdown",
    FLAG_ZA:         "ZA-inject",
    FLAG_ZA_SETFLOW: "ZA-setflow",
    FLAG_ZA_WAIT:    "ZA-wait-before",
    FLAG_ZA_END:     "ZA-wait-after",
    FLAG_HE:         "He-inject",
    FLAG_HE_SETFLOW: "He-setflow",
    FLAG_HE_WAIT:    "He-wait-before",
    FLAG_HE_END:     "He-wait-after",
}

# Pressure raw → mbar (raw × 0.01 × 6894.73 Pa/PSI ÷ 100)
P_SCALE = 0.01 * 6894.73326 / 100.0   # ≈ 0.6894733
P_VALID_LO, P_VALID_HI = 800.0, 1200.0  # mbar plausibility window

# Time decoding (per 박사님 read_data_CAESAR_Araon_2025_3ch.m)
LABVIEW_REF_SEC_2026 = 3_723_840_000      # MATLAB line 49
LABVIEW_EPOCH = datetime(1904, 1, 2)      # MATLAB datenum(1904,1,2)
KST = timezone(timedelta(hours=9))

# Sentinel raw values that mean "no reading"
#
# **0 이 정말 '값 없음'이다 — 계기 담당자 확인(2026-09-15).** 데이터를 오래 본 경험상
# 이 계기는 미연결/미측정 채널에 0 을 쓴다. 전수조사도 이를 뒷받침한다: 핫 1314개
# 전 파일에서 tempcell3(6176)·tempsptrm(6177)이 **한 번도** 0 이 아닌 적이 없고,
# templed4(6152)는 늘 65535 다(두 가지 '없음' 표기가 섞여 쓰인다).
#
# ⚠ 그래서 **정확히 0.00 °C(또는 raw 0)는 원리적으로 결측과 구분되지 않는다.**
#   HK 판독은 그 필드를 NaN 으로 보고 폴백한다. 0.01 °C 분해능이라 셀이 딱 0.00 °C 에
#   앉아 있어야 걸리지만, **빙점 근처 운용(한랭지·항공·야간 해양)이면 반복될 수 있다.**
#   지금은 여수(셀 29~33 °C)라 실제로 걸린 적이 없어 그대로 둔다.
#
#   고쳐야 할 때가 오면: 0 을 목록에서 빼는 게 아니라(그러면 위의 죽은 열들이 0.00 °C 를
#   실측값으로 보고한다) **필드별 sentinel 을 프로파일에 두는 것**이 답이다 —
#   `hk.fields[].sentinel: [65535]` 처럼. 그때까지는 YAGNI.
SENTINEL_RAW = (0.0, 65535.0)


# ── 스펙트럼 CCD 포화 ──────────────────────────────────────────────────────────
# 16-bit ADC 라 만재는 65535 지만, 문턱은 그보다 낮게 둔다 — 만재 직전에 이미
# 응답이 휘어 흡수를 **과소평가**하기 때문이다. 64000 은 Vigil 프로파일
# (`vigil/profiles/caesar_*.example.json` 의 `saturation.adc_max`)이 쓰는 값과
# 같게 맞춘 것이다. 프로파일 쪽은 계기마다 덮어쓸 수 있는 설정이고, 이 상수는
# 프로파일 체계가 없는 Augur 본 파이프라인의 기본값이다.
#
# 실측 유병률(2026-09-16, 여수 표본 24파일×매7행):
#   ambient(flag=1)  콜드 0.00 % · 핫 0.00 %      <- 대기 측정은 깨끗하다
#   He(flag 510)     콜드 3.45 % · 핫 **21.43 %**
#   He(flag 512)                  핫 12.07 %
#   ZA(flag 502)                  핫  1.96 %
# ⚠ 포화가 몰리는 He/ZA 는 거울반사도 R 계산 입력이고, R 은 **이후 모든 ambient
#   스캔의 α 에 곱해진다.** 그래서 한 스캔이 아니라 구간 전체가 틀어진다.
SATURATION_ADC_MAX = 64000.0


def count_saturated(spectrum, adc_max: float = SATURATION_ADC_MAX) -> int:
    """스펙트럼에서 포화 픽셀 수. 무결성 헌장대로 **버리지 않고 세기만** 한다.

    같은 판정을 Vigil 는 `core.profile.Profile.is_saturated` 로 한다(프로파일별
    adc_max). 문턱식이 갈리지 않게 기본값을 여기 한 곳에서 관리한다.
    """
    a = np.asarray(spectrum, dtype=float)
    return int(np.count_nonzero(np.isfinite(a) & (a > adc_max)))


def _is_sentinel(v: float) -> bool:
    return (not np.isfinite(v)) or (v in SENTINEL_RAW)


# ──────────────────────────────────────────────────────────────────────────────────
# 캠페인 레이아웃 — **채널 정의의 단일 출처는 vigil/profiles/*.json** (2026-10-02)
# ──────────────────────────────────────────────────────────────────────────────────
# 어느 열 블록이 어느 셀인지, HK 열이 무엇인지, 채널마다 어느 압력·온도 센서를 쓰는지는
# 이제 **프로파일 JSON 한 곳**에만 있다. 예전엔 같은 사실이 세 곳에 있었다 — 여기 내장 표
# (HotHKMap/ColdHKMap), core/data_io 의 채널↔센서 짝, Vigil 프로파일 — 그래서 채널을 하나
# 추가하면 세 곳을 같이 고쳐야 했고, 한쪽만 고치면 Augur 와 Vigil 이 다른 채널을 봤다.
# 이 모듈은 import 때 프로파일 폴더를 읽어 레이아웃 표를 만든다(jsonschema 검증 없이 — 1.9 s
# 라 부팅에 안 넣는다. 검증은 vigil/test_profile.py·CI). 옛 내장 표의 열 번호는
# tools/test_raw_layout.py 가 "프로파일이 같은 열을 만든다"로 지킨다. 열별 근거(전수 sentinel
# 열, 6180 의심, 6174 선두 5열 결손)는 vigil/profiles/README.md "HK 열 근거" 절로 옮겼다.
#
# 채널 위치는 **역할 이름**으로도 적는다(block_a/primary/secondary) — 절대 열은 META_COLS·
# CH_PIXELS에서 유도되므로 SPEC_* 한 곳에만 존재한다.

ROLE_BLOCKS: dict[str, tuple[int, int]] = {
    "block_a":   SPEC_BLOCK_A,
    "primary":   SPEC_PRIMARY,
    "secondary": SPEC_SECONDARY,
}

# unit → (scale, kind). **단위 환산은 core가 단일 출처다** — 캠페인 프로파일은 "어느 열이
# 무엇인가"를 말할 뿐, PSI가 몇 Pa인지를 다시 정의하지 않는다(원칙 3).
UNIT_SCALES: dict[str, tuple[float, str]] = {
    "degC": (0.01, "temp"),
    "C":    (0.01, "temp"),
    "mbar": (P_SCALE, "press"),
    "raw":  (1.0, "raw"),
}


@dataclass
class CampaignLayout:
    """한 raw 구성(열 수 + 파일 날짜 구간)의 채널·HK 지도 — 프로파일 하나에서 만든다."""
    ncols: int
    kind: str
    channels: dict                # 표시이름 → 역할명 또는 (start, end)
    hk_map: dict                  # 이름 → (절대열, scale, unit, kind)
    campaign: str = ""
    source: str = "builtin"
    # 채널 **이름**(PNs/ANs 등)이 유효한 파일 날짜 구간 ("YYYY-MM-DD", 양끝 포함). None = 제한 없음.
    # 같은 ncols라도 캠페인이 끝나고 광섬유-ROI 배치가 바뀌면 이름이 거짓말이 된다
    # (실측: 2026-09-27 실험실 raw는 6181열인데 block 2053 = 콜드 캐비티).
    # 구간 밖 파일은 구조적 이름(ch1/ch2)으로 떨어뜨린다 — 블록 위치·HK 열은 그대로.
    date_range: tuple = None
    # 채널 이름 → (압력 키 목록, 온도 키 목록) — 프로파일 채널 `cavity`(우선순위 순).
    # core/data_io 가 n_air 용 T/P 를 이걸로 고른다(채널 이름으로 분기하지 않는다).
    cavity: dict = field(default_factory=dict)
    # 'caesar_hot.example.json@1.3.0#1a2b3c4d' — 어느 프로파일(파일·판·내용 해시)에서 왔나.
    # 알파 헤더 raw_layout 줄·결과 meta 에 남는다(오프라인 PC 끼리 정의가 같은지 대조용).
    profile: str = ""
    # 미션(셀 정체를 얹은 것)인가, 기본(구조)인가. 같은 열 수에서 날짜가 맞는 미션이 기본보다 먼저.
    is_mission: bool = False

    def spec_blocks(self) -> dict:
        out = {}
        for name, role in self.channels.items():
            out[name] = ROLE_BLOCKS[role] if isinstance(role, str) else tuple(role)
        return out

    def channel_at(self, block_start: int):
        """block_start 열로 시작하는 블록의 채널 이름(없으면 None)."""
        for name, (start, _end) in self.spec_blocks().items():
            if int(start) == int(block_start):
                return name
        return None


# 열 수 → 레이아웃 **목록**. 같은 열 수라도 날짜 구간이 다른 구성(배치가 바뀐 뒤의 프로파일)이
# 여럿 있을 수 있다 — 고르는 건 `layout_for(ncols, path)`.
CAMPAIGN_LAYOUTS: dict[int, list] = {}


def _ranges_overlap(a, b) -> bool:
    if a is None or b is None:
        return True
    return not (a[1] < b[0] or b[1] < a[0])


def register_campaign_layout(ncols, kind, channels, hk_map, *, campaign="",
                             source="builtin", replace=False,
                             date_range=None, cavity=None, profile="",
                             is_mission=False) -> CampaignLayout:
    """raw 구성 하나를 등록한다. 같은 ncols 에 **날짜 구간이 겹치는** 구성이 이미 있으면
    `replace=True` 라야 덮는다(겹치는 것들을 뺀다).

    조용한 덮어쓰기를 막는 이유: 두 구성이 같은 ncols·같은 날짜를 주장하면 어느 HK 지도로
    파싱할지 정할 수 없다 — 그걸 말없이 고르면 다른 구성의 HK 로 파싱하면서 아무 경고도 안 난다.
    """
    dr = tuple(date_range) if date_range else None
    have = CAMPAIGN_LAYOUTS.get(int(ncols), [])
    # 겹침은 **같은 층끼리만** 따진다 — 기본(구조)은 날짜와 무관한 바탕이고, 미션이 그 위에 얹힌다.
    clash = [h for h in have if h.is_mission == bool(is_mission)
             and _ranges_overlap(h.date_range, dr)]
    if clash and not replace:
        h = clash[0]
        raise ValueError(
            f"ncols={ncols} layout already exists for overlapping dates ({h.kind}, source={h.source}, "
            f"date_range={h.date_range}). Pass replace=True to overwrite — or give the new "
            f"configuration a date_range that does not overlap")
    lay = CampaignLayout(ncols=int(ncols), kind=str(kind), channels=dict(channels),
                         hk_map=hk_map, campaign=str(campaign), source=str(source),
                         date_range=dr, cavity=dict(cavity or {}), profile=str(profile),
                         is_mission=bool(is_mission))
    for name, role in lay.channels.items():
        if isinstance(role, str) and role not in ROLE_BLOCKS:
            raise ValueError(f"Channel '{name}' has unknown role '{role}'. "
                             f"Must be one of {list(ROLE_BLOCKS)} or (start, end)")
    CAMPAIGN_LAYOUTS[lay.ncols] = [h for h in have if h not in clash] + [lay]
    return lay


def layout_for(ncols, path=None):
    """(레이아웃, 날짜 구간 안인가) — 이 열 수·파일에 맞는 구성. 모르는 열 수면 (None, False).

    우선순위: ① 파일명 날짜가 맞는 **미션**(셀 정체) ② 그 열 수의 **기본(구조)** 프로파일 —
    날짜와 무관하게 '안'(블록 이름은 ch0/ch1/ch2, 캐비티 센서 없음 → data_io 는 슬롯 규칙).
    ③ 기본도 없으면 첫 미션을 **구간 밖**으로(블록·HK 는 쓰되 채널 이름은 주장하지 않는다 —
    `_detect_layout`). path 가 없으면 날짜를 모르므로 첫 미션(없으면 기본)."""
    lays = CAMPAIGN_LAYOUTS.get(int(ncols)) if ncols else None
    if not lays:
        return None, False
    missions = [l for l in lays if l.is_mission]
    bases = [l for l in lays if not l.is_mission]
    if path is None:
        return (missions or bases)[0], True
    for lay in missions:
        if not lay.date_range or _in_date_range(str(path), None, lay.date_range):
            return lay, True
    if bases:
        return bases[0], True
    return lays[0], False


def missions_not_covering(ncols, path) -> list:
    """이 열 수의 미션 중 path 의 날짜를 안 덮는 것(경고용 — 그 파일은 기본 프로파일로 읽힌다)."""
    return [l for l in CAMPAIGN_LAYOUTS.get(int(ncols), [])
            if l.is_mission and l.date_range and not _in_date_range(str(path), None, l.date_range)]


def hk_col(ncols, key, path=None):
    """이 구성에서 HK 키의 절대 열(없으면 None) — 도구가 열 번호를 따로 적지 않게."""
    lay, _ = layout_for(ncols, path)
    ent = lay.hk_map.get(key) if lay is not None else None
    return ent[0] if ent else None


def load_campaign_layout(path: str, *, kind=None, replace=False,
                         validate=False, verbose=True, source=None) -> CampaignLayout:
    """**캠페인 프로파일 JSON**(`vigil/profiles/*.json`)에서 raw 레이아웃을 등록.

    캠페인별 컬럼 지도는 그 파일이 갖고 있다(`match.n_columns`·`date_range`, `channels[].columns`·
    `cavity`, `hk.start_col`+`fields[].rel`). 새 포맷을 만들지 않고 그걸 읽는다 — Augur와 Vigil이
    **한 파일**을 본다(Vigil 설계 §2-A "역수혈").

    파싱은 `core.profile`(그 포맷의 **유일한** 리더)에 맡기고, 여기서는 그 결과를 raw_parser의
    레이아웃 표로 옮기기만 한다. validate=True 면 jsonschema 검증까지(느리다 — 테스트용).

    단위 환산은 **core 상수**를 쓴다(UNIT_SCALES). 프로파일이 반올림한 scale을 적어 두면
    0.1%까지는 무시하고, 그보다 크게 어긋나면 경고한다 — 조용히 다른 물리를 쓰지 않도록.
    """
    from core.profile import load_profile   # 지연 임포트(순환 없음: profile은 stdlib만 씀)

    prof = load_profile(path, validate=validate)
    ncols = prof.match.n_columns if prof.match else None
    if not ncols:
        raise ValueError(f"{os.path.basename(path)}: no match.n_columns, so "
                         f"the raw configuration cannot be determined")

    warn = []
    hdr = prof.header
    # bytepack 수식이 정본이다: (col0<<16)|col1. 이름(hi/lo)은 양쪽이 반대로 부르지만
    # **열 번호**가 같아야 한다 — 다르면 시각이 통째로 틀어진다.
    tb = getattr(hdr, "time_bytepack", None)
    if tb is not None and {tb.hi_col, tb.lo_col} != {COL_TIME_LO, COL_TIME_HI}:
        warn.append(f"time_bytepack columns {tb.hi_col}/{tb.lo_col} != core "
                    f"{COL_TIME_LO}/{COL_TIME_HI}")
    if getattr(hdr, "exposure_col", COL_EXPOSURE) != COL_EXPOSURE:
        warn.append(f"exposure_col {hdr.exposure_col} != core {COL_EXPOSURE}")
    if getattr(hdr, "state_flag_col", COL_FLAG) != COL_FLAG:
        warn.append(f"state_flag_col {hdr.state_flag_col} != core {COL_FLAG}")

    channels, cavity = {}, {}
    for ch in prof.candidate_channels():          # signal + auto(기본 프로파일의 블록)
        if ch.columns is None:
            warn.append(f"channel '{ch.id}' has no columns (autodetect only) — skipped")
            continue
        block = (int(ch.columns[0]), int(ch.columns[1]) + 1)   # 프로파일은 포함 끝
        role = next((r for r, b in ROLE_BLOCKS.items() if b == block), block)
        name = str(ch.label or ch.id)
        channels[name] = role
        pk, tk = tuple(ch.pressure_keys()), tuple(ch.temp_keys())
        if pk or tk:                              # 센서를 정한 채널만(기본 프로파일 블록은 없음)
            cavity[name] = (pk, tk)

    hk_map = {}
    for f in prof.hk.fields:
        unit = f.unit or "raw"
        scale, knd = UNIT_SCALES.get(unit, (1.0, "raw"))
        if f.offset:
            # raw_parser의 HK 튜플은 (열, scale, unit, kind) — offset 자리가 없다.
            # 조용히 버리면 물리값이 틀리므로 아예 안 싣는다.
            warn.append(f"{f.key}: offset={f.offset} cannot be expressed in the raw_parser HK table — excluded")
            continue
        if f.scale is not None and scale and abs(float(f.scale) - scale) / scale > 1e-3:
            warn.append(f"{f.key}: profile scale {f.scale} vs core {scale:.8g} "
                        f"({unit}) — using the core value")
        hk_map[str(f.key)] = (int(prof.hk.start_col) + int(f.rel), scale, unit, knd)
    for name, (pk, tk) in cavity.items():
        missing = [k for k in (*pk, *tk) if k not in hk_map]
        if missing:
            warn.append(f"channel '{name}' cavity refers to unknown hk keys {missing}")

    if verbose:
        for w in warn:
            print(f"[raw_parser] Campaign profile note ({os.path.basename(path)}): {w}")

    return register_campaign_layout(
        ncols, kind or prof.kind or str(prof.profile_id or "campaign"), channels, hk_map,
        campaign=str(prof.campaign or (prof.profile_id if prof.is_mission else "")),
        source=source or os.path.basename(path),
        replace=replace, date_range=prof.match.date_range, cavity=cavity,
        profile=prof.provenance, is_mission=prof.is_mission)


def autoload_campaign_layouts(profile_dir=None, *, verbose=True) -> list:
    """프로파일 폴더의 캠페인 JSON 을 **아직 등록 안 된 것만** 등록한다(파일 이름 기준, 여러 번
    불러도 안전). import 때 한 번 돌고(`_PROFILE_LOAD`), main.py 가 부팅 단계로 다시 부른다.

    raw 파일의 열 수(+ 파일명 날짜)가 곧 그 구성이므로 라우팅은 **데이터가** 한다 — 사용자가
    프로파일을 고를 필요가 없다. 한 파일이 깨져 있어도 나머지는 등록한다(앱이 안 뜨면 안 된다)
    — 대신 stderr 로 반드시 알린다: 등록이 빠진 열 수는 HK 지도 없이 구조적 폴백으로 떨어진다.
    반환: 이번에 새로 등록된 CampaignLayout 목록.
    """
    import glob as _glob

    if profile_dir is None:
        try:
            from core.profile import DEFAULT_PROFILE_DIR
            profile_dir = DEFAULT_PROFILE_DIR
        except Exception:                        # noqa: BLE001
            return []
    known = {lay.source for lays in CAMPAIGN_LAYOUTS.values() for lay in lays}
    out = []
    try:                                         # 설치된 미션 패키지(<profile_dir>/missions/<이름>/)
        from core.mission_package import installed_mission_files, missions_root
        pkg = installed_mission_files(missions_root(profile_dir))
    except Exception:                            # noqa: BLE001
        pkg = []
    for path in sorted(_glob.glob(os.path.join(profile_dir, "*.json"))) + pkg:
        # 이름 = 프로파일 폴더 기준 상대경로(패키지마다 mission_*.json 이름이 같다)
        name = os.path.relpath(path, profile_dir).replace("\\", "/")
        if os.path.basename(path).startswith("_") or name in known:
            continue                             # _schema.json 등 메타 파일 · 이미 등록
        try:
            out.append(load_campaign_layout(path, verbose=verbose, source=name))
            if verbose:
                print(f"[raw_parser] Registered campaign layout: {name} "
                      f"(ncols={out[-1].ncols}, channels={list(out[-1].channels)})")
        except Exception as e:                   # noqa: BLE001
            print(f"[raw_parser] ⚠ Campaign profile registration failed — skipped "
                  f"({name}): {type(e).__name__}: {e}", file=sys.stderr)
    return out


# ──────────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ──────────────────────────────────────────────────────────────────────────────────

@dataclass
class ParsedRow:
    """One parsed row from a raw .dat file."""
    row_idx: int
    time_centisec: float          # raw col1 (high 16 bits of the LabVIEW bytepack)
    time_lo: float                # raw col0 (low 16 bits of the LabVIEW bytepack)
    exposure: float
    temp_ccd_C: float
    flag: int
    hk: dict[str, float]          # name → value in physical units (°C, mbar, ...)
    # Spectrum slices are not stored on the row by default to save memory.
    # Call .spectrum(...) on the parser to get them on demand.

    @property
    def bytepack_sec(self) -> float:
        """LabVIEW bytepack ((col0<<16)|col1)/100 → seconds (this-year scale).

        Returns NaN if either half is missing. The *absolute* offset depends
        on LABVIEW_REF_SEC_2026 (which can be wrong), but the *relative*
        spacing between rows is reliable (~0.97 s/row), so this is ideal for
        anchoring a file's rows to its mtime:
            t(row) = mtime - (bytepack_sec[last] - bytepack_sec[row])
        """
        import math
        if math.isnan(self.time_lo) or math.isnan(self.time_centisec):
            return float("nan")
        return ((int(self.time_lo) << 16) | int(self.time_centisec)) / 100.0


@dataclass
class FileLayout:
    """Detected file layout (Cold vs Hot)."""
    path: str
    ncols: int                    # actual ncols of first non-empty row
    kind: str                     # "cold" | "hot" | "unknown"
    hk_map: dict[str, tuple[int, float, str, str]]
    spec_blocks: dict[str, tuple[int, int]]   # name → (start, end) slice
    mtime: datetime               # file mtime in KST


# ──────────────────────────────────────────────────────────────────────────────────
# Parser
# ──────────────────────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")


def _file_date(path: str):
    """파일명의 YYYY-MM-DD, 없으면 None. (mtime은 복사하면 바뀌므로 쓰지 않는다.)"""
    m = _DATE_RE.search(os.path.basename(path))
    return "-".join(m.groups()) if m else None


def _in_date_range(path: str, mtime, date_range) -> bool:
    """파일명 날짜가 구간 밖일 때만 False. 날짜를 모르면 제한하지 않는다(합성 테스트 파일 등)."""
    d = _file_date(path)
    if d is None:
        return True
    lo, hi = date_range
    return lo <= d <= hi


class RawParser:
    """Streaming parser for CAESAR Araon Mega-Matrix .dat files.

    Examples
    --------
    >>> p = RawParser("D:/.../2026-05-25-001.dat")
    >>> p.layout.kind                 # 'cold' or 'hot'
    'cold'
    >>> for row in p.iter_rows():     # streamed, low memory
    ...     if row.flag == FLAG_ZA:
    ...         spec = p.get_spectrum(row.row_idx, 'ch1')  # NO2/Cold spectrum
    ...         T = row.hk['cavity_T']; P = row.hk['cavity_P']
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.layout = self._detect_layout(path)

    # ── Layout detection ────────────────────────────────────────────────────────
    @staticmethod
    def _detect_layout(path: str) -> FileLayout:
        """Read first non-empty data row to determine ncols, then classify."""
        # 파일을 첫 행 하나로 판정하면 안 된다 — LabVIEW가 파일 맨 앞에 쓰는 flag=0
        # 헤더행은 데이터행과 열 수가 다르다. 실측은 **양방향 다** 나온다:
        #   · 핫  : 헤더 6177 <  데이터 6181 (1314개 중 22개)
        #   · 콜드: 헤더 6177 >  데이터 6174 — 2026-06-11-020.dat은 데이터행 3693개가
        #           전부 6174다(HK 선두 5열이 통째로 빠진 파일. 파일 전체의 성질이지
        #           첫 행만의 사고가 아니다). core/data_io.py는 이 5열 손실을
        #           hk_shift로 복구한다(거기 주석 참고).
        #
        # 등록 레이아웃과 맞는 행이 있으면 그 열수가 정답이다. **하나도 없으면 첫 행이
        # 아니라 훑은 행들의 최빈 열수를 쓴다.** 첫 행을 쓰면 그게 헤더행일 때
        # layout.ncols가 데이터행보다 **커지고**, iter_rows의 `len(toks) < ncols`
        # 가드가 데이터행을 전부 버린다 — 위 콜드 파일에서 실제로 3694행 중 1행
        # (그 헤더행)만 나왔다.
        ncols = 0
        seen: dict[int, int] = {}
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                toks = s.split("	") if "	" in s else s.split()
                n = len(toks)
                if n in CAMPAIGN_LAYOUTS:
                    ncols = n
                    break
                seen[n] = seen.get(n, 0) + 1
                if sum(seen.values()) >= LAYOUT_PROBE_ROWS:
                    break
        if ncols == 0 and seen:
            # 최빈값, 동률이면 좁은 쪽. 넓게 잡으면 iter_rows가 행을 버리고,
            # 좁게 잡으면 안 버린다 — 틀리더라도 데이터를 조용히 잃지 않는 쪽으로.
            ncols = min(seen, key=lambda k: (-seen[k], k))
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=KST)

        lay, in_range = layout_for(ncols, path)
        if lay is not None and in_range and not lay.is_mission:
            missed = missions_not_covering(ncols, path)
            if missed:
                # 이 열 수의 미션(셀 정체)이 이 날짜를 안 덮는다 — 기본(구조) 프로파일로 읽는다.
                print(f"[raw_parser] {os.path.basename(path)}: no mission covers this date "
                      f"({', '.join(f'{m.campaign or m.kind} {m.date_range}' for m in missed)}) "
                      f"→ base profile, structural names {list(lay.spec_blocks())}",
                      file=sys.stderr)
                return FileLayout(
                    path=path, ncols=ncols, kind=f"{lay.kind}(no mission)",
                    hk_map=lay.hk_map, spec_blocks=lay.spec_blocks(), mtime=mtime)
        if lay is not None and not in_range:
            # 같은 열 수지만 캠페인 기간 밖 — 채널 이름은 주장하지 않는다(블록·HK는 유지).
            blocks = spec_blocks_for_ncols(ncols)
            blocks = {k: v for k, v in blocks.items() if v in lay.spec_blocks().values()}
            print(f"[raw_parser] {os.path.basename(path)}: {lay.campaign}: outside date range "
                  f"{lay.date_range} → using structural names {list(blocks)} instead of channel names",
                  file=sys.stderr)
            return FileLayout(
                path=path, ncols=ncols, kind=f"{lay.kind}(outside {lay.campaign})",
                hk_map=lay.hk_map,
                spec_blocks=blocks,
                mtime=mtime,
            )
        if lay is not None:
            return FileLayout(
                path=path, ncols=ncols, kind=lay.kind,
                hk_map=lay.hk_map,
                spec_blocks=lay.spec_blocks(),
                mtime=mtime,
            )
        # 등록 안 된 구성(예: 세 번째 캐비티가 켜진 CAESAR) — HK는 모르지만 스펙트럼
        # 블록은 구조적으로 추론해서 R 계산 등 스펙트럼 레벨 도구는 그대로 돌게 한다.
        # 실제 HK 레이아웃이 확인되면 vigil/profiles 에 그 구성의 프로파일 JSON 을 추가할 것.
        blocks = spec_blocks_for_ncols(ncols)
        return FileLayout(
            path=path, ncols=ncols, kind=f"unknown({len(blocks)}ch structural)",
            hk_map={},
            spec_blocks=blocks,
            mtime=mtime,
        )

    # ── Row-by-row streaming ─────────────────────────────────────────────────
    def iter_rows(self) -> Iterator[ParsedRow]:
        """Stream-parse the file. Skips header / malformed rows silently."""
        for i, line in enumerate(self._iter_data_lines()):
            toks = line.split("\t") if "\t" in line else line.split()
            if len(toks) < self.layout.ncols:
                continue
            try:
                flag = int(float(toks[COL_FLAG]))
            except ValueError:
                continue
            row = ParsedRow(
                row_idx=i,
                time_centisec=self._safe_float(toks[COL_TIME_HI]),
                time_lo=self._safe_float(toks[COL_TIME_LO]),
                exposure=self._safe_float(toks[COL_EXPOSURE]),
                temp_ccd_C=self._safe_float(toks[COL_TEMP_CCD]) / 100.0,
                flag=flag,
                hk=self._extract_hk(toks),
            )
            yield row

    def _iter_data_lines(self) -> Iterator[str]:
        with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                yield s

    def _extract_hk(self, toks: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, (col, scale, unit, kind) in self.layout.hk_map.items():
            if col >= len(toks):
                out[name] = float("nan")
                continue
            try:
                raw = float(toks[col])
            except ValueError:
                out[name] = float("nan")
                continue
            if _is_sentinel(raw):
                out[name] = float("nan")
                continue
            out[name] = raw * scale
        return out

    # ── Spectrum extraction (random access) ──────────────────────────────────
    def get_spectrum(self, row_idx: int, channel: str) -> np.ndarray:
        """Return the spectrum array for a single row & channel.

        Slower than ``iter_rows`` because it scans the file again. Use
        ``iter_rows_with_spectra`` for bulk extraction.
        """
        if channel not in self.layout.spec_blocks:
            raise KeyError(
                f"Channel '{channel}' not in layout. Available: "
                f"{list(self.layout.spec_blocks)}"
            )
        start, end = self.layout.spec_blocks[channel]
        for i, line in enumerate(self._iter_data_lines()):
            if i != row_idx:
                continue
            toks = line.split("\t") if "\t" in line else line.split()
            return np.array([self._safe_float(t) for t in toks[start:end]], dtype=np.float64)
        raise IndexError(f"row {row_idx} not found in {self.path}")

    def iter_rows_with_spectra(
        self, channels: tuple[str, ...] = ("ch1_NO2",)
    ) -> Iterator[tuple[ParsedRow, dict[str, np.ndarray]]]:
        """Stream rows together with selected spectra. Memory-efficient."""
        blocks = {ch: self.layout.spec_blocks[ch] for ch in channels
                  if ch in self.layout.spec_blocks}
        missing = [ch for ch in channels if ch not in self.layout.spec_blocks]
        if missing:
            # 조용히 빼면 '채널 하나가 비었다'를 아무도 모른다(캠페인 기간 밖 파일 등).
            print(f"[raw_parser] {os.path.basename(self.path)}: requested channels {missing} not present "
                  f"(available: {list(self.layout.spec_blocks)})", file=sys.stderr)
        for i, line in enumerate(self._iter_data_lines()):
            toks = line.split("\t") if "\t" in line else line.split()
            if len(toks) < self.layout.ncols:
                continue
            try:
                flag = int(float(toks[COL_FLAG]))
            except ValueError:
                continue
            row = ParsedRow(
                row_idx=i,
                time_centisec=self._safe_float(toks[COL_TIME_HI]),
                time_lo=self._safe_float(toks[COL_TIME_LO]),
                exposure=self._safe_float(toks[COL_EXPOSURE]),
                temp_ccd_C=self._safe_float(toks[COL_TEMP_CCD]) / 100.0,
                flag=flag,
                hk=self._extract_hk(toks),
            )
            specs = {
                name: np.array(
                    [self._safe_float(t) for t in toks[start:end]],
                    dtype=np.float64,
                )
                for name, (start, end) in blocks.items()
            }
            yield row, specs

    # ── Grouping helpers ──────────────────────────────────────────────────────
    def collect_spectra_by_flag(
        self,
        flags: set[int],
        channel: str,
    ) -> list[tuple[ParsedRow, np.ndarray]]:
        """Read the file once and return all (row, spectrum) pairs whose flag
        is in ``flags``. Convenient for R calculation (flags={500, 510}).
        """
        out: list[tuple[ParsedRow, np.ndarray]] = []
        for row, specs in self.iter_rows_with_spectra(channels=(channel,)):
            if row.flag in flags:
                out.append((row, specs[channel]))
        return out

    # ── Time decoding ────────────────────────────────────────────────────────
    def decode_time(self, row: ParsedRow,
                    ref_sec: int = LABVIEW_REF_SEC_2026) -> datetime | None:
        """Decode the LabVIEW timestamp from cols 0-1 into a KST datetime.

        Returns ``None`` if the bytepack value is not plausible (e.g. file
        uses a different time encoding). NOTE: the *absolute* result can be
        off by hours on 2026 Yeosu files (ref_sec mismatch). For plotting,
        prefer anchoring ``ParsedRow.bytepack_sec`` to the file mtime.
        """
        # We need col0 (low 16 bits) and col1 (high 16 bits) — but
        # iter_rows() didn't keep col0. Re-read just that row's first two
        # values. Slow path; intended for occasional use, not every row.
        for i, line in enumerate(self._iter_data_lines()):
            if i != row.row_idx:
                continue
            toks = line.split("\t") if "\t" in line else line.split()
            try:
                c0 = int(float(toks[COL_TIME_LO]))
                c1 = int(float(toks[COL_TIME_HI]))
            except ValueError:
                return None
            bytepack = (c0 << 16) | c1
            this_year_sec = bytepack / 100.0
            labview_total = ref_sec + this_year_sec
            return LABVIEW_EPOCH.replace(tzinfo=KST) + timedelta(seconds=labview_total)
        return None

    def estimate_row_time(self, row: ParsedRow,
                          row_period_sec: float = 0.97) -> datetime:
        """Cheap timestamp estimate using file mtime + row_idx * row_period.

        Use this for plotting / bulk processing where decode_time() is too
        slow. Per ``r_trend_monitor.py`` docstring, row spacing is ~0.97 s.
        """
        return self.layout.mtime + timedelta(seconds=row.row_idx * row_period_sec)

    # ── Utility ────────────────────────────────────────────────────────────
    @staticmethod
    def _safe_float(s: str) -> float:
        try:
            return float(s)
        except (ValueError, TypeError):
            return float("nan")


def block_channel_name(path: str, block_start: int):
    """이 raw 파일에서 `block_start` 열로 시작하는 스펙트럼 블록의 **캠페인 채널 이름**(예 'ANs').

    이름은 코드가 아니라 등록된 캠페인 레이아웃(`register_campaign_layout`, 날짜 범위 포함)이
    정한다 — 어느 블록이 어느 셀인지는 캠페인·배치마다 바뀌기 때문이다(2026-09-27 실험실 raw 는
    같은 6181열인데 block 2053 = 콜드). 레이아웃이 모르는 구성이거나 날짜 범위 밖이면 None.
    파일을 못 읽어도 None(라벨용이라 실패가 결과를 바꾸지 않는다)."""
    try:
        fl = RawParser._detect_layout(path)
    except OSError:
        return None
    lay, in_range = layout_for(fl.ncols, path)
    if lay is None or not in_range or not lay.is_mission:
        return None              # 기본(구조) 프로파일의 ch1/ch2 는 셀 이름이 아니다 — 블록 번호만
    return lay.channel_at(block_start)


def block_label(path: str, block_start: int, prefix: str = "") -> str:
    """표시용 라벨 — 레이아웃이 아는 셀이면 'ANs (block 2053)', 모르면 'block 2053'.
    파일·폴더 **이름**에는 쓰지 말 것: 이름은 블록 번호 기준(캠페인이 바뀌어도 틀리지 않게)."""
    name = block_channel_name(path, block_start) if path else None
    head = f"{prefix} " if prefix else ""
    return f"{head}{name} (block {int(block_start)})" if name else f"{head}block {int(block_start)}"


# ── 채널 정의 로드 — 프로파일 폴더(단일 출처)에서 레이아웃 표를 만든다 ───────────────
_PROFILE_LOAD = autoload_campaign_layouts(verbose=False)
if not CAMPAIGN_LAYOUTS:
    print("[raw_parser] ⚠ No campaign layouts — the profile folder (vigil/profiles) is missing or "
          "unreadable. Raw files will be parsed with structural fallbacks only (no HK map: T/P may "
          "fall back to defaults).", file=sys.stderr)


__all__ = [
    "RawParser",
    "block_channel_name", "block_label",
    "ParsedRow",
    "FileLayout",
    "layout_for", "hk_col", "CAMPAIGN_LAYOUTS",
    "FLAG_HEADER", "FLAG_AMBIENT", "FLAG_ZA", "FLAG_ZA_WAIT", "FLAG_ZA_END",
    "FLAG_HE", "FLAG_HE_WAIT", "FLAG_HE_END",
    "FLAG_STABLE", "FLAG_TRANSITIONAL", "FLAG_NAMES",
    "SPEC_PRIMARY", "SPEC_SECONDARY", "SPEC_BLOCK_A",
    "SPEC_CH1_NO2", "SPEC_CH2_UV",   # legacy aliases
    "spec_blocks_for_ncols",         # 미등록 구성용 구조적 폴백
    "P_SCALE", "LABVIEW_REF_SEC_2026", "LABVIEW_EPOCH", "KST",
]
