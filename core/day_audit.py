"""core/day_audit.py — 측정일 감사(day audit). raw의 교정 블록이 주기대로 들어왔나.

왜 필요한가
-----------
Setup Status는 wavecal·I₀·R·refs·range가 **로드됐는지**만 본다. 정작 중요한 건
**그날 raw에 ZA/He 블록이 주기대로 들어있는지**다. He가 빠진 구간은 R(t)가 그
사이를 외삽하고, 그 결과는 **경로길이가 틀린 농도**가 된다 — 그런데 화면은 초록
체크를 보여준다. 이 모듈은 그 구멍을 RUN 전에 빨간불로 잡는다.

설계
----
* **읽기 전용 진단.** 아무것도 지우거나 고치지 않는다(무결성 헌장 ①⑦: 검증 ≠ 필터).
* **기대 주기를 코드에 박지 않는다.** 기본은 그날 **관측된 간격의 중앙값**이고,
  거기서 크게 벗어난 간격만 결손으로 본다 — 캠페인·장비 구성마다 주기가 다르므로
  데이터가 기준을 정하게 한다(`param_optimizer`가 bounds를 실측 분포에서 뽑는 것과
  같은 원칙). 아는 주기가 있으면 `expected_period_sec`로 넘겨 고정할 수 있다.
* **flag 어휘·bytepack 공식은 `core/raw_parser.py`가 단일 출처.** 여기서 다시
  정의하지 않는다.
* 스펙트럼을 파싱하지 않는다 — 한 줄이 25 KB(파일 ~90 MB)라 전체 파싱하면 하루치
  24파일에 수 분이 걸린다. `split('\\t', 5)`로 앞 5열만 잘라 스트리밍한다.

    from core.day_audit import audit_day        # 자기검증: python -m core.day_audit
    rep = audit_day(r"D:\\CAESAR raw\\yeosu", "2026-09-04")
    print(rep.status, rep.summary())
"""
from __future__ import annotations

import glob
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .raw_parser import (
    COL_FLAG, COL_TIME_HI, COL_TIME_LO,
    FLAG_ZA, FLAG_HE,
    ParsedRow,
)

# 등급 어휘는 health_checks와 같게 유지한다(Setup Status가 둘을 같이 보여준다).
PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
_RANK = {SKIP: 0, PASS: 1, WARN: 2, FAIL: 3}

# 간격이 주기의 몇 배를 넘으면 결손으로 보나. 1.8 = "한 번은 확실히 건너뜀"
# (1.0 근처는 정상 지터, 2.0이면 정확히 한 번 결손이므로 그 사이에 문턱을 둔다).
GAP_FACTOR = 1.8
# 이 배수를 넘으면 연속 결손 — 그 구간 R(t)는 외삽이라 FAIL.
GAP_FACTOR_FAIL = 2.8
# 하루에 이보다 적으면 주기를 논할 표본이 안 된다.
MIN_BLOCKS_FOR_PERIOD = 3


def role_of(flag: int) -> str | None:
    """측정 창(stable)인 flag만 역할로 승격. 전이(wait/setflow/end)는 None.

    R 계산에 실제로 쓰이는 건 안정 구간뿐이라(`data_io.read_scans_via_dataio`),
    감사도 같은 기준으로 센다."""
    if flag == FLAG_ZA:
        return "ZA"
    if flag == FLAG_HE:
        return "He"
    return None


@dataclass
class Block:
    """연속된 같은 역할의 행 묶음 = 교정 스캔 한 번."""
    role: str
    t0: datetime
    t1: datetime
    n_rows: int
    file: str

    @property
    def duration_sec(self) -> float:
        return (self.t1 - self.t0).total_seconds()


@dataclass
class Gap:
    """블록 사이의 비정상적으로 긴 간격 = 교정 시퀀스가 건너뛴 자리."""
    role: str
    after: datetime
    before: datetime
    seconds: float
    period_sec: float

    @property
    def missed(self) -> int:
        """건너뛴 것으로 추정되는 횟수. 0이면 '길긴 한데 한 번도 아님'."""
        if self.period_sec <= 0:
            return 0
        return max(0, int(round(self.seconds / self.period_sec)) - 1)


