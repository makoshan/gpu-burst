"""Every .bdf must exist with the byte size encoded in its git-annex key
(SHA256E-s<bytes>--...). Exits 1 on any missing or mismatched file."""
import os, sys
from pathlib import Path

git = Path(os.path.expanduser("~/neural-compet26/nm000281-git"))
data = Path(os.path.expanduser("~/neural-compet26/data/neural_compet/Salter2024Emg2pose/download/nm000281"))
n = missing = bad = 0
for link in git.rglob("*.bdf"):
    if not link.is_symlink():
        continue
    size = int(os.readlink(link).split("SHA256E-s")[1].split("--")[0])
    f = data / link.relative_to(git)
    n += 1
    if not f.exists():
        missing += 1
    elif f.stat().st_size != size:
        bad += 1
print(f"checked {n} missing {missing} size-mismatch {bad}")
sys.exit(0 if n == 25253 and missing == 0 and bad == 0 else 1)
