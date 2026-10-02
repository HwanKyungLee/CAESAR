# CAESAR 인스트루먼트 프로파일 — 채널 정의의 단일 출처

**raw 파일의 채널 정의는 이 폴더의 JSON 한 곳에만 있다**(2026-10-02 단일화). Augur
(`core/raw_parser` → 알파·R·핏의 블록·HK·n_air T/P)와 Vigil(실시간 감시)이 **같은 파일**을 읽는다.
예전엔 같은 사실이 세 곳(raw_parser 내장 표, data_io 의 채널↔센서 짝, 이 폴더)에 있어서 채널을
추가하면 세 곳을 같이 고쳐야 했고, 한쪽만 고치면 Augur 와 Vigil 이 다른 채널을 봤다.

`Cold`/`Hot`/`PNs`/`ANs` 같은 이름은 채널 구성·캐비티 선택에 따라 매번 달라지므로 코드에 두지
않는다. 파싱·경보 로직은 프로파일이 선언한 열지도·채널·센서·밴드·flag 규약만 본다.

## 파일

| 파일 | 역할 |
|---|---|
| `_schema.json` | 프로파일 JSON Schema (draft 2020-12). 모든 프로파일은 이걸로 검증된다. |
| `base_hot_6181.json` | **기본(구조)** Hot 6181열 — 블록 ch0/ch1/ch2, HK·flag·주기. 셀 정체 없음 |
| `base_cold_6179.json` | **기본(구조)** Cold 6179열 |
| `base_cold_6174.json` | **기본(구조)** Cold 6174열 (6/11~6/15 — HK 선두 5열 결손, 아래 §HK 열 근거) |
| `caesar_hot.example.json` | **미션** 2026 여수 Hot — ch1=ANs, ch2=PNs, 센서·FitSet·R, **파일 날짜 2026-05-01~08-31** |
| `caesar_cold.example.json` | **미션** 2026 여수 Cold — ch1=NO₂ (날짜 제한 없음) |
| `caesar_cold_6174.example.json` | **미션** 2026 여수 Cold 6174 — ch1=NO₂ |

**두 층이다.** 기본(구조) 프로파일은 열 수마다 하나 — raw 를 *읽는 법*(블록 위치, HK 열지도, flag, 주기)
만 담고 어떤 배치든 맞는다. 미션(`"base": "<기본 id>"`)은 그 위에 *그 기간의 정체* — 블록 이름(ANs…),
`cavity` 센서, FitSet(`concentration`), R(`reflectance`), `match.date_range` — 만 얹는다(구조는 못 바꾼다:
열 이동·없는 블록·열 수 변경은 로드 오류). 파일 날짜를 덮는 미션이 있으면 미션, 없으면 기본으로 읽는다:
Augur 는 블록 이름 ch1/ch2 + 옛 슬롯 규칙 T/P, Vigil 은 **HK·블록 밝기(빛이 들어오는 블록만)·포화·유입**
을 감시하고 농도·R 만 빠진다(P2 "No mission … Load the mission"). 그래서 Vigil 은 미션 없이 어디서
켜도 동작한다.

`.example.` 프로파일은 **기본값(씨앗)**이다. 새 캠페인은 이걸 복제해
`caesar_hot_<campaign>.json` 처럼 이름 붙이고 값만 조정한다.

## 동작 방식

0. **Augur**: `core/raw_parser` 가 import 때 이 폴더를 읽어 raw 레이아웃 표를 만든다(열 수 +
   파일 날짜 → 구성). 블록 이름·HK 열·채널별 압력/온도 센서가 전부 여기서 온다. 폴더가 없거나
   못 읽으면 stderr 로 경고하고 구조적 폴백(HK 없음)으로 파싱한다.
1. Vigil은 이 폴더의 프로파일을 전부 로드한다.
2. 감시 폴더에서 raw 파일을 만나면 `match`(우선 `n_columns`, 보조 `filename_glob`)로
   프로파일을 **라우팅**한다. → 한 인스턴스가 Cold·Hot 등 여러 레이아웃을 동시에 처리(§0-A.5).
