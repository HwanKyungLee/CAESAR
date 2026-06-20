# AnalysisWorker.run() 기존 핏 로직 — 정밀 기록 (2026-06-17)

좌측 RUN 경로(`gui/worker.py` `AnalysisWorker.run`, 현재 줄 246~714)의 동작을 그대로
기록한다. **청크+워밍업 병렬화가 "현재와 같은 답"을 내는지 검증하는 기준 문서.**
병렬화는 이 로직을 바꾸지 않고, 스캔을 청크로 쪼개 각 청크가 이 재귀를 그대로 돌린다.

## 전체 흐름
1. `current_params` 초기화(shift0, squeeze1, gas..., poly...). `last_valid_shift = current_params[0]`.
2. KalmanTracker 생성(q,r). expand_to_scan_list로 (file, row) 스캔 목록 펼침. `scan_count_ready`.
3. temporal-I0면 `_prescan_za_scans()`로 ZA 목록 프리스캔.
4. **스캔 루프**(i, entry): 타임스탬프 파싱→TZ보정, 스펙트럼+HK 로드(알파면 자체 파장축+`_alpha_fit_slice`), T/P 갱신(가스온도 오버라이드).
5. **플래그 분기**:
   - ZA(500): `i0_array`·`i_za_last`·`t_za_last`·`p_za_last` 갱신(501~503은 i_za만/ I0 유지). He 있으면 `update_mirror_reflectivity`로 R 갱신. `result_ready` 후 **continue**.
   - He(510): `i_he_last`·`t_he_last`·`p_he_last` 갱신. ZA 있으면 R 갱신. **continue**.
   - 미지 플래그: skip continue. 전부-0: skip continue.
   - **Ambient**: 핏 진행.
6. **Ambient 핏**: linear_mode 판정(|mean|<1=알파/OD), scale_factor(언더플로 방지), 다크/오프셋/stray 보정, I0 선택(temporal이면 `_interpolate_i0(za_scan_list,i)` 아니면 `i0_array`), **BBCEAS α 공식**(`one_minus_r_over_d`, RL, Rayleigh ZA/sample with `t_za_last`/`p_za_last` & 현재 T/P).
7. etalon_freq 최초 1회 검출(`_detect_etalon_frequency`) 후 재사용.
8. **retry 루프(max_retries=2)**: `needs_pre_calibration`면 `auto_pre_calibrate`로 shift/sq 재설정. `_setup_fit_parameters(initial_shift_center=last_valid_shift, current_params)` → VarPro(`_execute_varpro_fit`) → 모델재구성·RMS. Status=OK/Recovered/Unstable(상대RMS). **`last_valid_shift = opt_shifts[0]` 갱신**(Unstable이어도). OK/Recovered거나 마지막 시도면 break, 아니면 `needs_pre_calibration=True`로 다음 시도.
9. 가스 농도→ppb(N_air at 현재 T/P). **`kalman_filter.process()` → `_Smooth` 컬럼 전용**(1차 ppb는 raw, 평활 아님).
10. QC: 절대RMS상한/상대RMS(Unstable)/SNR하한 걸리면 가스값 NaN(+Status=QC-Excluded). Status/RMS/SNR은 유지.
11. update_interval마다 `plot_update`·`trend_update`. 매 스캔 `result_ready`. `delay_ms` sleep(관찰=200ms).
12. 끝: `scan_count_ready`, `finished`.

## ★스캔 간 캐리오버 상태 (병렬화가 반드시 재현해야 할 것)
| 상태 | 갱신 시점 | 사용처 | 캐리오버 성격 |
|---|---|---|---|
| `last_valid_shift` | 매 ambient 핏(652) | 다음 핏 shift창 중심(289→517) | **재귀(핵심)**. shift는 벽에 빨리 붙음(콜드+2,핫CH1-5) |
| `current_params` | 핏마다 mutate(509,513) | theta0 seed | 재귀(shift/sq seed) |
| `i0_array`,`i_za_last`,`t_za_last`,`p_za_last` | ZA-500 스캔 | ambient I0·Rayleigh ZA | **주입 cadence(~3h)**. 워밍업으로 못 닿음→프리패스 필요 |
| `i_he_last`,`t_he_last`,`p_he_last` | He-510 스캔 | R 계산 | 주입 cadence(~1h) |
| `one_minus_r_over_d` | ZA&He 둘 다 있을 때(R-cal) | ambient α | 주입 cadence. R(t) 프리컴퓨트로 대체가능 |
| `etalon_freq` | 최초 ambient 1회 | 모든 핏 | 사실상 전역. 1회 검출 후 공유 |
| `needs_pre_calibration` | 핏 실패/예외 시 set, 매 시도 reset | auto_pre_calibrate 트리거 | 국소 재귀(최근 실패). 워밍업 내 재현됨 |
| `kalman_filter` | 매 ambient | `_Smooth`만(1차 ppb 무관) | **순차지만 후처리 가능** |

## 청크+워밍업 설계 결론 (이 카탈로그 기반)
- **프리패스(싸다)**: 전 스캔 시간순 1회 훑어 플래그 처리만 → 스캔index→(I0,t_za,p_za,i_he,t_he,p_he,one_minus_r_over_d) **스텝 룩업** 구축 + `etalon_freq` 1회 검출. (temporal-I0/R(t)는 이미 index기반이라 그대로 재사용 가능.) 핏 안 함.
- **청크 분할**: ambient 스캔을 K개 연속 구간으로.
- **각 청크(프로세스)**: [워밍업시작, 청크끝] 범위를 기존 핏 재귀 그대로 실행하되 I0/R은 프리패스 룩업에서 가져오고, `last_valid_shift`·`current_params`·`needs_pre_calibration`은 워밍업 replay로 복원. **본체 스캔 결과만 기록**. 워밍업 M은 shift가 벽에 빨리 붙으니 작아도 됨(~10~40). 검증: 워밍업 꼬리에서 last_valid_shift 안정 확인.
- **메인 스레드**: 청크 결과를 순서대로 모아 `result_ready`(테이블) emit + **Kalman은 전체 순서열에 후처리**로 `_Smooth` 채움 + (터보면 플롯 생략). 
- **터보 모드 한정 적용**(interval-1, 라이브플롯 끔). 일반/관찰은 기존 순차 유지.
- 검증 게이트: 콜드+핫 한 런씩 순차 vs 청크 **per-scan ppb 바이트/허용오차 대조**(특히 청크 경계·콜드 불안정 구간).

## 주의
- 알파 입력 경로(`_is_alpha_input`/`_alpha_fit_slice`)도 동일 루프 안. 청크 함수가 이 분기도 그대로 포함해야 함.
- 채널 루프는 상위(app_window:3725 채널마다 AnalysisWorker)라 청크는 한 채널 내부 분할.
