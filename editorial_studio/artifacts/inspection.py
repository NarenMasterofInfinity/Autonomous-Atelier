"""Three inspection scales use the exact saved render, with pixel coordinates preserved."""

import base64
from io import BytesIO

from PIL import Image
from pydantic import Field

from editorial_studio.contracts.models import BoundsMM, StrictModel
from editorial_studio.llm.contracts import ImageInput
from editorial_studio.photos.pipeline import png
from editorial_studio.telemetry.tools import tool_span


class InspectionSet(StrictModel):
    source_png_asset_id: str
    full_asset_id: str
    thumbnail_asset_id: str
    crop_asset_id: str
    crop_box_px: tuple[int, int, int, int]
    dpi: float = Field(gt=0)


def image_input(store, project, asset_id, detail="high"):
    asset = store.asset(project, asset_id)
    return ImageInput(
        asset_id=asset_id,
        data_base64=base64.b64encode(store.read_blob(project, asset_id)).decode(),
        media_type=asset.media_type,
        detail=detail,
    )


def vision_input(store, context, asset_id, *, max_edge=2048):
    """Bound provider image payloads while preserving native export assets."""
    source = Image.open(BytesIO(store.read_blob(context.project_id, asset_id)))
    if max(source.size) <= max_edge:
        return image_input(store, context.project_id, asset_id)
    with tool_span(store, context, "prepare_vision_preview", asset_id) as tool:
        source.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        preview = store.put_blob(context.project_id, png(source), "image/png")
        tool.output_asset_ids.append(preview.id)
    return image_input(store, context.project_id, preview.id)


def inspect_render(store, context, png_asset_id, *, dpi=144, crop: BoundsMM | None = None):
    with tool_span(store, context, "inspect_render_scales", png_asset_id) as tool:
        image = Image.open(BytesIO(store.read_blob(context.project_id, png_asset_id))).convert(
            "RGB"
        )
        full = image.copy()
        full.thumbnail((1400, 1000))
        thumb = image.copy()
        thumb.thumbnail((420, 297))
        crop = crop or BoundsMM(x_mm=20, y_mm=35, width_mm=100, height_mm=70)
        x = max(0, round(crop.x_mm * dpi / 25.4))
        y = max(0, round(crop.y_mm * dpi / 25.4))
        right = min(image.width, round((crop.x_mm + crop.width_mm) * dpi / 25.4))
        bottom = min(image.height, round((crop.y_mm + crop.height_mm) * dpi / 25.4))
        if right <= x or bottom <= y:
            raise ValueError("inspection crop lies outside saved render")
        assets = [
            store.put_blob(context.project_id, png(item), "image/png").id
            for item in (full, thumb, image.crop((x, y, right, bottom)))
        ]
        tool.output_asset_ids.extend(assets)
        return InspectionSet(
            source_png_asset_id=png_asset_id,
            full_asset_id=assets[0],
            thumbnail_asset_id=assets[1],
            crop_asset_id=assets[2],
            crop_box_px=(x, y, right, bottom),
            dpi=dpi,
        )
