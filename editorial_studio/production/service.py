"""Hard production checks over immutable issue evidence and physical-page export."""

import hashlib
import json
import re
from io import BytesIO

import numpy as np
import pymupdf
import yaml
from PIL import Image
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from editorial_studio.canvas.models import CanvasDocument, RenderMetadata
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.canvas.typography.paths import flatten, region
from editorial_studio.contracts import models as m
from editorial_studio.contracts.operation_registry import path_bounds
from editorial_studio.core.storage import utcnow
from editorial_studio.creative.critics import execution_critic
from editorial_studio.creative.issue import issue_assets
from editorial_studio.creative.issue_models import IssueResult
from editorial_studio.creative.models import CompiledConcept
from editorial_studio.photos.models import IngestedStory, UpscaleResult
from editorial_studio.production.models import (
    ImageSampling,
    PreflightFinding,
    ProductionExport,
    ProductionPreflight,
)
from editorial_studio.production.render import bleed_pdf
from editorial_studio.segmentation.models import SegmentationResult
from editorial_studio.settings import ROOT
from editorial_studio.telemetry.tools import tool_span

PT = 72 / 25.4


def configuration():
    return yaml.safe_load((ROOT / "config/production.yaml").read_text())


def source_hash(issue):
    return hashlib.sha256(issue.model_dump_json().encode()).hexdigest()


def lineage_fingerprint(store, issue):
    mapping = native_sources(store, issue.project_id)
    selected = {}
    for entry in issue.spreads:
        doc = CanvasDocument.model_validate_json(
            store.read_blob(issue.project_id, entry.spread.document_asset_id)
        )
        for layer in doc.scene.layers:
            if not isinstance(layer, m.ImageLayer):
                continue
            chain = []
            key = layer.asset_id
            while key in mapping:
                if key in chain:
                    raise ValueError("cyclic source lineage")
                chain.append(key)
                key = mapping[key]
            selected[layer.asset_id] = chain + [key]
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


def world_matrices(document):
    states = {p.layer_id: p for p in document.presentations}
    parents = {
        member: layer.id
        for layer in document.scene.layers
        if isinstance(layer, m.GroupLayer)
        for member in layer.member_layer_ids
    }
    result = {}

    def get(key):
        if key not in result:
            t = states[key].transform
            local = np.array([[t.a, t.c, t.e_mm], [t.b, t.d, t.f_mm], [0, 0, 1]], dtype=float)
            result[key] = (get(parents[key]) @ local) if key in parents else local
        return result[key]

    for key in states:
        get(key)
    return result


def transformed_rect(bounds, matrix):
    points = (
        np.array(
            [
                [bounds.x_mm, bounds.y_mm, 1],
                [bounds.x_mm + bounds.width_mm, bounds.y_mm, 1],
                [bounds.x_mm, bounds.y_mm + bounds.height_mm, 1],
                [bounds.x_mm + bounds.width_mm, bounds.y_mm + bounds.height_mm, 1],
            ]
        )
        @ matrix.T
    )
    return Polygon(points[[0, 1, 3, 2], :2])


def transformed_shape(shape, matrix):
    return affine_transform(
        shape, [matrix[0, 0], matrix[0, 1], matrix[1, 0], matrix[1, 1], matrix[0, 2], matrix[1, 2]]
    )


