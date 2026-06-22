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
                    self.log.emit(f"[{label}] ⚠️ 0 knots — not saved")
                    continue
                processed = [_os.path.basename(f) for f in all_files]
                RTP.save_rt(outp, ks, od, wv, label=label, config=cfg,
                            processed_files=processed)
                self.log.emit(f"[{label}] ✅ {len(ks)} knots ({len(processed)} files) → {_os.path.basename(outp)}")
                done.append(f"{label}({len(ks)})")
            except Exception as e:
                self.log.emit(f"[{label}] ❌ failed: {e}\n{traceback.format_exc()}")
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
                    self.log.emit(f"[{label}] ⚠️ {len(added)} files processed but 0 valid knots (no He/ZA?)")
                elif n_new == 0:
                    self.log.emit(f"[{label}] no new files — skipped")
                else:
                    self.log.emit(f"[{label}] ✅ +{n_new} knots ({len(added)} files) → {_os.path.basename(outp)}")
                    done.append(f"{label}(+{n_new})")
            except Exception as e:
                self.log.emit(f"[{label}] ❌ failed: {e}\n{traceback.format_exc()}")
        self.finished.emit("  |  ".join(done) if done else "no knots added")




class _ChannelRWorker(QThread):
    """채널별 scan_directory() 호출 — 계산 시작 버튼용.
    channel_cfgs: list of {label, raw_dir, wave_nm, rtcfg, file_list, color}"""
    log        = pyqtSignal(str)
    finished   = pyqtSignal(str)
    data_ready = pyqtSignal(object, object, object, object)

    def __init__(self, channel_cfgs, out_dir, cavity_len, rl_factor):
        super().__init__()
        self.channel_cfgs = channel_cfgs
        self.out_dir      = out_dir
        self.cavity_len   = cavity_len
        self.rl_factor    = rl_factor

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

            self.log.emit(f"[{label}] scan_directory start…")
            try:
                from datetime import timezone, timedelta
                ts_tz  = timezone(timedelta(hours=rtcfg.ts_tz_hours))
                _buf   = io.StringIO()
                with contextlib.redirect_stdout(_buf):
                    results = rtm.scan_directory(
                        raw_dir, wave_nm, file_list=flist,
                        col_press=rtcfg.col_press, col_temp=rtcfg.col_temp,
                        ts_tz=ts_tz,
                        spec_start=rtcfg.spec_start, spec_end=rtcfg.spec_end,
                        fit_window_nm=rtcfg.fit_window_nm,
                        parallel=True)
                for line in _buf.getvalue().splitlines():
                    if line.strip():
                        self.log.emit(line)

                if results:
                    rtm.save_dat(results,
                                 _os.path.join(self.out_dir, f"{label}_R_trend.dat"))
                    rtm.save_r_curves_per_file(results, f"R_{label}", self.out_dir)
                    self.log.emit(f"[{label}] ✅ {len(results)} cycles")
                else:
                    self.log.emit(f"[{label}] ⚠️ no results")

                all_results.append({"label": label, "results": results or [], "color": color})

            except Exception as e:
                self.log.emit(f"[{label}] ❌ {e}\n{traceback.format_exc()}")
                all_results.append({"label": label, "results": [], "color": color})

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
