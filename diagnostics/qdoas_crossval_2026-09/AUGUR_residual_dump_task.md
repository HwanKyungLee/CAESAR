# 작업: Augur VarPro 피팅의 픽셀별(파장별) 잔차(residual)를 파일로 저장

## 배경 / 왜 필요한가
AUGUR(CAESAR) 소프트웨어 논문의 외부 교차검증(QDOAS와의 비교, `diagnostics/qdoas_crossval_2026-09/`)에서
Hot ANs 채널의 CHOCHO/H2O 계수가 QDOAS 결과와 상관성이 낮게 나오는 원인을 조사 중이다(공선성/신호세기/
Shift bound 불일치 세 가설은 데이터로 이미 기각됨). 다음 조사 단계는 "Augur의 피팅 잔차가 파장별로
QDOAS의 잔차와 어디서 갈라지는지" 직접 비교하는 것인데, **QDOAS는 이미 스캔당 픽셀별 잔차를 ASCII로
저장하는 내장 기능이 있음**(Analysis Window > Output 탭의 "Residual spectrum" 필드). 반면 **Augur는
이 값을 파일로 저장하지 않는다** — 계산은 하지만 버려진다. 이 작업은 그 갭을 메우는 것이다.

## 현재 코드 상태 (원인 확인 완료)
파일: `gui/worker.py`, 클래스 `AnalysisWorker`.

스캔 하나를 피팅하는 두 지점(둘 다 `execute_varpro_fit` 직후) 모두 동일한 패턴을 갖는다:

**지점 1 — 순차 처리 경로, ~line 596-621** (`is_linear_mode` 분기 포함):
```python
abs_val_orig, poly_val_orig = abs_val_scaled / scale_factor, poly_val_scaled / scale_factor
etalon_part_orig = (etalon_amp_scaled * np.sin(fixed_e_f * pixel_idx + best_ep)) / scale_factor
y_fit_model_orig = poly_val_orig + (fit_sign * abs_val_orig) + etalon_part_orig
if is_linear_mode:
    residual = intensity_raw - y_fit_model_orig
else:
    residual = optical_depth - y_fit_model_orig
rms = np.sqrt(np.mean(residual**2))

result['RMS'] = rms
result['Shift'] = opt_shifts[0] if len(opt_shifts) > 0 else 0
result['Squeeze'] = opt_squeezes[0] if len(opt_squeezes) > 0 else 1
final_params_dict = {
    'shifts': opt_shifts, 'squeezes': opt_squeezes,
    'gas_coeffs': (gas_coeffs_scaled / scale_factor).tolist(),
    'poly_coeffs': (poly_coeffs_scaled / scale_factor).tolist(),
    'etalon_amp': etalon_amp_scaled / scale_factor,
    'etalon_phase': float(best_ep), 'etalon_freq': float(fixed_e_f),
    'channel': self.channel
}
result['Params'] = final_params_dict
```

**지점 2 — 배치/병렬 청크 처리 경로로 추정, ~line 868-890** (구조 거의 동일, `is_linear_mode` 분기가
안 보임 — **구현 전에 이 경로가 실제로 어떤 모드에서만 호출되는지 확인 필요**):
```python
residual = intensity_raw - y_fit_model_orig
rms = np.sqrt(np.mean(residual ** 2))
result['RMS'] = rms
result['Shift'] = opt_shifts[0] if len(opt_shifts) > 0 else 0
result['Squeeze'] = opt_squeezes[0] if len(opt_squeezes) > 0 else 1
result['Params'] = {
    'shifts': opt_shifts, 'squeezes': opt_squeezes,
    'gas_coeffs': (gas_coeffs_scaled / scale_factor).tolist(),
    'poly_coeffs': (poly_coeffs_scaled / scale_factor).tolist(),
    'etalon_amp': etalon_amp_scaled / scale_factor,
    'etalon_phase': float(best_ep), 'etalon_freq': float(fixed_e_f),
    'channel': self.channel}
```

**핵심 문제**: `residual` 배열(픽셀별, 이미 스케일 복원됨 — QDOAS의 광학밀도 잔차와 같은 물리적 단위)과
`result['Params']`가 두 지점 모두에서 계산까지는 되지만, `result['RMS']` 스칼라 하나만 남기고 버려진다.
`core/result_io.py`를 확인한 결과 `"Params"` 키를 전혀 참조하지 않음 (grep 0건) — 즉 최종 출력 파일
(`*_alpha_trace.dat`, `*_merge*.dat`)에는 이 정보가 전혀 남지 않는다.

## 참고할 기존 코드 패턴 (같은 스타일로 작성할 것)
`gui/worker.py` 안에 이미 비슷한 "헤더 한 줄 + 스캔당 한 줄" 텍스트 덤프 함수가 있다
(~line 1399-1421, alpha_trace.dat를 쓰는 함수 — 정확한 함수명은 주변 코드에서 확인할 것):
```python
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(f"# CAESAR Pro Alpha Export — {os.path.basename(fp)}\n")
    ...
    wv_str = '\t'.join(f"{w:.4f}" for w in ctx['wave_nm'])
    f.write(f"# wavelength_nm:\t{wv_str}\n")
    ...
    for rid, rep_sec, T, P, alpha, n_avg in rows:
        ...
        vals = '\t'.join(f"{v:.6e}" for v in alpha)
        f.write(f"{rid}\t{doy:.6f}\t{iso}\t{T:.2f}\t{P:.2f}\t{vals}\n")
```
새 잔차 덤프도 이 컨벤션(주석 헤더 + `# wavelength_nm:` 한 줄 + 스캔당 한 줄, tab-separated,
`%.6e` 포맷)을 그대로 따를 것 — 코드베이스 일관성 + QDOAS의 Residual 출력 포맷(첫 줄=파장 보정값,
이후 레코드당 한 줄)과도 구조가 맞아떨어져 비교 스크립트 작성이 쉬워진다.

