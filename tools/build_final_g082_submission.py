# -*- coding: utf-8 -*-
"""R0 최종 제출본 빌드 스크립트 (2026-08-12, 지도교수 최종 확정 방식).

⚠️ 재실행 주의: 이 스크립트는 Downloads의 공식 취합 템플릿 xlsx를 통째로 덮어쓴다.
교수님이 그 파일을 직접 손으로 수정(전화번호 삭제, 시간해상도 "1sec"로 정정, MDL/불확도
TBD로 단순화)하신 뒤라 -- **이 스크립트를 그대로 재실행하면 그 수기 수정이 날아간다.**
방법론 참고용으로 보존하는 것이지, 그대로 재실행하는 스크립트가 아니다. 재실행하려면
info_updates 딕셔너리를 교수님 최종본 내용으로 먼저 맞출 것.

방법:
  1. NO2 = 콜드 raw, 이상구간만 공란 처리(스케일 보정 없음)
  2. ANs = NO2(300도C 셀) - g*NO2(180도C 셀), g=0.82 (2026-08-11 NO2 인젝션, R^2=0.9998,
     6/9 재분석 g=0.83으로 재확인)
소스 CSV는 Output/figure/NIER_submit/GIST_CAESAR_{cold_NO2,ANs}_...csv (R0 최종본).
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
import openpyxl
import pandas as pd
from datetime import timedelta

SUB = r"C:\Doasis_Work\Output\figure\NIER_submit"
NO2_CSV = os.path.join(SUB, "GIST_CAESAR_cold_NO2_5min_KST_20260517_20260618.csv")
ANS_CSV = os.path.join(SUB, "GIST_CAESAR_ANs_5min_KST_20260518_20260710.csv")
d = r"C:\Users\holle\Downloads"
TEMPLATE = os.path.join(d, [x for x in os.listdir(d) if x.endswith("CAESAR_GIST.xlsx")][0])

no2 = pd.read_csv(NO2_CSV, comment="#")
ans = pd.read_csv(ANS_CSV, comment="#")
no2["datetime_KST"] = pd.to_datetime(no2["datetime_KST"])
ans["datetime_KST"] = pd.to_datetime(ans["datetime_KST"])
full = pd.merge(no2[["datetime_KST", "NO2_ppb"]], ans[["datetime_KST", "ANs_ppb"]],
                 on="datetime_KST", how="outer").sort_values("datetime_KST").reset_index(drop=True)
full["END_TIME"] = full["datetime_KST"] + timedelta(minutes=5)
full = full.rename(columns={"datetime_KST": "START_TIME", "NO2_ppb": "SDD_CAESAR_NO2_ppbv",
                             "ANs_ppb": "SDD_CAESAR_ANs_ppbv"})
full = full[["START_TIME", "END_TIME", "SDD_CAESAR_NO2_ppbv", "SDD_CAESAR_ANs_ppbv"]]
print(f"rows: {len(full)}  range {full.START_TIME.min()} ~ {full.START_TIME.max()}")

LOCATION = "전남 순천시 해룡면 신대리 2040 (34.92959, 127.54514)"
METHOD = ("Nitrogen dioxide (NO2): CAESAR-cold, BBCEAS (Broadband Cavity-Enhanced Absorption "
          "Spectroscopy)\nTotal alkyl nitrates (ANs): CAESAR-hot, TD-BBCEAS "
          "(Thermal-Dissociation BBCEAS), g=0.82 채널이득보정 적용")
TIMERES = "Nitrogen dioxide (NO2): 1sec\nTotal alkyl nitrates (ANs): 1sec"
MDL = "TBD"
UNC = "TBD"
OTHER = ("현재 농도 보정이 완료되지 않은 R0 버전 자료로, 데이터 사용 시 반드시 PI에게 이메일로 "
         "사전 문의 필요")

wb = openpyxl.load_workbook(TEMPLATE)
ws = wb["Data"]
ws.delete_rows(1, ws.max_row)
if ws.max_column > 4:
    ws.delete_cols(5, ws.max_column - 4)
headers = ["START_TIME", "END_TIME", "SDD_CAESAR_NO2_ppbv", "SDD_CAESAR_ANs_ppbv"]
for c, h in enumerate(headers, start=1):
    ws.cell(1, c, h)
for i, row in enumerate(full.itertuples(index=False), start=2):
    ws.cell(i, 1, row.START_TIME)
    ws.cell(i, 2, row.END_TIME)
    ws.cell(i, 3, None if pd.isna(row.SDD_CAESAR_NO2_ppbv) else round(float(row.SDD_CAESAR_NO2_ppbv), 4))
    ws.cell(i, 4, None if pd.isna(row.SDD_CAESAR_ANs_ppbv) else round(float(row.SDD_CAESAR_ANs_ppbv), 4))

info = wb["Info"]
info.cell(9, 2).value = LOCATION
info.cell(10, 2).value = METHOD
info.cell(11, 2).value = TIMERES
info.cell(12, 2).value = MDL
info.cell(13, 2).value = UNC
info.cell(14, 2).value = OTHER
info.cell(17, 1).value = None
info.cell(17, 2).value = None

if __name__ == "__main__":
    raise SystemExit(
        "재실행 방지 가드: 위 docstring 읽고, 교수님 최종 수기수정본과 info_updates가 "
        "일치하는지 확인 후 이 raise 줄을 지우고 wb.save(TEMPLATE)를 호출할 것."
    )
