"""Enforce the dependency direction drawn in docs/02-architecture-overview.md.

Lower layers must not import higher ones: `store` never imports `retrieve`,
`retrieve` never imports `api`, and so on. That keeps every layer testable on
its own and makes import cycles impossible. Changing this table is allowed —
but it is then a deliberate, reviewed decision, not an accident.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# package -> app packages it may import (besides itself)
ALLOWED: dict[str, set[str]] = {
    "config": set(),
    "telemetry": {"config"},
    "store": {"config", "telemetry"},
    "embed": {"config", "telemetry"},
    "ingest": {"config", "telemetry", "store", "embed"},
    "retrieve": {"config", "telemetry", "store", "embed"},
    "generate": {"config", "telemetry", "store", "retrieve"},
    "api": {"config", "telemetry", "store", "embed", "retrieve", "generate"},
}


def package_of(path: Path) -> str:
    rel = path.relative_to(APP)
    return rel.parts[0].removesuffix(".py")


def app_imports(path: Path) -> set[str]:
    """Top-level app packages imported by one file (absolute and relative imports)."""
    tree = ast.parse(path.read_text(), filename=str(path))
    own = package_of(path)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "app" and len(parts) > 1:
                    found.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import stays inside the same package
                found.add(own)
            elif node.module and node.module.split(".")[0] == "app":
                parts = node.module.split(".")
                if len(parts) > 1:
                    found.add(parts[1])
                else:  # `from app import x`
                    found.update(alias.name for alias in node.names)
    return found - {own}


def test_every_app_package_is_in_the_dependency_table():
    packages = {package_of(p) for p in APP.rglob("*.py") if p.name != "__init__.py" or p.parent != APP}
    packages.discard("__init__")
    assert packages <= set(ALLOWED), f"add {sorted(packages - set(ALLOWED))} to ALLOWED"


def test_no_layer_imports_a_layer_above_it():
    violations = []
    for path in sorted(APP.rglob("*.py")):
        if path.parent == APP and path.name == "__init__.py":
            continue
        own = package_of(path)
        for imported in app_imports(path):
            if imported not in ALLOWED[own]:
                violations.append(f"{path.relative_to(APP.parent)}: {own} -> {imported}")
    assert not violations, "forbidden imports:\n" + "\n".join(violations)
