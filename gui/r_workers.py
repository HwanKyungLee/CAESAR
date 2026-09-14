"""gui/r_workers.py
R Calibrator용 백그라운드 QThread 워커 모음 (ui_dialogs_r.py에서 분리).
무거운 import(rt_precompute·r_trend_monitor)는 각 run() 안에서 lazy 수행한다.
"""
from PyQt6.QtCore import QThread, pyqtSignal


class _LiveStream:
    """sys.stdout 대체 — write() 호출마다 log 시그널로 실시간 전달."""
    def __init__(self, emit_fn):
        self._emit = emit_fn
        self._buf  = ""

    def write(self, text):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)

    def flush(self):
        if self._buf:
            self._emit(self._buf)
            self._buf = ""

    def isatty(self):
        return False


class _RTrendWorker(QThread):
    """백그라운드에서 r_trend_monitor.main()을 실행."""
    log        = pyqtSignal(str)
    finished   = pyqtSignal(str)    # 결과 폴더 경로
    # 시계열 데이터와 테이블 정보 전송용 시그널 확장
    data_ready = pyqtSignal(object, object, object, object)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            import sys as _sys, os as _os
            _tools_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
            if _tools_dir not in _sys.path:
                _sys.path.insert(0, _tools_dir)
            
            # 정적 분석기(Pylance) 가짜 경고 무시
            import r_trend_monitor as rtm # type: ignore
            cfg = self.cfg

            # 사용자 설정 오버라이드
            rtm.COLD_DIR         = cfg.get("cold_dir", "")
            rtm.HOT_DIR          = cfg.get("hot_dir",  "")
            rtm.WAVE_CAL_COLD    = cfg.get("wl_cold",  "")
            rtm.WAVE_CAL_HOT     = cfg.get("wl_hot",   "")      # PNs(roi1)=CH2
            rtm.WAVE_CAL_HOT_ANS = cfg.get("wl_hot_ans", "")    # ANs(roi2)=CH3
            rtm.OUTPUT_DIR       = cfg.get("out_dir",  ".")
            rtm.COLD_FILES       = cfg.get("cold_files", None)  
            rtm.HOT_FILES        = cfg.get("hot_files",  None)  
            rtm.SHOW_PLOT        = False
            rtm.CAVITY_LEN       = cfg.get("cavity_len", rtm.CAVITY_LEN)
            rtm.RL_FACTOR        = cfg.get("rl_factor",  rtm.RL_FACTOR)

            _tz_map = {"UTC": rtm._UTC, "KST": rtm._KST_TZ}
            rtm.COLD_TS_TZ    = _tz_map.get(cfg.get("cold_tz", "UTC"), rtm._UTC)
            rtm.HOT_TS_TZ     = _tz_map.get(cfg.get("hot_tz",  "KST"), rtm._KST_TZ)
            rtm.HOT_ANS_TS_TZ = rtm.HOT_TS_TZ   

            # stdout 리다이렉트
            _live = _LiveStream(self.log.emit)
            old_stdout = _sys.stdout
            _sys.stdout = _live
            _rtm_result = None
            try:
                _rtm_result = rtm.main()
            finally:
                _sys.stdout = old_stdout
                _live.flush()

            _out_dir = rtm.OUTPUT_DIR
            if _rtm_result and len(_rtm_result) >= 4:
                self.data_ready.emit(_rtm_result[0], _rtm_result[1], _rtm_result[2], _rtm_result[3])
                _out_dir = _rtm_result[3] or _out_dir

            self.finished.emit(_out_dir)

        except Exception as e:
            import traceback
            self.log.emit(f"[error] {e}\n{traceback.format_exc()}")
            self.finished.emit("")


