"""Ten built-in techniques expand into typed registry operations, never executable model code."""

import numpy as np
from PIL import Image, ImageDraw

from editorial_studio.contracts import models as m
from editorial_studio.photos.pipeline import png
from editorial_studio.spatial.assistant import SpatialAssistant


def rect(x, y, w, h):
    return m.PathGeometry(
        commands=[
            m.MoveTo(p=m.PointMM(x_mm=x, y_mm=y)),
            m.LineTo(p=m.PointMM(x_mm=x + w, y_mm=y)),
            m.LineTo(p=m.PointMM(x_mm=x + w, y_mm=y + h)),
            m.LineTo(p=m.PointMM(x_mm=x, y_mm=y + h)),
            m.ClosePath(),
        ]
    )


def fixture_assets(store, project):
    yy, xx = np.indices((600, 800))
    array = (
        np.stack(
            [
                (xx / 800 * 180 + 40),
                ((np.sin(xx / 60) + 1) * 45 + yy / 600 * 70 + 40),
                (yy / 600 * 120 + 80),
            ],
            axis=2,
        )
        .clip(0, 255)
        .astype("uint8")
    )
    photo = store.put_blob(project, png(Image.fromarray(array)), "image/png")
    mask = Image.new("L", (800, 600))
    ImageDraw.Draw(mask).ellipse((180, 25, 620, 580), fill=255)
    matte = store.put_blob(project, png(mask), "image/png")
    return photo.id, matte.id


BODY = "An image can hold a story without filling every space. A line moves around its subject, leaving a deliberate pause. The reader follows that movement, then returns to the detail. Café light, an office doorway, and the ordinary texture of a wall offer different ways to begin. "


