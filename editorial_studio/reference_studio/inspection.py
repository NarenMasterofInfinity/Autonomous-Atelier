"""Native views centered on actual display ink, reading copy and photo/type overlap."""

from io import BytesIO

import numpy as np
from PIL import Image

from editorial_studio.canvas.models import RenderMetadata
from editorial_studio.contracts import models as m
from editorial_studio.photos.pipeline import png
from editorial_studio.reference_studio.models import NativeViews
from editorial_studio.reference_studio.quality import Probe


def native_views(store, project, spread, document, proposal):
    probe = Probe(store, project, document, dpi=48)
    roles = {t.node_id: t.style_role for t in proposal.treatments}
    headline = [
        layer.id
        for layer in document.scene.layers
        if isinstance(layer, m.TextLayer) and roles.get(layer.id) == "headline"
    ]
    reading = [
        layer.id
        for layer in document.scene.layers
        if isinstance(layer, m.TextLayer) and roles.get(layer.id) == "body"
    ]
    images = {layer.id for layer in document.scene.layers if isinstance(layer, m.ImageLayer)}
    title_masks = {
        key: probe.plate(only={key}, paint={key: "#ffffff"}).max(axis=2) / 255 for key in headline
    }
    display_key = max(title_masks, key=lambda key: title_masks[key].sum())
    display = title_masks[display_key]
    body_key = reading[0]
    body = probe.plate(only={body_key}, paint={body_key: "#ffffff"}).max(axis=2) / 255
    photo = probe.plate(only=images, paint=dict.fromkeys(images, "#ffffff")).max(axis=2) / 255
    junction = np.minimum(np.maximum.reduce(list(title_masks.values())), photo)
    if junction.sum() < 1:
        junction = display
    source = Image.open(BytesIO(store.read_blob(project, spread.png_asset_id)))
    metadata = RenderMetadata.model_validate_json(
        store.read_blob(project, spread.metadata_asset_id)
    )
    assets, boxes = {}, {}
    for name, mask in (("display", display), ("reading", body), ("junction", junction)):
        ys, xs = np.where(mask > 0.1)
        if not len(xs):
            continue
        x0, x1 = xs.min() * 25.4 / 48, (xs.max() + 1) * 25.4 / 48
        y0, y1 = ys.min() * 25.4 / 48, (ys.max() + 1) * 25.4 / 48
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        width, height = (
            min(420 if name == "display" else 195, x1 - x0 + 12),
            min(297 if name == "display" else 105, y1 - y0 + 12),
        )
        left, top = (
            max(0, min(420 - width, cx - width / 2)),
            max(0, min(297 - height, cy - height / 2)),
        )
        box = (
            round(left * metadata.dpi / 25.4),
            round(top * metadata.dpi / 25.4),
            min(source.width, round((left + width) * metadata.dpi / 25.4)),
            min(source.height, round((top + height) * metadata.dpi / 25.4)),
        )
        boxes[name] = box
        assets[name] = store.put_blob(project, png(source.crop(box)), "image/png").id
    return NativeViews(
        source_png_asset_id=spread.png_asset_id, dpi=metadata.dpi, assets=assets, boxes_px=boxes
    )