class _RTExportWorker(QThread):
    """α용 R(t) npz 저장 워커 — 채널별 compute_rt_knots(병렬) → save_rt.
    tasks: list of (label, raw_dir, wave_nm, RTConfig, file_list, out_path)."""
    log      = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)   # (done, total, channel label)
    finished = pyqtSignal(str)   # 요약 문자열

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks

    def run(self):
        import sys as _sys, os as _os, traceback
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import rt_precompute as RTP
        except Exception as e:
            self.finished.emit(f"ERROR: rt_precompute import failed: {e}")
            return
        done = []
        for label, rdir, wave, cfg, flist, outp in self.tasks:
            try:
                self.log.emit(f"[{label}] computing R(t) in parallel…")
                all_files = RTP._RT._resolve_files(rdir, flist)
                ks, od, wv = RTP.compute_rt_knots(
                    rdir, wave, cfg, file_list=flist, parallel=True,
                    progress_cb=lambda d, t, _l=label: self.progress.emit(d, t, _l))
                if len(ks) == 0:
                    self.log.emit(f"[{label}]  0 knots — not saved")
                    continue
                processed = [_os.path.basename(f) for f in all_files]
                RTP.save_rt(outp, ks, od, wv, label=label, config=cfg,
                            processed_files=processed)
                self.log.emit(f"[{label}]  {len(ks)} knots ({len(processed)} files) → {_os.path.basename(outp)}")
                done.append(f"{label}({len(ks)})")
            except Exception as e:
                self.log.emit(f"[{label}]  failed: {e}\n{traceback.format_exc()}")
        self.finished.emit("  |  ".join(done) if done else "no R(t) saved")


class _RTAppendWorker(QThread):
    """α용 R(t) 증분 추가 워커 — 채널별 append_rt(병렬) → 기존 npz에 머지.
    tasks: list of (label, raw_dir, wave_nm, RTConfig, file_list, out_path)"""
    log      = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str)

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks

    def run(self):
        import sys as _sys, os as _os, traceback
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import rt_precompute as RTP
        except Exception as e:
            self.finished.emit(f"ERROR: rt_precompute import failed: {e}")
            return
        done = []
        for label, rdir, wave, cfg, flist, outp in self.tasks:
            try:
                self.log.emit(f"[{label}] appending incrementally…")
                n_new, added = RTP.append_rt(
                    outp, rdir, wave, cfg, file_list=flist, parallel=True,
                    progress_cb=lambda d, t, _l=label: self.progress.emit(d, t, _l))
                if n_new == 0 and added:
                    self.log.emit(f"[{label}]  {len(added)} files processed but 0 valid knots (no He/ZA?)")
                elif n_new == 0:
                    self.log.emit(f"[{label}] no new files — skipped")
                else:
                    self.log.emit(f"[{label}]  +{n_new} knots ({len(added)} files) → {_os.path.basename(outp)}")
                    done.append(f"{label}(+{n_new})")
            except Exception as e:
                self.log.emit(f"[{label}]  failed: {e}\n{traceback.format_exc()}")
        self.finished.emit("  |  ".join(done) if done else "no knots added")