@dataclass
class AuditReport:
    date: str
    files: list = field(default_factory=list)
    blocks: dict = field(default_factory=dict)     # role → [Block]
    gaps: list = field(default_factory=list)       # [Gap]
    periods: dict = field(default_factory=dict)    # role → 중앙값 주기(초)
    status: str = SKIP
    messages: list = field(default_factory=list)   # [(status, text)]
    span: tuple = (None, None)

    def summary(self) -> str:
        return " · ".join(f"[{s}] {m}" for s, m in self.messages) or "(no findings)"

    def to_meta(self) -> dict:
        """`.meta.json`에 넣을 요약. 그림이 아니라 판정과 수치만."""
        return {
            "status": self.status,
            "date": self.date,
            "files": len(self.files),
            "blocks": {r: len(b) for r, b in self.blocks.items()},
            "period_sec": {r: round(p, 1) for r, p in self.periods.items()},
            "gaps": [{"role": g.role, "after": g.after.isoformat(timespec="seconds"),
                      "seconds": round(g.seconds, 1), "missed": g.missed}
                     for g in self.gaps],
            "messages": [f"{s}: {m}" for s, m in self.messages],
        }


def iter_flag_times(path: str):
    """(row_idx, bytepack_sec, flag) 스트리밍. 스펙트럼은 건드리지 않는다.

    bytepack의 **절대** 시각은 LABVIEW_REF_SEC가 틀릴 수 있어 못 믿지만 **행 간
    간격**은 믿을 수 있다(raw_parser 주석) → 호출부가 mtime에 앵커한다."""
    want = max(COL_FLAG, COL_TIME_LO, COL_TIME_HI)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t", want + 1)
            if len(parts) <= want:
                continue
            try:
                flag = int(float(parts[COL_FLAG]))
                # bytepack 공식은 raw_parser가 정본 — 여기서 다시 쓰지 않고
                # ParsedRow에 태워 그쪽 property를 쓴다.
                sec = ParsedRow(row_idx=i,
                                time_centisec=float(parts[COL_TIME_HI]),
                                time_lo=float(parts[COL_TIME_LO]),
                                exposure=float("nan"), temp_ccd_C=float("nan"),
                                flag=flag, hk={}).bytepack_sec
            except (ValueError, IndexError):
                continue
            yield i, sec, flag


def file_blocks(path: str, mtime: datetime | None = None) -> list:
    """파일 하나 → 교정 블록 목록. 시각은 bytepack 간격을 파일 mtime에 앵커.

    mtime을 명시하면 그 값을 쓴다(테스트·재현용)."""
    rows = [(i, s, f) for i, s, f in iter_flag_times(path)]
    if not rows:
        return []
    if mtime is None:
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
    last = next((s for _, s, _ in reversed(rows) if not math.isnan(s)), None)

    def at(sec):
        if last is None or math.isnan(sec):
            return None
        return mtime - timedelta(seconds=(last - sec))

    blocks, cur = [], None
    for _i, sec, flag in rows:
        role = role_of(flag)
        t = at(sec)
        if role is None or t is None:
            cur = None                      # 역할이 끊기면 블록도 끊긴다
            continue
        if cur is not None and cur.role == role:
            cur.t1 = t
            cur.n_rows += 1
        else:
            cur = Block(role=role, t0=t, t1=t, n_rows=1, file=path)
            blocks.append(cur)
    return blocks


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _worst(a, b):
    return a if _RANK[a] >= _RANK[b] else b


def day_files(raw_dir: str, date: str) -> list:
    """그날의 raw 파일. 이름 규약 `YYYY-MM-DD-NNN.dat`(_load_folder와 같은 전제)."""
    return sorted(glob.glob(os.path.join(raw_dir, f"{date}-*.dat")))


