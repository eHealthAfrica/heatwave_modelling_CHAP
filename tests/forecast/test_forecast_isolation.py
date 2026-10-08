"""DATA-05: the forecast package must never import Earth Engine or EE-dependent modules."""
import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FORBIDDEN_ROOTS = {"ee", "geemap"}


def _module_allowed(name: str) -> bool:
    root = name.split(".")[0]
    if root in FORBIDDEN_ROOTS:
        return False
    if root == "heatwave":
        return (
            name in ("heatwave", "heatwave.config")
            or name == "heatwave.forecast"
            or name.startswith("heatwave.forecast.")
        )
    return True


def scan_file(path: Path, in_forecast_pkg: bool = False):
    """Return a list of 'file:line module' violations found by AST walk."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    bad = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                if not in_forecast_pkg:
                    names = ["<relative>"]
            else:
                base = node.module or ""
                names = [base]
                # `from heatwave import auth` imports heatwave.auth
                if base == "heatwave":
                    names = [f"heatwave.{a.name}" for a in node.names]
        elif isinstance(node, ast.Call):
            f = node.func
            is_dyn = (isinstance(f, ast.Name) and f.id == "__import__") or (
                isinstance(f, ast.Attribute) and f.attr == "import_module"
            )
            if (
                is_dyn
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                names = [node.args[0].value]
        for n in names:
            if n == "<relative>" or not _module_allowed(n):
                bad.append(f"{path}:{node.lineno} {n}")
    return bad


def test_forecast_package_never_imports_earth_engine():
    code = """
import importlib, pkgutil, sys
import heatwave.forecast as pkg
seen = set()
for m in pkgutil.walk_packages(pkg.__path__, "heatwave.forecast."):
    importlib.import_module(m.name)
    seen.add(m.name.rsplit(".", 1)[-1])
need = {"config", "weeks", "data", "artifacts", "fixtures"}
assert need <= seen, f"missing modules: {need - seen}"
bad = sorted(
    n for n in sys.modules
    if n.split(".")[0] in {"ee", "geemap"}
    or (n.startswith("heatwave.") and n != "heatwave.config"
        and not n.startswith("heatwave.forecast"))
)
if bad:
    print(bad)
    sys.exit(1)
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"


def test_static_imports_are_allowed():
    violations = []
    for p in sorted((REPO / "heatwave" / "forecast").rglob("*.py")):
        violations += scan_file(p, in_forecast_pkg=True)
    violations += scan_file(REPO / "scripts" / "verify_frozen.py")
    assert not violations, "\n".join(violations)


def test_static_scan_detects_violation(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("def f():\n    import ee\n", encoding="utf-8")
    b = tmp_path / "b.py"
    b.write_text("from heatwave import auth\n", encoding="utf-8")
    assert scan_file(a)
    assert scan_file(b)
