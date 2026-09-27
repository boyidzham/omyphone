"""Catch missing QML types, imports and syntax errors without starting a shell.

qs.Commons and qs.Ui come from the installed Omarchy shell, linked into a temp
import directory (the same approach as the omaplug plugin's tests).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
shell = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"
lint = "/usr/lib/qt6/bin/qmllint" if Path("/usr/lib/qt6/bin/qmllint").is_file() else shutil.which("qmllint")
if not (shell / "Ui" / "qmldir").is_file() or not lint:
    sys.exit("qml_lint: needs the Omarchy shell sources and qmllint")

with tempfile.TemporaryDirectory(prefix="omyphone-qml-") as directory:
    (Path(directory) / "qs").mkdir()
    for module in ("Commons", "Ui"):
        (Path(directory) / "qs" / module).symlink_to(shell / module, target_is_directory=True)
    files = sorted(str(p) for p in root.glob("*.qml"))
    if not files:
        sys.exit("qml_lint: no QML files found")
    result = subprocess.run([lint, "-I", directory, "--json", "-", *files],
                            capture_output=True, text=True, timeout=120)
    report = json.loads(result.stdout)
    failures = [f'{Path(f["filename"]).name}:{w.get("line", 0)}: {w["message"]}'
                for f in report["files"] for w in f["warnings"]
                if w["type"] == "error" or w.get("id") in
                ("import", "unresolved-type", "inheritance-cycle", "required", "syntax")]
    if failures:
        sys.exit("\n".join(failures))
print(f"qml_lint: ok ({len(files)} files)")
