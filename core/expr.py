# -*- coding: utf-8 -*-
"""core/expr.py — 열 단위(element-wise) 수식의 안전 평가기. Qt 비의존.

Result Lab 데이터 계산기(`gui/dlg_calculator.py`)와 Plot Maker 파생 열·행 필터가
**같은 엔진**을 쓴다(단일 출처). 전엔 계산기 안에만 있어서 Qt를 끌고 다녔다.

안전성: `eval()`을 쓰지 않는다. ast를 직접 걸어 화이트리스트 노드만 평가한다 —
속성 접근(`x.__class__`), 첨자, 람다, 컴프리헨션, 임의 함수 호출은 전부 거부.

문법
----
- 숫자, 문자열(범주형 비교용: ``Flag == "ok"``), ``True``/``False``, ``nan``·``inf``·``pi``
- 사칙·거듭제곱 ``+ - * / **``, 단항 ``± ~``, 괄호
- 비교 ``< <= > >= == !=`` (연쇄 ``0 < x < 5`` 가능)
- 논리는 **원소별** ``&  |  ~`` — 파이썬 ``and/or/not``은 배열에서 모호해 거부하고
  대신 쓸 연산자를 알려준다. ``&``가 비교보다 우선순위가 높으므로 ``(A > 1) & (B < 2)``처럼 괄호.
- 함수: `FUNCS` 참고. ``col("이름 있는 열")``은 식별자가 아닌 열 이름을 꺼낸다.
"""
from __future__ import annotations

import ast

import numpy as np


def _nan_reduce(fn):
    def f(x):
        x = np.asarray(x, float)
        return fn(x) if np.isfinite(x).any() else np.nan
    return f


# 허용 함수 — 원소별 + 몇 개의 축약(스칼라를 돌려 배열에 브로드캐스트: NO2 - mean(NO2)).
FUNCS = {
    "abs": np.abs, "sqrt": np.sqrt, "log": np.log, "log10": np.log10, "exp": np.exp,
    "where": np.where, "isfinite": np.isfinite, "isnan": np.isnan, "clip": np.clip,
    "minimum": np.fmin, "maximum": np.fmax,
    "mean": _nan_reduce(np.nanmean), "median": _nan_reduce(np.nanmedian),
    "std": _nan_reduce(np.nanstd),
}
CONSTS = {"nan": np.nan, "inf": np.inf, "pi": np.pi}

_BIN = {
    ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply,
    ast.Div: np.divide, ast.Pow: np.power,
    ast.BitAnd: np.logical_and, ast.BitOr: np.logical_or,
}
_CMP = {
    ast.Lt: np.less, ast.LtE: np.less_equal, ast.Gt: np.greater,
    ast.GtE: np.greater_equal, ast.Eq: np.equal, ast.NotEq: np.not_equal,
}


class ExprError(ValueError):
    """식이 문법적으로 틀렸거나 허용되지 않은 것을 썼다."""


def names_in(expr):
    """식이 참조하는 변수 이름 집합(함수·상수 제외). 파싱 실패면 빈 집합."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id not in FUNCS and n.id not in CONSTS and n.id != "col":
            out.add(n.id)
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "col"
              and n.args and isinstance(n.args[0], ast.Constant)):
            out.add(str(n.args[0].value))
    return out


def safe_eval(expr, variables):
    """ast 화이트리스트 안전 평가. variables: {name: ndarray|scalar}.

    산술 경고(0으로 나눔·음수 log)는 NaN/inf로 조용히 둔다 — 데이터 열 계산에선 그게
    맞는 결과다. 허용 안 된 문법·모르는 이름은 `ExprError`(ValueError 하위)."""
    if not isinstance(expr, str) or not expr.strip():
        raise ExprError("Empty expression")
    try:
        node = ast.parse(expr.strip(), mode="eval").body
    except SyntaxError as e:
        raise ExprError(f"Expression syntax error: {e.msg}")

    def var(name):
        if name in variables:
            return variables[name]
        if name in CONSTS:
            return CONSTS[name]
        raise ExprError(f"Unknown variable '{name}'")

    def ev(n):
        if isinstance(n, ast.BinOp):
            op = _BIN.get(type(n.op))
            if op is None:
                raise ExprError("Operator not allowed (use + - * / ** & |)")
            return op(ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            if isinstance(n.op, ast.USub):
                return np.negative(v)
            if isinstance(n.op, ast.UAdd):
                return v
            if isinstance(n.op, ast.Invert):
                return np.logical_not(v)
            raise ExprError("Use ~ instead of 'not' (element-wise)")
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            acc = None
            for op, right_n in zip(n.ops, n.comparators):
                fn = _CMP.get(type(op))
                if fn is None:
                    raise ExprError("Comparison not allowed (use < <= > >= == !=)")
                right = ev(right_n)
                r = fn(left, right)
                acc = r if acc is None else np.logical_and(acc, r)
                left = right
            return acc
        if isinstance(n, ast.BoolOp):
            raise ExprError("Use & and | instead of 'and'/'or' (element-wise), "
                            "with parentheses: (A > 1) & (B < 2)")
        if isinstance(n, ast.Constant):
            if isinstance(n.value, (bool, int, float, str)):
                return n.value
            raise ExprError("Only numbers, strings and True/False are allowed as constants")
        if isinstance(n, ast.Name):
            return var(n.id)
        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name) or n.keywords:
                raise ExprError("Only plain function calls are allowed")
            fname = n.func.id
            if fname == "col":
                if len(n.args) == 1 and isinstance(n.args[0], ast.Constant) \
                        and isinstance(n.args[0].value, str):
                    return var(n.args[0].value)
                raise ExprError('col() takes one quoted column name: col("name")')
            fn = FUNCS.get(fname)
            if fn is None:
                raise ExprError(f"Function not allowed: {fname} "
                                f"(available: {', '.join(sorted(FUNCS))}, col)")
            return fn(*[ev(a) for a in n.args])
        raise ExprError(f"Expression not allowed: {type(n).__name__}")

    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        return ev(node)


def eval_column(expr, variables, n):
    """식을 길이 n짜리 float 열로 평가. 스칼라는 브로드캐스트, bool은 1/0.
    문자열 결과·길이 불일치는 ExprError."""
    v = safe_eval(expr, variables)
    a = np.asarray(v)
    if a.dtype.kind in "USO":
        raise ExprError("Result is text, not numbers (compare it: Flag == \"ok\")")
    a = a.astype(float)
    if a.ndim == 0:
        return np.full(n, float(a))
    if a.shape != (n,):
        raise ExprError(f"Result length {a.shape} ≠ {n} rows")
    return a


def eval_mask(expr, variables, n):
    """조건식을 길이 n짜리 bool 마스크로 평가(True = 조건 만족). NaN 비교는 False."""
    a = eval_column(expr, variables, n)
    return np.isfinite(a) & (a != 0)