3. 매칭된 프로파일의 열지도로 헤더·채널·HK를 뽑고, `flags`로 측정 단계를 구분하고,
   `hk[].alert`·`saturation`·`cadence`로 경보를 판정한다.

## 필드 요약

- **`match`** — 파일 → 프로파일 라우팅. `n_columns`가 1차 판별(견고), `filename_glob` 보조,
  **`date_range`** `["YYYY-MM-DD","YYYY-MM-DD"]` = 파일명 날짜가 이 밖이면 이 프로파일을 쓰지
  않는다(같은 열 수인데 배치가 바뀐 경우를 날짜로 나눈다). 같은 열 수의 프로파일끼리 날짜가 겹치면
  Augur 가 등록을 거부한다.
- **`kind`·`campaign`** — 결과 헤더 `raw_layout` 줄에 남는 이름(예 `hot`, `2026-yeosu`). 표시용.
- **`header`** — CAESAR 공통 선두 열. `time_bytepack`은 `(raw[hi]<<16)|raw[lo]` = 연초 기준
  센티초. `state_flag_col`이 측정 상태.
- **`flags`** — **의미 역할 → flag 숫자** 매핑. 역할 이름은 **열린 집합**이라 새 단계가
  생겨도 스키마 수정 없이 받는다. 로직은 `flags.za_inject` 같은 역할 이름으로 접근하며
  숫자를 직접 보지 않는다. (규약 표는 아래 §교정 시퀀스 참조)
- **`channels`** — 스펙트럼 블록. `id`는 로직이 참조하는 안정 식별자, `label`은 **표시용
  문자열**(로직이 여기 의존 금지). `role`이 `signal`인 것만 피팅·감시. `columns`는 절대
  열범위 `[start, end]`(양끝 포함). Augur 의 채널 번호는 블록 위치다(1 = 2053, 2 = 4101).
  **`cavity`** `{pressure_hk: [...], temperature_hk: [...]}` = 이 채널 캐비티의 압력·기체온도
  센서(hk 키) **우선순위 목록** — 앞 센서가 결측(0/65535)이면 다음. Augur 의 n_air(ppb 밀도 보정)와
  Vigil 의 농도·R 이 모두 이걸 쓴다. 목록이 다 결측이면 Augur 는 25 °C·1013.25 mbar + 경고.
- **`autodetect`** — `columns`를 비운 채널을, 첫 몇 스캔의 **블록별 최대값**으로 signal/noise
  분류(실측: 신호 6,445~50,833 / 노이즈 502~1,011). 프로파일이 부분적이거나 새 구성일 때 무설정 폴백.
- **`hk`** — Housekeeping 열지도. `start_col` + 각 필드 `rel`(상대 오프셋), `scale`/`offset`
  로 물리단위 환산(÷100 → `scale:0.01`, 압력 → `scale:0.6895`), `nominal`은 기준선,
  **`alert.warn`(→P2) / `alert.alarm`(→P1)** 밴드는 **선택**. 밴드가 없으면 "표시만, 경보
  없음"(오탐 방지 — 확실한 것만 경보). **`alert.phases`**로 밴드가 유효한 측정 구간을
  한정할 수 있다(예: `["sampling"]` → 교정 중엔 평가 안 함).
- **`saturation.adc_max`** — 이 값 초과 픽셀은 포화. 현 CAESAR **64000**
  (16비트 한계 65535, He 교정 구간이 정상적으로 61,387까지 밝아짐 — §교정 시퀀스 참조).
- **`cadence`** — 정상 유입 리듬. `scan_interval_sec`(실측 ≈0.965초 = exposure 900ms + 오버헤드),
  `file_rollover_sec`(현 3600),
  `liveness_grace_sec`(이 시간 넘게 새 행 없으면 측정 정지 → **P0**).

