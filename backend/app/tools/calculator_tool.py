"""Safe arithmetic calculator.

Expressions are parsed with :mod:`ast` and evaluated by walking an allowlist of node types:
numbers, + - * / // % **, unary +/-, parentheses, and a few math functions/constants. No
names, attributes, calls to arbitrary functions, or Python evaluation are possible.
"""

from __future__ import annotations

import ast
import math
import operator

from pydantic import BaseModel, Field

from app.schemas.chat import ToolName
from app.tools.base import Tool, ToolContext, ToolOutput


class CalculatorError(ValueError):
    pass


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTS = {"pi": math.pi, "e": math.e}
MAX_EXPONENT = 1000
MAX_MAGNITUDE = 1e100


def safe_eval(expression: str) -> float | int:
    expression = expression.strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    if not expression or len(expression) > 200:
        raise CalculatorError("Expression must be 1-200 characters.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError("Not a valid arithmetic expression.") from exc

    def _eval(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise CalculatorError("Exponent too large.")
            try:
                result = _BINOPS[type(node.op)](left, right)
            except ZeroDivisionError as exc:
                raise CalculatorError("Division by zero.") from exc
            if isinstance(result, complex) or abs(result) > MAX_MAGNITUDE:
                raise CalculatorError("Result out of range.")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS
            and not node.keywords
            and len(node.args) <= 2
        ):
            try:
                return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
            except (ValueError, OverflowError, TypeError) as exc:
                raise CalculatorError(f"Invalid argument for {node.func.id}.") from exc
        raise CalculatorError(f"Unsupported element in expression: {type(node).__name__}.")

    result = _eval(tree)
    if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
        return int(result)
    return result


class CalculatorArgs(BaseModel):
    expression: str = Field(min_length=1, max_length=200, description="Arithmetic expression, e.g. '129 * 347'")


class CalculatorTool(Tool):
    name = ToolName.CALCULATOR
    description = "Evaluate an arithmetic expression exactly (+ - * / // % ** and sqrt, log, sin, cos, round)."
    args_model = CalculatorArgs

    async def run(self, args: CalculatorArgs, ctx: ToolContext) -> ToolOutput:  # type: ignore[override]
        try:
            value = safe_eval(args.expression)
        except CalculatorError as exc:
            return ToolOutput(
                summary=f"Could not evaluate: {exc}",
                observation=f"Calculator error: {exc}",
                status="error",
                error=str(exc),
                details={"expression": args.expression},
            )
        text = f"{args.expression} = {value}"
        return ToolOutput(summary=text, observation=text, details={"expression": args.expression, "result": value})
