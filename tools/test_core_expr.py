# -*- coding: utf-8 -*-
"""tools/test_core_expr.py — core/expr.py(열 수식 안전 평가기) 자체검증. Qt·데이터 불필요.

Result Lab 계산기와 Plot Maker 파생 열이 같은 엔진을 쓴다. 여기서 지키는 것:
  1. 산술·비교·원소별 논리·범주형 비교가 numpy와 같은 값을 낸다
  2. 위험한 문법(속성·첨자·람다·임의 함수·import)은 **실행 전에** 거부된다
  3. and/or/not 은 & | ~ 로 안내한다(배열에서 모호)
  4. 결과 정규화: 스칼라 브로드캐스트, bool→1/0, 문자열 결과·길이 불일치 거부

    python tools/test_core_expr.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np

from core.expr import ExprError, eval_column, eval_mask, names_in, safe_eval


def main():
    A = np.array([1.0, 4.0, np.nan, -2.0])
    B = np.array([2.0, 0.0, 1.0, 1.0])
    F = np.array(["ok", "qc", "ok", "unstable"], dtype=object)
    v = {"A": A, "B": B, "Flag": F, "odd name": A * 10}

    # 1. 값
    r = safe_eval("(A - B) / B", v)
    assert r[0] == -0.5 and np.isinf(r[1]), r
    assert np.allclose(eval_column("A ** 2 + 1", v, 4), A ** 2 + 1, equal_nan=True)
    assert np.array_equal(eval_mask("(A > 0) & (B < 2)", v, 4), [False, True, False, False])
    assert np.array_equal(eval_mask("0 < A < 2", v, 4), [True, False, False, False])
    assert np.array_equal(eval_mask('Flag == "ok"', v, 4), [True, False, True, False])
    assert np.array_equal(eval_mask('~(Flag == "ok") | (A < 0)', v, 4), [False, True, False, True])
    ok_only = eval_column('where(Flag == "ok", A, nan)', v, 4)
    assert ok_only[0] == 1.0 and np.isnan(ok_only[1]) and np.isnan(ok_only[3])
    assert np.allclose(eval_column("A - mean(A)", v, 4), A - np.nanmean(A), equal_nan=True)
    assert np.allclose(eval_column('col("odd name") / 10', v, 4), A, equal_nan=True)
    assert eval_mask("A > 0", v, 4)[2] == False   # NaN 비교는 False  # noqa: E712

    # 2. 안전 — 실행 전에 거부
    for bad in ("A.__class__", "A[0]", "lambda: 1", '__import__("os")', "open('x')",
                "[a for a in A]", "A if B else A", "eval('1')", "getattr(A, 'x')"):
        try:
            safe_eval(bad, v)
        except ExprError:
            pass
        else:
            raise AssertionError(f"rejected expected: {bad}")

    # 3. 안내
    try:
        safe_eval("A > 1 and B < 2", v)
    except ExprError as e:
        assert "&" in str(e), e
    else:
        raise AssertionError("'and' should be rejected")

    # 4. 정규화
    assert np.array_equal(eval_column("3", v, 4), [3, 3, 3, 3])
    assert np.array_equal(eval_column("B > 0.5", v, 4), [1.0, 0.0, 1.0, 1.0])
    for bad in ("Flag", "nosuch + 1", "", "A +"):
        try:
            eval_column(bad, v, 4)
        except ExprError:
            pass
        else:
            raise AssertionError(f"rejected expected: {bad!r}")
    try:
        eval_column("A", {"A": np.zeros(3)}, 4)
    except ExprError:
        pass
    else:
        raise AssertionError("length mismatch should be rejected")

    assert names_in('col("odd name") + B * 2 + nan + mean(A)') == {"odd name", "B", "A"}

    # 5. (2026-10-02 리뷰) 거듭제곱은 실수로 — int64 넘침이 조용히 틀린 값을 내던 것
    one = {"X": np.ones(2)}
    assert np.allclose(eval_column("X * 10**20", one, 2), 1e20), eval_column("X * 10**20", one, 2)
    assert np.allclose(eval_column("X * 2.46 * 10**19", one, 2), 2.46e19)
    assert eval_column("2**63", one, 2)[0] == 2.0 ** 63
    assert np.isinf(eval_column("10**400", one, 2)).all()
    assert eval_column("2 ** -1", one, 2)[0] == 0.5

    # 6. & | ~ 에서 NaN 은 거짓(eval_mask 규약과 같게)
    w = {"R": np.array([np.nan, 1.0, 0.0]), "F": np.array(["ok", "ok", "ok"])}
    assert eval_mask('(F == "ok") & R', w, 3).tolist() == [False, True, False]
    assert eval_mask("R | (R > 5)", w, 3).tolist() == [False, True, False]
    assert eval_mask("~R", w, 3).tolist() == [True, False, True]

    # 7. 데이터 의존 오류도 ExprError — 호출측은 ExprError 만 잡는다(필터 규칙 하나만 ✗)
    for bad in ('A == "a"', "mean(Flag)", 'Flag + 1', "Flag & 1"):
        try:
            eval_mask(bad, v, 4)
        except ExprError:
            pass
        except Exception as e:      # noqa: BLE001
            raise AssertionError(f"{bad!r} raised {type(e).__name__}, not ExprError: {e}")
    print("test_core_expr: all OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