## 채널을 추가하거나 배치가 바뀌었을 때 — 미션 패키지 (권장)

**코드는 고치지 않는다.** Augur Setup 탭 **"Vigil…"** 버튼 → *Export mission for Vigil*:

1. FitSet(저장된 것)과 미션 이름·**시작 날짜**를 정한다. 같은 열 수의 옛 미션과 날짜가 겹치면 설치가
   거부된다 — 옛 미션의 끝 날짜를 먼저 정할 것.
2. FitSet 채널마다 **raw 구성(hot 6181 / cold 6179 …)·블록(ch1 = 2053, ch2 = 4101, ch0 = 5)·셀 이름·
   압력 센서·기체온도 센서**를 고른다(같은 블록의 기존 미션 값이 기본으로 채워진다). FitSet 의
   `data_label` 은 쓰지 않는다 — 뒤바뀐 이력이 있다.
3. **Check with raw…** — 그 구성의 raw 파일 하나로 블록마다 밝기·LED 봉우리·"핏 창이 반치 구간 안인가"를
   보여 주고 스펙트럼을 그린다. **셀 정체는 LED 모양으로 판정**(블록 번호·기억 금지 — 2026-09 오판).
4. **Export…** → 폴더 하나(아래). 기본으로 이 PC 의 Augur 에도 설치된다(`vigil/profiles/missions/` —
   git 으로 커밋하면 다른 분석 PC 도 받는다).
5. 그 폴더를 USB 로 측정 PC 에 옮기고 Vigil 대시보드 **"Load mission…"** → 검사(파일·해시·날짜 겹침) 후
   Vigil 상태 폴더의 `missions/` 에 설치되고, 그 날짜의 파일에서 농도·R 이 켜진다.

```
<미션>/manifest.json          형식·만든 때·Augur 판·원본 FitSet·파일별 sha1·출처 문자열
       fitset.json            FitSet 사본 — 경로는 이 폴더 기준 상대(어디에 두든 열린다)
       wavecal/<wl_dir>/…  refs/<채널 키>/…   사본(원본은 읽기만)
       base_*.json            바탕 기본 프로파일 사본 — PC 마다 같은 구조로 합쳐진다
       mission_<base>.json    셀 이름·센서·FitSet 채널 키(fitset_channel)·date_range
```

손으로 JSON 을 쓸 수도 있다(이 폴더에 `"base": "caesar_cold_base"` 미션 파일) — 그때도 날짜 겹침·없는
블록·구조 변경은 로드 단계에서 막힌다(`python tools/test_raw_layout.py`, `python vigil/test_profile.py`).

그러면 Augur 는 그 날짜 이후 파일에서 그 블록을 그 채널로 읽고 그 채널 센서로 T/P 를 고르며, Vigil 은
채널마다 농도·R·램프 감시기를 따로 만든다. 미션이 없는 날짜는 기본 프로파일(구조)로 읽힌다.

## 측정 PC 배포 (인터넷 없음 — USB)

측정 PC 는 git 을 쓸 수 없다고 보고 설계했다.

- **프로그램**(Augur/Vigil 폴더)은 한 번 USB 로 옮긴다 — 기본 프로파일이 안에 있어 미션 없이도 Vigil 이
  HK·밝기·유입을 감시한다.
- **미션**은 위의 미션 패키지 폴더만 옮긴다(FitSet·레퍼런스·wavecal 이 다 들어 있다 — 경로 문제 없음).
  예전 `tools/bundle_vigil_deps.py`(대상 PC 절대경로로 다시 쓰기)는 미션 패키지로 대체돼 지웠다.
  Vigil 의 'Augur data…'(다른 PC 의 Augur Output 아래에서 경로 찾기)는 **절대경로를 가진 옛 미션**
  (저장소의 여수 미션 등)용으로 남겨 둔다 — 새 미션은 패키지로 옮기면 필요 없다.
