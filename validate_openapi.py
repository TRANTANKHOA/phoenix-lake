#!/usr/bin/env python3
"""Validate OpenAPI 3.0 spec and check for structural issues."""

import sys
import yaml
import json
from pathlib import Path

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

errors = []
warnings = []


def err(msg):
    errors.append(msg)
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg):
    warnings.append(msg)
    print(f"  {YELLOW}⚠{RESET} {msg}")


def ok(msg):
    print(f"  {GREEN}✓{RESET} {msg}")


def validate_ref(ref, spec, path=""):
    """Check that a $ref points to a valid location in the spec."""
    if not ref.startswith("#/"):
        warn(f"External $ref not validated: {ref}")
        return
    parts = ref[2:].split("/")
    node = spec
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            err(f"Broken $ref '{ref}' at {path}")
            return


def check_refs(spec, node, path=""):
    """Recursively check all $ref values."""
    if isinstance(node, dict):
        if "$ref" in node:
            validate_ref(node["$ref"], spec, path)
        for k, v in node.items():
            check_refs(spec, v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            check_refs(spec, item, f"{path}[{i}]")


def collect_schemas(spec):
    """Return set of defined schema names."""
    schemas = spec.get("components", {}).get("schemas", {})
    return set(schemas.keys())


def collect_refs(spec):
    """Return set of all referenced schema names."""
    refs = set()

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if ref.startswith("#/components/schemas/"):
                    refs.add(ref.split("/")[-1])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(spec)
    return refs


def check_security_schemes(spec):
    """Check that securityDefinitions/securitySchemes are defined if used."""
    security = spec.get("security", [])
    schemes = spec.get("components", {}).get("securitySchemes", {})
    for sec in security:
        for name in sec:
            if name not in schemes:
                err(f"Security scheme '{name}' referenced in global security but not defined in components/securitySchemes")


def check_tags(spec):
    """Check that all tags used in operations are defined."""
    defined = {t["name"] for t in spec.get("tags", [])}
    used = set()
    for path_obj in spec.get("paths", {}).values():
        for method in ["get", "post", "put", "patch", "delete", "options", "head"]:
            op = path_obj.get(method, {})
            if op:
                used.update(op.get("tags", []))
    for tag in used:
        if tag not in defined:
            warn(f"Tag '{tag}' used in operations but not defined in top-level tags")


def check_path_item(path, item):
    """Validate a single path item."""
    # Check it's actually a path item object (has HTTP methods or parameters)
    valid_methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace", "servers"}
    keys = set(item.keys())
    if not keys.issubset(valid_methods | {"parameters", "summary", "description", "servers", "callbacks"}):
        bad = keys - valid_methods - {"parameters", "summary", "description", "servers", "callbacks"}
        err(f"Path '{path}' has invalid keys: {bad} — looks like it may be misplaced or malformed")


def check_operation_ids(spec):
    """Check for missing operationId (warning only)."""
    for path, path_obj in spec.get("paths", {}).items():
        for method in ["get", "post", "put", "patch", "delete"]:
            op = path_obj.get(method, {})
            if op and "operationId" not in op:
                warn(f"Missing operationId on {method.upper()} {path}")


def check_response_examples(spec):
    """Check that 2xx responses have examples or example fields."""
    for path, path_obj in spec.get("paths", {}).items():
        for method in ["get", "post", "put", "patch", "delete"]:
            op = path_obj.get(method, {})
            if not op:
                continue
            for code, resp in op.get("responses", {}).items():
                if code.startswith("2"):
                    content = resp.get("content", {})
                    for ct, media in content.items():
                        schema = media.get("schema", {})
                        if "example" not in media and "examples" not in media:
                            # Only warn if schema is inline (not a $ref)
                            if "$ref" not in schema:
                                warn(f"No example for {method.upper()} {path} {code} ({ct})")


def main():
    spec_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/openapi.yaml")
    print(f"\nValidating: {spec_path}\n")

    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    # --- Basic structure ---
    print("Basic Structure")
    if spec.get("openapi", "").startswith("3."):
        ok(f"OpenAPI version: {spec['openapi']}")
    else:
        err(f"Invalid or missing openapi version: {spec.get('openapi')}")

    if spec.get("info", {}).get("title"):
        ok(f"Title: {spec['info']['title']}")
    else:
        err("Missing info.title")

    if spec.get("info", {}).get("version"):
        ok(f"Version: {spec['info']['version']}")
    else:
        err("Missing info.version")

    if spec.get("paths"):
        ok(f"Paths defined: {len(spec['paths'])}")
    else:
        err("No paths defined")

    # --- Path validation ---
    print("\nPath Validation")
    for path, item in spec.get("paths", {}).items():
        if not path.startswith("/"):
            err(f"Path must start with /: {path}")
        check_path_item(path, item)

    # --- Schema validation ---
    print("\nSchema Validation")
    schemas = collect_schemas(spec)
    refs = collect_refs(spec)
    ok(f"Defined schemas: {sorted(schemas)}")

    undefined = refs - schemas
    for name in sorted(undefined):
        err(f"Schema '{name}' referenced but not defined")

    unused = schemas - refs
    for name in sorted(unused):
        warn(f"Schema '{name}' defined but never referenced")

    # --- $ref validation ---
    print("\nReference Validation")
    check_refs(spec, spec)
    ok("$ref paths validated (see above for errors)")

    # --- Tags ---
    print("\nTag Validation")
    check_tags(spec)

    # --- Security ---
    print("\nSecurity Validation")
    check_security_schemes(spec)
    if spec.get("security"):
        ok("Global security configured")
    else:
        warn("No global security defined")

    # --- Operation IDs ---
    print("\nOperation ID Check")
    check_operation_ids(spec)

    # --- Response Examples ---
    print("\nResponse Example Check")
    check_response_examples(spec)

    # --- Health endpoint check ---
    print("\nEndpoint Completeness")
    health = spec.get("paths", {}).get("/health", {})
    if health.get("get"):
        ok("/health has GET operation")
    else:
        err("/health is missing GET operation — path item contains misplaced schema definitions")

    # --- Summary ---
    print(f"\n{'='*50}")
    print(f"Results: {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors:
        print(f"{RED}FAILED{RESET}")
        sys.exit(1)
    elif warnings:
        print(f"{YELLOW}PASSED with warnings{RESET}")
        sys.exit(0)
    else:
        print(f"{GREEN}PASSED{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
