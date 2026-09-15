# V2 실측 운영 확인 — 로컬 입력/출력

원본 α/reference/wavecal은 수정하지 않는다. `yeosu_pns` 입력은 경로와 실제
reference 배열을 포함하므로 공개 fixture가 아니다. 저장소 공개 커밋 대상에서 제외한다.

준비 명령:

```powershell
python tools/prepare_fit_explorer_v2_field_case.py --metadata-config diagnostics/yeosu_profile_2026-09/yeosu_hot_runtime_fitset.json --channel-key 2 --alpha-root diagnostics/yeosu_reprovenanced_alpha_2026-09/PNs --output-directory diagnostics/fit_explorer_v2_operational_2026-09/yeosu_pns
```

- Discovery: 2026-05-26, 2026-05-30 각각 파일의 첫/마지막 행.
- Validation: 2026-06-04 첫/마지막 행.
- Holdout: 2026-06-09 첫/마지막 행. 이번 실행에서만 분리한 날짜이며 과거에
  검토했던 자료다. 모든 observation의 `previously_used=True`; 독립 신규 검증 아님.
- 탐색 범위: 445–469 / 446–469 nm, poly 2/3/4, shift -5..5 px,
  squeeze 0.9999..1.0001. 유한 운영 확인 범위이지 전체 최적범위 주장 아님.
- NO2/H2O/CHOCHO 모두 사용한다. source header가 절대 단위를 명시하지 않으므로
  전부 `arb`로 표시한다. H2O의 `10^-12` 배율은 기존 로더 metadata에서 명시적으로
  가져와 적용하되 `cm²/molecule` 또는 ppb라는 미확인 해석을 붙이지 않는다.
- 레퍼런스의 Dynamic-ILS-Applied header와 wave/reference 길이 대응을 검사한다.
- legacy FitSet의 window/poly/registration은 가져오지 않는다.
- 민감도 임계값을 만들지 않는다. 기준 부족과 과거 holdout 노출이 결과에 드러나야 한다.

실제 실행/추천 연결 결과는 실행 후 별도로 기록한다. 입력 준비 성공은 피팅 성공이 아니다.