def missing_bleed_sides(paint, bleed, tolerance):
    """Conservative normal-continuation check along actual trim intersections.

    Sample at 0.25 mm, including component endpoints. Bounding extents alone
    cannot establish continuation of a disjoint or irregular clipped shape.
    """
    edges = [
        ("LEFT", LineString([(0, 0), (0, 297)]), (-bleed + tolerance, 0)),
        ("RIGHT", LineString([(420, 0), (420, 297)]), (bleed - tolerance, 0)),
        ("TOP", LineString([(0, 0), (420, 0)]), (0, -bleed + tolerance)),
        ("BOTTOM", LineString([(0, 297), (420, 297)]), (0, bleed - tolerance)),
    ]
    expanded = paint.buffer(tolerance)
    failures = []
    for side, line, offset in edges:
        touch = paint.intersection(line)
        if touch.is_empty or touch.length <= tolerance:
            continue
        parts = list(touch.geoms) if hasattr(touch, "geoms") else [touch]
        for part in parts:
            if part.length <= tolerance:
                continue
            samples = max(2, int(part.length / 0.25) + 2)

            def covered(i, part=part, samples=samples, offset=offset):
                point = part.interpolate(i / (samples - 1), normalized=True)
                normal = LineString(
                    [(point.x, point.y), (point.x + offset[0], point.y + offset[1])]
                )
                return expanded.covers(normal)

            if not all(covered(i) for i in range(samples)):
                failures.append(side)
                break
    return failures


def native_sources(store, project):
    """Only full-frame, verified geometry-preserving lineage is supported.

    A cropped derivative needs its own explicit sampling transform; dimensions
    cannot be used to infer restored native resolution after enlargement.
    """

    def size(key):
        with Image.open(BytesIO(store.read_blob(project, key))) as image:
            return image.size

    for row in store.list("upscale", UpscaleResult, project):
        before = size(row.source_asset_id)
        if size(row.output_asset_id) != tuple(v * row.scale for v in before):
            raise ValueError("upscale lineage geometry is unsupported or cropped")
    for row in store.list("segmentation", SegmentationResult, project):
        if size(row.cutout_asset_id) != size(row.source_asset_id):
            raise ValueError("segmentation lineage must preserve the full source frame")
    mapping = {
        r.output_asset_id: r.source_asset_id for r in store.list("upscale", UpscaleResult, project)
    }
    mapping.update(
        {
            r.cutout_asset_id: r.source_asset_id
            for r in store.list("segmentation", SegmentationResult, project)
        }
    )
    return mapping


def sampling_for_image(store, project, layer, presentation, matrix, native_map):
    with Image.open(BytesIO(store.read_blob(project, layer.asset_id))) as image:
        width, height = image.size
    b = presentation.source_bounds
    cover = max(b.width_mm / width, b.height_mm / height)
    stretch = float(np.linalg.svd(matrix[:2, :2] * cover, compute_uv=False).max())
    effective = 25.4 / stretch
    native_id = layer.asset_id
    seen = set()
    while native_id in native_map:
        if native_id in seen:
            raise ValueError("cyclic image source history")
        seen.add(native_id)
        native_id = native_map[native_id]
    with Image.open(BytesIO(store.read_blob(project, native_id))) as original:
        factor = min(original.width / width, original.height / height)
    return ImageSampling(
        scene_id="",
        layer_id=layer.id,
        asset_id=layer.asset_id,
        native_source_asset_id=native_id,
        effective_ppi=effective,
        native_ppi=effective * min(1, factor),
    )


def pdf_fonts(pdf):
    findings = []
    ids = set()
    for page in pdf:
        for font in page.get_fonts(full=True):
            xref, name = font[0], font[3]
            ids.add(xref)
            if not xref or not pdf.extract_font(xref)[3]:
                findings.append(
                    PreflightFinding(
                        code="FONT_NOT_EMBEDDED",
                        severity="error",
                        description="A PDF font has no embedded program.",
                        page_number=page.number + 1,
                    )
                )
            elif not re.match(r"^[A-Z]{6}\+", name):
                findings.append(
                    PreflightFinding(
                        code="FONT_NOT_SUBSET",
                        severity="error",
                        description="A PDF font is not named as an embedded subset.",
                        page_number=page.number + 1,
                    )
                )
    return findings, len(ids)


