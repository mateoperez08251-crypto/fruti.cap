"""Windows-MCP stdio entry with a narrow UTF-16 serialization compatibility fix.

Windows UI text can contain a truncated UTF-16 surrogate. Pydantic then aborts
the entire MCP transport. Normalize only such strings, preserving typed models,
aliases, unset fields and the original message. Installed only in this child.
"""
from __future__ import annotations

import sys
from importlib.metadata import entry_points

from pydantic import BaseModel

_DUMP_JSON = BaseModel.model_dump_json


def normalize_unicode(value):
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            return value.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
        return value
    if isinstance(value, BaseModel):
        changes = {}
        for key, item in value.__dict__.items():
            normalized = normalize_unicode(item)
            if normalized is not item:
                changes[key] = normalized
        extras = normalize_unicode(value.model_extra) if value.model_extra is not None else None
        if not changes and extras is value.model_extra:
            return value
        result = value.model_copy(update=changes)
        object.__setattr__(result, "__pydantic_fields_set__", value.model_fields_set.copy())
        if value.model_extra is not None:
            object.__setattr__(result, "__pydantic_extra__", extras)
        return result
    if isinstance(value, dict):
        result = {normalize_unicode(key): normalize_unicode(item) for key, item in value.items()}
        if all(a is b and value[a] is result[b] for a, b in zip(value, result, strict=True)):
            return value
        return result
    if isinstance(value, (list, tuple)):
        result = [normalize_unicode(item) for item in value]
        if all(a is b for a, b in zip(value, result, strict=True)):
            return value
        return tuple(result) if isinstance(value, tuple) else result
    return value


def safe_model_dump_json(self, *args, **kwargs):
    return _DUMP_JSON(normalize_unicode(self), *args, **kwargs)


def main():
    BaseModel.model_dump_json = safe_model_dump_json
    matches = list(entry_points(group="console_scripts", name="windows-mcp"))
    if len(matches) != 1:
        raise RuntimeError("No se encontró una única entrada Windows-MCP instalada.")
    sys.argv[0] = "windows-mcp"
    return matches[0].load()()


if __name__ == "__main__":
    main()
