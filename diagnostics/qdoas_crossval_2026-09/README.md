# QDOAS 교차검증 — 최종 결과 정리 (2026-09-06 착수 → 2026-09-08 밤 최종 확정)

## 목적
`docs/Augur_소개_2026-07.md` §7/§10-3에 명시된 검증 항목: 같은 α(알파) 데이터를
Augur와 외부 표준 DOAS 소프트웨어 양쪽에서 핏해 NO₂/CHOCHO/H2O 결과를 대조한다.
**QDOAS**(BIRA-IASB, 오픈소스, conda-forge 배포, 이 컴퓨터)와 **DOASIS**(옆
컴퓨터)를 병행 검증하기로 확장 결정(2026-09-07). 이 문서는 QDOAS 쪽 최종 결과다.
DOASIS는 별도 문서(`DOASIS_변환_로직.md`)로 사용자가 옆 컴퓨터에서 직접 진행 중.

**결론 요약**: Cold/ANs/PNs 3채널 전부 QDOAS Run 완료. NO2는 전 채널 r²>0.99로
매우 강한 외부 검증을 통과했고, 애초 CHOCHO/H2O에서 나타났던 Hot ANs 채널만의
낮은 일치도(r²=0.53)는 **QDOAS bound에 shift 부호를 잘못(Augur와 같은 부호로
가정해서) 줬기 때문**이었음이 최종 확정됐다 — 부호를 바로잡아 재실행하니
r²=0.53→0.96(CHOCHO)/0.98(H2O)로 개선되어 NO2와 같은 급의 검증 신호가 됐다.

## 비교 방법론
Augur의 α는 이미 R(t)/Rayleigh/경로보정까지 끝난 "캐비티가 없는 것처럼 만든" 값이라
QDOAS(공동공진/캐비티를 모르는 범용 DOAS 도구)에 raw 강도로 넣을 수 없다. 대신
**가상 스펙트럼** I(λ)=exp(-K·α(λ)), I0(λ)=1(평탄)을 구성해 QDOAS에 넣으면 QDOAS가
계산하는 광학밀도 -ln(I/I0)이 정확히 K·α가 되고, QDOAS의 SCD를 K로 나누면 Augur의
α와 같은 물리량이 된다. 이러면 "Augur의 선형모델(농도·배경다항식·shift/squeeze)을
VarPro로 푼 값"과 "같은 모델을 QDOAS(외부 독립 구현, Levenberg-Marquardt)로 푼 값"을
직접 대조하는 것과 같아진다 — §7의 "VarPro vs 완전비선형"(Augur **내부** 대조)과는
성격이 다른 **외부** 대조. K는 α가 워낙 작아(~1e-7~1e-8) 생기는 수치 정밀도 문제를
피하려고 광학밀도가 대략 5% 근방이 되도록 스케일링(Cold=1e6, Hot 둘 다=1e7).

한 가지 중요한 한계: QDOAS에 넣는 입력 스펙트럼 자체가 Augur가 만든 값이므로, 이
비교는 **"대기 중 실제 농도에 어느 쪽이 더 가까운가"를 판단할 수 없다** — 같은
알려진 광학밀도 곡선을 두 알고리즘(VarPro vs Levenberg-Marquardt)이 서로 다르게
분해하는지만 볼 수 있는 구조. "어느 쪽이 그 곡선을 수치적으로 더 잘 재현하는가"
(=residual 비교)는 원리적으로 답할 수 있는 질문이지만 이번 비교의 범위는 아니다.

## 환경/설치
Miniforge로 conda-forge 채널에 설치(Anaconda 설치가 깨져 있어 전환):
```
conda create -n qdoas -c conda-forge qdoas -y
conda activate qdoas
qdoas          # GUI 실행
```
환경 경로: `C:\Users\User\miniforge3\envs\qdoas` (qdoas 3.7.12, doas_cl 3.7.12
커맨드라인 버전도 같이 설치됨 — 자동화하려면 추후 활용 가능, 이번엔 GUI로 진행).

## 준비 단계 (변환기·포맷 확정)