def check_scene(store, project, entry, cfg):
    spread = entry.spread
    findings = []
    sampling = []
    document = CanvasDocument.model_validate_json(
        store.read_blob(project, spread.document_asset_id)
    )
    metadata = RenderMetadata.model_validate_json(
        store.read_blob(project, spread.metadata_asset_id)
    )

    def add(code, description, layer=None, severity="error"):
        findings.append(
            PreflightFinding(
                code=code,
                severity=severity,
                description=description,
                scene_id=spread.scene_id,
                layer_id=layer,
            )
        )

    if (
        hashlib.sha256(store.read_blob(project, spread.document_asset_id)).hexdigest()
        != metadata.document_hash
    ):
        add("SOURCE_HASH", "Render metadata does not belong to the selected document.")
    if abs(document.scene.width_mm - 420) > 0.001 or abs(document.scene.height_mm - 297) > 0.001:
        add("SPREAD_SIZE", "Source scene is not a 420 × 297 mm continuous spread.")
    try:
        FontRegistry(configuration=document.typography)
    except (ValueError, FileNotFoundError) as error:
        add("FONT_PIN", str(error))
    compiled = store.get("concept", spread.concept_id, CompiledConcept)
    story = store.get("story", spread.story_id, IngestedStory)
    from editorial_studio.canvas.repository import SceneRepository

    version = SceneRepository(store, project).version(spread.scene_id, spread.scene_version)
    execution = execution_critic(store, project, compiled, version, story)
    for finding in execution.findings:
        if finding.severity in (m.Severity.HIGH, m.Severity.CRITICAL):
            add("SOURCE_" + finding.category.upper(), finding.description)
    states = {p.layer_id: p for p in document.presentations}
    layers = {layer.id: layer for layer in document.scene.layers}
    parents = {
        child: layer.id
        for layer in layers.values()
        if isinstance(layer, m.GroupLayer)
        for child in layer.member_layer_ids
    }

    def ancestors(key):
        chain = [key]
        while key in parents:
            key = parents[key]
            chain.append(key)
        return chain

    def visible(key):
        return all(layers[k].visible and layers[k].opacity > 0 for k in ancestors(key))

    matrices = world_matrices(document)
    native_map = native_sources(store, project)
    roles = {t.node_id: t.style_role for t in compiled.proposal.treatments}
    gutter = box(210 - cfg["fold_safe_mm"], 0, 210 + cfg["fold_safe_mm"], 297)
    display_ink = []
    for layout in metadata.text_layouts:
        layer = layers[layout.result.text_layer_id]
        if not visible(layer.id):
            continue
        p = states[layer.id]
        if roles.get(layer.id) == "headline" and not (
            p.path_text or p.shape_flow or p.glyph_transforms or p.outline_text
        ):
            display_ink.append(
                (layer.id, transformed_rect(layout.result.ink_bounds, matrices[layer.id]))
            )
        if roles.get(layer.id) in ("body", "deck"):
            outlines = [
                g
                for g in metadata.glyph_outlines
                if g.text_layer_id == layer.id and g.path is not None
            ]
            if outlines:
                regions = [
                    transformed_rect(path_bounds(g.path), matrices[layer.id]) for g in outlines
                ]
            else:
                regions = [
                    transformed_rect(line.logical_bounds, matrices[layer.id])
                    for line in layout.lines
                ]
            if any(region.intersection(gutter).area > 0.01 for region in regions):
                add("READING_GUTTER", "Reading text enters the 10 mm fold-safe zone.", layer.id)
        elif (
            roles.get(layer.id) == "headline"
            and transformed_rect(layout.result.ink_bounds, matrices[layer.id])
            .intersection(gutter)
            .area
            > 0.01
        ):
            add(
                "DISPLAY_GUTTER",
                "Display type enters the fold-safe zone in the selected visual proof; inspect the printed fold.",
                layer.id,
                "warning",
            )
    for i, (key, ink) in enumerate(display_ink):
        for other, other_ink in display_ink[i + 1 :]:
            if ink.intersection(other_ink).area > 0.25 * min(ink.area, other_ink.area):
                add(
                    "DISPLAY_COLLISION",
                    f"Independent display text {key} and {other} substantially overprint; resolve or use an explicit glyph-level composition.",
                    key,
                )
    bleed = cfg["bleed_mm"]
    tol = cfg["geometry_tolerance_mm"]
    for layer in document.scene.layers:
        if not visible(layer.id) or isinstance(layer, (m.TextLayer, m.GroupLayer, m.MaskLayer)):
            continue
        p = states[layer.id]
        matrix = matrices[layer.id]
        paint = transformed_rect(p.source_bounds, matrix)
        if isinstance(layer, m.VectorLayer):
            shapes = []
            if layer.fill_color:
                shapes.append(region(layer.path))
            if layer.stroke_color and p.stroke_width_mm:
                shapes.extend(
                    LineString(points).buffer(p.stroke_width_mm / 2)
                    for points in flatten(layer.path)
                )
            paint = transformed_shape(unary_union(shapes), matrix)
        for ancestor in ancestors(layer.id):
            state = states[ancestor]
            for clip in state.clips:
                paint = paint.intersection(transformed_shape(region(clip), matrices[ancestor]))
            for key in state.clip_layer_ids:
                paint = paint.intersection(
                    transformed_shape(region(layers[key].path), matrices[key])
                )
        if paint.is_empty or not paint.intersects(box(0, 0, 420, 297)):
            continue
        for side in missing_bleed_sides(paint, bleed, tol):
            add(
                "BLEED_" + side,
                "Artwork lacks 3 mm normal source continuation along part of the actual trim intersection.",
                layer.id,
            )
        if isinstance(layer, m.ImageLayer):
            sample = sampling_for_image(store, project, layer, p, matrix, native_map)
            sample.scene_id = spread.scene_id
            sampling.append(sample)
            if sample.native_ppi + 1e-3 < cfg["minimum_native_ppi"]:
                add(
                    "SOURCE_PPI",
                    f"Photo has {sample.native_ppi:.1f} native source PPI; production requires {cfg['minimum_native_ppi']:g}.",
                    layer.id,
                )
    with pymupdf.open(stream=store.read_blob(project, spread.pdf_asset_id), filetype="pdf") as pdf:
        if (
            len(pdf) != 1
            or abs(pdf[0].rect.width / PT - 420) > 0.001
            or abs(pdf[0].rect.height / PT - 297) > 0.001
        ):
            add("SOURCE_PDF_SIZE", "Selected PDF does not match the source spread dimensions.")
        font_findings, count = pdf_fonts(pdf)
        findings.extend(f.model_copy(update={"scene_id": spread.scene_id}) for f in font_findings)
    return findings, sampling, count, document


