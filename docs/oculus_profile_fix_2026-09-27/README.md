# Oculus hot 프로파일 정정안 (2026-09-27)

> **✅ 2026-10-01 적용됨** — `vigil/profiles/caesar_hot.example.json` 1.2.0. 이 폴더는 근거 기록으로 남긴다.
> wavecal 짝(FitSet 기준 ANs=roi1)과 `CHANNEL_IDENTITY_YEOSU2026.md` 표(ANs=roi2)의 차이는 미결로 그 문서에 메모.

`oculus/` 폴더는 Windows 권한 때문에 이 작업 환경에서 읽기·쓰기가 막혀 있다. 그래서 **git에 커밋된 판**
(`oculus/profiles/caesar_hot.example.json`, profile_version 1.0.0)을 git 객체에서 직접 읽어 점검했고,
정정한 파일을 여기에 둔다. 작업트리의 `oculus/` 판이 커밋 판과 다를 수 있으니 적용 전에 diff를 볼 것.

## 커밋 판에서 발견한 문제 세 가지

| 항목 | 커밋 판 (1.0.0) | 정정안 (1.2.0) | 근거 |
|---|---|---|---|
| 채널 이름 | block 2053 = `PNs`, block 4101 = `ANs` | 2053 = `ANs`, 4101 = `PNs` | LED 스펙트럼 판정, `CHANNEL_IDENTITY_YEOSU2026.md` |
| 캐비티 압력 | 2053 ← `p_pns_cavity`(6162), 4101 ← `p_ans_cavity`(6164) | 2053 ← `p_ans_cavity`, 4101 ← `p_pns_cavity` | `core/data_io.py` 압력 짝 정정과 같음 |
| 캐비티 기체 온도 | **오븐 설정값** `oven_pns_setpoint`(180 °C) / `oven_ans_setpoint`(300 °C) | 실측 `tempcell1`(2053) / `tempcell2`(4101), ~35–38 °C | Augur와 같은 센서·같은 짝 |
| R 계산 창(`reflectance.roi_nm`) | 2053에 444.1–470.6, 4101에 429.7–466.0 (서로 바뀜) | 2053에 429.7–466.0, 4101에 444.1–470.6 | 각 블록 LED 대역, FitSet 채널 창과 일치 |

농도 핏이 고르는 FitSet 채널은 `wl_dir`로 정해지고(`conc_monitor.pick_fitset_channel`), roi1 → FitSet 채널 1
(429.7–466.0 nm), roi2 → 채널 2(444.1–470.6 nm)라 **핏 창 자체는 원래도 맞았다**. `wl_dir`은 그대로 두었다.

## 영향 (2026-06-01-001.dat, 대기 행 중앙값으로 계산)

온도와 압력은 `n_air = P/(kT)`로 ppb 환산에 들어간다(`param_optimizer.fit_scan`). 커밋 판의 hot 실시간 ppb를
Augur 기준으로 나누면 **block 2053 × 1.39, block 4101 × 1.96**이다. 대부분은 오븐 설정값을 기체 온도로 쓴 탓이다.
R 모니터도 같은 T/P로 레일리 항을 계산하므로 hot R 경보 수준도 영향을 받는다. Oculus는 실시간 감시용이라 논문
수치에는 들어가지 않는다.

정정안을 커밋된 Oculus 로더(`oculus.profile.ProfileSet`)로 읽으면 스키마 검증을 통과한다. 같은 raw 행에서 뽑은 T/P는
2053: 37.8 °C, 922.6 mbar / 4101: 34.5 °C, 968.1 mbar로, Augur(`read_scans_via_dataio`)의 ZA 블록 값
37.4 °C, 916.3 mbar / 34.4 °C, 961.8 mbar와 같은 센서 짝이다.

## 적용 (관리자 PowerShell)

```powershell
icacls C:\GHL\CAESAR\oculus /reset /T
cd C:\GHL\CAESAR
fc.exe oculus\profiles\caesar_hot.example.json docs\oculus_profile_fix_2026-09-27\caesar_hot.example.json
Copy-Item docs\oculus_profile_fix_2026-09-27\caesar_hot.example.json oculus\profiles\caesar_hot.example.json
```

현장 PC가 `.example`이 아닌 사본(`caesar_hot.json` 등)을 쓰고 있다면 그 파일도 같은 방식으로 바꿔야 한다.
`vigorous-lederberg-8c5f2a` worktree에는 이 파일의 커밋 안 된 수정(1.1.0, `roi_nm`만 교정)이 남아 있다 — 이름·온도·압력은
그대로라 정정안이 그것을 포함한다.
