"""Download all 193 emg2pose subjects (NEMAR nm000281) via eegdash, in groups.

Re-running skips files already on disk. Exits non-zero if a group fails, so the
caller's retry loop resumes.
"""
import logging, os, sys
from pathlib import Path
from neuralfetch import download

logging.basicConfig(level=logging.WARNING)
dset = Path(os.path.expanduser("~/neural-compet26/data/neural_compet/Salter2024Emg2pose"))
# argv: first last (inclusive). The downloader is one GIL-bound process (~27 MB/s from the EU),
# so dataprep.sh runs several of these side by side on disjoint subject ranges.
lo, hi = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (1, 193)
subs = [f"{i:02d}" for i in range(lo, hi + 1)]
for k in range(0, len(subs), 40):
    group = subs[k:k + 40]
    # ._download(): .download() would stop at a success marker left by an earlier group
    download.Eegdash(study="nm000281", dset_dir=dset, subject=group)._download()
    print("GROUP DONE", group[0], group[-1], flush=True)
print("DONE", flush=True)