class _ChannelRWorker(QThread):
    """채널별 scan_directory() 호출 — 계산 시작 버튼용.
    channel_cfgs: list of {label, raw_dir, wave_nm, rtcfg, file_list, color, npz_path}
    auto_npz=True면 scan한 results를 그대로 α R(t) npz에 증분 머지한다(재스캔 0)."""
    log        = pyqtSignal(str)
    finished   = pyqtSignal(str)
    data_ready = pyqtSignal(object, object, object, object)

    def __init__(self, channel_cfgs, out_dir, cavity_len, rl_factor,
                 auto_npz=False, skip_done=False):
        super().__init__()
        self.channel_cfgs = channel_cfgs
        self.out_dir      = out_dir
        self.cavity_len   = cavity_len
        self.rl_factor    = rl_factor
        self.auto_npz     = auto_npz
        self.skip_done    = skip_done   # True면 npz processed_files에 있는 파일은 재계산 안 함

    def run(self):
        import sys as _sys, os as _os, traceback, io, contextlib
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import r_trend_monitor as rtm
        except Exception as e:
            self.finished.emit(f"ERROR: {e}")
            return

        rtm.CAVITY_LEN = self.cavity_len
        rtm.RL_FACTOR  = self.rl_factor
        _os.makedirs(self.out_dir, exist_ok=True)
        all_results = []

        for ch_cfg in self.channel_cfgs:
            label   = ch_cfg["label"]
            raw_dir = ch_cfg["raw_dir"]
            wave_nm = ch_cfg["wave_nm"]
            rtcfg   = ch_cfg["rtcfg"]
            flist   = ch_cfg.get("file_list")
            color   = ch_cfg["color"]
            npz_gaps = None   # 머지 후 채워짐 — 중간 빈 날 목록(있으면 GUI가 팝업)
            npz_path = ch_cfg.get("npz_path") or \
                _os.path.join(self.out_dir, f"R_{label}.npz")
            trend_path = _os.path.join(self.out_dir, f"{label}_R_trend.dat")

            self.log.emit(f"[{label}] scan_directory start…")
            try:
                from datetime import timezone, timedelta
                ts_tz  = timezone(timedelta(hours=rtcfg.ts_tz_hours))

                # ── 이미 npz에 있는 파일은 다시 계산하지 않는다(속도) ──
                # npz의 processed_files를 'done 장부'로 보고 그 파일은 스캔에서 제외.
                scan_list = flist
                if self.skip_done:
                    candidates = rtm._resolve_files(raw_dir, flist)
                    done_set = set()
                    if _os.path.exists(npz_path):
                        try:
                            import rt_precompute as RTP
                            done_set = set(RTP.load_rt(npz_path).get("processed_files", []))
                        except Exception:
                            pass
                    scan_list = [f for f in candidates
                                 if _os.path.basename(f) not in done_set]
                    n_skip = len(candidates) - len(scan_list)
                    if n_skip:
                        self.log.emit(
                            f"[{label}] ⏭ skip {n_skip} already-computed file(s); "
                            f"scanning {len(scan_list)} new")

                _buf   = io.StringIO()
                with contextlib.redirect_stdout(_buf):
                    results = rtm.scan_directory(
                        raw_dir, wave_nm, file_list=scan_list,
                        col_press=rtcfg.col_press, col_temp=rtcfg.col_temp,
                        ts_tz=ts_tz,
                        spec_start=rtcfg.spec_start, spec_end=rtcfg.spec_end,
                        fit_window_nm=rtcfg.fit_window_nm,
                        parallel=True)
                for line in _buf.getvalue().splitlines():
                    if line.strip():
                        self.log.emit(line)

                # 새로 계산된 파일: 곡선 저장 + npz 증분 머지 (재스캔 없이 results 재사용)
                if results:
                    rtm.save_r_curves_per_file(results, f"R_{label}", self.out_dir)
                    self.log.emit(f"[{label}]  {len(results)} new cycles")
                    if self.auto_npz:
                        try:
                            import rt_precompute as RTP
                            n_new, n_tot = RTP.merge_results_into_npz(
                                npz_path, results, raw_dir, wave_nm, rtcfg,
                                file_list=flist)
                            self.log.emit(
                                f"[{label}]  α npz +{n_new} new knots "
                                f"(total {n_tot}) → {_os.path.basename(npz_path)}")
                            # 계단 가드: 머지된 npz에서 계단 후보 감지 → 경고 로그
                            # (보고만 — knot은 건드리지 않음. 분절은 α 생성 시 적용)
                            try:
                                for _ln in RTP.step_report(npz_path)["lines"]:
                                    self.log.emit(f"[{label}] {_ln}")
                            except Exception as _se:
                                self.log.emit(f"[{label}] step-guard report failed: {_se}")
                            # 중간 빈 날(달력상 knot 0개) 탐지 → 로그 + GUI 팝업용 첨부
                            npz_gaps = RTP.find_date_gaps(npz_path)
                            if npz_gaps:
                                self.log.emit(
                                    f"[{label}]  {npz_gaps['n_days']} day(s) with no data "
                                    f"between {npz_gaps['first']}~{npz_gaps['last']}: "
                                    + ", ".join(npz_gaps["missing"]))
                        except Exception as _e:
                            self.log.emit(f"[{label}]  α npz update failed: {_e}")
                elif not self.skip_done:
                    self.log.emit(f"[{label}]  no results")

                # ── 플롯/트렌드: 스킵 시 기존 트렌드 dat과 합쳐 전체를 보존 ──
                # 스킵된 파일은 이번 results에 없으므로, 기존 트렌드 dat을 불러와
                # 새 결과와 파일명 기준 병합(새 결과 우선)→시간순 정렬. 트렌드 dat도
                # 누적본으로 갱신. (스킵 OFF면 기존 동작과 동일)
                plot_results = results
                if self.skip_done:
                    prior = []
                    if _os.path.exists(trend_path):
                        try:
                            prior = rtm.load_dat(trend_path)
                        except Exception:
                            pass
                    fresh = {r["filename"] for r in results}
                    plot_results = [r for r in prior if r["filename"] not in fresh] + results
                    plot_results.sort(key=lambda r: r["timestamp"].replace(tzinfo=None))
                    if not results:
                        self.log.emit(
                            f"[{label}] no new files; showing {len(plot_results)} existing")

                if plot_results:
                    rtm.save_dat(plot_results, trend_path)

                all_results.append({"label": label, "results": plot_results or [],
                                    "color": color, "npz_gaps": npz_gaps})

            except Exception as e:
                self.log.emit(f"[{label}]  {e}\n{traceback.format_exc()}")
                all_results.append({"label": label, "results": [], "color": color,
                                    "npz_gaps": None})

        # arg0 = new-format [{label, results, color}]; arg1/arg2 = [] (unused)
        self.data_ready.emit(all_results, [], [], self.out_dir)
        self.finished.emit(self.out_dir)


