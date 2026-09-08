# Explorer V1 운영 acceptance — 2026-09-09

여수 PNs raw 네 날짜(2026-05-26, 05-30, 06-04, 06-09)에서 현재 production
`AlphaExportWorker`를 headless로 실행했다. 각 raw에는 He가 없으므로 당시 운영에서
사용한 공용 `R_CH2.npz`를 명시 입력으로 재사용했다. 새 alpha 네 파일은 모두
`T_P_PROVENANCE: measured_raw_housekeeping`와 R 파일 provenance를 기록했다.

그 alpha로 기존 PNs mid 후보를 Stage 2에 실행했다.

- 4일, 날짜당 3행, 총 12행 × controlled start 2개 = 24회
- 24/24 fit 완료, 최대 paired-start 농도 차이 `1.22e-6 ppb`
- boundary hit 2/24
- Review JSON 생성과 no-Apply 계약 확인

이 acceptance는 alpha 생성 → deterministic Stage 2 표본 → 실제 production fit →
Review 카드 입력까지의 **운영 경로**가 동작함을 보인다. 새 alpha의 중앙값은 기존 Yeosu
evidence와 달랐으므로, 이것을 기존 후보의 과학적 재현 또는 추천으로 해석하지 않는다.
이 실행의 Review verdict는 holdout·이웃 후보 비교가 없어서
`NON_IDENTIFIABLE_OR_ABSTAIN`이다.
