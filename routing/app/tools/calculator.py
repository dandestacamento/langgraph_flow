"""Calculator tool (Level 8 - tool selection and execution): safe
arithmetic expression evaluation for questions that combine a retrieved
or given fact with arithmetic (e.g. a midpoint of a day-range, a total
cost across repeated fees), rather than a single CSV/database lookup
(see `sql_query.py` for that case) or prose retrieval.

Uses Python's `ast` module to parse the expression into a syntax tree and
evaluate it node-by-node, allowing only numeric literals and the
`+ - * / ( )` operators - never Python's `eval()`/`exec()` on
LLM-supplied input, since that would execute arbitrary code.
"""

from __future__ import annotations

import ast
import operator

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"Unsupported expression element: {ast.dump(node)}")


def calculate(expression: str) -> float:
    """Safely evaluate a numeric expression using only `+ - * / ( )` and
    numeric literals. Raises `ValueError` for anything else (names,
    function calls, attribute access, etc.) so an LLM-generated
    expression can never execute arbitrary code."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Could not parse expression {expression!r}: {exc}") from exc
    return _eval_node(tree)

