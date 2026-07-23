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

## 출처와 주의

- 예제 값의 근거는 `core/raw_parser.py`의 컬럼 레이아웃 + HK 상대 오프셋
  **VALUE-INSPECTION 기록**(2026-05 여수 Cold/Hot)이다. 그 파일이 현 CAESAR 레이아웃의
  1차 사료다.
- **경보 밴드(`alert`)는 잠정값**이다. 실제 정상 범위는 캠페인 초기 데이터로 튜닝해야 한다.
  확신 없는 필드는 밴드를 비워 두었다(표시만).
- Cold 프로파일의 `sentinel`(rel 6, raw 15000~15500)은 정체 미상 열이라 감시에서 제외
  대상이다(표시만). 라벨에 `?`를 남겨 둔다.
- `tempcell2`(Hot rel 26)는 2026 여수에서 5/27 이전 고장 이력이 있다 → **센서 결측 감지**
  (§1.3)의 대표 사례. 밴드 대신 "값이 고정/비정상이면 결측 플래그" 규칙으로 다루는 게 맞다
  (M1에서 구현).
- 채널 라벨(`PNs`/`ANs`/`NO2`)은 **표시용일 뿐**이다. 캐비티 교체·채널 재배치가 있으면
  프로파일만 바꾸고 코드는 손대지 않는다 — 그게 이 계층의 존재 이유다.
