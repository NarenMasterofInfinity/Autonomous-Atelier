"""Prompted MobileSAM with OpenCV trimap refinement; no implicit network downloads."""

import hashlib
from typing import Protocol

import cv2
import numpy as np
import yaml
from PIL import Image

from editorial_studio.content.ledger import digest
from editorial_studio.photos.pipeline import decode, png
from editorial_studio.segmentation.models import EdgeQuality, SegmentationResult, SegmentPrompt
from editorial_studio.settings import ROOT
from editorial_studio.telemetry.tools import tool_span


class Segmenter(Protocol):
    name: str
    model_sha256: str

    def predict(self, rgb: np.ndarray, prompt: SegmentPrompt) -> tuple[np.ndarray, float]: ...


def configuration():
    return yaml.safe_load((ROOT / "config/segmentation.yaml").read_text())


class MobileSAMBackend:
    name = "mobilesam-vit_t"

    def __init__(self):
        import torch
        from mobile_sam import SamPredictor, sam_model_registry

        cfg = configuration()
        path = ROOT / cfg["checkpoint"]
        self.model_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.model_sha256 != cfg["sha256"]:
            raise ValueError("MobileSAM checkpoint hash mismatch")
        torch.set_num_threads(cfg["threads"])
        model = (
            sam_model_registry[cfg["model_type"]](checkpoint=str(path))
            .to(device=cfg["device"])
            .eval()
        )
        self.predictor = SamPredictor(model)

    def predict(self, rgb, prompt):
        import torch

        h, w = rgb.shape[:2]
        points = (
            np.array([[p.x * (w - 1), p.y * (h - 1)] for p in prompt.points], dtype=np.float32)
            if prompt.points
            else None
        )
        labels = np.array(prompt.labels, dtype=np.int32) if prompt.points else None
        b = prompt.box
        box = (
            np.array(
                [b.x * w, b.y * h, (b.x + b.width) * w, (b.y + b.height) * h], dtype=np.float32
            )
            if b
            else None
        )
        with torch.inference_mode():
            self.predictor.set_image(rgb)
            masks, scores, _ = self.predictor.predict(
                point_coords=points, point_labels=labels, box=box, multimask_output=True
            )
        index = int(np.argmax(scores))
        return masks[index].astype("uint8") * 255, float(np.clip(scores[index], 0, 1))


def refine_alpha(rgb: np.ndarray, mask: np.ndarray, radius=2) -> np.ndarray:
    if mask.shape != rgb.shape[:2] or mask.dtype != np.uint8:
        raise ValueError("mask must be uint8 with source dimensions")
    binary = (mask >= 128).astype("uint8") * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    # Preserve small detail; refine only the unknown trimap band, keeping definite interior/exterior exact.
    inside = cv2.erode(binary, kernel)
    outside = cv2.dilate(binary, kernel)
    initial = cv2.GaussianBlur(binary, (0, 0), max(radius / 2, 0.5)).astype("float32") / 255
    guide = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype("float32") / 255
    alpha = cv2.ximgproc.guidedFilter(guide, initial, max(radius * 2, 1), 1e-3).clip(0, 1)
    alpha[inside == 255] = 1
    alpha[outside == 0] = 0
    return (alpha * 255).round().astype("uint8")


def fill_enclosed_holes(mask: np.ndarray) -> np.ndarray:
    """Opt-in solid-subject policy; preserve exterior background and concavities.

    Padding supplies an exterior seed even when the subject meets every source
    edge. This is unsuitable for subjects with intentional holes, so it is part
    of the saved prompt rather than an unconditional segmentation cleanup.
    """
    binary = (mask >= 128).astype("uint8") * 255
    padded = np.pad(binary, 1)
    exterior = padded.copy()
    cv2.floodFill(exterior, None, (0, 0), 255)
    holes = cv2.bitwise_not(exterior)[1:-1, 1:-1]
    return cv2.bitwise_or(binary, holes)


