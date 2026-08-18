# -*- coding: utf-8 -*-
"""연구실 공유용 R0 -- 1분 해상도 버전 (2026-08-13).

`build_labshare.py`(5분)는 이미 만들어진 5분 CSV를 소비했지만, 그 CSV를 만든 스크립트가
레포에 없어서(애드혹으로 생성됨) 이번엔 raw 핏 결과(.dat)부터 직접 1분 시리즈를 만든다.

콜드/핫 raw 스캔은 원래 ~60초 간격, 한 분에 스캔 1개뿐이라(겹치는 경우 없음 -- 확인됨)
"1분평균"은 실질적으로 여러 스캔 평균이 아니라 기존 분당-1스캔 데이터를 1분 격자에 얹는 것과
같다. QC는 기존 5분 CSV와 동일 관행: Chi2<10, Status 필드는 의도적으로 안 씀(저SNR 정상핏을
지워 평균을 편향시키므로).

flag 로직·bad-window 리스트는 build_labshare.py 것을 그대로 재사용(타임스탬프 기반이라
격자 해상도 무관). low_quality(6/17)는 원 판정 스크립트가 없어 고정 날짜창으로 대체.
"""
import glob
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import openpyxl
import pandas as pd

CFG_DIR = r"C:\Doasis_Work\Output\fitting\ch1_429.5~461.9_ch2_444.1~470.6_ch3_438.4~475.8"
G = 0.82

DROPBOX_XLSX = (r"C:\Users\holle\ATMOS Dropbox\GyungHwan Lee\ATMOS_all\(mission)2026_yeosu"
                r"\측정자료제출\2_`26년 남부지역 오존 집중조사 자료 취합 파일_CAESAR_GIST_labshare.xlsx")
OUT_XLSX = r"C:\Doasis_Work\Output\figure\NIER_submit\SDD_CAESAR_O3campaign_2026_labshare.xlsx"

COLD_BAD_WINDOWS_9 = [
    ("2026-05-20 00:00:00", "2026-05-24 00:00:00"),
    ("2026-05-27 18:00:00", "2026-05-28 12:00:00"),
    ("2026-06-05 00:00:00", "2026-06-05 23:59:59"),
    ("2026-06-17 00:00:00", "2026-06-17 23:59:59"),  # low_quality, 원 판정식 없어 고정창 대체
]
COLD_CAL_WINDOWS_4 = [
    ("2026-06-02 16:10:00", "2026-06-02 16:55:00"),
]
HOT_SUSPECT_3 = [
    ("2026-05-22 09:00:00", "2026-05-22 10:22:00"),
    ("2026-05-23 08:49:00", "2026-05-23 09:29:00"),
    ("2026-05-24 10:15:00", "2026-05-24 10:55:00"),
    ("2026-05-26 17:18:00", "2026-05-26 18:15:00"),
    ("2026-06-05 21:17:00", "2026-06-05 22:34:00"),
    ("2026-06-07 16:49:00", "2026-06-07 17:29:00"),
    ("2026-06-09 12:46:00", "2026-06-09 13:00:00"),
    ("2026-06-12 04:21:00", "2026-06-12 05:01:00"),
    ("2026-06-14 11:27:00", "2026-06-14 12:07:00"),
    ("2026-06-21 06:38:00", "2026-06-21 22:38:00"),
    ("2026-06-22 09:08:00", "2026-06-22 09:48:00"),
    ("2026-06-22 10:12:00", "2026-06-22 10:52:00"),
    ("2026-06-23 17:01:00", "2026-06-23 17:41:00"),
    ("2026-07-09 08:40:00", "2026-07-09 09:31:00"),
]
HOT_MISSING_9 = [
    ("2026-06-09 11:00:00", "2026-06-09 12:46:00"),
]
HOT_CAL_4 = [
    ("2026-06-09 19:55:00", "2026-06-09 20:45:00"),
]


def in_any(t, windows):
    return any(pd.Timestamp(s) <= t <= pd.Timestamp(e) for s, e in windows)


