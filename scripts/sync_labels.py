"""Copy the master species list into the Lambda layer. Run before `sam build`.

config/labels.json is the only copy anyone edits (D-04). The copy inside the
layer is git-ignored so it can't drift.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "config" / "labels.json"
DST = ROOT / "backend" / "layers" / "common" / "common" / "labels.json"

if __name__ == "__main__":
    shutil.copyfile(SRC, DST)
    print(f"copied {SRC.relative_to(ROOT)} -> {DST.relative_to(ROOT)}")