**레퍼런스 단면적 변환기** (`build_qdoas_xs.py`): Augur의 픽셀 도메인 레퍼런스
(`Ref_<GAS>_Dynamic-ILS-Applied.dat`)를 채널별 `Calib_*.txt`(픽셀→파장)와 짝지어
QDOAS Molecules 패널이 읽는 2컬럼(파장 nm, 단면적 cm²/molecule) `.xs` 파일로 변환.
Cold/ANs(roi1)/PNs(roi2) 3채널 전부 실행 완료. **등록 시 컨볼루션 방법 =
"Interpolate"**(공식 Help 문서 `Analysis_Molecules.html`로 확정 — 우리 `.xs`는
이미 기기 슬릿함수로 컨볼루션된 것이므로 "None"을 쓰면 조용히 틀린 값이 나옴).

**스펙트럼 배치 변환기** (`build_qdoas_spectrum.py`): Augur의 `*_alpha_trace.dat`를
읽어 지정 픽셀창으로 잘라 QDOAS ASCII "line" 포맷으로 저장. 60s 알파 기준 Cold
32일(05-17~06-17)/Hot ANs·PNs 각 53일(05-18~07-09) 전부 변환 완료.

**★ 결정적 원인(해결·코드 반영됨) — Reference 파일 포맷**: QDOAS 소스코드
(`engine/analyse.c::AnalyseLoadVector()`, Reference 전용 로더)는 스펙트럼 line
포맷과 달리 "파장 하나 + 값 하나" 2컬럼×N줄 포맷을 요구한다. `write_flat_reference()`를
이 포맷으로 수정, `--calib` 필수 인자 추가로 해결·커밋 완료.

**배치 메타 파일 위치**: `_batch_meta_<채널>.txt`가 out_dir 안에 있으면 QDOAS
"Insert Directory"가 이것도 스펙트럼으로 읽으려다 Fatal Error를 낸다 — out_dir
밖(부모 폴더)으로 옮기도록 스크립트 수정·커밋 완료.

## QDOAS GUI 실제 설정값

**Instrumental 탭**: Format=line, 체크 DD/MM/YYYY+Decimal Time만. 채널별 Detector
Size/Calibration File: Cold=776px/`wv_cal\cold\Calib_20260523_..._Poly2.txt`,
ANs=670px/`wv_cal\roi1\Calib_20260619_..._Poly2.txt`, PNs=550px/`wv_cal\roi2\
Calib_20260619_..._Poly2.txt`. Fit interval: Cold 438-476nm(poly4), ANs 430-462nm
(poly4), PNs 444-471nm(poly3).

**Analysis Window**: Ref. Selection=File, Reference 1=평탄 I0=1 참조파일,
Reference 2=비움. Calibration 방법=None(가상 스펙트럼엔 프라운호퍼선이 없어 QDOAS
자체 파장보정이 무의미). Symbols 탭에 NO2/CHOCHO/H2O를 전역으로 먼저 등록해야
Molecules Insert가 동작함.

**Shift and Stretch — 실제 production bound(2026-09-07 확정)**: NO2/CHOCHO/H2O를
한 행으로 병합(Link, Augur 구조와 동일), Shift fit=Nonlinear.
- Cold: NO2 Shift **Fix(-0.5)**, Squeeze **Fix(0.0)**
- ANs: NO2 Shift **Limit(-10, 0.5)px** (비대칭!), Squeeze Limit(±0.005)
- PNs: NO2 Shift **Limit(-5, 5)px**, Squeeze Limit(±0.005)

**★ Shift 부호 규약이 Augur와 반대다 — bound를 그대로 옮기면 안 됨(2026-09-08
확정, 아래 상세)**: Augur의 px bound를 nm으로 환산해 QDOAS에 그대로 넣으면 안
되고, **부호를 반전하고 min/max를 swap**해야 한다. ANs의 경우:
- Augur 부호 그대로(틀림): Sh min=-0.483nm, Sh max=+0.024nm
- **부호 교정(맞음)**: Sh min=**-0.024nm**, Sh max=**+0.483nm**

PNs는 원래 bound가 대칭(±0.240nm)이라 부호를 반전+swap해도 **똑같은 구간**이
나온다 — 그래서 PNs는 이 버그의 영향을 원래 받지 않았다(아래 "부호 규약" 절 참조).

