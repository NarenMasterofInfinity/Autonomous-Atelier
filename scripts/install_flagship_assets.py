"""Fetch the small benchmark inputs and reject bytes that differ from their pins."""

import hashlib
import json
import urllib.request

import yaml

from editorial_studio.settings import ROOT


def assets(cfg):
    font_hashes = {font["path"]: font["sha256"] for font in cfg["fonts"]}
    rows = []
    for source in cfg["asset_sources"]:
        row = dict(source)
        if "/" in row["filename"] or "\\" in row["filename"]:
            raise ValueError("benchmark assets must have plain filenames")
        row.setdefault("sha256", font_hashes.get("data/flagship/" + row["filename"]))
        if not row["sha256"]:
            raise ValueError("every benchmark input requires an explicit SHA-256 pin")
        rows.append(row)
    return rows


def verify_assets(cfg):
    for row in assets(cfg):
        path = ROOT / "data/flagship" / row["filename"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(
                f"Pinned benchmark asset missing or changed: {path.name}; run python -m scripts.install_flagship_assets"
            )


def main():
    cfg = yaml.safe_load((ROOT / "config/flagship.yaml").read_text())
    root = ROOT / "data/flagship"
    root.mkdir(parents=True, exist_ok=True)
    rows = assets(cfg)
    for row in rows:
        path = root / row["filename"]
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]:
            print("Verified", path.name)
            continue
        data = urllib.request.urlopen(row["url"], timeout=60).read()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"Download hash mismatch: {path.name}; existing file preserved")
        temporary = path.with_suffix(path.suffix + ".download")
        temporary.write_bytes(data)
        temporary.replace(path)
        print("Installed", path.name)
    verify_assets(cfg)
    (root / "sources.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
