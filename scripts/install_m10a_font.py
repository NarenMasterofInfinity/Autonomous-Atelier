"""Fetch the small italic font pinned by the M10A manifest, verifying before publication."""

import hashlib
import json
from urllib.request import urlopen

from editorial_studio.settings import ROOT


def main():
    manifest = json.loads((ROOT / "config/m10a_fonts.json").read_text())
    spec = manifest["fonts"][0]
    target = ROOT / spec["path"]
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == spec["sha256"]:
        print("Pinned Newsreader italic already available")
        return
    with urlopen(manifest["source_url"], timeout=60) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000 or hashlib.sha256(data).hexdigest() != spec["sha256"]:
        raise ValueError("Downloaded italic font does not match the pinned manifest")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".download")
    temporary.write_bytes(data)
    temporary.replace(target)
    print("Installed pinned Newsreader italic")


if __name__ == "__main__":
    main()
