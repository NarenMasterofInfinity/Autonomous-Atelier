"""Resolve authored anchor intents to typed operations; freeform geometry stays authored."""

from editorial_studio.contracts import models as m
from editorial_studio.segmentation.geometry import silhouette_path
from editorial_studio.spatial.skills import rect


def anchor_operations(layers, intent, store, project, *, width_mm=420, height_mm=297):
    current = {key: layer.model_copy(deep=True) for key, layer in layers.items()}
    operations = []
    edges = {key: set() for key in current}
    indegree = dict.fromkeys(current, 0)
    for anchor in intent.anchor_relationships:
        if anchor.relationship_type not in ("behind", "above"):
            continue
        a, b = (
            (anchor.source_layer_id, anchor.target_layer_id)
            if anchor.relationship_type == "behind"
            else (anchor.target_layer_id, anchor.source_layer_id)
        )
        if a not in current or b not in current:
            raise ValueError("spatial anchor refers to missing layer")
        if b not in edges[a]:
            edges[a].add(b)
            indegree[b] += 1
    ready = sorted(
        (key for key, value in indegree.items() if value == 0), key=lambda key: current[key].z_index
    )
    depth = []
    while ready:
        key = ready.pop(0)
        depth.append(key)
        for child in sorted(edges[key]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort(key=lambda key: current[key].z_index)
    if len(depth) != len(current):
        raise ValueError("spatial depth anchors contain a cycle")

    for anchor in intent.anchor_relationships:
        if anchor.source_layer_id not in current or anchor.target_layer_id not in current:
            raise ValueError("spatial anchor refers to missing layer")
        source, target = current[anchor.source_layer_id], current[anchor.target_layer_id]
        a, b = source.bounds, target.bounds
        offset = anchor.offset_mm
        kind = anchor.relationship_type
        if kind in ("behind", "above"):
            continue
        if kind == "wrap_around":
            if not isinstance(source, m.TextLayer) or not isinstance(
                target, (m.ImageLayer, m.MaskLayer)
            ):
                raise ValueError("wrap anchor requires text and isolated image/mask")
            asset = target.asset_id if isinstance(target, m.ImageLayer) else target.mask_asset_id
            exclusion = silhouette_path(
                store, project, asset, b, is_mask=isinstance(target, m.MaskLayer)
            )
            boundary = (
                intent.custom_paths[0]
                if intent.custom_paths
                else rect(a.x_mm, a.y_mm, a.width_mm, a.height_mm)
            )
            operations.append(
                m.FlowTextIntoShapeOp(
                    layer_id=source.id,
                    text_content=source.text_content,
                    style_name=source.style_name,
                    boundary=boundary,
                    exclusion_paths=[exclusion],
                )
            )
            continue
        dx = dy = 0.0
        if kind == "align_left":
            dx = b.x_mm + offset - a.x_mm
        elif kind == "align_center":
            dx = b.x_mm + b.width_mm / 2 + offset - a.x_mm - a.width_mm / 2
        elif kind == "overlaps":
            dx = b.x_mm + b.width_mm / 2 + offset - a.x_mm - a.width_mm / 2
            dy = b.y_mm + b.height_mm / 2 - a.y_mm - a.height_mm / 2
        elif kind == "avoid":
            overlap = (
                a.x_mm < b.x_mm + b.width_mm
                and a.x_mm + a.width_mm > b.x_mm
                and a.y_mm < b.y_mm + b.height_mm
                and a.y_mm + a.height_mm > b.y_mm
            )
            if not overlap:
                continue
            gap = abs(offset)
            candidates = [
                (b.x_mm - gap - a.width_mm - a.x_mm, 0),
                (b.x_mm + b.width_mm + gap - a.x_mm, 0),
                (0, b.y_mm - gap - a.height_mm - a.y_mm),
                (0, b.y_mm + b.height_mm + gap - a.y_mm),
            ]
            feasible = [
                (x, y)
                for x, y in candidates
                if a.x_mm + x >= 0
                and a.y_mm + y >= 0
                and a.x_mm + x + a.width_mm <= width_mm
                and a.y_mm + y + a.height_mm <= height_mm
            ]
            if not feasible:
                raise ValueError("avoid anchor has no feasible in-canvas placement")
            dx, dy = min(feasible, key=lambda pair: abs(pair[0]) + abs(pair[1]))
        else:
            raise ValueError("unsupported anchor relationship")
        if dx or dy:
            operations.append(m.TransformLayerOp(layer_id=source.id, dx_mm=dx, dy_mm=dy))
            source.bounds = a.model_copy(update={"x_mm": a.x_mm + dx, "y_mm": a.y_mm + dy})
    if any(
        anchor.relationship_type in ("behind", "above") for anchor in intent.anchor_relationships
    ):
        operations.extend(
            m.SetZIndexOp(layer_id=key, z_index=index) for index, key in enumerate(depth)
        )
    return operations
