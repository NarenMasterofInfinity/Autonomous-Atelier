"""Hash-pinned Potrace tracing with Bézier conversion and independent raster comparison."""

import hashlib
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

import cairo
import cv2
import numpy as np
import yaml
from fontTools.svgLib.path import SVGPath
from PIL import Image

from editorial_studio.artifacts.models import TracedVector
from editorial_studio.canvas.geometry import cairo_path
from editorial_studio.canvas.typography.outlines import GeometryPen
from editorial_studio.contracts import models as m
from editorial_studio.photos.pipeline import decode
from editorial_studio.settings import ROOT
from editorial_studio.telemetry.tools import tool_span


def config():
    return yaml.safe_load((ROOT / "config/artifacts.yaml").read_text())


def trace_raster(store, context, asset_id) -> TracedVector:
    cfg = config()
    binary_path = ROOT / cfg["potrace_path"]
    if hashlib.sha256(binary_path.read_bytes()).hexdigest() != cfg["potrace_sha256"]:
        raise ValueError("Potrace binary hash mismatch")
    with tool_span(store, context, "potrace_vectorize", asset_id) as tool:
        source = decode(store.read_blob(context.project_id, asset_id))
        gray = np.asarray(source.convert("L"))
        foreground = (gray < cfg["threshold"]).astype("uint8")
        count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground)
        for label in range(1, count):
            if stats[label, cv2.CC_STAT_AREA] < cfg["minimum_component_pixels"]:
                foreground[labels == label] = 0
        if not foreground.any() or foreground.all():
            raise ValueError("vector motif must have distinct foreground and background")
        with tempfile.TemporaryDirectory(prefix="editorial-trace-") as temp:
            root = Path(temp)
            pbm = root / "source.pbm"
            svg = root / "trace.svg"
            Image.fromarray(np.where(foreground, 0, 255).astype("uint8")).convert("1").save(pbm)
            subprocess.run(
                [
                    str(binary_path),
                    "--svg",
                    "--flat",
                    "--turdsize",
                    "0",
                    "--alphamax",
                    "1",
                    "--opttolerance",
                    "0.2",
                    "--output",
                    str(svg),
                    str(pbm),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            raw = svg.read_bytes()
        # Potrace's SVG viewBox is in source pixels. GeometryPen reverses Y for fonts;
        # negate its Y through a transform so SVG top-down coordinates are retained.
        from fontTools.pens.transformPen import TransformPen

        group = ET.fromstring(raw).find("{http://www.w3.org/2000/svg}g")
        match = (
            re.fullmatch(
                r"translate\(0\.0+,([0-9.]+)\) scale\(0\.100000,-0\.100000\)",
                group.attrib.get("transform", ""),
            )
            if group is not None
            else None
        )
        if not match or abs(float(match.group(1)) - source.height) > 1e-6:
            raise ValueError("unexpected transform from pinned Potrace SVG backend")
        pen = GeometryPen(None, 1)
        # fontTools applies transforms on paths but does not inherit this group's transform.
        SVGPath.fromstring(raw, transform=(0.1, 0, 0, -0.1, 0, source.height)).draw(
            TransformPen(pen, (1, 0, 0, -1, 0, 0))
        )
        path = m.PathGeometry(commands=pen.commands)
        # Render the traced paths independently back onto the source pixel grid.
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, source.width, source.height)
        cr = cairo.Context(surface)
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.set_source_rgb(0, 0, 0)
        cr.scale(25.4 / 72, 25.4 / 72)
        cairo_path(cr, path)
        cr.fill()
        out = BytesIO()
        surface.write_to_png(out)
        raster = np.asarray(Image.open(BytesIO(out.getvalue())).convert("L")) < 128
        union = np.logical_or(raster, foreground).sum()
        iou = float(np.logical_and(raster, foreground).sum() / union)
        if iou < 0.85:
            raise ValueError(f"tracing fidelity below technical threshold: {iou:.3f}")
        svg_asset = store.put_blob(context.project_id, raw, "image/svg+xml")
        version = subprocess.run(
            [str(binary_path), "--version"], capture_output=True, text=True, check=True, timeout=5
        ).stdout.splitlines()[0]
        result = TracedVector(
            source_asset_id=asset_id,
            svg_asset_id=svg_asset.id,
            path=path,
            source_width_px=source.width,
            source_height_px=source.height,
            potrace_version=version,
            threshold=cfg["threshold"],
            source_foreground_fraction=float(foreground.mean()),
            reconstructed_iou=iou,
        )
        tool.output_asset_ids.extend([svg_asset.id, store.json_blob(context.project_id, result).id])
        return result