def load_dat(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    header_i = next(i for i, l in enumerate(lines) if l.split("\t")[0].strip() == "File")
    cols = [c.strip() for c in lines[header_i].strip("\n").split("\t")]
    rows = [l.rstrip("\n").split("\t") for l in lines[header_i + 1:] if l.strip()]
    df = pd.DataFrame(rows, columns=cols)
    df["Time"] = pd.to_datetime(df["Time"])
    df["NO2"] = pd.to_numeric(df["NO2"], errors="coerce")
    df["Chi2"] = pd.to_numeric(df["Chi2"], errors="coerce")
    return df[["Time", "NO2", "Chi2"]]


def load_species_1min(species_suffix, qc_chi2=10.0):
    pattern = os.path.join(CFG_DIR, "??????", "neg_o", "QCoff", f"*_{species_suffix}_*.dat")
    files = sorted(glob.glob(pattern))
    print(f"[{species_suffix}] {len(files)} daily files")
    dfs = [load_dat(f) for f in files]
    df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset="Time").sort_values("Time")
    df = df[df["Chi2"] < qc_chi2]
    df["minute"] = df["Time"].dt.floor("min")
    s = df.groupby("minute")["NO2"].mean()
    return s


print("=== 콜드 로드 ===")
cold = load_species_1min("cold").rename("cold_NO2")

print("=== ANs(ch1)/PNs(ch2) 로드 ===")
ch1 = load_species_1min("ANs").rename("ch1_NO2")
ch2 = load_species_1min("PNs").rename("ch2_NO2")
hot = pd.concat([ch1, ch2], axis=1).dropna()
hot["ANs_NO2"] = hot["ch1_NO2"] - G * hot["ch2_NO2"]
print(f"cold: {len(cold)} min-bins  {cold.index.min()} ~ {cold.index.max()}")
print(f"hot(matched ch1&ch2): {len(hot)} min-bins  {hot.index.min()} ~ {hot.index.max()}")

no2 = pd.DataFrame({"datetime_KST": cold.index, "v": cold.values})
ans = pd.DataFrame({"datetime_KST": hot.index, "v": hot["ANs_NO2"].values})


def cold_flag(row):
    t = row["datetime_KST"]
    v = row["v"]
    if pd.isna(v):
        return 9
    if in_any(t, COLD_CAL_WINDOWS_4):
        return 4
    if in_any(t, COLD_BAD_WINDOWS_9):
        return 9
    if v < -10:
        return 9
    return 0


no2["flag"] = no2.apply(cold_flag, axis=1)
no2.loc[no2["flag"].isin([4, 9]), "v"] = np.nan


def hot_flag(row):
    t = row["datetime_KST"]
    if in_any(t, HOT_CAL_4):
        return 4
    if in_any(t, HOT_MISSING_9):
        return 9
    if pd.isna(row["v"]):
        return 9
    if in_any(t, HOT_SUSPECT_3):
        return 3
    return 0


ans["flag"] = ans.apply(hot_flag, axis=1)
ans.loc[ans["flag"].isin([4, 9]), "v"] = np.nan

t_min = min(no2.datetime_KST.min(), ans.datetime_KST.min())
t_max = max(no2.datetime_KST.max(), ans.datetime_KST.max())
grid = pd.date_range(t_min, t_max, freq="1min")
print(f"grid: {len(grid)} 1-min bins  {t_min} ~ {t_max}")

no2_i = no2.set_index("datetime_KST")[["v", "flag"]].reindex(grid)
no2_i["flag"] = no2_i["flag"].fillna(9).astype(int)
ans_i = ans.set_index("datetime_KST")[["v", "flag"]].reindex(grid)
ans_i["flag"] = ans_i["flag"].fillna(9).astype(int)

full = pd.DataFrame(index=grid)
full["SDD_CAESAR_NO2_ppbv"] = no2_i["v"].round(4)
full["SDD_CAESAR_NO2_flag"] = no2_i["flag"]
full["SDD_CAESAR_ANs_ppbv"] = ans_i["v"].round(4)
full["SDD_CAESAR_ANs_flag"] = ans_i["flag"]
full = full.reset_index().rename(columns={"index": "START_TIME"})
full["END_TIME"] = full["START_TIME"] + pd.Timedelta(minutes=1)
full = full[["START_TIME", "END_TIME", "SDD_CAESAR_NO2_ppbv", "SDD_CAESAR_NO2_flag",
             "SDD_CAESAR_ANs_ppbv", "SDD_CAESAR_ANs_flag"]]

