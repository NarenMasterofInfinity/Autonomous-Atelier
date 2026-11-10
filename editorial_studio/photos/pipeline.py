"""Deterministic OpenCV maps, source-aware photo feasibility and frozen ingestion."""

import base64
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import yaml
from PIL import Image, ImageOps

from editorial_studio.content.ledger import ProvenanceLedger, digest
from editorial_studio.contracts.models import BoundsMM, NormalizedRegion
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import CallContext
from editorial_studio.photos.models import (
    IngestedStory,
    PhotoAssessment,
    PlacementAssessment,
    StoryInput,
    UpscaleResult,
)
from editorial_studio.settings import ROOT
from editorial_studio.telemetry.tools import tool_span


def configuration():
    return yaml.safe_load((ROOT / "config/photo_pipeline.yaml").read_text())


def png(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def decode(data: bytes) -> Image.Image:
    with Image.open(BytesIO(data)) as source:
        if source.width * source.height > configuration()["max_image_pixels"]:
            raise ValueError("image exceeds pixel limit")
        return ImageOps.exif_transpose(source).convert("RGB")


def assess_placement(photo: PhotoAssessment, frame: BoundsMM) -> PlacementAssessment:
    cfg = configuration()
    ppi = min(photo.width_px / frame.width_mm, photo.height_px / frame.height_mm) * 25.4
    scale = max(frame.width_mm / photo.width_px, frame.height_mm / photo.height_px)
    fraction = (
        (frame.width_mm / scale) * (frame.height_mm / scale) / (photo.width_px * photo.height_px)
    )
    status = (
        "native"
        if ppi >= cfg["native_ppi"]
        else "inspect_crop"
        if ppi >= cfg["review_ppi"]
        else "stylize_or_reduce"
    )
    return PlacementAssessment(
        source_asset_id=photo.source_asset_id,
        frame=frame,
        effective_ppi=ppi,
        original_ppi=ppi,
        visible_source_fraction=min(1, fraction),
        status=status,
        upscale_eligible=status == "inspect_crop",
        requires_visual_review=status != "native",
    )


def analyze_photo(
    store: Store, context: CallContext, asset_id: str, *, source_uri: str, credit: str
) -> PhotoAssessment:
    record_id = digest(f"{context.project_id}\0{asset_id}\0{source_uri}\0{credit}")
    prior = store.get("photo", record_id, PhotoAssessment)
    if prior:
        for a in (prior.source_asset_id, prior.saliency_asset_id, prior.negative_space_asset_id):
            store.read_blob(context.project_id, a)
        return prior
    cfg = configuration()
    with tool_span(store, context, "analyze_photo", asset_id) as tool:
        original = decode(store.read_blob(context.project_id, asset_id))
        small = original.copy()
        small.thumbnail((cfg["analysis_max_edge"], cfg["analysis_max_edge"]))
        rgb = np.asarray(small)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        _, sal = cv2.saliency.StaticSaliencySpectralResidual_create().computeSaliency(rgb)
        sal = np.nan_to_num(sal, nan=0).clip(0, 1)
        edges = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
        edges = cv2.GaussianBlur(edges, (0, 0), 3)
        edges /= max(float(edges.max()), 1)
        neg = (
            (sal < cfg["negative_space_threshold"]) & (edges < cfg["negative_space_threshold"])
        ).astype("uint8") * 255
        regions = []
        # Fixed cells describe quiet regions without pretending a binary map is a text-flow solver.
        h, w = gray.shape
        for row in range(4):
            for col in range(4):
                if (
                    np.mean(
                        neg[row * h // 4 : (row + 1) * h // 4, col * w // 4 : (col + 1) * w // 4]
                    )
                    > 220
                ):
                    regions.append(NormalizedRegion(x=col / 4, y=row / 4, width=0.25, height=0.25))
        detector = cv2.CascadeClassifier(
            str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        )
        faces = [
            NormalizedRegion(
                x=float(x) / w, y=float(y) / h, width=float(fw) / w, height=float(fh) / h
            )
            for x, y, fw, fh in detector.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)
            )
        ]
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        residual = gray.astype("float32") - cv2.medianBlur(gray, 3).astype("float32")
        noise = float(np.median(np.abs(residual - np.median(residual))) * 1.4826)
        contrast = float((np.percentile(gray, 95) - np.percentile(gray, 5)) / 255)
        findings = []
        if sharp < cfg["sharpness_min"]:
            findings.append("low_sharpness: consider a smaller frame or a graphic treatment")
        if noise > cfg["noise_max"]:
            findings.append("high_noise: inspect a source-resolution crop")
        if contrast < cfg["contrast_min"]:
            findings.append("low_contrast: inspect tonal separation")
        if min(original.size) < 600:
            findings.append("small_source: verify placed effective PPI")
        if not regions:
            findings.append("busy_framing: no large quiet text region detected")
        sal_asset = store.put_blob(
            context.project_id, png(Image.fromarray((sal * 255).astype("uint8"))), "image/png"
        )
        neg_asset = store.put_blob(context.project_id, png(Image.fromarray(neg)), "image/png")
        report = PhotoAssessment(
            id=record_id,
            project_id=context.project_id,
            source_asset_id=asset_id,
            width_px=original.width,
            height_px=original.height,
            sharpness=sharp,
            noise=noise,
            contrast=contrast,
            faces=faces,
            saliency_asset_id=sal_asset.id,
            negative_space_asset_id=neg_asset.id,
            suggested_negative_space=regions,
            findings=findings,
            source_uri=source_uri,
            credit=credit,
        )
        store.put_records(("photo", record_id, context.project_id, report))
        tool.output_asset_ids.extend(
            [sal_asset.id, neg_asset.id, store.json_blob(context.project_id, report).id]
        )
        return report