def audit_day(raw_dir: str, date: str, *, expected_period_sec: dict | None = None,
              roles=("ZA", "He"), files=None) -> AuditReport:
    """그날 raw의 ZA/He 블록 타임라인을 훑어 누락·간격초과를 판정한다.

    `expected_period_sec`: {'ZA': 300, 'He': 900} 처럼 아는 주기를 고정하고 싶을 때.
    생략하면 그날 관측된 간격의 중앙값을 주기로 삼는다.
    """
    rep = AuditReport(date=date)
    rep.files = list(files) if files is not None else day_files(raw_dir, date)
    if not rep.files:
        rep.status = SKIP
        rep.messages.append((SKIP, f"{date}: raw file not found in {raw_dir}"))
        return rep

    all_blocks = []
    for fp in rep.files:
        try:
            all_blocks.extend(file_blocks(fp))
        except OSError as e:
            rep.messages.append((WARN, f"unreadable: {os.path.basename(fp)} ({e})"))
    all_blocks.sort(key=lambda b: b.t0)
    if all_blocks:
        rep.span = (all_blocks[0].t0, all_blocks[-1].t1)

    status = PASS
    for role in roles:
        bl = [b for b in all_blocks if b.role == role]
        rep.blocks[role] = bl
        if not bl:
            # 하루 종일 한 번도 없음 = R(t)가 이 날 전체를 외삽한다
            status = _worst(status, FAIL)
            rep.messages.append((FAIL, f"{role}: no calibration block all day "
                                       f"-> R(t) is extrapolated across {date}"))
            continue

        starts = [b.t0 for b in bl]
        deltas = [(b - a).total_seconds() for a, b in zip(starts, starts[1:])]
        fixed = (expected_period_sec or {}).get(role)
        if fixed:
            period = float(fixed)
        elif len(deltas) >= MIN_BLOCKS_FOR_PERIOD - 1:
            period = _median(deltas)
        else:
            period = 0.0
        rep.periods[role] = period

        if period <= 0:
            status = _worst(status, WARN)
            rep.messages.append((WARN, f"{role}: only {len(bl)} block(s) - too few to "
                                       f"judge cadence (need >= {MIN_BLOCKS_FOR_PERIOD})"))
            continue

        for (a, b), d in zip(zip(starts, starts[1:]), deltas):
            if d <= GAP_FACTOR * period:
                continue
            gap = Gap(role=role, after=a, before=b, seconds=d, period_sec=period)
            rep.gaps.append(gap)
            sev = FAIL if d > GAP_FACTOR_FAIL * period else WARN
            status = _worst(status, sev)
            rep.messages.append((sev,
                f"{role}: {d / 60:.0f} min gap after {a:%H:%M} "
                f"(period {period / 60:.0f} min, ~{gap.missed} missed) "
                f"-> R(t) interpolated across it"))

        if not any(g.role == role for g in rep.gaps):
            rep.messages.append((PASS, f"{role}: {len(bl)} blocks, every "
                                       f"{period / 60:.0f} min - no gap"))

    rep.status = status
    return rep


