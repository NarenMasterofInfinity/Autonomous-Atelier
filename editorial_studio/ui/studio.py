"""Read stored canvas versions and queue typed edits; never render in Streamlit."""

from io import BytesIO
from uuid import uuid4

import streamlit as st
from PIL import Image

from editorial_studio.canvas.models import CanvasDocument, RenderMetadata, SceneVersion
from editorial_studio.canvas.repository import SceneRepository
from editorial_studio.contracts import models as m
from editorial_studio.core.jobs import (
    Command,
    CreateProofCommand,
    PatchSceneCommand,
    Queue,
    RollbackSceneCommand,
)


def render_studio(store, project_id, preferred_scene_ids=None):
    repo = SceneRepository(store, project_id)
    versions = store.list("scene_version", SceneVersion, project_id)
    scene_ids = sorted({v.scene_id for v in versions})
    if preferred_scene_ids:
        scene_ids = [scene_id for scene_id in preferred_scene_ids if scene_id in scene_ids] + [
            scene_id for scene_id in scene_ids if scene_id not in preferred_scene_ids
        ]
    if not scene_ids:
        st.info("No rendered canvases in this project yet.")
        if st.button("Queue canvas proof"):
            Queue(store).submit(
                Command(
                    project_id=project_id,
                    payload=CreateProofCommand(scene_id="canvas-" + uuid4().hex[:8]),
                )
            )
            st.success(
                "Queued a local typography proof. The worker will render it without model calls."
            )
        return
    scene_id = st.selectbox("Canvas", scene_ids)
    head = repo.head(scene_id)
    history = repo.history(scene_id)
    version_id = st.selectbox("Version", [v.version for v in reversed(history)], index=0)
    version = repo.version(scene_id, version_id)
    document = CanvasDocument.model_validate_json(
        store.read_blob(project_id, version.document_asset_id)
    )
    png = store.read_blob(project_id, version.png_asset_id)
    st.image(png, width="stretch")
    st.caption(
        f"{document.scene.width_mm:g} × {document.scene.height_mm:g} mm · version {version.version[:12]}"
    )
    with st.expander("Inspect at 1:1 pixels"):
        image = Image.open(BytesIO(png))
        x = st.number_input(
            "Crop left (px)", min_value=0, max_value=max(0, image.width - 1), value=0, step=50
        )
        y = st.number_input(
            "Crop top (px)", min_value=0, max_value=max(0, image.height - 1), value=0, step=50
        )
        st.image(
            image.crop((x, y, min(x + 700, image.width), min(y + 500, image.height))),
            width="content",
        )
    with st.expander("Typography and render measurements"):
        metadata = RenderMetadata.model_validate_json(
            store.read_blob(project_id, version.metadata_asset_id)
        )
        st.json(metadata.model_dump(mode="json"))
    if version.version == head.version:
        layers = {layer.id: layer for layer in document.scene.layers}
        selected = st.selectbox("Layer", list(layers), format_func=lambda i: layers[i].name)
        layer = layers[selected]
        with st.form("edit-layer"):
            opacity = st.slider(
                "Opacity", min_value=0.0, max_value=1.0, value=float(layer.opacity), step=0.05
            )
            dx = st.number_input("Horizontal shift (mm)", value=0.0)
            dy = st.number_input("Vertical shift (mm)", value=0.0)
            rotation = st.number_input("Rotation (degrees)", value=0.0)
            edit = st.form_submit_button("Queue layer edit")
        if edit:
            operations = []
            if opacity != layer.opacity:
                operations.append(m.SetOpacityOp(layer_id=selected, opacity=opacity))
            if dx or dy or rotation:
                operations.append(
                    m.TransformLayerOp(layer_id=selected, dx_mm=dx, dy_mm=dy, rotation_deg=rotation)
                )
            if operations:
                affected = {selected}

                def collect(layer_id):
                    if isinstance(layers[layer_id], m.GroupLayer):
                        for child in layers[layer_id].member_layer_ids:
                            affected.add(child)
                            collect(child)

                collect(selected)
                patch = m.ScenePatch(
                    patch_id=uuid4().hex,
                    target_scene_id=scene_id,
                    parent_version=head.version,
                    operations=operations,
                    modified_layer_ids=sorted(affected),
                    declared_dependencies=sorted(affected),
                )
                Queue(store).submit(
                    Command(project_id=project_id, payload=PatchSceneCommand(patch=patch))
                )
                st.success(
                    "Edit queued. It becomes current after successful validation and rendering."
                )
            else:
                st.info("No layer change to apply.")
    else:
        if st.button("Restore this version"):
            Queue(store).submit(
                Command(
                    project_id=project_id,
                    payload=RollbackSceneCommand(
                        scene_id=scene_id,
                        expected_parent_version=head.version,
                        restored_version=version.version,
                    ),
                )
            )
            st.success("Snapshot restoration queued as a new version.")
    if version.parent_version:
        parent = repo.version(scene_id, version.parent_version)
        prior = CanvasDocument.model_validate_json(
            store.read_blob(project_id, parent.document_asset_id)
        )
        before = {layer.id: layer for layer in prior.scene.layers}
        after = {layer.id: layer for layer in document.scene.layers}
        changed = [i for i in sorted(set(before) | set(after)) if before.get(i) != after.get(i)]
        st.caption(
            "Changed layers: " + (", ".join(changed) or "presentation or version state only")
        )


def render_exports(store, project_id):
    versions = store.list("scene_version", SceneVersion, project_id)
    scene_ids = sorted({v.scene_id for v in versions})
    if not scene_ids:
        st.info("No vector proofs are ready. Queue a canvas proof in Spread Studio.")
        return
    scene_id = st.selectbox("Proof to download", scene_ids)
    version = SceneRepository(store, project_id).head(scene_id)
    st.caption(
        "Continuous spread proof. Use Production PDF and preflight above for twelve-page print exports."
    )
    for label, asset_id, filename, mime in [
        ("Download vector PDF", version.pdf_asset_id, "spread.pdf", "application/pdf"),
        ("Download PNG preview", version.png_asset_id, "spread.png", "image/png"),
        ("Download editable scene", version.document_asset_id, "scene.json", "application/json"),
    ]:
        st.download_button(label, store.read_blob(project_id, asset_id), filename, mime=mime)
