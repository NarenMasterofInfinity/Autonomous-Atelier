"""Reproduce the pinned NASA inputs and their conservative downsample-only derivatives."""

import hashlib
import json
import urllib.request

from PIL import Image

from editorial_studio.settings import ROOT


def main():
    rows = json.loads((ROOT / "config/issue_sources.json").read_text())
    root = ROOT / "data/issue-sources"
    root.mkdir(parents=True, exist_ok=True)
    for row in rows:
        source = root / row["original_filename"]
        if not source.exists():
            data = urllib.request.urlopen(row["url"], timeout=60).read()
            if hashlib.sha256(data).hexdigest() != row["original_sha256"]:
                raise ValueError("NASA original hash mismatch")
            source.write_bytes(data)
        if hashlib.sha256(source.read_bytes()).hexdigest() != row["original_sha256"]:
            raise ValueError("NASA original changed")
        prepared = root / row["filename"]
        if not prepared.exists():
            with Image.open(source) as image:
                image = image.convert("RGB")
                image.thumbnail((6000, 4000), Image.Resampling.LANCZOS)
                if row.get("crop_box"):
                    image = image.crop(tuple(row["crop_box"]))
                image.save(prepared)
        if hashlib.sha256(prepared.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Prepared NASA image hash mismatch")
        print("Verified", row["id"], row["size"])


if __name__ == "__main__":
    main()