def edge_quality(alpha: np.ndarray, reference: np.ndarray | None = None) -> EdgeQuality:
    cfg = configuration()
    binary = (alpha >= 128).astype("uint8")
    fraction = float(binary.mean())
    components = int(cv2.connectedComponents(binary)[0] - 1)
    soft = float(np.mean((alpha > 0) & (alpha < 255)))
    gradient = cv2.magnitude(
        cv2.Sobel(alpha.astype("float32") / 255, cv2.CV_32F, 1, 0, ksize=1),
        cv2.Sobel(alpha.astype("float32") / 255, cv2.CV_32F, 0, 1, ksize=1),
    )
    edge = gradient[gradient > 0]
    mean = float(edge.mean()) if edge.size else 0
    findings = []
    if not cfg["minimum_foreground_fraction"] <= fraction <= cfg["maximum_foreground_fraction"]:
        findings.append("foreground area is empty or implausibly large")
    if mean > cfg["maximum_edge_gradient"]:
        findings.append("edge transition is abrupt")
    iou = None
    if reference is not None:
        if reference.shape != alpha.shape:
            raise ValueError("reference mask dimensions differ")
        truth = reference >= 128
        intersection = np.logical_and(binary, truth).sum()
        union = np.logical_or(binary, truth).sum()
        iou = float(intersection / union) if union else 1.0
        if iou < 0.9:
            findings.append("reference silhouette agreement below 0.90")
    return EdgeQuality(
        foreground_fraction=fraction,
        soft_edge_fraction=soft,
        edge_gradient=min(mean, 1),
        components=components,
        passed=not findings,
        findings=findings,
        reference_iou=iou,
    )


def segment(
    store, context, prompt: SegmentPrompt, backend: Segmenter | None = None
) -> SegmentationResult:
    cfg = configuration()
    backend = backend or MobileSAMBackend()
    record_id = digest(
        context.project_id
        + prompt.model_dump_json()
        + backend.name
        + backend.model_sha256
        + str(cfg["refinement_radius"])
    )
    old = store.get("segmentation", record_id, SegmentationResult)
    if old:
        for a in (old.source_asset_id, old.mask_asset_id, old.alpha_asset_id, old.cutout_asset_id):
            store.read_blob(context.project_id, a)
        return old
    with tool_span(store, context, "segment_subject", prompt.source_asset_id) as tool:
        rgb = np.asarray(decode(store.read_blob(context.project_id, prompt.source_asset_id)))
        mask, score = backend.predict(rgb, prompt)
        if prompt.fill_enclosed_holes:
            mask = fill_enclosed_holes(mask)
        if prompt.keep_largest_component:
            count, labels, stats, _ = cv2.connectedComponentsWithStats(
                (mask >= 128).astype("uint8")
            )
            if count > 1:
                largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
                mask = (labels == largest).astype("uint8") * 255
        alpha = refine_alpha(rgb, mask, cfg["refinement_radius"])
        quality = edge_quality(alpha)
        raw = store.put_blob(context.project_id, png(Image.fromarray(mask)), "image/png")
        matte = store.put_blob(context.project_id, png(Image.fromarray(alpha)), "image/png")
        cutout = Image.fromarray(rgb).convert("RGBA")
        cutout.putalpha(Image.fromarray(alpha))
        cut = store.put_blob(context.project_id, png(cutout), "image/png")
        result = SegmentationResult(
            id=record_id,
            project_id=context.project_id,
            source_asset_id=prompt.source_asset_id,
            prompt=prompt,
            backend=backend.name,
            model_sha256=backend.model_sha256,
            predicted_iou=score,
            mask_asset_id=raw.id,
            alpha_asset_id=matte.id,
            cutout_asset_id=cut.id,
            quality=quality,
        )
        store.put_records(("segmentation", record_id, context.project_id, result))
        tool.output_asset_ids.extend(
            [raw.id, matte.id, cut.id, store.json_blob(context.project_id, result).id]
        )
        return result
