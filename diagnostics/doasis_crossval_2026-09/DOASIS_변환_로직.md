# DOASIS 교차검증 — 변환 로직 문서 (2026-09-07, 사용자 직접 실행용)

## 이 문서의 성격
QDOAS 쪽(`qdoas_crossval_2026-09/`)은 QDOAS를 이 컴퓨터에 직접 설치해서 번들된 공식
Help 문서(Analysis.html 등)를 읽고 바이트 단위 포맷을 확정한 뒤 변환기를 만들었다.
DOASIS는 옆 컴퓨터에 있어 내가 직접 설치/확인할 수 없으므로, 이 문서는 **(a) 두
소프트웨어 공통으로 이미 확정된 방법론**과 **(b) DOASIS 쪽에서 반드시 사용자가
그 컴퓨터에서 직접 확인해야 할 부분**을 명확히 구분해서 정리한다. QDOAS 때처럼
"확인 안 된 걸 확정처럼 안내"하는 실수를 반복하지 않기 위해서다.

## 1. 공통 방법론 (확정, QDOAS와 동일 — 재설명)
Augur의 α는 이미 R(t)/Rayleigh/경로보정이 끝난 값이라 raw 강도가 아니다. DOASIS도
QDOAS와 마찬가지로 "캐비티가 없는" 범용 DOAS 도구이므로 α를 직접 넣을 수 없다.
대신 가상 스펙트럼을 만든다:

- **I(λ) = exp(-K·α(λ))**, **I0(λ) = 1** (평탄, 전 파장에서 강도값 전부 1.0)
- DOASIS가 계산하는 광학밀도(-ln(I/I0))는 정확히 K·α가 되고, DOASIS 결과 농도를
  K로 나누면 Augur의 α와 같아진다.
- K는 α가 너무 작아서(~1e-7~1e-8) I=exp(-α)≈1-α가 1.0에 극히 가까워지는 수치
  정밀도 문제를 피하려고 두는 스케일 인자. 광학밀도 크기가 대략 0.05(5%) 근방이
  되도록 10의 거듭제곱으로 고른다(QDOAS Cold 실측 예: K=1e6).
- 이러면 "Augur의 선형모델(농도·배경다항식·shift/squeeze)을 VarPro로 푼 값"과
  "같은 모델을 DOASIS의 독립 구현(non-linear least squares)으로 푼 값"을 직접
  대조하는 것이 된다 — QDOAS 검증과 정확히 같은 성격의 **외부 독립 구현** 대조.

**QDOAS와 결과를 나중에 서로 비교하려면(선택사항이지만 권장)**: 같은 채널·같은
날짜·같은 피팅 창(px 범위)·같은 다항식 차수·같은 shift/squeeze 제약을 QDOAS 쪽과
동일하게 맞춰서 돌리는 게 좋다. QDOAS Cold 설정 예시: 774-1550px, poly4,
NO2·CHOCHO·H2O(Link), shift/squeeze Limit ±2px. (2026-09-07 기준 Hot 채널은 ANs/PNs
윈도우 매핑이 재검토 중이라 Cold부터 먼저 진행 권장 — `qdoas_crossval_2026-09/README.md`
참조.)

## 2. Python 쪽 변환 로직 (재사용 가능 — 이 부분은 포맷 무관하게 확정)
`build_qdoas_spectrum.py`에서 이미 검증된 두 함수는 DOASIS용으로도 그대로 쓸 수
있다 (α 파일을 읽고 스케일을 정하는 로직은 출력 포맷과 무관하다):