- **어느 PC 가 어느 정의를 쓰는지는 해시로 대조한다.** 프로파일마다
  `파일@판#내용해시8[+바탕@판#해시8]` 문자열이 남는다:
  - Vigil — 시작·미션 불러올 때 `status.jsonl` 에 `profiles loaded: …` / `Mission loaded: …`
  - Augur — 알파 헤더 `# raw_layout: … profile=…`, raw 입력 결과의 meta `raw_layout.profile`
  - 패키지 — `manifest.json` 의 `provenance`
  같은 문자열이면 같은 정의다(줄바꿈 CRLF/LF 차이는 해시에서 무시).

## HK 열 근거 (옛 core/raw_parser 내장 표에서 옮김, 2026-10-02)

옛 이름 → 프로파일 키: `ANs_oven`→`oven_ans_setpoint`, `PNs_oven`→`oven_pns_setpoint`,
`temppreh`→`preheater`, `cavity_gas_T`→`cell_heater`, `P_PNs`→`p_pns_cavity`(6162),
`P_ANs`→`p_ans_cavity`(6164), `tempsptrm`→`t_spectrometer`, `cavity_P`→`p_cavity`,
`cavity_T`→`t_cavity`. 열 번호·scale 은 그대로다(`tools/test_raw_layout.py` 가 옛 표를 기준값으로 고정).

- **핫 전수 sentinel 열**(2026-09-15, 1314개 × 5행): `templed4`(6152)·`tempcell3`(6176)·
  `t_spectrometer`(6177)은 한 번도 실측값이 없다(항상 0 또는 65535). 반면 지도에 이름 없던
  **6180(`unknown_rel31`)은 1314개 중 1239개 파일에서 median 29.74 °C** — 콜드 분광기 온도(6174,
  26.98 °C)와 같은 계열로 보여 **핫 분광기 온도는 6180일 가능성이 높다.** 하드웨어 사실이라 계기
  담당자 확인 전에는 바꾸지 않는다. (campaigns/yeosu_2026/hot_cavity_t 스크립트는 핫 6174 를
  'T_spt' 라 부르는데 여기선 `tempcell1` — 이름 충돌 주의.)
- **`cell_heater`(6155)는 셀히터 설정값(~75 °C)** 이지 기체 온도가 아니다. cavity 목록의 마지막
  폴백 — 쓰이면 ppb 가 ~15 % 과대.
- **`tempcell2`(6175)는 5/27 10:56 까지 고장.** 셀 온도 센서의 캐비티 짝(1→2053, 2→4101)은 데이터로
  특정 불가(항상 +3.1–3.4 °C 차, 영향 < 0.1 %).
- **6174열 콜드(2026-06-11-020 ~ 06-15-026)** 는 다른 캐비티가 아니라 HK 블록 **선두 5열**이 빠진
  것이다(전수 748개 중 97개, 양쪽 경계가 DAQ 재시작 직후). 6174행을 +5 이동하면 6179행과 정확히
  겹친다(cavity_P 1466↔1462 · cavity_T 3012↔2948). 명목 열로 읽으면 t_cavity 가 33.93 °C(진값
  29.16 °C) — 둘 다 그럴듯해서 범위검사로 안 걸린다. 그래서 `caesar_cold_6174` 의 rel 은 전부 -5.

## 프로파일 검증

```bash
pip install jsonschema
python -c "import json,jsonschema; s=json.load(open('vigil/profiles/_schema.json')); \
jsonschema.validate(json.load(open('vigil/profiles/caesar_hot.example.json')), s); print('valid')"
```

## 실데이터 검증 (2026-06-02 샘플, Hot 1행 / Cold 4행)

프로파일을 실제 raw로 대조한 결과 — **핵심은 전부 통과**:

| 항목 | 결과 |
|---|---|
| 열 수 | Hot **6181** / Cold **6179** — 선언과 일치 ✅ |
| `route()` 라우팅 | 두 파일 모두 올바른 프로파일 선택 ✅ |
| bytepack 시각 | `2026-06-02 05:15:25.64` — **파일명 날짜와 일치** ✅ |
| **스캔 간격** | **0.96~0.97 s** — 1초 케이던스 확증 ✅ |
| flag | `1` = sampling ✅ |
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

## HK 열 전수조사 (Hot 9행 · Cold 4행, 2026-06-02)

값이 **행마다 변하는가**로 살아있는 센서를 가렸다(상수·0·65535는 죽었거나 미사용).

**Hot (HK 32열)** — 변동 = 살아있음
`templed1` 23.94 · `templed2` 17.04 · `oven_ans` 299.90 · `preheater` 41.07 ·
`oven_pns` 180.01 · `cell_heater` 74.92 · `tempcell1` 36.75 · `tempcell2` 32.72 ·
**rel31 30.59** ← 매핑 없던 살아있는 센서
죽음(전부 0): rel 27(`tempcell3`) · **rel 28(`t_spectrometer` 자리)** · 29 · 30

**Cold (HK 30열)** — 변동 = 살아있음
**rel0 25.71** ← 매핑 없음 · `t_cavity` 28.57 · `t_spectrometer` 27.63 ·
**rel28 32.35 · rel29 33.93** ← 매핑 없음

### 3셀 → 2셀 개조가 데이터로 확인됨

원래 3셀 측정기를 보수하면서 2셀로 바꿨다는 운용 이력과 데이터가 정확히 맞는다:
**`tempcell1`·`tempcell2`는 둘 다 살아있고(36.75 / 32.72 °C), `tempcell3`(rel 27)만 0**이다.
즉 온도 센서는 **슬롯 1·2에 정상 연결**돼 있고 3번 슬롯이 비어 있는 것 — "2가 아니라 3에
연결했을 수도"라는 추정과 달리, 배선은 예상대로 1·2다. 3셀 시절 열이 그대로 남아 0을 뱉는다.

> **함의**: `tempcell3`가 0인 것은 **고장이 아니라 정상**이다. 여기에 경보 밴드를 걸면
> 영구 오경보가 된다 → 밴드 없이 표시만(라벨에 `(미연결)` 명시). 반대로 `tempcell1/2`가
> 0이 되면 그건 진짜 이상이다.

### 살아있지만 정체 미상인 열 → 버리지 않고 표시

Hot rel31, Cold rel0·rel28·rel29는 **실제로 변동하는 온도스러운 값**인데 `raw_parser` 기록에
대응 항목이 없다. 이름을 지어내지 않되 **데이터를 버리지도 않기 위해** `unknown_rel*` 키로
프로파일에 넣고 **밴드 없이 표시만** 한다. 정체가 밝혀지면 키·라벨만 바꾸면 된다.

Hot의 `t_spectrometer`(rel 28)가 0이고 rel31이 살아있는 건, **센서 고장**인지 **분광기 온도가
실은 rel31**인지 데이터만으로는 못 가린다 → 추측으로 재매핑하지 않는다.

### ⏱ 스캔 주기는 노출시간에 종속된다 (liveness 설계에 중요)

측정 간격이 Hot·Cold 모두 **0.96~0.97초**로 일정한데, `exposure`(col2)가 **900**이다.
900 ms + 오버헤드 ~65 ms ≈ 0.965 s로 정확히 맞는다. 즉 **케이던스는 고정 1초가 아니라
`exposure + 오버헤드`**다. 운용자가 노출을 바꾸면 주기도 바뀐다.

> **liveness 경보 설계 함의**: "1초 안 오면 정지"로 하드코딩하면 노출을 늘리는 순간
> 전부 오경보가 된다. `liveness_grace_sec`는 `exposure`에서 유도하거나(예: `exposure×3 + 여유`)
> 넉넉히 잡아야 한다. 현재 10 s는 노출 3 s까지는 안전하다.