# ── 자기검증 ────────────────────────────────────────────────────────────────
def _demo():
    """합성 raw로 정상/결손/전무 세 경우를 확인한다."""
    import tempfile

    d = tempfile.mkdtemp()
    t0 = datetime(2026, 9, 4, 0, 0, 0)

    def synth(name, plan):
        """plan = [(flag, n_rows)] 순서대로. 1행 = 1초."""
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as fh:
            sec = 0
            for flag, n in plan:
                for _ in range(n):
                    cs = int(sec * 100)
                    lo, hi = (cs >> 16) & 0xFFFF, cs & 0xFFFF
                    # col0=HIGH, col1=LOW (raw_parser: bytepack=(col0<<16)|col1)
                    fh.write(f"{lo}\t{hi}\t0\t0\t{flag}\t0\n")
                    sec += 1
        os.utime(p, (t0.timestamp() + sec, t0.timestamp() + sec))
        return p, sec

    # 정상: ZA 30s가 300s마다 6번
    normal = [(FLAG_ZA, 30)] + [(1, 270), (FLAG_ZA, 30)] * 5
    p1, _ = synth("2026-09-04-001.dat", normal)
    r = audit_day(d, "2026-09-04", files=[p1])
    assert len(r.blocks["ZA"]) == 6, r.blocks["ZA"]
    assert abs(r.periods["ZA"] - 300) < 2, r.periods
    assert not [g for g in r.gaps if g.role == "ZA"], r.summary()
    assert r.status == FAIL and any("He" in m for _s, m in r.messages), r.summary()

    # ZA만 보면 PASS여야 한다(He를 안 물으면)
    r_za = audit_day(d, "2026-09-04", files=[p1], roles=("ZA",))
    assert r_za.status == PASS, r_za.summary()

    # 결손: 3번째 ZA가 통째로 빠짐 → 600s 간격
    holed = [(FLAG_ZA, 30), (1, 270), (FLAG_ZA, 30), (1, 570), (FLAG_ZA, 30),
             (1, 270), (FLAG_ZA, 30), (1, 270), (FLAG_ZA, 30)]
    p2, _ = synth("2026-09-05-001.dat", holed)
    r2 = audit_day(d, "2026-09-05", files=[p2], roles=("ZA",))
    gaps = [g for g in r2.gaps if g.role == "ZA"]
    assert len(gaps) == 1 and gaps[0].missed == 1, [(g.seconds, g.missed) for g in gaps]
    assert r2.status == WARN, r2.summary()          # 1회 결손 = WARN

    # 연속 결손(2회) = FAIL
    holed2 = [(FLAG_ZA, 30), (1, 270), (FLAG_ZA, 30), (1, 870), (FLAG_ZA, 30),
              (1, 270), (FLAG_ZA, 30), (1, 270), (FLAG_ZA, 30)]
    p3, _ = synth("2026-09-06-001.dat", holed2)
    r3 = audit_day(d, "2026-09-06", files=[p3], roles=("ZA",))
    assert r3.status == FAIL, r3.summary()
    assert [g.missed for g in r3.gaps] == [2], [g.missed for g in r3.gaps]

    # 전이 flag는 블록으로 안 센다(측정 창만 센다)
    trans = [(502, 30), (FLAG_ZA, 30), (503, 30), (1, 240)] * 4
    p4, _ = synth("2026-09-07-001.dat", trans)
    r4 = audit_day(d, "2026-09-07", files=[p4], roles=("ZA",))
    assert len(r4.blocks["ZA"]) == 4, r4.blocks["ZA"]
    assert all(abs(b.duration_sec - 29) < 2 for b in r4.blocks["ZA"])

    # He 섞인 하루 — 두 역할이 독립적으로 판정된다
    both = [(FLAG_ZA, 30), (1, 270)] * 3 + [(FLAG_HE, 30), (1, 870)] * 3
    p5, _ = synth("2026-09-08-001.dat", both)
    r5 = audit_day(d, "2026-09-08", files=[p5])
    assert len(r5.blocks["ZA"]) == 3 and len(r5.blocks["He"]) == 3
    assert abs(r5.periods["He"] - 900) < 3, r5.periods

    # 고정 주기를 주면 관측 중앙값 대신 그걸 쓴다
    r6 = audit_day(d, "2026-09-04", files=[p1], roles=("ZA",),
                   expected_period_sec={"ZA": 60})
    assert r6.status == FAIL and r6.periods["ZA"] == 60, r6.summary()

    # 파일 없음 → SKIP (죽지 않는다)
    assert audit_day(d, "1999-01-01").status == SKIP

    # meta 직렬화가 JSON으로 나가는지
    import json
    json.dumps(r2.to_meta())
    print("day_audit self-check OK:", r2.summary())


if __name__ == "__main__":
    _demo()
