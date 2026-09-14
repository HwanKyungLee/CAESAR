"""oculus/profile.py — 하위호환 껍데기. 실제 구현은 `core/profile.py`.

2026-09-14에 로더를 core로 옮겼다 — 캠페인 프로파일이 Oculus 감시뿐 아니라 Augur의
raw 파싱 레이아웃(`core/raw_parser.load_campaign_layout`)도 정하게 됐고, 같은 포맷을
두 곳에서 따로 읽으면 반드시 어긋나기 때문이다. 기존 `from oculus.profile import ...`는
전부 그대로 동작한다.
"""
from core.profile import *          # noqa: F401,F403
from core.profile import (          # noqa: F401  — 명시 re-export
    DEFAULT_PROFILE_DIR, SCHEMA_PATH, SEVERITY_ALARM, SEVERITY_NONE, SEVERITY_WARN,
    Autodetect, Cadence, Channel, ConcentrationConfig, Flags, HK, HKField, Header,
    Match, Profile, ProfileError, ProfileSet, ReflectanceConfig, ScaledField,
    TimeBytepack, load_profile, load_profiles, validate_profile_dict,
)