def validate_export(store, project, issue, pdf_bytes, cfg):
    findings = []
    by_scene = {entry.spread.scene_id: entry for entry in issue.spreads}
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        if len(pdf) != 12:
            return [
                PreflightFinding(
                    code="PAGE_COUNT",
                    severity="error",
                    description="Production PDF must contain twelve physical pages.",
                )
            ], 0
        font_findings, font_count = pdf_fonts(pdf)
        findings.extend(font_findings)
        for page, physical in zip(pdf, issue.page_map.pages, strict=True):
            trim = page.trimbox
            bleed = page.bleedbox
            media = page.mediabox
            b = cfg["bleed_mm"] * PT
            if abs(trim.width / PT - 210) > 0.001 or abs(trim.height / PT - 297) > 0.001:
                findings.append(
                    PreflightFinding(
                        code="TRIM_BOX",
                        severity="error",
                        description="TrimBox does not measure A4.",
                        page_number=physical.number,
                    )
                )
            if (
                min(trim.x0 - bleed.x0, trim.y0 - bleed.y0, bleed.x1 - trim.x1, bleed.y1 - trim.y1)
                < b - 0.02
            ):
                findings.append(
                    PreflightFinding(
                        code="BLEED_BOX",
                        severity="error",
                        description="BleedBox does not provide 3 mm on every side.",
                        page_number=physical.number,
                    )
                )
            if media != bleed:
                findings.append(
                    PreflightFinding(
                        code="MEDIA_BOX",
                        severity="error",
                        description="Production MediaBox and BleedBox differ.",
                        page_number=physical.number,
                    )
                )
            entry = by_scene[physical.spread_id]
            with pymupdf.open(
                stream=store.read_blob(project, entry.spread.pdf_asset_id), filetype="pdf"
            ) as source:
                x = 0 if physical.side == m.PageSide.LEFT else 210 * PT
                # Normalize both clips to an A4 origin before rasterizing. A
                # crop at 3mm has a different fractional device-pixel phase
                # from a crop at 0mm; resizing those rasters invents drift.
                with pymupdf.open() as normalized:
                    rect = pymupdf.Rect(0, 0, 210 * PT, 297 * PT)
                    expected_page = normalized.new_page(width=rect.width, height=rect.height)
                    expected_page.show_pdf_page(
                        rect, source, 0, clip=pymupdf.Rect(x, 0, x + rect.width, rect.height)
                    )
                    actual_page = normalized.new_page(width=rect.width, height=rect.height)
                    actual_page.show_pdf_page(rect, pdf, page.number, clip=trim)
                    expected = normalized[0].get_pixmap(dpi=cfg["verification_dpi"], alpha=False)
                    actual = normalized[1].get_pixmap(dpi=cfg["verification_dpi"], alpha=False)
                expected_image = Image.open(BytesIO(expected.tobytes("png"))).convert("RGB")
                actual_image = Image.open(BytesIO(actual.tobytes("png"))).convert("RGB")
                if actual_image.size != expected_image.size:
                    actual_image = actual_image.resize(
                        expected_image.size, Image.Resampling.BILINEAR
                    )
                delta = np.abs(
                    np.array(expected_image, dtype=np.int16)
                    - np.array(actual_image, dtype=np.int16)
                )
                if (
                    float(delta.mean()) > cfg["maximum_mean_channel_error"]
                    or float((delta.max(axis=2) <= 10).mean()) < cfg["minimum_near_pixel_fraction"]
                ):
                    findings.append(
                        PreflightFinding(
                            code="CANVAS_PARITY",
                            severity="error",
                            description="Production trim raster differs materially from its selected scene half.",
                            page_number=physical.number,
                        )
                    )
    return findings, font_count


