"""
process_inlet.py

Yeosu 2026 Inlet(jNO2/jO3) 데이터 처리 스크립트
원본 MATLAB 코드의 기능을 그대로 Python으로 변환.

사용법:
    python process_inlet.py
    (하단 main() 내 date 변수만 바꿔서 사용)
"""

import os
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.io import savemat


# ================================================================
# LabVIEW .dat 파일 읽기 함수
# 포맷: 탭 구분 텍스트, 11열, 헤더 없음, CRLF 줄바꿈
#   col 0 : timestamp 상위 16비트
#   col 1 : timestamp 하위 16비트
#   col 2 : jNO2 upward   × 1000
#   col 3 : jNO2 downward × 1000
#   col 4 : jO3 upward    × 1000  (2026 N/A)
#   col 5 : jO3 downward  × 1000  (2026 N/A)
#   col 6~10 : 기타 채널
# ================================================================
def Func_Read_2026_Yeosu_Inlet(filename: str) -> np.ndarray:
    # names=range(11): 열 수를 11로 강제 고정 (첫 행이 불완전해도 오탐 방지)
    # on_bad_lines='skip': 열이 더 많은 이상 행 스킵
    # dropna: 11열 미만인 불완전 행 제거
    df = pd.read_csv(filename, sep='\t', header=None,
                     names=range(11), on_bad_lines='skip')
    df = df.dropna()
    return df.values