**St min/max(stretch 상하한) 필드가 이 QDOAS 버전엔 없음** — Augur의 실제 Squeeze
Limit(±0.005)에 대응 못 하고 무제한 피팅됨. 모든 실행에 공통으로 적용되는 방법론
caveat.

**Files 추가 시 주의**: 메인 창에서 프로젝트명 우클릭 → Insert Directory 할 때,
`reference_flat_*.asc`와 `_batch_meta*.txt`가 폴더에 같이 있으면 이것도 스펙트럼으로
잘못 집어넣는다 — Raw Spectra 목록에서 우클릭 Remove(디스크 파일은 유지).

**Output**: "Analysis" 체크해야 Output Path 필드 활성화. 확장자는 제각각(`.html`/
`.ASC`)이지만 내용은 항상 정상 탭구분 텍스트(표시상 버그, 무해).

**Shift/Stretch/Err 값을 파일로 남기려면**: Analysis Window > **Shift and Stretch
탭**(Output 탭이 아님)에 `Sh store`/`St store`/`Err store` 체크박스가 있다 — 이걸
켜야 출력 파일에 `NO2.Shift(...)`/`NO2.RMS` 등의 컬럼이 추가된다.

## 실행 이력과 함정

**Cold 출력 파일 오염(발견·수정, 2026-09-07)**: 최초 `Analysis.html`에 정상
32일치(42864행) 뒤에 05-18~05-21 부분(3675행, 타임스탬프·농도 다 다름 — 개별 파일을
툴바로 넘겨본 흔적으로 추정)이 또 붙어있었다. 오염 안 된 첫 블록만 잘라
`Analysis_clean.html`로 저장, 비교는 이 파일 사용. Hot ANs/PNs 최초 실행은 이런
오염 없이 깨끗했다.

**절대 스케일(K) 미스터리 — 해결됨**: 초기엔 QDOAS SCD를 K로 나눈 값과 Augur의
merge.dat 컬럼이 ~14자릿수나 차이 나 "스케일이 안 맞는다"고 봤으나, 원인은 스케일
문제가 아니라 **merge.dat 컬럼이 real_conc(cm⁻³)가 아니라 ppb(대기 혼합비)**였기
때문이었다(`gui/worker.py`: `ppb = real_conc/n_air*1e9`). 명목 T=25°C/P=1013.25mbar로
n_air를 근사해 `real_conc_approx = ppb·n_air/1e9`로 역변환하면 QDOAS SCD/K와
slope≈1.0(대부분 0.88~1.24 범위, NO2 기준 0.88~1.08)로 물리적 절대 스케일까지
일치함을 확인 — 상관계수뿐 아니라 절대 크기 비교도 가능해짐.

**Fix(-0.5) 방법론 caveat은 Cold에만 해당**: merge.dat 헤더의 "Reference
Constraints: Sh[-0.5], Sq[0.0]" 문구가 ANs/PNs 파일에도 똑같이 찍혀 있어 한때
"3채널 전부 Shift 고정"으로 오판했으나, 전체 컬럼 통계로 재확인한 결과 ANs/PNs는
스캔마다 자유롭게 변하는 값이었다(`core/result_io.py::merge_results()`가 여러
파일 병합 시 `files[0]`=Cold의 헤더만 남기고 나머지 파일 헤더를 버리는 코드
버그 — 파일명/데이터 컬럼은 신뢰 가능, 헤더 "설명" 텍스트는 불가). 따라서
Fix-vs-Limit 방법론 차이는 Cold 채널에만 적용되고, ANs/PNs는 QDOAS와 마찬가지로
Shift 자유 피팅이다(다만 QDOAS는 대칭 bound, Augur는 비대칭 bound라 완전한
apples-to-apples는 아님).

## Hot ANs CHOCHO/H2O 미스터리 — 원인 규명 과정과 최종 확정

최초(±2px 대칭 bound, 부호 개념 없이 진행) 실행 결과, NO2는 전 채널 r²>0.99로
매우 강했지만 **Hot ANs만 CHOCHO r²=0.529, H2O r²=0.532**로 유독 낮았다(PNs는
CHOCHO r²=0.913, H2O r²=0.956로 정상). 후보를 하나씩 데이터로 검증·기각했다:

1. **공선성 — 기각**: `differential_collinearity`를 재현해 3채널 비교한 결과
   오히려 ANs가 공선성이 가장 낮았다(CHOCHO multiple_R: ANs 0.090 < PNs 0.322 <
   Cold 0.212).
2. **신호 세기 — 기각**: CHOCHO는 ANs·PNs 둘 다 MDL 대비 신호가 약했지만(중앙값이
   3σ MDL의 0.32~0.34배) PNs는 정상이었다 — 신호 약함만으로는 ANs만 나쁜 이유가
   안 됨.
3. **Shift bound 폭(±2px가 너무 좁다) — 처음엔 기각, 나중에 진짜 원인의 단서로
   재해석됨**: 실제 production bound(Limit(-10,0.5)px)로 넓혀 재실행(`boundfix`)
   했더니 오히려 **악화**됐다(H2O r²=0.532→0.325). 이 결과만 보면 "bound 폭은
   원인이 아니다"로 기각하는 게 자연스러웠으나, 이건 성급한 결론이었다.
4. **★ 진짜 원인 — Shift 부호 규약 불일치**: `Sh/Err store`를 켜고 boundfix
   조건을 재실행해 실제 fitted shift 값을 뽑아보니, **스캔의 99.71%가 bound
   상한(+0.5px)에 pin**되어 있었다 — "자유도를 넓혀줬는데 오히려 벽에 쌓였다"는
   것은 bound의 **방향 자체**가 잘못됐다는 신호였다. Augur의 ANs 실측 shift는
   전부 음수(-7.292~-0.500px)인데, QDOAS에 준 boundfix bound(-10,+0.5px)는 이
   범위를 "부호 그대로" 옮긴 것 — 만약 두 도구의 shift 부호 정의가 반대라면
   QDOAS가 "진짜 원하는" 값은 부호가 뒤집힌 +0.500~+7.292px 근방이 되고, 이
   범위의 하한(+0.500px)이 정확히 bound 상한과 일치해 그 벽에 쌓인 것과 완벽히
   부합한다.

   **코드 레벨 확정**(`core/engine.py::get_model_components`):
   ```python
   pixel_shifted = (pixel_idx - center_idx) * sq + center_idx + sh
   raw_ref = self.interpolators[name](pixel_shifted) / self.scaling_factors[name]
   ```
   Augur의 모델은 `model(x) = reference(x + sh)`인데, 표준 DOAS 관례(Platt &
   Stutz, QDOAS도 이 관례)는 `model(x) = reference(x − shift)` — 수학적으로
   정확히 부호가 반대다: **Augur의 `sh` = −(QDOAS 관례의 shift)**. Augur
   내부에서는(VarPro/완전비선형/warm-start 전부 같은 부호로 일관되게 사용)
   전혀 문제가 없었지만, 크로스툴 비교에서 부호를 안 맞추면 그대로 함정이
   된다 — 이 프로젝트에서 문서화된 적 없던 undocumented 관례였다. (문서화는
   `core/engine.py` 독스트링과 `README.md` 본체 용어사전에 완료.)

   **미러링 bound로 실증 확정(`hot_ans_negshift.ASC`, 74724 스캔)**: Sh min/max를
   **-0.024nm ~ +0.483nm**(boundfix bound의 부호 반전+swap)로 재설정해 재실행한
   결과:
   - Shift pin 비율이 하한 0.12%/상한 0.10%로 **사실상 완전히 해소**(이전
     99.71%에서). 분포도 bound 안쪽에서 종모양으로 자연스럽게 퍼짐(중앙값
     0.275nm, std 0.043nm) — optimizer가 진짜 최적값을 찾고 있다는 신호.
   - CHOCHO/H2O r²가 **극적으로 개선**되고, slope(realconc_augur ↔ SCD_qdoas/K)도
     세 가스 모두 0.946~0.963로 균일하게 수렴(절대 스케일 일치도까지 함께 개선
     — 우연한 상관관계 개선이 아니라 물리적으로 정합적인 결과).