## 요구사항

1. **완전히 opt-in이어야 한다.** 기본 동작(속도, 출력 파일)에 어떤 영향도 주면 안 됨 — 논문/제품
   출력에 쓰이는 기존 `merge.dat`/`alpha_trace.dat` 생성 경로는 절대 건드리지 않는다.
   - `AnalysisWorker.__init__`(또는 실행 시작 시점)에 `self.residual_dump_path: str | None = None` 같은
     속성을 추가하고, 외부(디버그 스크립트/GUI 고급 옵션)에서 명시적으로 경로를 설정했을 때만 덤프가
     동작하도록 한다 (`if getattr(self, 'residual_dump_path', None):`).
   - GUI에 새 체크박스/입력란을 추가할 필요는 없음(선택 사항) — 최소 요구사항은 스크립트로
     `worker.residual_dump_path = "..."`처럼 지정할 수 있으면 충분하다.

2. **두 지점(위 지점 1, 2) 모두에 동일한 덤프 로직을 추가한다.** 구현 전에 지점 2가 정말로 순차 경로와
   병렬로 존재하는 별도 코드 경로인지(예: `_run_parallel`에서 쓰는 워커 프로세스용 코드인지) 확인하고,
   두 경로가 실제로 다른 상황에서 호출된다면 둘 다 빠짐없이 패치할 것 — 하나만 패치하면 순차 실행과
   병렬 실행 결과가 서로 다른 정보량을 가지게 되어 혼란을 유발한다.

3. **덤프 파일 포맷** (`residual_dump_path`로 지정된 파일에 append):
   - 첫 줄(파일이 처음 열릴 때 한 번만): `# wavelength_nm:\t{탭구분 wave_nm 배열}` — 그 스캔의
     `pixel_idx`/`optical_depth`와 같은 길이·같은 순서여야 함(이미 코드 안에 `wave_nm` 변수가 있음,
     ~line 363-377/815-819 참조).
   - 이후 스캔마다 한 줄: 스캔을 식별할 키(merge.dat와 매칭 가능해야 하므로 **datetime 또는 row_idx**,
     `compare_qdoas_augur.py`가 지금 초 단위 타임스탬프로 inner join하고 있으므로 그 컬럼과 이름/포맷을
     맞출 것) + tab + RMS(참고용, 기존 `result['RMS']`와 동일해야 함, 회귀 테스트용) + tab + residual
     배열(`%.6e`, 탭구분).
   - 예:
     ```
     # wavelength_nm:	429.5123	429.5532	...
     datetime	rms	residual...
     2026-05-18 11:40:37	5.6816e-09	1.234e-08	-3.21e-09	...
     ```

4. **단위 확인**: `residual` 변수는 이미 `/scale_factor`로 원래 스케일로 복원된 뒤 계산된 값이다
   (지점 1의 `abs_val_orig`/`poly_val_orig` 라인 참조) — 즉 QDOAS의 광학밀도 잔차와 같은 물리적
   단위(무차원 광학밀도)여야 한다. 구현 후 반드시 다음을 확인할 것: 저장된 `residual` 배열로부터
   `sqrt(mean(residual**2))`를 다시 계산했을 때 같은 줄에 저장한 RMS 값과 (부동소수점 오차 이내로)
   일치하는지 — 스케일 실수를 잡아내는 가장 빠른 자체 검증이다.

5. **성능**: 덤프가 켜졌을 때만 파일 I/O가 발생해야 하며, 매 스캔마다 파일을 열고 닫지 말고 컨텍스트
   매니저를 워커 실행 시작~종료까지 유지하거나(가능하면), 최소한 append 모드로 열되 버퍼링에 유의할 것
   (수만 스캔 단위이므로 스캔마다 open/close하면 느려질 수 있음 — 기존 alpha_trace.dat 쓰기 함수가
   어떻게 하는지 참고).

## 완료 기준 (Acceptance Criteria)
- [ ] `residual_dump_path`를 지정하지 않고 실행한 기존 회귀 테스트/워크플로우가 **바이트 단위로 동일한**
      `merge.dat`/`alpha_trace.dat`를 만들어낸다(변경 없음 확인).
- [ ] `residual_dump_path`를 지정하고 실행하면, 처리된 스캔 수와 덤프 파일의 데이터 행 수가 일치한다.
- [ ] 덤프 파일의 각 행에서 재계산한 RMS가 같은 행에 저장된 RMS 값과 허용오차 내로 일치한다.
- [ ] 순차 실행 경로와 병렬(청크) 실행 경로 둘 다에서 덤프가 정상 동작한다(둘 중 하나만 지원한다면
      그 사실과 이유를 명시해서 보고할 것).
- [ ] `diagnostics/qdoas_crossval_2026-09/` 폴더의 실제 ANs 데이터(`C:\GHL\2026 yeosu\Output\alpha\
      10s\hot\ch1\` 아래 날짜 폴더, `run_hot_real.py`/`build_qdoas_spectrum.py`가 참조하는 것과 같은
      데이터)로 소규모 시험 실행(하루 치 정도)해서 덤프 파일이 실제로 만들어지고 위 검증을 통과하는지
      확인 후 결과를 보고할 것.

## 범위에 포함되지 않는 것
- GUI에 새 버튼/체크박스를 추가하는 것(선택 사항, 필수 아님).
- QDOAS 쪽 잔차 export 설정(이건 사용자가 QDOAS GUI에서 직접 처리 중).
- 이 잔차를 이용한 실제 비교 분석 스크립트 작성(별도 후속 작업 — `compare_qdoas_augur.py`를 확장하게 될 것).