def export_production(store, context, issue_id, *, expected_evidence_fingerprint):
    """Publish a proof or a diagnostic blocked record for trusted scene defects.

    Missing/corrupt evidence, unsupported lineage and renderer failures abort
    without a production record: they cannot establish a trustworthy preflight.
    The worker persists the failure separately and never publishes a PDF.
    """
    issue = store.get("issue", issue_id, IssueResult)
    if issue is None or issue.project_id != context.project_id:
        raise PermissionError("issue outside project")
    if issue.evidence_fingerprint != expected_evidence_fingerprint:
        raise ValueError("stale issue selection; inspect the current issue proof")
    issue_assets(store, issue)
    original_hash = source_hash(issue)
    original_lineage = lineage_fingerprint(store, issue)
    prior = store.get("production_export", context.run_id, ProductionExport)
    if prior:
        if (
            prior.project_id != context.project_id
            or prior.issue_id != issue_id
            or prior.source_issue_hash != original_hash
            or prior.lineage_fingerprint != original_lineage
        ):
            raise ValueError("export ID is bound to different issue evidence")
        for asset in [prior.preflight_asset_id, prior.issue_snapshot_asset_id] + (
            [prior.pdf_asset_id] if prior.pdf_asset_id else []
        ):
            store.read_blob(context.project_id, asset)
        return prior
    cfg = configuration()
    findings = []
    sampling = []
    documents = {}
    fonts = 0
    with tool_span(store, context, "production_preflight") as tool:
        for entry in issue.spreads:
            found, samples, count, document = check_scene(store, context.project_id, entry, cfg)
            findings.extend(found)
            sampling.extend(samples)
            fonts += count
            documents[entry.spread.scene_id] = document
        tool.output_asset_ids.append(store.json_blob(context.project_id, issue).id)
    pdf_asset = None
    if not any(f.severity == "error" for f in findings):
        with tool_span(store, context, "export_physical_pages_with_bleed") as tool:
            pdf = pymupdf.open()
            sources = {}
            try:
                for scene, document in documents.items():
                    sources[scene] = pymupdf.open(
                        stream=bleed_pdf(store, context.project_id, document, cfg["bleed_mm"]),
                        filetype="pdf",
                    )
                for physical in issue.page_map.pages:
                    page = pdf.new_page(
                        width=(210 + 2 * cfg["bleed_mm"]) * PT,
                        height=(297 + 2 * cfg["bleed_mm"]) * PT,
                    )
                    x = 0 if physical.side == m.PageSide.LEFT else 210 * PT
                    page.show_pdf_page(
                        page.rect,
                        sources[physical.spread_id],
                        0,
                        clip=pymupdf.Rect(
                            x,
                            0,
                            x + (210 + 2 * cfg["bleed_mm"]) * PT,
                            (297 + 2 * cfg["bleed_mm"]) * PT,
                        ),
                    )
                    page.set_trimbox(
                        pymupdf.Rect(
                            cfg["bleed_mm"] * PT,
                            cfg["bleed_mm"] * PT,
                            (210 + cfg["bleed_mm"]) * PT,
                            (297 + cfg["bleed_mm"]) * PT,
                        )
                    )
                    page.set_bleedbox(page.mediabox)
                pdf.subset_fonts()
                output = pdf.tobytes(garbage=4, deflate=True)
            finally:
                pdf.close()
                for source in sources.values():
                    source.close()
            export_findings, font_count = validate_export(
                store, context.project_id, issue, output, cfg
            )
            findings.extend(export_findings)
            fonts = font_count
            if not any(f.severity == "error" for f in findings):
                pdf_asset = store.put_blob(context.project_id, output, "application/pdf").id
                tool.output_asset_ids.append(pdf_asset)
    report = ProductionPreflight(
        id=context.run_id,
        project_id=context.project_id,
        issue_id=issue_id,
        issue_evidence_fingerprint=issue.evidence_fingerprint,
        source_issue_hash=original_hash,
        lineage_fingerprint=original_lineage,
        configuration_json=json.dumps(cfg, sort_keys=True),
        findings=findings,
        sampling=sampling,
        checked_scene_versions=[e.spread.scene_version for e in issue.spreads],
        embedded_font_count=fonts,
        passed=not any(f.severity == "error" for f in findings),
    )
    report_asset = store.json_blob(context.project_id, report)
    snapshot = store.json_blob(context.project_id, issue)
    result = ProductionExport(
        id=context.run_id,
        project_id=context.project_id,
        issue_id=issue_id,
        issue_evidence_fingerprint=issue.evidence_fingerprint,
        source_issue_hash=original_hash,
        lineage_fingerprint=original_lineage,
        issue_snapshot_asset_id=snapshot.id,
        preflight_asset_id=report_asset.id,
        pdf_asset_id=pdf_asset,
        page_count=12 if pdf_asset else 0,
        trim_width_mm=210,
        trim_height_mm=297,
        bleed_mm=cfg["bleed_mm"],
        state="proof" if pdf_asset else "blocked",
        created_at=utcnow(),
    )
    # Source issue must still be the exact reviewed input before publishing output.
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT payload FROM records WHERE kind='issue' AND id=? AND project_id=?",
            (issue_id, context.project_id),
        ).fetchone()
        if (
            row is None
            or source_hash(IssueResult.model_validate_json(row[0])) != original_hash
            or lineage_fingerprint(store, issue) != original_lineage
        ):
            raise ValueError("issue changed during production export")
        if db.execute(
            "SELECT 1 FROM records WHERE kind='production_export' AND id=?", (context.run_id,)
        ).fetchone():
            raise ValueError("export was committed concurrently")
        for kind, record in [("production_preflight", report), ("production_export", result)]:
            db.execute(
                "INSERT INTO records VALUES(?,?,?,?,?)",
                (
                    kind,
                    record.id,
                    context.project_id,
                    record.model_dump_json(),
                    utcnow().isoformat(),
                ),
            )
    return result
