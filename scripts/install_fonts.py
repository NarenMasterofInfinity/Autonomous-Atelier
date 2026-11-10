"""Install only the exact pinned DejaVu font files from the workstation's system fonts."""

import hashlib
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
config = yaml.safe_load((ROOT / "config/fonts.yaml").read_text())
for spec in config["fonts"]:
    target = ROOT / spec["path"]
    source = Path("/usr/share/fonts/truetype/dejavu") / target.name
    if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != spec["sha256"]:
        raise SystemExit(
            f"Pinned source unavailable: {source}; supply the exact hash from config/fonts.yaml"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    print("Installed", target.name)
