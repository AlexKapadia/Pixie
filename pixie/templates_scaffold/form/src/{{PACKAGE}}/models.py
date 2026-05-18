"""Pydantic models for {{TOOL_NAME}}.

The ``Inputs`` model is built dynamically from ``tool.json`` at import
time so the schema's ``default`` values are honoured automatically and
the dashboard can send ``null`` for any key that has a schema default.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, create_model, model_validator

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))


_PY_TYPE: dict[str, type] = {
    "text": str, "textarea": str, "select": str, "radio": str,
    "colour": str, "date": str, "time": str, "datetime": str,
    "number": float, "slider": float,
    "checkbox": bool, "toggle": bool,
    "multiselect": list, "date_range": list,
    "file": str, "image": str, "audio": str,
}


def _resolve_numeric_type(spec: dict[str, Any]) -> type:
    """Return int when a number/slider has integer-valued step and bounds."""
    step = spec.get("step")
    default = spec.get("default")
    candidates = [step, default, spec.get("min"), spec.get("max")]
    if any(isinstance(v, float) and not v.is_integer() for v in candidates if v is not None):
        return float
    if isinstance(step, int) or (isinstance(step, float) and step.is_integer()):
        return int
    return float


class _PixieInputsBase(BaseModel):
    """Base for the dynamic Inputs model. Drops ``None`` for keys with a
    schema default so the pydantic default kicks in."""
    _schema_defaults: ClassVar[set[str]] = set()

    @model_validator(mode="before")
    @classmethod
    def _drop_none_with_default(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items()
                    if not (v is None and k in cls._schema_defaults)}
        return data


def _build_inputs_model(schema: dict[str, Any]) -> type[BaseModel]:
    defaults_set: set[str] = set()
    fields: dict[str, tuple[Any, Any]] = {}
    for spec in schema.get("inputs", []) or []:
        key = spec.get("key")
        if not key:
            continue
        kind = spec.get("type")
        if kind in {"number", "slider"}:
            py_type = _resolve_numeric_type(spec)
        else:
            py_type = _PY_TYPE.get(kind, Any)
        if "default" in spec:
            default = spec["default"]
            defaults_set.add(key)
        else:
            default = None
        fields[key] = (Optional[py_type], default)
    model = create_model("Inputs", __base__=_PixieInputsBase, **fields)
    model._schema_defaults = defaults_set
    return model


Inputs = _build_inputs_model(SCHEMA)


class RunRequest(BaseModel):
    # Pixie sends {"run_id": "...", "inputs": {...}} per the decisions log.
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: dict[str, Any] | None = None


class Outputs(BaseModel):
    peak_value: float
    growth_chart: dict[str, Any]
    breakdown: dict[str, Any]
