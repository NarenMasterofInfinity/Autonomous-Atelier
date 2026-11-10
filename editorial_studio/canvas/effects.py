"""Deterministic source-resolution raster effects; alpha and random seeds are preserved."""

import math

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from editorial_studio.contracts import models as m


def process(image, presentation, read_image):
    result = image.copy().convert("RGBA")
    b = presentation.source_bounds
    # Cover sampling matches the renderer's source-to-frame mapping.
    px_per_mm = min(result.width / b.width_mm, result.height / b.height_mm)
    for op in presentation.color_adjustments:
        alpha = result.getchannel("A")
        rgb = result.convert("RGB")
        rgb = ImageEnhance.Brightness(rgb).enhance(1 + op.brightness)
        rgb = ImageEnhance.Contrast(rgb).enhance(op.contrast)
        rgb = ImageEnhance.Color(rgb).enhance(op.saturation)
        result = rgb.convert("RGBA")
        result.putalpha(alpha)
    for op in presentation.displacements:
        mapping = (
            read_image(op.map_asset_id).convert("L").resize(result.size, Image.Resampling.BILINEAR)
        )
        displacement = (
            (np.asarray(mapping, dtype=np.float32) / 255 - 0.5) * 2 * op.scale_mm * px_per_mm
        )
        yy, xx = np.indices((result.height, result.width), dtype=np.float32)
        array = cv2.remap(
            np.asarray(result),
            xx + displacement,
            yy + displacement,
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        result = Image.fromarray(array)
    for spec in presentation.filters:
        if isinstance(spec, m.BlurFilter):
            result = result.filter(ImageFilter.GaussianBlur(spec.radius_mm * px_per_mm))
        elif isinstance(spec, m.GrainFilter):
            array = np.asarray(result).astype("float32")
            rng = np.random.default_rng(spec.random_seed)
            array[:, :, :3] += rng.normal(0, spec.strength * 30, array.shape[:2])[:, :, None]
            result = Image.fromarray(array.clip(0, 255).astype("uint8"))
        elif isinstance(spec, m.ShadowFilter):
            color = tuple(int(spec.rgba_hex[i : i + 2], 16) for i in (1, 3, 5, 7))
            alpha = np.asarray(
                result.getchannel("A").filter(ImageFilter.GaussianBlur(spec.radius_mm * px_per_mm))
            )
            shadow = Image.new("RGBA", result.size, color[:3] + (0,))
            shadow.putalpha(
                Image.fromarray((alpha.astype("float32") * color[3] / 255).astype("uint8"))
            )
            shifted = Image.new("RGBA", result.size)
            shifted.alpha_composite(
                shadow, (round(spec.offset.x_mm * px_per_mm), round(spec.offset.y_mm * px_per_mm))
            )
            result = Image.alpha_composite(shifted, result)
        elif isinstance(spec, m.HalftoneFilter):
            spacing = max(2, round(spec.dot_spacing_mm * px_per_mm))
            angle = math.radians(spec.angle_deg)
            yy, xx = np.indices((result.height, result.width), dtype=np.float32)
            u = (xx * math.cos(angle) + yy * math.sin(angle)) % spacing - spacing / 2
            v = (-xx * math.sin(angle) + yy * math.cos(angle)) % spacing - spacing / 2
            darkness = 1 - np.asarray(result.convert("L"), dtype=np.float32) / 255
            radius = np.sqrt(np.minimum(darkness, 1 - darkness) / math.pi) * spacing
            circles = u * u + v * v <= radius * radius
            dots = np.where(darkness <= 0.5, circles, ~circles)
            dots = np.where(darkness == 0, False, np.where(darkness == 1, True, dots))
            gray = np.where(dots, 0, 255).astype("uint8")
            alpha = result.getchannel("A")
            result = Image.fromarray(gray).convert("RGBA")
            result.putalpha(alpha)
    return result