for sp in ("NO2", "ANs"):
    vc = full[f"SDD_CAESAR_{sp}_flag"].value_counts().sort_index()
    print(sp, dict(vc))

FLAG_NOTE = ("Flag codes: 0=Good/Valid, 1=Below LOD, 2=Interpolated, 3=Suspect(instrument "
             "unstable/maintenance nearby, value kept), 4=Calibration(injection test, not "
             "ambient), 9=Missing/Bad. Suspect windows derived from field-log maintenance "
             "events (LED TEC adjustments, filter changes, cylinder swaps, filter test "
             "06-21). Injection contamination confirmed: cold 06-02 16:10-16:55 (raw file "
             "N_valid 5->1 drop), hot 06-09 19:55-20:45 (raw noise spike).")

LABELS = {
    1: "연구책임자 성명(영문명)", 2: "연구책임자 소속(영문)", 3: "연구책임자 이메일",
    4: "연구책임자 연락처", 5: "자료관리자 성명(영문명)", 6: "자료관리자 이메일",
    7: "자료관리자 연락처", 8: "자료버전 *R0부터 시작", 9: "측정 장소(위도, 경도)",
    10: "측정 장비명 및 분석방법 *측정 항목별로 간단히 작성",
    11: "측정 원자료 시간 해상도 *측정 항목별로 간단히 작성",
    12: "최소검출한계(MDL) *측정 항목 또는 분석법별 작성",
    13: "측정불확도 또는 정밀도 *측정 항목 또는 분석법별 작성",
    14: "기타 정보(자료 처리 방법 등 특이사항)",
    15: "변수명 1", 16: "변수명 2",
}


def build_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    wb.create_sheet("Info")
    headers = list(full.columns)
    for c, h in enumerate(headers, start=1):
        ws.cell(1, c, h)
    for i, row in enumerate(full.itertuples(index=False), start=2):
        for c, v in enumerate(row, start=1):
            ws.cell(i, c, None if (isinstance(v, float) and pd.isna(v)) else v)

    info = wb["Info"]
    for r, lab in LABELS.items():
        info.cell(r, 1).value = lab
    info.cell(1, 2).value = "민경은 (Kyung-Eun Min)"
    info.cell(2, 2).value = "광주과학기술원 (Gwangju Institute of Science and Technology, GIST)"
    info.cell(3, 2).value = "kemin@gist.ac.kr"
    info.cell(4, 2).value = "062-715-3280"
    info.cell(5, 2).value = "이경환 (Gyung-Hwan Lee)"
    info.cell(6, 2).value = "gh548080@gist.ac.kr"
    info.cell(7, 2).value = "062-715-2470"
    info.cell(8, 2).value = "R0"
    info.cell(9, 2).value = "전남 순천시 해룡면 신대리 2040 (34.92959, 127.54514)"
    info.cell(10, 2).value = ("Nitrogen dioxide (NO2): CAESAR-cold, BBCEAS (Broadband "
                              "Cavity-Enhanced Absorption Spectroscopy)\nTotal alkyl nitrates "
                              "(ANs): CAESAR-hot, TD-BBCEAS (Thermal-Dissociation BBCEAS), "
                              "g=0.82 채널이득보정 적용")
    info.cell(11, 2).value = ("Nitrogen dioxide (NO2): 1sec (raw), 제출자료는 1분 평균\n"
                              "Total alkyl nitrates (ANs): 1sec (raw), 제출자료는 1분 평균")
    info.cell(12, 2).value = "TBD"
    info.cell(13, 2).value = "TBD"
    info.cell(14, 2).value = (FLAG_NOTE + "\nPNs(과산화질산염)는 콜드/핫 NO2 인젝션 재실험 진행 후 "
                              "추가 예정 — 이번 버전엔 미포함.\n현재 농도 보정이 완료되지 않은 R0 "
                              "버전 자료로, 데이터 사용 시 반드시 PI에게 이메일로 사전 문의 필요.")
    info.cell(15, 2).value = "SDD_CAESAR_NO2_ppbv"
    info.cell(16, 2).value = "SDD_CAESAR_ANs_ppbv"

    wb.save(path)
    print("saved", path)


build_xlsx(DROPBOX_XLSX)
build_xlsx(OUT_XLSX)
