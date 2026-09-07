"""Small conversion helpers shared by framework adapters."""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timezone
from typing import Any

from tracetotest.trace.redaction import redact
from tracetotest.trace.schema import ActionRecord


def stable_run_id(framework: str, source: str, started_at: str) -> str:
    digest = hashlib.sha256(f"{framework}:{source}:{started_at}".encode()).hexdigest()[:16]
    return f"run_{digest}"


def parse_time(value: Any, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = fallback or datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_agentlab_action(value: Any) -> ActionRecord:
    if not isinstance(value, str) or not value.strip():
        return ActionRecord(type="noop", parameters={})
    try:
        tree = ast.parse(value)
    except SyntaxError:
        return ActionRecord(type="unparsed", parameters={"raw": redact(value)})
    calls = [
        statement.value
        for statement in tree.body
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
    ]
    if not calls or not isinstance(calls[0].func, ast.Name):
        return ActionRecord(type="unparsed", parameters={"raw": redact(value)})
    call = calls[0]
    parameters: dict[str, Any] = {}
    for index, node in enumerate(call.args):
        try:
            parameters[f"arg{index}"] = ast.literal_eval(node)
        except (ValueError, TypeError):
            parameters[f"arg{index}"] = ast.unparse(node)
    for item in call.keywords:
        if item.arg:
            try:
                parameters[item.arg] = ast.literal_eval(item.value)
            except (ValueError, TypeError):
                parameters[item.arg] = ast.unparse(item.value)
    target_id = parameters.get("bid", parameters.get("index"))
    coordinates = None
    if "x" in parameters and "y" in parameters:
        try:
            coordinates = (float(parameters["x"]), float(parameters["y"]))
        except (TypeError, ValueError):
            coordinates = None
    return ActionRecord(
        type=call.func.id,
        parameters=redact(parameters),
        coordinates=coordinates,
        target_text=str(parameters["text"]) if parameters.get("text") is not None else None,
        target_element_id=str(target_id) if target_id is not None else None,
    )


def parse_structured_action(value: Any) -> ActionRecord:
    if not isinstance(value, dict) or not value:
        return ActionRecord(type="noop")
    name, raw_parameters = next(iter(value.items()))
    parameters = raw_parameters if isinstance(raw_parameters, dict) else {"value": raw_parameters}
    coordinates = None
    if "coordinate_x" in parameters and "coordinate_y" in parameters:
        try:
            coordinates = (float(parameters["coordinate_x"]), float(parameters["coordinate_y"]))
        except (TypeError, ValueError):
            coordinates = None
    target_id = parameters.get("index", parameters.get("element_id"))
    return ActionRecord(
        type=str(name),
        parameters=redact(parameters),
        coordinates=coordinates,
        target_text=str(parameters["text"]) if parameters.get("text") is not None else None,
        target_element_id=str(target_id) if target_id is not None else None,
    )
