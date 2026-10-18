"""Build the common Lambda layer for Linux without Docker (D-15).

Lambda runs Linux; a plain `pip install` on Windows fetches Windows builds of
pydantic-core and the Lambdas crash on import. This asks pip for the Linux
wheels explicitly, then adds our own `common` package and labels.json.

Output: backend/build/layer/python/...  (git-ignored; template.yaml points here)

    python scripts/build_layer.py
    cd backend && sam build && sam deploy
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "backend" / "layers" / "common"
OUT = ROOT / "backend" / "build" / "layer"
PY = OUT / "python"


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    PY.mkdir(parents=True)

    # Keep pip's temp files next to the output, not on the system drive.
    tmp = ROOT / "backend" / "build" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp)}

    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "-r", str(SRC / "requirements.txt"),
        "--target", str(PY),
        "--platform", "manylinux2014_x86_64",
        "--implementation", "cp",
        "--python-version", "3.11",
        "--only-binary=:all:",
        "--no-cache-dir", "--quiet",
    ], check=True, env=env)

    shutil.copytree(SRC / "common", PY / "common",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(ROOT / "config" / "labels.json", PY / "common" / "labels.json")
    shutil.rmtree(tmp, ignore_errors=True)

    so = list(PY.glob("pydantic_core/*.so"))
    if not so or "linux" not in so[0].name:
        sys.exit("pydantic_core Linux binary missing; the layer would crash on Lambda")
    print(f"layer built at {OUT.relative_to(ROOT)} ({so[0].name})")


if __name__ == "__main__":
    main()