class Upscaler(Protocol):
    name: str
    model_sha256: str

    def upscale(self, image: np.ndarray) -> np.ndarray: ...


class OpenCVUpscaler:
    name = "opencv_fsrcnn"

    def __init__(self, path: Path, sha256: str, scale=2):
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            raise ValueError("upscaler model hash mismatch")
        self.model_sha256 = sha256
        self.engine = cv2.dnn_superres.DnnSuperResImpl_create()
        self.engine.readModel(str(path))
        self.engine.setModel("fsrcnn", scale)

    def upscale(self, image):
        return self.engine.upsample(image)


def conditional_upscale(
    store: Store,
    context: CallContext,
    photo: PhotoAssessment,
    frame: BoundsMM,
    *,
    inspected: bool,
    backend: Upscaler | None = None,
) -> UpscaleResult:
    placement = assess_placement(photo, frame)
    if not placement.upscale_eligible or not inspected:
        raise ValueError("upscaling requires a 150–249 PPI source and explicit crop inspection")
    cfg = configuration()["upscaler"]
    path = ROOT / cfg["path"]
    if not cfg["sha256"]:
        raise ValueError("upscaler model must be installed and hash-pinned")
    backend = backend or OpenCVUpscaler(path, cfg["sha256"], cfg["scale"])
    with tool_span(store, context, "conditional_upscale", photo.source_asset_id) as tool:
        bgr = cv2.cvtColor(
            np.asarray(decode(store.read_blob(context.project_id, photo.source_asset_id))),
            cv2.COLOR_RGB2BGR,
        )
        result = backend.upscale(bgr)
        if result.shape[:2] != (bgr.shape[0] * cfg["scale"], bgr.shape[1] * cfg["scale"]):
            raise ValueError("upscaler returned wrong dimensions")
        asset = store.put_blob(
            context.project_id,
            png(Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))),
            "image/png",
        )
        tool.output_asset_ids.append(asset.id)
        # Original sampling quality is preserved even when output pixels increase.
        result_record = UpscaleResult(
            source_asset_id=photo.source_asset_id,
            output_asset_id=asset.id,
            backend=backend.name,
            model_sha256=backend.model_sha256,
            scale=cfg["scale"],
            placement=placement,
        )
        record_id = digest(context.project_id + result_record.model_dump_json())
        store.put_records(("upscale", record_id, context.project_id, result_record))
        tool.output_asset_ids.append(store.json_blob(context.project_id, result_record).id)
        return result_record


def ingest_story(store: Store, context: CallContext, story: StoryInput) -> IngestedStory:
    revision = digest(story.model_dump_json())
    story_id = digest(f"{context.project_id}\0{story.id}\0{revision}")
    prior = store.get("story", story_id, IngestedStory)
    if prior:
        return prior
    with tool_span(store, context, "ingest_story") as tool:
        photos = []
        assets = []
        for photo in story.photos:
            raw = base64.b64decode(photo.data_base64, validate=True)
            normalized = png(decode(raw))
            asset = store.put_blob(context.project_id, normalized, "image/png")
            assets.append(asset.id)
            photos.append(
                analyze_photo(
                    store, context, asset.id, source_uri=photo.source_uri, credit=photo.credit
                ).id
            )
        ledger = ProvenanceLedger(store, context.project_id)
        blocks = [
            ledger.source(story.id, field, getattr(story, field), assets)
            for field in ("title", "deck", "body")
        ]
        result = IngestedStory(
            id=story_id,
            project_id=context.project_id,
            source_revision_id=revision,
            title_block_id=blocks[0].id,
            deck_block_id=blocks[1].id,
            body_block_id=blocks[2].id,
            photo_assessment_ids=photos,
            author=story.author,
            run_id=context.run_id,
        )
        store.put_records(("story", story_id, context.project_id, result))
        tool.output_asset_ids.extend(assets + [store.json_blob(context.project_id, result).id])
        return result