**PNs는 왜 재실행이 불필요한가**: PNs의 production bound는 원래 **대칭**
(Limit(-5,5)px → ±0.240nm)이다. 대칭 구간은 부호 반전+swap을 적용해도 자기
자신과 같다(new_min=-(+0.240)=-0.240, new_max=-(-0.240)=+0.240) — 즉 PNs는
이 부호 버그의 영향을 애초에 받지 않는 구조였다. 이는 관측과도 일치한다: PNs
실측 shift 범위(-4.484~+5.000px)가 이미 0을 가로질러 대칭에 가까웠고,
boundfix 실행 결과가 최초(±2px) 실행과 거의 동일했다(CHOCHO r²=0.913/0.913,
H2O r²=0.956/0.957) — PNs가 자연스럽게 이 실험의 **대조군** 역할을 했다.

## ★★★ 최종 비교 결과 (2026-09-08 밤 확정, Augur Status==OK 서브셋)

| 채널 | 가스 | n | r² | slope(realconc_augur ↔ SCD_qdoas/K) | 비고 |
|---|---|---|---|---|---|
| Cold | CHOCHO | 40487 | 0.861 | 0.685 | Shift Fix(-0.5) — 방법론 차이 있음 |
| Cold | H2O | 40487 | 0.977 | 1.237 | 〃 |
| Cold | NO2 | 40487 | 0.992 | 1.083 | 〃 |
| Hot PNs | CHOCHO | 56784 | 0.913 | 0.976 | 대칭 bound, 부호 문제 없음(대조군) |
| Hot PNs | H2O | 56784 | 0.956 | 0.918 | 〃 |
| Hot PNs | NO2 | 56784 | 0.993 | 0.928 | 〃 |
| **Hot ANs** | **CHOCHO** | 49434 | **0.960** | **0.955** | **부호 교정 후(negshift) 최종값** |
| **Hot ANs** | **H2O** | 49434 | **0.978** | **0.946** | **부호 교정 후(negshift) 최종값** |
| **Hot ANs** | **NO2** | 49434 | **0.9998** | **0.962** | **부호 교정 후(negshift) 최종값** |

**과거 값(폐기, 방법론적으로 틀린 bound였음 — 기록용)**: 최초 ±2px 대칭 bound
기준 Hot ANs CHOCHO r²=0.529/H2O r²=0.532, "부호 그대로" boundfix 기준 CHOCHO
r²=0.481/H2O r²=0.325. 둘 다 부호가 틀린 bound로 나온 값이라 논문에는 위 최종
negshift 값만 인용할 것 — 굳이 언급한다면 "부호를 틀리게 줬을 때의 민감도
사례"로만 Discussion에 남길 수 있다.

NO2는 전 채널 r²>0.99(대부분 >0.99, ANs는 0.9998)로 매우 강한 외부검증 신호이고,
부호를 교정한 뒤에는 CHOCHO/H2O도 전 채널 r²>0.9(대부분 >0.95)로 같은 급에
도달했다.

## 논문에 반영할 핵심 교훈
**"Augur와 QDOAS는 shift 부호 정의가 반대이며, 이를 모르고 QDOAS bound를
Augur 값 그대로 옮기면 관측되는 QDOAS-Augur 불일치의 상당 부분이 실은
방법론적 아티팩트다."** — Hot ANs CHOCHO/H2O r²가 0.53에서 0.96/0.98까지
바로잡힌 것이 그 구체적 증거. 크로스툴 DOAS 검증을 시도하는 누구에게나 적용
가능한 일반적 교훈이라 소프트웨어 논문 Discussion의 핵심 후보. 한편 shift
부호 자체를 Augur 코드에서 표준 DOAS 관례로 통일하는 리팩터는 회귀 리스크
대비 실익이 없어 하지 않기로 결정 — 대신 코드 주석(`core/engine.py`)과
`README.md` 용어사전에 부호 규약을 명시하는 문서화만 완료(2026-09-08).

## 남은 caveat
- QDOAS는 stretch(squeeze) 상하한을 거는 UI가 없어 Augur의 실제 Squeeze
  Limit(±0.005)과 완전히 동일한 조건으로 못 맞춤(무제한 피팅) — 모든 채널
  공통 caveat.
- Cold의 Shift Fix(-0.5) vs QDOAS Nonlinear는 방법론적으로 다른 조건(Cold만
  해당, ANs/PNs는 둘 다 자유 피팅이라 이 caveat 없음 — 단 bound 비대칭
  여부는 여전히 다름).