```python
def read_alpha_file(path, px_lo, px_hi):
    """AUGUR *_alpha_trace.dat 1개 파일 -> (datetime 문자열 리스트,
    alpha 배열 [n_scans, px_hi-px_lo])."""
    lines = open(path, encoding='utf-8', errors='replace').readlines()
    hdr_i = next(i for i, l in enumerate(lines) if l.startswith('row_idx'))
    cols = lines[hdr_i].rstrip('\n').split('\t')
    idx_dt = cols.index('datetime')
    ipx = next(i for i, c in enumerate(cols) if c.startswith('px'))
    times, rows = [], []
    for l in lines[hdr_i + 1:]:
        if not l.strip() or l.startswith('#'):
            continue
        p = l.rstrip('\n').split('\t')
        if len(p) < ipx + px_hi:
            continue
        try:
            a = np.array(p[ipx + px_lo:ipx + px_hi], dtype=float)
        except ValueError:
            continue
        times.append(p[idx_dt])
        rows.append(a)
    return times, np.array(rows)


def pick_scale_factor(alpha, target=0.05):
    """|alpha|의 대표값(중앙값 절대값)을 target 근방으로 올리는 10의 거듭제곱 K."""
    ref = np.median(np.abs(alpha))
    if ref == 0:
        ref = np.max(np.abs(alpha))
    if ref == 0:
        return 1.0
    return float(10 ** np.round(np.log10(target / ref)))
```

여기까지 실행하면 `alpha` 배열(스캔 수 × 픽셀 수)과 `K`가 나온다. `intensity =
np.exp(-K * alpha)` 한 줄이면 강도 배열도 나온다. **여기서부터가 DOASIS 전용이라
확인이 필요한 부분이다** (아래 3절).

## 3. DOASIS 쪽 — 반드시 그 컴퓨터에서 직접 확인할 것
DOASIS(IUP Heidelberg 개발)는 QDOAS와 달리 이 세션에서 직접 설치/문서 확인을 못 했다.
아래는 DOAS 커뮤니티에 일반적으로 알려진 내용이며, **정확한 바이트 포맷은 옆
컴퓨터의 DOASIS Help(도움말) 메뉴 또는 설치 폴더의 매뉴얼에서 직접 확인 후 진행할
것** — QDOAS 때 겪었던 "확인 안 하고 추측하면 조용히 틀린 값이 들어갈 위험"이
DOASIS에도 똑같이 적용된다.

### 방법 A (권장): DOASIS BasicScript로 직접 스펙트럼 객체 생성
DOASIS는 자체 스크립팅 엔진(DOASIS BasicScript, VB 계열 문법)을 내장하고 있어서,
외부 ASCII 포맷을 DOASIS의 파서가 어떻게 해석하는지 추측할 필요 없이 **스펙트럼
객체를 스크립트로 직접 만들어 값만 채워 넣고 저장**하는 방법이 가장 안전하다.
일반적으로 알려진 개념(정확한 클래스/메서드명은 그 컴퓨터의 DOASIS Help >
Scripting Reference에서 확인 필요):

1. 새 스펙트럼 객체 생성 (예: `CSpectrum` 계열 객체)
2. 픽셀 수(`NValues` 또는 유사 속성) 설정
3. 반복문으로 각 픽셀 인덱스에 `intensity[i]` 값 대입 (`Datum(i)` 또는 유사 속성/메서드)
4. 스캔의 날짜/시각 메타데이터 설정
5. DOASIS 네이티브 포맷(예: `.spe` 계열)으로 저장 — 이러면 포맷 자체를 DOASIS가
   책임지므로 ASCII 바이트 포맷 불일치 위험이 없음
6. 스캔 개수만큼 반복 (하루치 알파 파일 → 여러 스펙트럼 파일, 또는 DOASIS가
   지원하면 한 파일에 여러 스펙트럼을 묶어 저장)
7. I0(평탄, 전부 1.0)도 같은 방식으로 스펙트럼 하나 생성해서 저장

이 스크립트 자체는 Python이 아니라 DOASIS BasicScript로 짜야 하므로, 이 문서의
Python 함수(2절)로 만든 `alpha`/`K`/`intensity` 배열을 **먼저 간단한 중간 텍스트
파일(예: 한 줄에 한 픽셀 값)로 떨궈두고, DOASIS 스크립트가 그 중간 파일을 한 줄씩
읽어 스펙트럼 객체에 채워 넣는 2단계** 구조를 권장한다. 중간 파일 포맷은 DOASIS가
아니라 우리가 정하는 것이므로 아무 위험 없이 아래처럼 단순하게 하면 된다:

```
# intermediate_<scan_index>.txt (한 줄에 강도값 하나, 픽셀 순서대로)
0.975724
0.989940
0.981875
...
```

DOASIS BasicScript에서 이 파일을 한 줄씩 읽어 `Datum(i) = CDbl(line)`처럼 대입하면
DOASIS 자체 ASCII 파서를 거치지 않아 포맷 불일치 위험이 없다.

### 방법 B (대안): DOASIS의 Generic/ASCII Import 필터 사용
DOASIS에는 보통 "Generic ASCII" 또는 유사한 가져오기(Import) 필터가 있어 헤더
줄 수, 구분자, 컬럼 배치를 GUI에서 지정할 수 있다. 이 경로를 쓴다면:

1. 그 컴퓨터에서 DOASIS Help(또는 설치 폴더의 매뉴얼 PDF/CHM)에서 "ASCII import"
   또는 "Generic import" 항목을 찾아 정확한 헤더/구분자 규칙을 확인
2. 확인된 규칙에 맞춰 위 Python 함수 출력(`times`, `intensity` 배열)을 텍스트로
   저장하는 함수를 하나 추가로 짜면 됨 (이 문서의 `read_alpha_file`/
   `pick_scale_factor`는 그대로 재사용, 마지막 저장 함수만 DOASIS 규격에 맞게 신규 작성)
3. I0 참조파일도 같은 규칙으로 저장 (모든 픽셀 값 = 1.0)

**방법 A와 B 중 어느 쪽이든, "확인 후 실행" 순서를 지킬 것** — QDOAS 검증에서 이미
한 번 (컨볼루션 "None"→"Interpolate" 정정) 겪었듯, 확인 없이 진행하면 조용히
틀린 값이 들어가도 알아채기 어렵다.

## 4. 비교 시 주의사항 (QDOAS와 공통)
- DOASIS 결과 농도(SCD)는 K배 커진 값이므로, Augur α와 비교할 때 **K로 나눌 것**.
- Reference 단면적도 QDOAS와 마찬가지로 **이미 기기 슬릿함수로 컨볼루션된 값**
  (`Ref_<GAS>_Dynamic-ILS-Applied.dat`)이므로, DOASIS 쪽 단면적 등록 옵션에서
  "이미 컨볼루션됨"에 해당하는 옵션을 찾아 지정할 것 (QDOAS의 "Interpolate"에
  대응하는 DOASIS 쪽 옵션명은 그 컴퓨터에서 확인 필요 — 다시 컨볼루션하면 슬릿함수
  이중 적용 오류).
- 파장 보정: 가상 스펙트럼엔 실제 태양 프라운호퍼선이 없으므로, DOASIS 자체
  파장 자동보정(있다면) 기능은 끄고 Calib_*.txt 기반 파장축을 그대로 신뢰하는
  옵션을 쓸 것 (QDOAS의 Calibration=None에 대응).

## 5. 요약 체크리스트 (옆 컴퓨터에서)
1. DOASIS Help/매뉴얼에서 스크립팅 API(또는 Generic ASCII import 규격) 정확한
   이름/문법 확인
2. 이 문서 2절 Python 함수로 `alpha`, `K`, `intensity` 계산 (스크립트는 이 컴퓨터의
   `build_qdoas_spectrum.py`를 참고해 직접 짜거나 요청하면 내가 DOASIS용으로
   별도 작성 가능 — 정확한 출력 포맷이 확정되면)
3. 중간 텍스트 파일 → DOASIS 네이티브 스펙트럼으로 변환 (방법 A 또는 B)
4. I0(평탄 1.0) 스펙트럼도 동일 방식으로 생성
5. 단면적 등록 시 컨볼루션 옵션 = "이미 컨볼루션됨"에 해당하는 것으로 지정
6. 파장보정 = 끄기/None 대응 옵션
7. Cold 774-1550px/poly4/NO2·CHOCHO·H2O(Link)/shift·squeeze Limit±2px로 QDOAS와
   동일 세팅 후 실행
8. 결과 SCD를 K로 나눠 Augur α 피팅 결과와 시계열 비교 (상관계수+rms/max_diff)
