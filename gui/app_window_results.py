"""gui/app_window_results.py
CAESARAnalyzer §12 — 결과 테이블 / QC 재적용 / fast 렌더 (gui/app_window.py에서 분리).

**순수 이동이다.** 메서드 본문은 한 글자도 안 고쳤다 — 호출부가 전부 self.xxx()라
믹스인으로 옮기는 것만으로 동작이 같다. 로직 개선은 다음 PR로.
가드는 tools/test_app_window_smoke.py (표면 골든 + 믹스인 이름 충돌 검사).
"""
import pyqtgraph as pg

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QMessageBox, QTableWidgetItem


class ResultsQCMixin:
    """§12 — 결과 테이블 / QC 재적용 / fast 렌더. CAESARAnalyzer에 믹스인된다."""

    # ══════════════════════════════════════════════════════════════════════
    # §12 결과 테이블 / QC / fast 렌더
    # ══════════════════════════════════════════════════════════════════════
    @staticmethod
    def _shsq_text(gases, props):
        """가스별 Shift/Squeeze 모드 한 줄 요약 (Link 관계 포함).

        ⚠ Center를 빠뜨리면 안 된다. 예전엔 모드 사다리가 Link/Limit/Fix 아니면
        전부 'Free'로 떨어져서 `Center -5.25, 1.9`가 **'Free'로 표시**됐다 —
        의미가 정확히 반대다(Free=제약 없음, Center=선언된 중심에 앵커).
        이 함수는 RUN 직전 확인 다이얼로그도 쓰므로 밤샘 런의 마지막 검문이 거짓이 된다.
        모르는 모드는 'Free'로 뭉개지 말고 이름 그대로 드러낸다."""
        props = props or {}

        def fmt(mode, val, default_mode, default_val):
            mode = mode or default_mode
            raw = str(val if val not in (None, '') else default_val).strip()
            compact = raw.replace(' ', '')
            if mode == 'Link':
                return f"→{raw}"
            if mode == 'Limit':
                return f"[{compact}]"
            if mode == 'Fix':
                return f"={compact}"
            if mode == 'Center':
                return f"@{compact}"      # 중심,반폭 — 0이 아니라 여기에 앵커된다
            if mode == 'Free':
                return 'Free'
            return f"?{mode}"             # 모르는 모드를 Free로 속이지 않는다

        def one(g):
            p = props.get(g, {})
            sh = fmt(p.get('sh_mode'), p.get('sh_val'), 'Limit', '-0.5, 0.5')
            sq = fmt(p.get('sq_mode'), p.get('sq_val'), 'Fix', '1.0')
            return f"{g} Sh{sh}·Sq{sq}"
        return "Sh/Sq:  " + "  │  ".join(one(g) for g in gases)

    def _toggle_shsq_table(self):
        show = not getattr(self, '_shsq_table_visible', True)
        self._shsq_table_visible = show
        self.tbl_shsq.setVisible(show)
        self._btn_shsq_tbl.setText(
            ("▼ " if show else "▶ ") + "Reference policy (Shift / Squeeze / T / bands)")

    def _on_shsq_table_changed(self):
        """상시 노출 테이블은 OK 버튼이 없다 — 편집 즉시 ref_props에 반영.

        ⚙️ Properties 팝업과 달리 되돌리기가 없으므로, 값을 **읽어 담기만** 하고
        엔진이나 결과는 건드리지 않는다(다음 RUN/Test Fit부터 적용)."""
        try:
            self.ref_props = self.tbl_shsq.get_properties()
        except Exception as e:                  # noqa: BLE001 — 편집 중 반쪽 상태 방어
            print(f"[ref policy] not applied: {e}")
            return
        if hasattr(self, 'lbl_shsq'):
            gases = list(getattr(self.engine, 'gas_list', []) or [])
            if gases:
                self.lbl_shsq.setText(self._shsq_text(gases, self.ref_props))

    def _refresh_shsq_summary(self):
        """Parameters 그리드의 Sh/Sq 요약 라벨 + 상시 노출 테이블 갱신.

        가스 목록이 바뀌는 지점(레퍼런스 락·채널 전환·시나리오 적용)에서 이미
        전부 호출되고 있어서, 테이블 재구성도 여기에 붙인다(새 훅을 만들지 않는다)."""
        gases = list(getattr(self.engine, 'gas_list', []) or [])
        if hasattr(self, 'tbl_shsq'):
            # 재구성 중의 changed 시그널이 ref_props를 덮어쓰지 않게 막는다
            self.tbl_shsq.blockSignals(True)
            try:
                self.tbl_shsq.set_gases(gases, getattr(self, 'ref_props', {}))
            except Exception as e:              # noqa: BLE001 — 표시가 핏을 막지 않는다
                print(f"[ref policy] table rebuild failed: {e}")
            finally:
                self.tbl_shsq.blockSignals(False)
        if not hasattr(self, 'lbl_shsq'):
            return
        if not gases:
            self.lbl_shsq.setText("Sh/Sq: (lock refs to show)")
            return
        self.lbl_shsq.setText(self._shsq_text(gases, getattr(self, 'ref_props', {})))

    def _compact_table_columns(self, cols):
        """결과 테이블을 좁은 패널에서 한눈에 들어오게 압축.
        기본 컬럼폭(~100px)×13컬럼 = 1300px가 가로 스크롤 뒤로 숨던 것을,
        내용에 맞는 고정폭 + 작은 폰트로 줄인다(정보 제거 없음, 필요시 드래그로 확장)."""
        try:
            from PyQt6.QtGui import QFont
            f = self.table.font()
            f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
            self.table.setFont(f)
            widths = {"Ch": 34, "File": 88, "Time": 118, "RMS": 58, "Chi2": 44,
                      "SNR": 52, "Status": 72, "Shift": 44, "Squeeze": 52}
            s = getattr(self, '_s', 1.0)
            for i, c in enumerate(cols):
                self.table.setColumnWidth(i, int(widths.get(c, 56) * s))   # 가스 컬럼 기본 56
            self.table.horizontalHeader().setStretchLastSection(False)
        except Exception:
            pass

    def update_table(self, result_dict, row_index):
        """Triggered by the worker thread per result."""
        self.results.append(result_dict)
        self._autosave_row(result_dict)   # 크래시 나도 여기까지는 디스크에 남음
        # Fast (batch) mode: do NOT touch the table/plots per result — that can't keep
        # up with parallel bursts (tens of thousands of rows → GUI freeze). Just collect
        # + autosave; a light timer (_flush_fast) updates the progress bar, and the
        # whole table+plots are rendered ONCE at the end (_render_fast_results).
        # Step mode renders live, one slow scan at a time.
        if getattr(self, '_fast_mode_active', False):
            return
        self._apply_row_to_table(result_dict, row_index)

    def _write_row_cells(self, result_dict, row, multi):
        """Write the cells of one table row (no plots / scroll / progress bar)."""
        if row >= self.table.rowCount():
            self.table.setRowCount(row + 1)
        c = 0
        if multi:
            self.table.setItem(row, 0, QTableWidgetItem(f"CH{result_dict.get('Channel', 1)}"))
            c = 1
        self.table.setItem(row, c + 0, QTableWidgetItem(str(result_dict.get('File', ''))))
        self.table.setItem(row, c + 1, QTableWidgetItem(str(result_dict.get('Time', ''))))
        self.table.setItem(row, c + 2, QTableWidgetItem(f"{result_dict.get('RMS', 0):.2e}"))
        self.table.setItem(row, c + 3, QTableWidgetItem(f"{result_dict.get('Chi2', 0):.2f}"))
        self.table.setItem(row, c + 4, QTableWidgetItem(f"{result_dict.get('SNR', 0):.1f}"))
        item_status = QTableWidgetItem(str(result_dict.get('Status', '')))
        try:
            status = result_dict.get('Status', '')
            if status not in ("OK", "Recovered"):
                item_status.setBackground(QColor(255, 100, 100))
            elif status == "Recovered":
                item_status.setBackground(QColor(255, 220, 100))
        except Exception:
            pass
        self.table.setItem(row, c + 5, item_status)
        for i, gas_name in enumerate(self.engine.gas_list):
            self.table.setItem(row, c + 6 + i, QTableWidgetItem(f"{result_dict.get(gas_name, 0):.2e}"))
        go = len(self.engine.gas_list)
        self.table.setItem(row, c + 6 + go,     QTableWidgetItem(f"{result_dict.get('Shift', 0):.2f}"))
        self.table.setItem(row, c + 6 + go + 1, QTableWidgetItem(f"{result_dict.get('Squeeze', 1):.4f}"))

    def _apply_row_to_table(self, result_dict, row_index):
        """Live per-row update (Step mode): cells + conc plot + scroll + progress bar."""
        multi = getattr(self, '_multi_channel_mode', False)
        if multi:
            row = self._next_table_row
            self._next_table_row += 1
        else:
            row = row_index
        self._write_row_cells(result_dict, row, multi)
        if hasattr(self.monitor, 'update_conc'):
            self.monitor.update_conc(result_dict, row_index)
        import time as _t
        if (_t.monotonic() - getattr(self, '_last_scroll_t', 0.0)) >= 0.15:
            self._last_scroll_t = _t.monotonic()
            item = self.table.item(row, 0)
            if item:
                self.table.scrollToItem(item)
        n = len(self.results)
        self.pbar.setValue(n)
        # E2: Step 모드도 진행 숫자를 한 줄로 보여준다(예전엔 막대만 움직였다).
        # 처리율·ETA는 넣지 않는다 — 워커가 emit하는 건 progress/total_ready 둘뿐이라
        # 어떤 속도 예측도 근거가 없다(있는 척하면 밤샘 런의 판단을 흐린다).
        if not getattr(self, '_fast_mode_active', False) and n % 10 == 0:
            self.status.setText(self._progress_text(n))

    def _progress_text(self, n):
        """RUN 진행 한 줄. 숫자는 실제로 아는 것만 — 완료/전체 스캔."""
        total = self.pbar.maximum() or n
        tag = f"{self._workers_total} CH · " if getattr(self, '_multi_channel_mode', False) else ""
        return (f"Fitting… {tag}{n:,} / {total:,} scans"
                "   (settings frozen for this run — edits apply to the next RUN)")

    def _flush_fast(self):
        """Fast mode: light periodic feedback while fitting (progress bar + status).
        The heavy table/plot render is done once at the end in _render_fast_results."""
        n = len(self.results)
        self.pbar.setValue(n)
        self.status.setText(self._progress_text(n))

    def _render_fast_results(self):
        """Render everything ONCE after a Fast run: table (capped preview) + plots.
        Full results live in self.results + the autosave file (open in result viewer)."""
        res = self.results
        if not res:
            return
        cap = getattr(self, '_fast_table_cap', 5000)
        n_show = min(len(res), cap)
        multi = getattr(self, '_multi_channel_mode', False)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(n_show)
            for row in range(n_show):
                self._write_row_cells(res[row], row, multi)
        finally:
            self.table.setUpdatesEnabled(True)
        if hasattr(self.monitor, 'rebuild_conc'):
            self.monitor.rebuild_conc(res)
        if hasattr(self.monitor, 'rebuild_trend'):
            self.monitor.rebuild_trend(res)
        self.pbar.setValue(len(res))
        if len(res) > n_show:
            self.status.setText(
                f"Fast complete: {len(res):,} scans fitted — table previews only {n_show:,} rows, "
                f"see full results in the graph + autosave file (Result Viewer).")

    def _fast_finalize(self):
        """End of a Fast run: stop the feedback timer and render results once."""
        t = getattr(self, '_fast_timer', None)
        if t is not None:
            t.stop()
        if getattr(self, '_fast_mode_active', False):
            self._render_fast_results()
        self._fast_mode_active = False
        if hasattr(self.monitor, 'flush_plots'):
            self.monitor.flush_plots()

    def analysis_finished(self, stopped=False):
        """Re-enables UI once ALL channel workers have finished."""
        self._analysis_running = False
        if stopped:
            # Stop requested — re-enable immediately regardless of pending workers
            self._fast_finalize()
            self._autosave_close()
            self.b_run.setEnabled(True)
            self.b_stop.setEnabled(False)
            self.status.setText("Analysis stopped by user.")
            self.status.setStyleSheet("color: red; font-weight: bold;")
            return

        # Count completed workers; wait until the last one finishes
        self._workers_done = getattr(self, '_workers_done', 0) + 1
        total = getattr(self, '_workers_total', 1)

        if self._workers_done < total:
            # Still waiting for other channels
            remaining = total - self._workers_done
            self.status.setText(
                f"CH{self._workers_done} done — waiting for {remaining} more channel(s)..."
            )
            return

        # All workers finished
        self.b_run.setEnabled(True)
        self.b_stop.setEnabled(False)
        # Stop the Fast flush timer, drain remaining buffered rows, redraw plots.
        self._fast_finalize()
        n_ch = total
        ch_label = f"{n_ch}-channel " if n_ch > 1 else ""
        # ── 자동 품질필터(QC): 핏 종료 후 채널별 RMS 분포에서 robust 이상치 제외 ──
        qc_changed = self._apply_auto_qc()
        if qc_changed:
            self._refresh_after_qc(qc_changed)

        self._autosave_close()
        was_stopped = getattr(self, '_stop_requested', False)
        self._stop_requested = False
        if was_stopped:
            self.status.setText(f"Stopped — partial results ({len(self.results):,} rows)")
            self.status.setStyleSheet("color: orange; font-weight: bold;")
        else:
            self.status.setText(f"{ch_label}Analysis Completed!")
            self.status.setStyleSheet("color: green; font-weight: bold;")
        # L3: 완료 시 자동 저장 (QC 적용 후, 정식 파일명 규칙)
        saved_msg = ""
        if (not was_stopped and hasattr(self, 'chk_auto_save')
                and self.chk_auto_save.isChecked() and self.results):
            try:
                self.save(auto=True)
                saved_msg = "\n Auto-saved (see status bar)"
            except Exception as _e:
                saved_msg = f"\n Auto-save failed: {_e}"

        qc_msg = f"\nAuto QC excluded: {len(qc_changed)} rows (gas → NaN)" if qc_changed else ""
        head = "Analyzed up to the stop point." if was_stopped else f"All files analyzed successfully ({n_ch} channel(s))."
        QMessageBox.information(self, "Done", f"{head}{qc_msg}{saved_msg}")

    def reapply_qc(self):
        """재핏 없이 라벨(Chi2) → Kalman Q/R → 자동 QC 순서로 후처리 재적용."""
        if not getattr(self, 'results', None):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Reapply", "No analysis results. Run a fit first.")
            return
        self._reapply_quality_label()
        self._reapply_kalman()
        changed = self._apply_auto_qc()
        self._refresh_after_qc(changed)
        from PyQt6.QtWidgets import QMessageBox
        K = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 8.0
        kq = self.spin_kalman_q.value() if hasattr(self, 'spin_kalman_q') else 0.0005
        kr = self.spin_kalman_r.value() if hasattr(self, 'spin_kalman_r') else 0.050
        rms_pct = self.spin_rms_thresh.value() if hasattr(self, 'spin_rms_thresh') else 10.0
        _settle_on = hasattr(self, 'chk_settle') and self.chk_settle.isChecked()
        _settle_str = (f", Settling (first {self.spin_settle_n.value()}/bin)"
                       if _settle_on else "")
        _n_settle = sum(1 for r in self.results if str(r.get('Status', '')) == 'Settling')
        QMessageBox.information(self, "Reapply",
                                f"Re-judged OK/Unstable (Chi2), Kalman (Q={kq}, R={kr}), "
                                f"QC (K={K:g}){_settle_str}.\n"
                                f"Excluded: {len(changed)} / {len(self.results):,} rows"
                                + (f"  (settling {_n_settle})" if _settle_on else ""))

    def _reapply_quality_label(self):
        """각 행의 OK/Unstable 을 Chi2 로 재판정 — 워커와 **같은 함수**를 쓴다
        (`core.result_io.quality_label`). _qc_orig_status를 갱신해두면 이후
        _apply_auto_qc()가 복원 시 새 상태를 쓴다.

        두 가지가 예전과 다르다:
          · 축이 Chi2 다. 옛 축(rms/mean|신호|)은 알파가 작아지면 멀쩡한 핏을
            Unstable 로 찍었다(교차검증 19.2만 행 측정 — quality_label 독스트링).
            그래서 이 재판정은 이제 'OK RMS%' 스핀박스와 무관하다.
          · **노트를 보존한다.** 예전엔 맨몸 'OK'/'Unstable' 로 덮어써서
            SATURATED·header row·AT_BOUND 가 Reapply 한 번에 사라졌다.
        """
        try:
            from core.result_io import quality_label
        except ImportError:
            from CAESAR.core.result_io import quality_label
        for r in self.results:
            orig_st = str(r.get('_qc_orig_status', r.get('Status', '')))
            head, sep, tail = orig_st.partition(' · ')
            if head not in ('OK', 'Recovered', 'Unstable'):
                continue                      # Skip/Error/Zero-Air/Settling/QC-… 은 건드리지 않는다
            try:
                chi2 = float(r.get('Chi2'))
            except (TypeError, ValueError):
                continue                      # Chi2 없는 레거시 행 — 로드된 라벨 유지
            new_st = quality_label(chi2, attempt=1 if head == 'Recovered' else 0)
            r['_qc_orig_status'] = new_st + sep + tail

    def _reapply_kalman(self):
        """현재 Kalman Q/R 값으로 _Smooth 컬럼을 채널별로 재계산.
        _qc_orig_sm을 새 값으로 갱신해두면 _apply_auto_qc()가 복원 후 QC를 재적용한다."""
        import numpy as _np
        try:
            from core.physics import KalmanTracker
        except ImportError:
            from CAESAR.core.physics import KalmanTracker
        kq = self.spin_kalman_q.value() if hasattr(self, 'spin_kalman_q') else 0.0005
        kr = self.spin_kalman_r.value() if hasattr(self, 'spin_kalman_r') else 0.050
        gas_list = self.engine.gas_list

        by_ch: dict = {}
        for i, r in enumerate(self.results):
            by_ch.setdefault(r.get('Channel', 1), []).append(i)

        for indices in by_ch.values():
            kf = KalmanTracker(num_variables=len(gas_list), q_noise=kq, r_noise=kr)
            for i in indices:
                r = self.results[i]
                raw = []
                orig_d = r.get('_qc_orig', {})
                for nm in gas_list:
                    v = orig_d.get(nm) if orig_d else r.get(nm)
                    try:
                        fv = float(v)
                        raw.append(fv if _np.isfinite(fv) else 0.0)
                    except (TypeError, ValueError):
                        raw.append(0.0)
                smooth = kf.process(raw)
                if '_qc_orig_sm' not in r:
                    r['_qc_orig_sm'] = {}
                for gi, nm in enumerate(gas_list):
                    r['_qc_orig_sm'][nm] = float(smooth[gi])

    def _apply_auto_qc(self):
        """핏 종료 후 채널별 RMS 분포에서 robust 임계(log median+K·MAD)로 이상치를 자동
        검출해 그 행의 가스 농도를 NaN으로 제외한다. 매직넘버 입력 불필요.
        원본 농도를 r['_qc_orig']에 백업하고 매 호출마다 복원 후 재필터하므로,
        K를 바꿔 여러 번 재적용해도 비파괴적이다.
        반환: 제외된 행들의 self.results 인덱스 리스트."""
        import numpy as _np
        # 재적용 전 상태 기록(복원·제외 양방향 변경행 추적 → 테이블 부분갱신용)
        prev_status = [str(r.get('Status', '')) for r in self.results]
        # ── (a) 원본 백업 / 복원: 재적용을 비파괴로 ──
        for r in self.results:
            if '_qc_orig' not in r:
                r['_qc_orig'] = {nm: r.get(nm) for nm in self.engine.gas_list}
                r['_qc_orig_sm'] = {nm: r.get(f"{nm}_Smooth")
                                    for nm in self.engine.gas_list if f"{nm}_Smooth" in r}
                r['_qc_orig_status'] = r.get('Status', '')
            else:
                for nm, v in r['_qc_orig'].items():
                    r[nm] = v
                for nm, v in r.get('_qc_orig_sm', {}).items():
                    r[f"{nm}_Smooth"] = v
                if not str(r.get('Status', '')).startswith('QC-Excluded'):
                    r['Status'] = r.get('_qc_orig_status', r.get('Status', ''))
        # ── (b) 정착(settling) 스캔 제외 — QC와 독립(자체 체크박스), 복원 뒤라 비파괴 ──
        # 각 빈 첫 N스캔 = 캘(He/ZA) 복귀 직후 퍼지 과도 → 농도 저편향. File의 '[NNNN]'이
        # 빈 내 스캔#. gas→NaN + Status='Settling'으로 flag(지우지 않음 — 복원/토글 가능).
        if hasattr(self, 'chk_settle') and self.chk_settle.isChecked():
            import re as _re
            n_settle = self.spin_settle_n.value() if hasattr(self, 'spin_settle_n') else 3
            for r in self.results:
                if str(r.get('Status', '')).startswith('QC-Excluded'):
                    continue
                m = _re.search(r'\[(\d+)\]', str(r.get('File', '')))
                si = int(m.group(1)) if m else -1
                if 0 <= si < n_settle:
                    for nm in self.engine.gas_list:
                        r[nm] = float('nan')
                        if f"{nm}_Smooth" in r:
                            r[f"{nm}_Smooth"] = float('nan')
                    r['Status'] = 'Settling'
        def _status_changed():
            return [i for i, r in enumerate(self.results)
                    if str(r.get('Status', '')) != prev_status[i]]
        if not (hasattr(self, 'chk_qc') and self.chk_qc.isChecked()):
            return _status_changed()   # 복원만 (이전 QC 해제) — settling은 위에서 이미 적용
        K = self.spin_qc_k.value() if hasattr(self, 'spin_qc_k') else 8.0
        if K <= 0:
            return _status_changed()   # 자동 끔(수동 RMS상한만 사용) — 복원만
        # 채널별 RMS 수집 → log공간 robust 임계 (단일 진실원: core.result_io)
        # min_n=1: 이 경로는 핏 결과 전체라 채널마다 표본이 충분 — 기존 동작(표본수
        # 무관 계산) 보존. 결과뷰어 QC는 부분 파일도 다루므로 min_n=5를 쓴다.
        from core.result_io import robust_rms_thresholds
        _rms_list, _ch_list = [], []
        for r in self.results:
            try:
                _rms_list.append(float(r.get('RMS', float('nan'))))
            except Exception:
                _rms_list.append(float('nan'))
            _ch_list.append(r.get('Channel', 1))
        thr_by_ch = robust_rms_thresholds(_rms_list, _ch_list, K=K, min_n=1)
        for r in self.results:
            # 워커 수동 QC(QC-Excluded)·정착(Settling) 행은 이미 제외됨 → 유지
            if str(r.get('Status', '')).startswith(('QC-Excluded', 'Settling')):
                continue
            try:
                rms = float(r.get('RMS', float('nan')))
            except Exception:
                rms = float('nan')
            thr = thr_by_ch.get(r.get('Channel', 1), float('inf'))
            if _np.isfinite(rms) and rms > thr:
                for nm in self.engine.gas_list:
                    r[nm] = float('nan')
                    if f"{nm}_Smooth" in r:
                        r[f"{nm}_Smooth"] = float('nan')
                r['Status'] = f"QC-Auto (rms={rms:.1e}>{thr:.1e})"
        return _status_changed()

    def _refresh_after_qc(self, changed_idx):
        """자동 QC 적용/재적용 후 농도 시계열을 벌크 재구성하고, 상태가 바뀐 행만 테이블에
        다시 그린다(2만행 전체 재렌더/행별 setData = O(n²) 멈춤 방지)."""
        # 농도 시계열 벌크 재구성(곡선당 setData 1회 → 빠름)
        try:
            if hasattr(self, 'monitor') and hasattr(self.monitor, 'rebuild_conc'):
                self.monitor.rebuild_conc(self.results)
        except Exception:
            pass
        # 변경된 행만 테이블 Status/가스 셀 갱신(복원·제외 양방향)
        try:
            from PyQt6.QtWidgets import QTableWidgetItem
            from PyQt6.QtGui import QColor
            multi = getattr(self, '_multi_channel_mode', False)
            c = 1 if multi else 0
            self.table.setUpdatesEnabled(False)
            for i in changed_idx:
                if i >= self.table.rowCount():
                    continue
                r = self.results[i]
                st = str(r.get('Status', ''))
                it = QTableWidgetItem(st)
                if st.startswith('QC-') or st not in ("OK", "Recovered"):
                    it.setBackground(QColor(255, 100, 100))
                elif st == "Recovered":
                    it.setBackground(QColor(255, 220, 100))
                self.table.setItem(i, c + 5, it)
                for gi, gas in enumerate(self.engine.gas_list):
                    try:
                        txt = f"{float(r.get(gas, 0)):.2e}"
                    except (TypeError, ValueError):
                        txt = "nan"
                    self.table.setItem(i, c + 6 + gi, QTableWidgetItem(txt))
            self.table.setUpdatesEnabled(True)
        except Exception:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass

    def _results_date_range(self):
        """결과 Time에서 데이터(raw) 날짜범위 'YYMMDD' 또는 'YYMMDD-YYMMDD'. 없으면 ''."""
        import re as _re
        ds = set()
        for r in getattr(self, 'results', []):
            m = _re.search(r'(\d{2})(\d{2})-(\d{2})-(\d{2})', str(r.get('Time', '')))
            if m:
                ds.add(m.group(2) + m.group(3) + m.group(4))   # YYMMDD
        if not ds:
            return ''
        lo, hi = min(ds), max(ds)
        return lo if lo == hi else f"{lo}-{hi}"

    def _channel_settings_tag(self, ch):
        """채널 ch 세팅 → (라벨, 파일명용 짧은 태그). 채널별 윈도우/poly/shift/가스T 인코딩."""
        cfg = self._channel_configs.get(ch) or {}
        lbl = (cfg.get('data_label') or '').strip() or f'CH{ch}'
        if cfg.get('fit_unit') == 'px':
            win = f"px{cfg.get('f_min', '?')}-{cfg.get('f_max', '?')}"
        else:
            try:
                win = f"{float(cfg.get('fit_start_nm', 0)):.0f}-{float(cfg.get('fit_end_nm', 0)):.0f}nm"
            except Exception:
                win = "win?"
        poly = cfg.get('poly_deg', '?')
        rp = cfg.get('ref_props', {}) or {}
        pg = next((r.get('name') for r in cfg.get('refs', []) if r.get('name')), None)
        sh = "Sh?"
        if pg and pg in rp:
            m = rp[pg].get('sh_mode', '')
            v = str(rp[pg].get('sh_val', '')).replace(' ', '')
            sh = f"Sh[{v}]" if m == 'Limit' else f"Sh{m}"
        try:
            gasT = float(cfg.get('gas_temp', 0) or 0)
        except Exception:
            gasT = 0
        gtag = f"_gT{int(gasT)}" if gasT > 0 else ""
        return lbl, f"{win}_Poly{poly}_{sh}{gtag}"