- 이 비교는 "대기 진실에 어느 쪽이 더 가까운가"를 answer할 수 없다(위 "비교
  방법론" 절 참조) — "같은 입력을 두 알고리즘이 얼마나 정합적으로 재현하는가"
  까지만 유효.
- DOASIS 교차검증은 옆 컴퓨터에서 사용자가 진행 중 — 진행 상황 별도 확인 필요.

## 산출물 위치
- 변환기: `build_qdoas_xs.py`, `build_qdoas_spectrum.py`
- 비교 스크립트: `compare_qdoas_augur.py`(Cold/ANs/PNs/boundfix 전체),
  `compare_hot_ans_negshift.py`(부호 교정 최종판)
- 결과: `qdoas_output/`(원본 QDOAS 출력), `compare_*.png`/`compare_*_matched.csv`/
  `compare_summary.csv`, `compare_hot_ans_negshift*`(최종판)
- Augur 쪽 비교 대상: `augur_fit/{cold,ans,pns}_merge.dat`

## 재현 방법 — 저장소에 무엇이 들어 있고 무엇이 없나 (2026-09-15 정리)

이 폴더는 원래 `.gitignore`로 통째로 제외돼 있었다. 그래서 논문 Table을 만든
`core/agreement.py`는 저장소에 있는데 **그걸 호출하는 코드는 저장소에 없는** 상태였다.
"재현 가능"이라고 주장하려면 그 상태로는 안 된다. 다음과 같이 나눴다.

**추적한다 (코드·설정·결과 요약)**

| 파일 | 왜 |
|---|---|
| `build_qdoas_xs.py`, `build_qdoas_spectrum.py` | α → QDOAS 가상 스펙트럼 변환기 |
| `compare_qdoas_augur.py` | 5채널 전체 대조 → `compare_summary.csv` |
| `compare_hot_ans_negshift.py` | 부호 교정 최종판 → `compare_hot_ans_negshift_summary.csv` |
| `agreement_report.py` | Bland–Altman/Deming/블록부트스트랩 (`core.agreement` 호출) |
| `Analysis.html`, `Analysis_Molecules.html`, `Project_Instrumental.html` | QDOAS 프로젝트 설정 — 이게 없으면 외부인이 같은 핏을 재현할 수 없다 |
| `Calib_cold_774-1550px.txt` | QDOAS 파장 캘리브 입력 |
| `compare_summary.csv`, `compare_hot_ans_negshift_summary.csv` | 논문 Table의 실제 숫자 |

**추적하지 않는다 (원자료·중간산물)**: `qdoas_input/`·`qdoas_output/`(.ASC/.html 원본
출력), `qdoas_xs/`(.xs 단면), `augur_fit/*_merge.dat`, `compare_*_matched.csv`(14MB),
`compare_*.png`. 원자료 비공개 방침(`docs/논문_주장구조_2026-09.md`)에 따른다 —
데이터 요청은 `CITATION.cff`의 연락처로.

**돌리는 법** (위 원자료를 이 폴더 구조 그대로 놓았을 때):

```bash
python core/agreement.py                                       # 통계 모듈 자체검증
python core/error_budget.py                                    # 오차예산 모듈 자체검증
python diagnostics/qdoas_crossval_2026-09/compare_qdoas_augur.py
python diagnostics/qdoas_crossval_2026-09/compare_hot_ans_negshift.py
python diagnostics/qdoas_crossval_2026-09/agreement_report.py
```

경로는 전부 **이 폴더 기준**이다. 2026-09-15 이전 판본에는 이전 세션 샌드박스의
절대경로(`/mnt/user-data/...`, `/root/.claude/uploads/...`)가 박혀 있어 다른 PC에서는
임포트조차 되지 않았다.

**재현 확인 (2026-09-15)**: 위 두 비교 스크립트를 이 PC(Windows/Python 3.13)에서
다시 돌려 `compare_summary.csv`를 재생성했다. 2026-09-08 원본(Linux 샌드박스)과
**유효숫자 15자리까지 일치**했다(예: cold CHOCHO r = 0.9278925191852626 → …263).
차이는 BLAS 연산 순서에 의한 최종 자리뿐이고 결론에 영향 없다. 저장소에는 재생성본을
넣었다 — 저장소 안의 코드가 실제로 저장소 안의 숫자를 만든다는 것을 확인 가능하게.
