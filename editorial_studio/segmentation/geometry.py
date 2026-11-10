"""Convert isolated alpha/mask contours into scene geometry using the renderer's cover crop."""

from io import BytesIO

import cv2
import numpy as np
from PIL import Image
from shapely import make_valid
from shapely.geometry import Polygon

from editorial_studio.contracts import models as m


def silhouette_path(store, project, asset_id, bounds, *, is_mask=False):
    image = Image.open(BytesIO(store.read_blob(project, asset_id)))
    if is_mask:
        channel = image.convert("L")
    else:
        image = image.convert("RGBA")
        channel = image.getchannel("A")
        if channel.getextrema() == (255, 255):
            raise ValueError("flow-around subject has no isolated alpha silhouette")
    binary = (np.asarray(channel) >= 128).astype("uint8") * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    scale = max(bounds.width_mm / image.width, bounds.height_mm / image.height)
    ox = bounds.x_mm + (bounds.width_mm - image.width * scale) / 2
    oy = bounds.y_mm + (bounds.height_mm - image.height * scale) / 2
    commands = []
    for contour in contours:
        points = cv2.approxPolyDP(contour, 1.0, True)[:, 0, :]
        if len(points) < 3 or abs(cv2.contourArea(points)) <= 1:
            continue
        # Pixel-connected alpha contours may touch themselves at a one-pixel
        # neck. Normalize raster-derived regions only; authored paths retain
        # their strict topology checks in the executor.
        shape = make_valid(Polygon(points))

        def polygons(value):
            if value.geom_type == "Polygon":
                return [value]
            return [p for child in getattr(value, "geoms", []) for p in polygons(child)]

        pieces = polygons(shape)
        for piece in pieces:
            if piece.geom_type != "Polygon" or piece.area <= 1:
                continue
            mapped = [
                m.PointMM(x_mm=ox + float(x) * scale, y_mm=oy + float(y) * scale)
                for x, y in list(piece.exterior.coords)[:-1]
            ]
            commands.extend(
                [m.MoveTo(p=mapped[0]), *[m.LineTo(p=point) for point in mapped[1:]], m.ClosePath()]
            )
    if not commands:
        raise ValueError("subject has no usable contour")
    return m.PathGeometry(commands=commands)
