"""Pure static verification selection; references and output are not run evidence."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "tools/workflow_boundary_registry.json"
TOOLING_COMMAND = "python -m unittest discover -s tests/tooling -p test_*.py -v"
DESCRIPTIONS = {
    "target_identity", "producer", "consumer", "intent", "attempt",
    "terminal_evidence", "artifacts", "packaging", "consumer_wording", "reconciliation",
}


class CatalogError(ValueError):
    pass


def normalize_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise CatalogError("path must be a nonempty string")
    value = value.replace("\\", "/")
    if value.startswith("/") or ":" in value or ".." in value.split("/"):
        raise CatalogError("path must be repository-relative without traversal")
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if not parts:
        raise CatalogError("empty normalized path")
    return "/".join(parts)


def rooted_file(root, value):
    value = normalize_path(value)
    if any(char in value for char in "*?["):
        raise CatalogError("file reference must not be a pattern")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise CatalogError("missing or escaping file reference: " + value)
    return path


def exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise CatalogError("invalid fields in " + label)


def strings(value, label, nonempty=True):
    if not isinstance(value, list) or (nonempty and not value):
        raise CatalogError("expected list in " + label)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise CatalogError("expected nonempty strings in " + label)
    if len(set(value)) != len(value):
        raise CatalogError("duplicate entries in " + label)


def patterns(values, label, exact=False):
    strings(values, label)
    for pattern in values:
        if normalize_path(pattern) != pattern:
            raise CatalogError("catalog paths must be normalized")
        if any(char in pattern for char in "?[") or pattern.count("*") > 1:
            raise CatalogError("only bounded terminal-star patterns are supported")
        if "*" in pattern and (exact or not pattern.endswith("*") or "/" not in pattern):
            raise CatalogError("unbounded or nonterminal catalog pattern")


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError("duplicate JSON key: " + key)
        result[key] = value
    return result


def named_node(tree, name):
    parts = name.split(".")
    nodes = tree.body
    result = None
    for part in parts:
        result = next((node for node in nodes if isinstance(
            node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name == part), None)
        if result is None:
            raise CatalogError("missing Python definition: " + name)
        nodes = result.body
    return result


def linked_call(tree, caller, caller_file, helper):
    symbol = helper["symbol"]
    called = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == symbol for node in ast.walk(caller))
    if not called:
        raise CatalogError("feature/helper does not call " + symbol)
    if caller_file == helper["file"]:
        return
    module = helper["file"].removesuffix(".py").replace("/", ".")
    imported = any(isinstance(node, ast.ImportFrom) and node.module == module
                   and node.level == 0 and any(alias.name == symbol
                   and alias.asname in (None, symbol) for alias in node.names)
                   for node in tree.body)
    if not imported:
        raise CatalogError("helper import does not match catalog: " + symbol)


def validate_catalog(catalog, root=ROOT):
    exact_keys(catalog, {"schema_version", "purpose", "governing_paths",
                       "shared_code_paths", "contracts"}, "catalog")
    if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1:
        raise CatalogError("unsupported schema_version")
    if catalog["purpose"] != "static_developer_verification_catalog":
        raise CatalogError("catalog is not a static developer verification catalog")
    for key in ("governing_paths", "shared_code_paths"):
        patterns(catalog[key], key, exact=key == "governing_paths")
    if not isinstance(catalog["contracts"], list) or not catalog["contracts"]:
        raise CatalogError("missing contracts")
    identifiers = set()
    trees = {}

    def tree_for(file):
        path = rooted_file(root, file)
        if file not in trees:
            try:
                trees[file] = ast.parse(path.read_text(encoding="utf-8"), filename=file)
            except (SyntaxError, UnicodeError) as exc:
                raise CatalogError("invalid referenced Python: " + file) from exc
        return trees[file]

    for contract in catalog["contracts"]:
        exact_keys(contract, DESCRIPTIONS | {"id", "status", "paths", "negative_cases",
                                            "feature_tests"}, "contract")
        identifier = contract["id"]
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise CatalogError("missing or duplicate contract id")
        identifiers.add(identifier)
        if contract["status"] not in ("implemented", "planned"):
            raise CatalogError("unknown contract status")
        for key in DESCRIPTIONS:
            if not isinstance(contract[key], str) or not contract[key].strip():
                raise CatalogError("missing contract meaning: " + key)
        strings(contract["negative_cases"], "negative_cases")
        patterns(contract["paths"], "contract paths")
        features = contract["feature_tests"]
        if not isinstance(features, list):
            raise CatalogError("feature_tests must be a list")
        if contract["status"] == "planned":
            if features:
                raise CatalogError("planned contract cannot claim implemented feature tests")
            continue
        if not features:
            raise CatalogError("implemented contract has no concrete feature tests")
        for feature in features:
            exact_keys(feature, {"file", "test", "helper_chain"}, "feature test")
            file = normalize_path(feature["file"])
            if file != feature["file"]:
                raise CatalogError("feature path must be normalized")
            if not file.startswith("tests/") or not isinstance(feature["test"], str):
                raise CatalogError("invalid feature test reference")
            tree = tree_for(file)
            caller = named_node(tree, feature["test"])
            if (len(feature["test"].split(".")) != 2 or
                    not isinstance(caller, (ast.FunctionDef, ast.AsyncFunctionDef)) or
                    not caller.name.startswith("test_")):
                raise CatalogError("reference is not a concrete test method")
            chain = feature["helper_chain"]
            if not isinstance(chain, list) or not chain:
                raise CatalogError("missing concrete helper chain")
            for helper in chain:
                exact_keys(helper, {"file", "symbol"}, "helper")
                if not isinstance(helper["symbol"], str) or not helper["symbol"].isidentifier():
                    raise CatalogError("invalid helper symbol")
                if normalize_path(helper["file"]) != helper["file"]:
                    raise CatalogError("helper path must be normalized")
                linked_call(tree, caller, file, helper)
                file = helper["file"]
                tree = tree_for(file)
                caller = named_node(tree, helper["symbol"])
                if not isinstance(caller, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    raise CatalogError("helper reference is not a function")
            if file != "tests/helpers/workflow_boundary_contract.py":
                raise CatalogError("chain must reach concrete workflow boundary helper")
    return catalog


def load_catalog(root=ROOT):
    try:
        data = json.loads(rooted_file(root, REGISTRY).read_text(encoding="utf-8"),
                          object_pairs_hook=no_duplicates)
        return validate_catalog(data, root)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError("catalog could not be read/parsed") from exc


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def select_paths(catalog, paths, root=ROOT):
    validate_catalog(catalog, root)
    normalized = sorted({normalize_path(path) for path in paths})
    if not normalized:
        raise CatalogError("at least one changed path is required")
    selected = {}
    unknown = []
    governing = False
    tooling_changed = False
    code_changed = False
    for path in normalized:
        if not (root / path).resolve().is_relative_to(root.resolve()):
            raise CatalogError("changed path escapes repository")
        if any(char in path for char in "*?["):
            raise CatalogError("changed path must not be a pattern")
        guidance = matches(path, catalog["governing_paths"])
        governing |= guidance
        docs = path.endswith(".md") and (path.startswith("docs/") or guidance or path in {
            "README.md", "CONTRIBUTING.md", "SECURITY.md", "AGENTS.md",
        })
        contracts = [item for item in catalog["contracts"] if matches(path, item["paths"])]
        tooling_changed |= guidance and not docs
        if matches(path, catalog["shared_code_paths"]):
            contracts = [item for item in catalog["contracts"] if item["status"] == "implemented"]
        if not (guidance or docs or contracts):
            unknown.append(path)
        code_changed |= not docs and not guidance
        for item in contracts:
            selected[item["id"]] = item
    ordered = [selected[key] for key in sorted(selected)]
    tests = sorted({feature["file"].removesuffix(".py").replace("/", ".")
                    for item in ordered for feature in item["feature_tests"]})
    commands = [TOOLING_COMMAND] if governing else []
    suites = sorted({".".join(module.split(".")[:2]) for module in tests})
    if code_changed and tests:
        commands.append("python manage.py test " + " ".join(suites) + " --verbosity 2")
    return {
        "status": "review_required" if unknown else "code" if code_changed else "tooling" if tooling_changed else "docs_only",
        "paths": normalized, "unknown_paths": unknown,
        "boundary_scan_required": bool(ordered) or governing or bool(unknown),
        "governing_guidance_required": governing,
        "contracts": [{"id": item["id"], "status": item["status"]} for item in ordered],
        "feature_test_modules": tests, "feature_suites": suites, "commands": commands,
        "evidence": "selection_and_static_references_only_not_execution",
        "planned_contracts": [item["id"] for item in ordered if item["status"] == "planned"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--validate", action="store_true", help="validate catalog only")
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog()
        if args.validate:
            if args.paths:
                raise CatalogError("--validate takes no changed paths")
            result = {"status": "catalog_valid", "evidence": "static_references_only_not_execution"}
        else:
            result = select_paths(catalog, args.paths)
    except (CatalogError, OSError, TypeError) as exc:
        result = {"status": "review_required", "error": str(exc), "boundary_scan_required": True}
        print(json.dumps(result, sort_keys=True) if args.json else str(result))
        return 2
    print(json.dumps(result, sort_keys=True) if args.json else str(result))
    return 2 if result["status"] == "review_required" else 0


if __name__ == "__main__":
    sys.exit(main())
