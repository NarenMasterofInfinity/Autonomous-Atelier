"""Detect asset gaps, create contextual motifs through the gateway, and integrate typed assets."""

import hashlib

from editorial_studio.artifacts.inspection import image_input
from editorial_studio.artifacts.models import ArtifactBuild
from editorial_studio.artifacts.tracing import config, trace_raster
from editorial_studio.canvas.geometry import transform_path
from editorial_studio.canvas.models import AffineMM
from editorial_studio.contracts import models as m
from editorial_studio.llm.contracts import ImageRequest
from editorial_studio.settings import load_settings
from editorial_studio.spatial.assistant import SpatialAssistant
from editorial_studio.spatial.skills import rect
from editorial_studio.telemetry.tools import tool_span


def detect_gaps(requests: list[m.ArtifactRequest], builds: list[ArtifactBuild]):
    complete = {b.request.id for b in builds}
    ids = [r.id for r in requests]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate artifact requirement")
    return [r for r in requests if r.id not in complete]


def build_artifact(
    gateway,
    context,
    request: m.ArtifactRequest,
    reference_asset_ids: list[str],
    *,
    source_raster_asset_id: str | None = None,
) -> ArtifactBuild:
    store = gateway.store
    record_id = hashlib.sha256(
        (
            context.project_id
            + request.model_dump_json()
            + ",".join(reference_asset_ids)
            + (source_raster_asset_id or "")
        ).encode()
    ).hexdigest()
    old = store.get("artifact_build", record_id, ArtifactBuild)
    if old:
        for asset in [old.raster_asset_id, old.output_asset_id, *old.reference_asset_ids]:
            store.read_blob(context.project_id, asset)
        return old
    if request.asset_type not in (m.AssetType.RASTER, m.AssetType.VECTOR):
        raise ValueError("M6 asset planner supports explicit raster/vector generation requests")
    call_id = None
    if source_raster_asset_id is None:
        settings = load_settings()
        cfg = config()
        prompt = cfg["prompt"].format(
            role=request.visual_role,
            specification=request.generation_spec,
            palette=", ".join(request.color_constraints),
            integration=request.integration_method,
        )
        call = gateway.invoke(
            context,
            ImageRequest(
                model=settings.image_model,
                prompt=prompt,
                quality=settings.image_quality,
                size=settings.image_size,
                images=[image_input(store, context.project_id, a) for a in reference_asset_ids],
            ),
        )
        if len(call.generated_artifact_ids) != 1:
            raise ValueError("artifact generation did not return exactly one raster")
        source_raster_asset_id = call.generated_artifact_ids[0]
        call_id = call.call_id
    else:
        store.read_blob(context.project_id, source_raster_asset_id)
    with tool_span(store, context, "classify_artifact", source_raster_asset_id) as tool:
        from editorial_studio.photos.pipeline import decode

        image = decode(store.read_blob(context.project_id, source_raster_asset_id))
        if isinstance(request.output, m.RasterOutputSpec) and image.size != (
            request.output.width_px,
            request.output.height_px,
        ):
            raise ValueError("generated raster dimensions differ from requested output")
        traced = (
            trace_raster(store, context, source_raster_asset_id)
            if request.asset_type == m.AssetType.VECTOR
            else None
        )
        result = ArtifactBuild(
            id=record_id,
            project_id=context.project_id,
            request=request,
            reference_asset_ids=reference_asset_ids,
            provider_call_id=call_id,
            raster_asset_id=source_raster_asset_id,
            output_asset_id=traced.svg_asset_id if traced else source_raster_asset_id,
            traced=traced,
            classification="editable_vector_motif" if traced else "raster_motif",
        )
        store.put_records(("artifact_build", record_id, context.project_id, result))
        tool.output_asset_ids.extend(
            [result.output_asset_id, store.json_blob(context.project_id, result).id]
        )
        return result


def integrate_artifact(store, context, executor, build: ArtifactBuild, scene_id: str):
    if (
        build.project_id != context.project_id
        or executor.repository.project_id != context.project_id
    ):
        raise PermissionError("artifact project mismatch")
    document = executor.repository.load(scene_id)
    request = build.request
    layers = {layer.id: layer for layer in document.scene.layers}
    if request.target_layer_dependency_id not in layers:
        raise ValueError("artifact target dependency missing")
    r = request.target_region
    b = m.BoundsMM(
        x_mm=r.x * document.scene.width_mm,
        y_mm=r.y * document.scene.height_mm,
        width_mm=r.width * document.scene.width_mm,
        height_mm=r.height * document.scene.height_mm,
    )
    layer_id = "artifact-" + build.id[:16]
    if build.traced:
        p = transform_path(
            build.traced.path,
            AffineMM(
                a=b.width_mm / build.traced.source_width_px,
                d=b.height_mm / build.traced.source_height_px,
                e_mm=b.x_mm,
                f_mm=b.y_mm,
            ),
        )
        operations = [
            m.AddPathOp(
                layer_id=layer_id,
                path=p,
                fill_color=request.color_constraints[0] if request.color_constraints else "#22211f",
            )
        ]
    else:
        operations = [m.AddImageOp(layer_id=layer_id, asset_id=build.output_asset_id, bounds=b)]
    target = layers[request.target_layer_dependency_id]
    if request.integration_method == "clipping":
        operations.append(
            m.ClipToPathOp(
                target_layer_id=layer_id,
                path=target.path
                if isinstance(target, m.VectorLayer)
                else rect(
                    target.bounds.x_mm,
                    target.bounds.y_mm,
                    target.bounds.width_mm,
                    target.bounds.height_mm,
                ),
            )
        )
    elif request.integration_method == "masking":
        if not isinstance(target, m.MaskLayer):
            raise ValueError("masking integration requires a mask dependency")
        operations.append(
            m.ApplyMaskOp(target_layer_id=layer_id, mask_asset_id=target.mask_asset_id)
        )
    elif request.integration_method == "blending":
        operations.append(m.SetBlendModeOp(layer_id=layer_id, blend_mode="multiply"))
    operations.append(m.SetZIndexOp(layer_id=layer_id, z_index=target.z_index + 1))
    if layer_id in layers:
        if build.placed_scene_id == scene_id and build.placed_version:
            version = executor.repository.version(scene_id, build.placed_version)
        else:
            matches = []
            for candidate in executor.repository.history(scene_id):
                patch = (
                    store.get("scene_patch", candidate.patch_id, m.ScenePatch)
                    if candidate.patch_id
                    else None
                )
                if (
                    candidate.run_id == context.run_id
                    and patch is not None
                    and patch.operations == operations
                ):
                    matches.append(candidate)
            if len(matches) != 1:
                raise ValueError(
                    "artifact layer exists without matching committed integration evidence"
                )
            version = matches[0]
        for asset in (
            version.png_asset_id,
            version.pdf_asset_id,
            version.document_asset_id,
            version.metadata_asset_id,
        ):
            store.read_blob(context.project_id, asset)
    else:
        version = SpatialAssistant(executor).apply(operations, scene_id, context)
    build.placed_scene_id = scene_id
    build.placed_version = version.version
    build.status = "placed_awaiting_visual_review"
    store.put_records(("artifact_build", build.id, context.project_id, build))
    return version