def main():
    # ----------------------------------------------------------
    # 입력값 (코드 유일한 입력) — 형식: 'YYYY-MM-DD'
    # ----------------------------------------------------------
    date = '2026-05-18'

    # ----------------------------------------------------------
    # 경로 설정
    # ----------------------------------------------------------
    BASE_PATH = r'H:\Yeosu_2026\Inlet_Oven_Box'

    crunchingdate = date
    year  = crunchingdate[0:4]
    month = crunchingdate[5:7]
    day   = crunchingdate[8:10]

    rawdatapath = os.path.join(BASE_PATH, crunchingdate[0:7])
    os.chdir(rawdatapath)

    # ----------------------------------------------------------
    # 해당 날짜 .dat 파일 목록 수집
    # MATLAB: eval(['rawfilename=dir(',39,concate_rawdatafile,39,')'])
    # ----------------------------------------------------------
    concate_rawdatafile = crunchingdate[0:5] + '*.dat'
    rawfilenames = sorted(glob.glob(concate_rawdatafile))

    # ----------------------------------------------------------
    # 파일 순차 로딩 → 세로로 쌓기
    # ----------------------------------------------------------
    data_list = []
    for fname in rawfilenames:
        print(fname)
        temp = Func_Read_2026_Yeosu_Inlet(fname)
        if len(temp) == 0:
            print(f"  → 유효 데이터 없음, 건너뜀")
            continue
        data_list.append(temp)

    data = np.vstack(data_list)

    # ----------------------------------------------------------
    # 16비트 상위/하위 바이트 → 32비트 정수 복원 (LabVIEW 타임스탬프)
    # MATLAB: x=uint16(data(:,1)); y=uint16(data(:,2));
    #         bytepack=bitshift(uint32(x),16);
    #         z=double(bitor(bytepack,uint32(y)));
    # ----------------------------------------------------------
    x = data[:, 0].astype(np.uint16)   # 상위 16비트
    y = data[:, 1].astype(np.uint16)   # 하위 16비트
    bytepack = x.astype(np.uint32) << 16
    z = np.double(np.bitwise_or(bytepack, y.astype(np.uint32)))

    # ----------------------------------------------------------
    # LabVIEW 타임스탬프 → UTC datetime 변환
    #
    # MATLAB 원문:
    #   ref_sec = 3660681600 + 31536000 + 31536000
    #   this_year_sec = z / 100
    #   labviewtime = ref_sec + this_year_sec
    #   time_UTC = datenum(1904,1,1) + labviewtime/(24*3600) + 366
    #   caldate = datevec(time_UTC);  caldate(:,1) = 2026
    #
    # Python 등가 유도:
    #   - MATLAB datenum = Python ordinal + 366  (알려진 오프셋)
    #   - time_UTC(datenum) = 695422 + labviewtime/86400 + 366
    #   - time_UTC(python ordinal) = 695422 + labviewtime/86400
    #   - fromordinal(695422) = 1905-01-01
    #     (1904-01-01 + 366일, 1904는 윤년이므로 정확히 1905-01-01)
    #   => effective_epoch = Timestamp('1905-01-01')
    # ----------------------------------------------------------
    ref_sec = 3660681600 + 31536000 + 31536000
    this_year_sec = z / 100
    labviewtime = ref_sec + this_year_sec          # LabVIEW 절대 초

    effective_epoch = pd.Timestamp('1905-01-01')
    time_UTC = pd.to_timedelta(labviewtime, unit='s') + effective_epoch

    # 연도를 2026으로 덮어씀 (MATLAB: caldate(:,1) = 2026)
    time_inlet = pd.DatetimeIndex(
        [t.replace(year=2026) for t in time_UTC]
    )

    # ----------------------------------------------------------
    # 측정 채널 추출 및 단위 변환
    # /1000: 저장 시 파일 용량 절감을 위해 ×1000 정수 저장 → 읽을 때 복원
    # ----------------------------------------------------------
    idx_temp = slice(None)   # 전체 데이터 (MATLAB: idx_temp = 1:length(data))

    n = len(data[idx_temp])
    data_inlet = np.empty((n, 8))

    data_inlet[:, 0] = data[idx_temp, 2] / 1000   # jNO2 upward
    data_inlet[:, 1] = data[idx_temp, 3] / 1000   # jNO2 downward
    data_inlet[:, 2] = data[idx_temp, 4] / 1000   # jO3 upward  (2026 N/A)
    data_inlet[:, 3] = data[idx_temp, 5] / 1000   # jO3 downward (2026 N/A)

    # 이동평균 스무딩 (window=150, centered) — MATLAB movmean(x, 150) 등가
    for i in range(4):
        data_inlet[:, i + 4] = (
            pd.Series(data_inlet[:, i])
            .rolling(150, center=True, min_periods=1)
            .mean()
            .values
        )

    # ----------------------------------------------------------
    # 변수명 목록 (MATLAB vrn_inlet 등가)
    # ----------------------------------------------------------
    vrn_inlet = [
        'jNO2_upward',        'jNO2_downward',
        'jO3_upward',         'jO3_downward',
        'jNO2_upward_smooth', 'jNO2_downward_smooth',
        'jO3_upward_smooth',  'jO3_downward_smooth',
    ]

    # ----------------------------------------------------------
    # 저장 (.mat 파일, MATLAB 호환)
    # time은 MATLAB datenum 값으로 변환하여 저장
    # (MATLAB datenum = Python ordinal + 366 + 시분초 소수점)
    # ----------------------------------------------------------
    time_inlet_may = time_inlet
    data_inlet_may = data_inlet

    time_inlet_may_datenum = np.array([
        t.toordinal() + 366
        + t.hour / 24.0
        + t.minute / 1440.0
        + t.second / 86400.0
        + t.microsecond / 86400e6
        for t in time_inlet_may
    ])

    save_path = r'D:\FieldData_Yeosu_2026\Inlet'
    savemat(
        os.path.join(save_path, 'data_inlet_May.mat'),
        {
            'time_inlet_may': time_inlet_may_datenum,
            'data_inlet_may': data_inlet_may,
            'vrn_inlet':      vrn_inlet,
        }
    )

    # ----------------------------------------------------------
    # 시각화
    # MATLAB: figure; plot(time_inlet, data_inlet(:,1));
    #         hold on; plot(time_inlet, data_inlet(:,5));
    # ----------------------------------------------------------
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(time_inlet, data_inlet[:, 0], label='jNO$_2$ upward (raw)')
    ax.plot(time_inlet, data_inlet[:, 4], label='jNO$_2$ upward (smooth)')
    ax.set_xlabel('Time [UTC]')
    ax.set_ylabel('jNO$_2$ signal [V]')
    ax.set_ylim([0, 5])
    ax.legend()
    plt.tight_layout()
    plt.show()


if __name__ == '__main__':
    main()
