"""Build all ten M5 technique proofs and a contact sheet, without model calls."""

from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from editorial_studio.core.jobs import worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import CallContext
from editorial_studio.settings import load_settings
from editorial_studio.spatial.proofs import build_capability_proofs


def main():
    store = Store(load_settings().data_root)
    context = CallContext(
        project_id="m5-proof", run_id="m5-r1-v3", agent_name="CapabilityProof", stage="M5"
    )
    target = Path("data/exports/m5-proof")
    target.mkdir(parents=True, exist_ok=True)
    with worker_lock(store):
        proofs = build_capability_proofs(store, context)
    sheet = Image.new("RGB", (1500, 1520), "#e6e3dc")
    draw = ImageDraw.Draw(sheet)
    book = pymupdf.open()
    for n, p in enumerate(proofs):
        folder = target / p.capability_id
        folder.mkdir(exist_ok=True)
        for name, asset in [
            ("spread.png", p.png_asset_id),
            ("spread.pdf", p.pdf_asset_id),
            ("scene.json", p.document_asset_id),
            ("metadata.json", p.metadata_asset_id),
            ("crop.png", p.crop_asset_id),
        ]:
            (folder / name).write_bytes(store.read_blob(context.project_id, asset))
        thumb = Image.open(BytesIO(store.read_blob(context.project_id, p.thumbnail_asset_id)))
        thumb.thumbnail((480, 315))
        x = n % 3 * 500
        y = n // 3 * 380
        sheet.paste(thumb, (x, y + 25))
        draw.text((x + 10, y + 5), p.capability_id, fill="#22211f")
        with pymupdf.open(
            stream=store.read_blob(context.project_id, p.pdf_asset_id), filetype="pdf"
        ) as pdf:
            book.insert_pdf(pdf)
    sheet.save(target / "contact-sheet.png")
    book.save(target / "techniques.pdf")
    book.close()
    (target / "proofs.json").write_text(
        "[" + ",".join(p.model_dump_json(indent=2) for p in proofs) + "]"
    )
    print(
        "M5: ten rendered technique proofs; technical verification complete, owner/artistic review pending"
    )


if __name__ == "__main__":
    main()