class _HeCheckWorker(QThread):
    """증분 추가 전 He 플래그 사전 스캔 — 메인 스레드 얼음 방지.
    tasks: list of (label, raw_dir, wave_nm, RTConfig, file_list, out_path)"""
    finished = pyqtSignal(object)   # list of (label, raw_dir, wave, rtcfg, flist, out_path, new_files, he_map)
    progress = pyqtSignal(str)      # 채널 이름

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks

    def run(self):
        import sys as _sys, os as _os
        _td = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools")
        if _td not in _sys.path:
            _sys.path.insert(0, _td)
        try:
            import rt_precompute as RTP
        except Exception as e:
            self.finished.emit([])
            return

        results = []
        for label, raw_dir, wave, rtcfg, flist, out_path in self.tasks:
            self.progress.emit(label)
            try:
                new_files, he_map = RTP.check_new_files(out_path, raw_dir, flist)
            except Exception:
                new_files, he_map = [], {}
            results.append((label, raw_dir, wave, rtcfg, flist, out_path, new_files, he_map))
        self.finished.emit(results)


class DayAuditWorker(QThread):
    """백그라운드 측정일 감사 (core.day_audit).

    하루치 raw는 ~2 GB라 메인 스레드에서 돌리면 GUI가 수십 초 멈춘다. flag 열만
    스트리밍하지만 파일 자체는 다 읽어야 하므로(한 줄 25 KB) I/O가 지배한다.
    """
    progress = pyqtSignal(str)          # 진행 중인 날짜
    done = pyqtSignal(object)           # {date: AuditReport}
    failed = pyqtSignal(str)

    def __init__(self, jobs, expected_period_sec=None):
        """jobs = [(date, [raw 파일경로, …]), …]"""
        super().__init__()
        self.jobs = list(jobs)
        self.expected_period_sec = expected_period_sec
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            from core.day_audit import audit_day
            out = {}
            for date, files in self.jobs:
                if self._stop:
                    break
                self.progress.emit(date)
                out[date] = audit_day("", date, files=files,
                                      expected_period_sec=self.expected_period_sec)
            self.done.emit(out)
        except Exception as e:                       # noqa: BLE001 — 진단이 앱을 죽이면 안 된다
            self.failed.emit(str(e))