## 교정 시퀀스 실측 (2026-06-02 03:52~03:54, Hot 36행)

`find_flags.py`로 전환 지점만 추출해 얻은 **완전한 ZA/He 교정 1사이클**:

```
sampling(1) → he_wait_before(512) → he_inject(510) → he_wait_after(513)
            → za_setflow(501) → za_wait_before(502) → za_inject(500) → za_wait_after(503) → sampling(1)
```

각 단계 약 30초, 전체 사이클 약 2분 15초.

**flag 규약 (LabVIEW DAQ 기준, 정본)** — 5xx = Zero Air, 51x = Helium으로 **계열이 갈리고
끝자리가 단계**를 뜻한다. 두 계열의 규칙은 동일하다:

| 끝자리 | 뜻 | ZA | He |
|---|---|---|---|
| x00 | **injecting** ← R 산출용 측정 구간 | 500 | 510 |
| x01 | setflow | 501 | 511 |
| x02 | wait-before | 502 | 512 |
| x03 | wait-after | 503 | 513 |

그 외: `1` = sampling(대기 측정) · `100` = shutdown · `0` = 파일 헤더.

> ⚠️ **`core/raw_parser.py`의 기존 flag 표에는 501·511·100이 아예 없었고**, `503`을
> "ZA-end (one-row marker)"로 적어둔 것도 추측이었다(실제로는 **wait-after**).
> 위 정본 규약으로 `raw_parser.py` 주석·상수도 함께 정정했다(기존 상수명은 호환 유지,
> 정확한 별칭 추가).

**물리 검증** — He는 공기보다 Rayleigh 산란이 훨씬 적어 투과광이 밝다:

| 구간 | PNs 최대 | ANs 최대 |
|---|---|---|
| 대기(1) / ZA(500) | ~51,000 | ~46,700 |
| **He(510)** | **~61,200** | **~57,900** |

이 밝기 차이가 곧 R(거울 반사율) 산출의 근거다. 예상대로 동작.

### 이 샘플이 잡아낸 문제 3가지 (전부 오경보 유발)

1. **`flag=501` 미정의** — `raw_parser` 문서에도 없던 값. 매핑이 없으면 대시보드에
   "알 수 없음"으로 뜬다. (처음엔 위치로만 보고 `za_start`로 추정했으나, LabVIEW 정본 규약
   확인 결과 **`za_setflow`**가 맞다. 관측되지 않은 `511`=`he_setflow`, `100`=`shutdown`도
   규약대로 함께 추가했다.)
2. **포화 임계 60000이 오경보** — He 구간 PNs가 정상적으로 **61,387**까지 밝아진다.
   60000은 `gui/monitor_widget.py`의 **UI 표시용 휴리스틱**이었지 하드웨어 사양이 아니었다
   (16비트 한계 65535, 실측 최대와 4,148 여유). → **64000**으로 상향.
   이대로 뒀으면 **교정할 때마다 포화 경보**가 떴을 것이다.
3. **캐비티 압력 밴드가 오경보** — He 주입으로 ANs 캐비티압이 **916 → 970 mbar**로 정상 상승.
   대기 기준 밴드 `[880,950]`이 매 교정마다 발화한다.
   → 밴드를 넓혀 민감도를 잃는 대신 **`alert.phases`** 를 도입해
   `"phases": ["sampling"]`로 **대기 측정 구간에만 적용**되도록 했다. 대기 중 970 mbar는
   여전히 warn으로 잡힌다(민감도 유지).

> **`alert.phases` 사용 규칙**: `HK.read(row, phase)`에 그 행의 flag 역할을 **반드시 넘겨야**
> 구간 한정이 동작한다. 안 넘기면(=None) 보수적으로 전 구간 평가한다.
> 교정 중 장비는 **의도적으로** off-nominal 상태이므로, 대기 기준 밴드를 그대로 들이대면
> 안 된다 — 이 원칙을 지키지 않아 위 3건이 모두 오경보였다.

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
