"""API contract checks: the published OpenAPI schema is a promise to the apps already installed
on people's phones (which update slowly) and to partners using the API.

``docs/api/openapi.json`` is the committed snapshot. ``breaking_changes(old, new)`` lists what
would break an existing client; additions (new endpoints, new optional fields, new enum values in
requests) are fine. The test suite fails on a breaking change; ``make contract`` refreshes the
snapshot after a deliberate, versioned change.

Breaking:
* an endpoint or method removed;
* a field removed from a success response, or its type changed;
* a request field that becomes required, or a new required request field;
* an enum value removed from a request (clients may still send it).
"""

import json
from pathlib import Path

from django.conf import settings

SNAPSHOT = Path(settings.BASE_DIR) / "docs" / "api" / "openapi.json"
METHODS = ("get", "post", "put", "patch", "delete")


def generate() -> dict:
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    return json.loads(json.dumps(schema, default=str))


def save(schema: dict | None = None) -> Path:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(schema or generate(), indent=1, sort_keys=True) + "\n")
    return SNAPSHOT


def load() -> dict:
    return json.loads(SNAPSHOT.read_text())


def _resolve(schema: dict, node: dict | None, depth: int = 0) -> dict:
    if not node or depth > 6:
        return node or {}
    if "$ref" in node:
        name = node["$ref"].split("/")[-1]
        return _resolve(
            schema, schema.get("components", {}).get("schemas", {}).get(name), depth + 1
        )
    if "allOf" in node:
        merged: dict = {"properties": {}, "required": []}
        for part in node["allOf"]:
            part = _resolve(schema, part, depth + 1)
            merged["properties"].update(part.get("properties", {}))
            merged["required"] += part.get("required", [])
            merged.setdefault("type", part.get("type"))
        return merged
    return node


def _type(schema: dict, node: dict) -> str:
    node = _resolve(schema, node)
    if "oneOf" in node or "anyOf" in node:
        return "union"
    return str(node.get("type", "object" if "properties" in node else "any"))


def _compare_response(old_s, new_s, old, new, where: str, out: list, depth: int = 0) -> None:
    old, new = _resolve(old_s, old), _resolve(new_s, new)
    if depth > 4:
        return
    if old.get("type") == "array" and new.get("type") == "array":
        _compare_response(
            old_s, new_s, old.get("items"), new.get("items"), f"{where}[]", out, depth + 1
        )
        return
    for name, prop in (old.get("properties") or {}).items():
        new_prop = (new.get("properties") or {}).get(name)
        if new_prop is None:
            out.append(f"{where}: response field '{name}' was removed")
            continue
        old_type, new_type = _type(old_s, prop), _type(new_s, new_prop)
        if (
            "any" not in (old_type, new_type)
            and old_type != new_type
            and "union" not in (old_type, new_type)
        ):
            out.append(f"{where}: response field '{name}' changed type {old_type} → {new_type}")
        elif old_type in ("object", "array"):
            _compare_response(old_s, new_s, prop, new_prop, f"{where}.{name}", out, depth + 1)


def _compare_request(old_s, new_s, old, new, where: str, out: list) -> None:
    old, new = _resolve(old_s, old), _resolve(new_s, new)
    old_required = set(old.get("required") or [])
    for name in sorted(set(new.get("required") or []) - old_required):
        out.append(f"{where}: request field '{name}' is now required")
    for name, prop in (old.get("properties") or {}).items():
        new_prop = (new.get("properties") or {}).get(name)
        if new_prop is None:
            continue  # a field the server now ignores doesn't break the client
        old_enum = set(_resolve(old_s, prop).get("enum") or [])
        new_enum = set(_resolve(new_s, new_prop).get("enum") or [])
        if old_enum and new_enum and old_enum - new_enum:
            gone = ", ".join(sorted(str(v) for v in old_enum - new_enum))
            out.append(f"{where}: request field '{name}' no longer accepts {gone}")


def _json_body(content: dict | None) -> dict | None:
    if not content:
        return None
    body = content.get("application/json") or next(iter(content.values()), None)
    return (body or {}).get("schema")


def breaking_changes(old: dict, new: dict) -> list[str]:
    out: list[str] = []
    for path, old_ops in old.get("paths", {}).items():
        new_ops = new.get("paths", {}).get(path)
        if new_ops is None:
            out.append(f"{path}: endpoint removed")
            continue
        for method in METHODS:
            if method not in old_ops:
                continue
            where = f"{method.upper()} {path}"
            if method not in new_ops:
                out.append(f"{where}: method removed")
                continue
            old_op, new_op = old_ops[method], new_ops[method]
            old_req = _json_body((old_op.get("requestBody") or {}).get("content"))
            new_req = _json_body((new_op.get("requestBody") or {}).get("content"))
            if new_req:
                _compare_request(old, new, old_req or {}, new_req, where, out)
            for code, response in (old_op.get("responses") or {}).items():
                if not str(code).startswith("2"):
                    continue
                new_response = (new_op.get("responses") or {}).get(code)
                if new_response is None:
                    out.append(f"{where}: {code} response removed")
                    continue
                _compare_response(
                    old,
                    new,
                    _json_body(response.get("content")),
                    _json_body(new_response.get("content")),
                    f"{where} → {code}",
                    out,
                )
    return out
