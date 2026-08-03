# Oculus 인스트루먼트 프로파일

Oculus가 "특정 장비 구성에 박제되지 않고 **어떤 CAESAR raw든 읽어** 모니터링한다"는 원칙
(설계문서 §0-A.6 · §2-A)을 실현하는 설정 계층이다. `Cold`/`Hot`/`PNs`/`ANs` 같은 이름은
채널 구성·캐비티 선택에 따라 매번 달라지므로, 이런 것들을 코드에서 빼내 **프로파일 JSON**으로
옮긴다. 파싱·경보 로직은 프로파일이 선언한 열지도·밴드·flag 규약만 본다.

## 파일

| 파일 | 역할 |
|---|---|
| `_schema.json` | 프로파일 JSON Schema (draft 2020-12). 모든 프로파일은 이걸로 검증된다. |
| `caesar_cold.example.json` | Cold 캐비티 레이아웃 예제 (6179열, NO₂ 1채널) |
| `caesar_hot.example.json` | Hot 캐비티 레이아웃 예제 (6181열, PNs+ANs 2채널) |

`.example.` 프로파일은 **기본값(씨앗)**이다. 새 캠페인은 이걸 복제해
`caesar_hot_<campaign>.json` 처럼 이름 붙이고 값만 조정한다.

## 동작 방식

1. Oculus는 이 폴더의 프로파일을 전부 로드한다.
2. 감시 폴더에서 raw 파일을 만나면 `match`(우선 `n_columns`, 보조 `filename_glob`)로
   프로파일을 **라우팅**한다. → 한 인스턴스가 Cold·Hot 등 여러 레이아웃을 동시에 처리(§0-A.5).
3. 매칭된 프로파일의 열지도로 헤더·채널·HK를 뽑고, `flags`로 대기/ZA/He를 구분하고,
   `hk[].alert`·`saturation`·`cadence`로 경보를 판정한다.

## 필드 요약

- **`match`** — 파일 → 프로파일 라우팅. `n_columns`가 1차 판별(견고), `filename_glob` 보조.
- **`header`** — CAESAR 공통 선두 열. `time_bytepack`은 `(raw[hi]<<16)|raw[lo]` = 연초 기준
  센티초. `state_flag_col`이 측정 상태.
- **`flags`** — **의미 역할 → flag 숫자** 매핑. 현재 CAESAR는 대기 1 / ZA 500 / He 510이지만
  값은 여기서만 정의(로직은 `flags.za` 같은 역할 이름으로 접근).
- **`channels`** — 스펙트럼 블록. `id`는 로직이 참조하는 안정 식별자, `label`은 **표시용
  문자열**(로직이 여기 의존 금지). `role`이 `signal`인 것만 피팅·감시. `columns`는 절대
  열범위 `[start, end]`(양끝 포함).
- **`autodetect`** — `columns`를 비운 채널을, 첫 몇 스캔의 **블록별 최대값**으로 signal/noise
  분류(신호 ≈3~5만, 노이즈 ≈700~900). 프로파일이 부분적이거나 새 구성일 때 무설정 폴백.
- **`hk`** — Housekeeping 열지도. `start_col` + 각 필드 `rel`(상대 오프셋), `scale`/`offset`
  로 물리단위 환산(÷100 → `scale:0.01`, 압력 → `scale:0.6895`), `nominal`은 기준선,
  **`alert.warn`(→P2) / `alert.alarm`(→P1)** 밴드는 **선택**. 밴드가 없으면 "표시만, 경보
  없음"(오탐 방지 — 확실한 것만 경보).
- **`saturation.adc_max`** — 이 값 초과 픽셀은 포화(현 CAESAR ≈60000).
- **`cadence`** — 정상 유입 리듬. `scan_interval_sec`(현 1초), `file_rollover_sec`(현 3600),
  `liveness_grace_sec`(이 시간 넘게 새 행 없으면 측정 정지 → **P0**).

## 프로파일 검증

```bash
pip install jsonschema
python -c "import json,jsonschema; s=json.load(open('oculus/profiles/_schema.json')); \
jsonschema.validate(json.load(open('oculus/profiles/caesar_hot.example.json')), s); print('valid')"
```