def technique_operations(capability, photo, mask):
    b = m.BoundsMM(x_mm=30, y_mm=60, width_mm=160, height_mm=180)

    def image(name="photo"):
        return m.AddImageOp(layer_id=name, asset_id=photo, bounds=b)

    def label(text):
        return m.AddTextOp(
            layer_id="title",
            text_content=text,
            style_name="headline",
            bounds=m.BoundsMM(x_mm=220, y_mm=65, width_mm=175, height_mm=70),
        )

    path = rect(30, 60, 160, 180)

    def gradient(target):
        return m.GradientMaskOp(
            target_layer_id=target,
            gradient_type="linear",
            start=m.PointMM(x_mm=30, y_mm=60),
            end=m.PointMM(x_mm=190, y_mm=240),
            stops=[m.GradientStop(offset=0, opacity=1), m.GradientStop(offset=1, opacity=0.05)],
        )

    if capability == "CAP_01":
        exclusion = rect(88, 105, 55, 65)
        return [
            m.AddPathOp(layer_id="boundary", path=path, fill_color="#e9e2d5"),
            m.FlowTextIntoShapeOp(
                layer_id="flow",
                text_content=BODY * 6,
                style_name="body",
                boundary=path,
                exclusion_paths=[exclusion],
            ),
            m.SetClipStackOp(target_layer_id="flow", clip_path_layer_ids=["boundary"]),
            label("Space for\na silhouette"),
        ]
    if capability == "CAP_02":
        return [
            image(),
            m.AddTextOp(
                layer_id="title",
                text_content="BEYOND\nTHE FRAME",
                style_name="headline",
                bounds=m.BoundsMM(x_mm=35, y_mm=110, width_mm=350, height_mm=80),
            ),
            image("subject"),
            m.ApplyMaskOp(target_layer_id="subject", mask_asset_id=mask),
            m.SetZIndexOp(layer_id="title", z_index=1),
            m.SetZIndexOp(layer_id="subject", z_index=2),
            m.CreateGroupOp(group_layer_id="depth", member_layer_ids=["photo", "title", "subject"]),
        ]
    if capability == "CAP_03":
        return [
            label("Office / café"),
            m.SetGlyphTransformsOp(
                layer_id="title",
                transforms=[
                    m.GlyphTransform(glyph_index=0, rotation_deg=-8, scale_y=1.25),
                    m.GlyphTransform(glyph_index=2, dy_mm=-2),
                ],
            ),
            m.AddPathOp(layer_id="mark", path=rect(35, 80, 120, 120), fill_color="#9e4d32"),
            m.EditPathOp(layer_id="mark", path=rect(35, 80, 110, 135)),
        ]
    if capability == "CAP_04":
        triangle = m.PathGeometry(
            commands=[
                m.MoveTo(p=m.PointMM(x_mm=30, y_mm=60)),
                m.LineTo(p=m.PointMM(x_mm=190, y_mm=60)),
                m.LineTo(p=m.PointMM(x_mm=65, y_mm=240)),
                m.ClosePath(),
            ]
        )
        return [
            image(),
            m.AddPathOp(layer_id="edge", path=triangle, stroke_color="#9e4d32"),
            m.ClipToPathOp(target_layer_id="photo", path=triangle),
            m.TransformLayerOp(layer_id="photo", rotation_deg=-3, dx_mm=8),
            label("A fragment\nheld in view"),
        ]
    if capability == "CAP_05":
        curve = m.PathGeometry(
            commands=[
                m.MoveTo(p=m.PointMM(x_mm=30, y_mm=115)),
                m.CubicTo(
                    control1=m.PointMM(x_mm=120, y_mm=30),
                    control2=m.PointMM(x_mm=265, y_mm=180),
                    p=m.PointMM(x_mm=390, y_mm=100),
                ),
            ]
        )
        return [
            m.AddPathOp(layer_id="curve", path=curve, stroke_color="#b6aa99", stroke_width_mm=0.3),
            m.TextOnPathOp(
                layer_id="title",
                text_content="Office, café — a line of thought",
                style_name="headline",
                path=curve,
            ),
            m.FlowTextIntoShapeOp(
                layer_id="flow",
                text_content=BODY,
                style_name="body",
                boundary=rect(220, 170, 170, 80),
            ),
        ]
    if capability == "CAP_06":
        bounds = m.BoundsMM(x_mm=30, y_mm=90, width_mm=360, height_mm=100)
        source = m.TextLayer(
            id="title",
            name="Source type",
            semantic_role="headline",
            z_index=0,
            text_content="FORM / LIGHT",
            style_name="headline",
            bounds=bounds,
        )
        outlines = SpatialAssistant.text_mask(source)
        return [
            m.AddTextOp(
                layer_id="title",
                text_content=source.text_content,
                style_name="headline",
                bounds=bounds,
            ),
            m.SetOpacityOp(layer_id="title", opacity=0),
            m.AddPathOp(layer_id="glyph-mask", path=outlines),
            m.SetOpacityOp(layer_id="glyph-mask", opacity=0),
            m.AddImageOp(layer_id="photo", asset_id=photo, bounds=bounds),
            m.SetClipStackOp(target_layer_id="photo", clip_path_layer_ids=["glyph-mask"]),
            m.ClipToPathOp(target_layer_id="photo", path=outlines),
            m.CreateGroupOp(
                group_layer_id="filled-type", member_layer_ids=["title", "glyph-mask", "photo"]
            ),
        ]
    if capability == "CAP_07":
        return [
            image(),
            m.AddPathOp(layer_id="color", path=rect(95, 100, 140, 140), fill_color="#9e4d32"),
            m.SetBlendModeOp(layer_id="color", blend_mode="multiply"),
            m.CreateGroupOp(group_layer_id="blend", member_layer_ids=["photo", "color"]),
            m.SetOpacityOp(layer_id="blend", opacity=0.8),
            label("Color as\na second voice"),
        ]
    if capability == "CAP_08":
        return [
            image(),
            gradient("photo"),
            m.AddPathOp(layer_id="clip", path=path),
            m.SetOpacityOp(layer_id="clip", opacity=0),
            m.SetClipStackOp(target_layer_id="photo", clip_path_layer_ids=["clip"]),
            m.SetBlendModeOp(layer_id="photo", blend_mode="multiply"),
            label("A gradual\ntransition"),
        ]
    if capability == "CAP_09":
        return [
            image(),
            m.AddPathOp(layer_id="fragment", path=rect(105, 125, 140, 110), fill_color="#9e4d32"),
            m.ClipToPathOp(target_layer_id="photo", path=path),
            gradient("fragment"),
            m.SetBlendModeOp(layer_id="fragment", blend_mode="multiply"),
            label("Collected\nimpressions"),
        ]
    if capability == "CAP_10":
        return [
            image(),
            m.ColorAdjustOp(layer_id="photo", brightness=0.05, contrast=1.2, saturation=0.45),
            gradient("photo"),
            m.ApplyFilterOp(layer_id="photo", filter=m.GrainFilter(strength=0.25, random_seed=7)),
            label("The tone\nof a place"),
        ]
    raise ValueError("unknown built-in capability")