## 실데이터 검증 (2026-06-02 샘플, Hot 1행 / Cold 4행)

프로파일을 실제 raw로 대조한 결과 — **핵심은 전부 통과**:

| 항목 | 결과 |
|---|---|
| 열 수 | Hot **6181** / Cold **6179** — 선언과 일치 ✅ |
| `route()` 라우팅 | 두 파일 모두 올바른 프로파일 선택 ✅ |
| bytepack 시각 | `2026-06-02 05:15:25.64` — **파일명 날짜와 일치** ✅ |
| **스캔 간격** | **0.96~0.97 s** — 1초 케이던스 확증 ✅ |
| flag | `1` = atmosphere ✅ |
| 채널 최대값 | Hot: noise 1011 / PNs **50833** / ANs **46504**, Cold: noise 502 / NO₂ **6445** / noise 524 ✅ |
| 자동탐지 | 선언 role과 완전 일치 (Hot `noise,signal,signal` · Cold `noise,signal,noise`) ✅ |
| HK 환산 | ANs오븐 **299.96**°C(기대 300), PNs오븐 **180.07**°C(180), 셀히터 **74.98**°C(75), PNs압 **958.4**mbar(965), ANs압 **913.6**mbar(915), Cold캐비티압 **999.8**mbar(1000) ✅ |

**이 검증으로 고친 것**

- `signal_min_max` 5000 → **2500**. Cold NO₂ 신호가 6445로 5000과 1.3배 차이밖에 안 나
  광원이 약해지면 노이즈로 오분류될 위험이 있었다. 실측 노이즈 최대 1011과 최소 신호 6445의
  기하평균(≈2550) 부근으로 낮춰 양쪽에 ~2.5배 여유 확보.
- Cold `t_cavity` 밴드 `[20,28]` → **`[15,40]`**, nominal 24 → **28.8**. 실측 28.77 °C가
  잠정 밴드를 벗어나 **오경보(⚠️WARN)가 났다**. 단일 시점이라 좁게 재설정하지 않고 넉넉히
  넓혔다 — 제대로 된 밴드는 전체 파일 분포를 봐야 한다.
- Cold `sentinel`의 `nominal: 15250` 제거. 실측 0으로 기록과 불일치 — 정체 미상 열이므로
  기댓값을 주장하지 않는다(표시만).

**미해결 (추가 데이터 필요)**

- Hot `tempcell3`(rel 27)·`t_spectrometer`(rel 28)가 **0**으로 읽히는데, HK 블록 **끝(rel 31)에
  3059**(=30.59 °C?)라는 온도스러운 값이 있다. 센서 고장인지 열 매핑이 한 칸 어긋난 건지
  이 샘플로는 판정 불가 → **추측으로 바꾸지 않고 그대로 둔다.**
- ZA(500)/He(510) flag는 이 샘플에 없다(전부 atmosphere). R 감시 검증은 교정 스캔이 포함된
  구간이 필요하다.

## 출처와 주의

- 예제 값의 근거는 `core/raw_parser.py`의 컬럼 레이아웃 + HK 상대 오프셋
  **VALUE-INSPECTION 기록**(2026-05 여수 Cold/Hot)이며, 위 2026-06-02 샘플로 교차검증했다.
- **경보 밴드(`alert`)는 여전히 잠정값**이다. 위 검증은 단일 시점(Hot 1행·Cold 4행)이라
  분포가 아니라 "말이 되는 값인가"만 확인한 수준이다. 확신 없는 필드는 밴드를 비워 둔다(표시만).
- `tempcell2`(Hot rel 26)는 2026 여수에서 5/27 이전 고장 이력이 있다 → **센서 결측 감지**
  (§1.3)의 대표 사례. 밴드 대신 "값이 고정/비정상이면 결측 플래그" 규칙으로 다루는 게 맞다
  (M1에서 구현).
- 채널 라벨(`PNs`/`ANs`/`NO2`)은 **표시용일 뿐**이다. 캐비티 교체·채널 재배치가 있으면
  프로파일만 바꾸고 코드는 손대지 않는다 — 그게 이 계층의 존재 이유다.
