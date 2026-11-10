"""Resolve authorized font/source handles and measure native display copyfit."""

from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.contracts import models as m
from editorial_studio.creative.models import ConceptTypography
from editorial_studio.creative.tournament import provider_materials, resolve_proposal
from editorial_studio.telemetry.tools import tool_span

VERSION = "native-display-fit-v1"


def prepare_proposal(
    store,
    context,
    proposal,
    materials,
    *,
    minimum_image_ppi=None,
    resize_images=False,
    maximum_image_reduction=None,
):
    _, bindings = provider_materials(materials)
    resolved = resolve_proposal(proposal, bindings)
    available = ConceptTypography.model_validate(materials["available_typography"])
    fonts = {f.id: f for f in available.fonts}
    styles = {s.name: s for s in available.styles}
    if resolved.typography:
        for requested in resolved.typography.fonts:
            if requested.id not in fonts:
                raise ValueError("font ID is outside the authorized material catalog")
            # Model text is not an authority for local filenames or file hashes.
            # Select the pinned catalog entry, preserving only validated axes.
            fonts[requested.id] = fonts[requested.id].model_copy(update={"axes": requested.axes})
        styles.update({style.name: style for style in resolved.typography.styles})
    typed = ConceptTypography(fonts=list(fonts.values()), styles=list(styles.values()))
    engine = TypographyEngine(FontRegistry(configuration=typed.freeze()))
    source = {row["derived_text_id"]: row["text"] for row in materials["copy"]}
    treatments = {t.node_id: t for t in resolved.treatments}
    role_styles = {style.name.rsplit(".", 1)[-1]: style.name for style in available.styles}
    adjustments = []
    image_adjustments = []
    reading_adjustments = []
    with tool_span(store, context, "resolve_sources_and_native_display_fit") as tool:
        for node in resolved.graph.nodes:
            if node.role in ("image", "subject", "texture"):
                r = node.target_region
                if min(r.x, r.y, 1 - r.x - r.width, 1 - r.y - r.height) < 0.0002:
                    treatments[node.id].image_bleed_mm = max(3, treatments[node.id].image_bleed_mm)
                if minimum_image_ppi:
                    from editorial_studio.creative.compiler import node_bounds

                    photo = next(
                        (p for p in materials["photos"] if p["asset_id"] == node.source_asset_id),
                        None,
                    )
                    if photo is None:
                        raise ValueError("photo handle is outside the supplied story")
                    b = node_bounds(node, treatments[node.id])
                    ppi = (
                        min(photo["width_px"] / b.width_mm, photo["height_px"] / b.height_mm) * 25.4
                    )
                    if ppi + 1e-3 < minimum_image_ppi:
                        if not resize_images:
                            raise ValueError(
                                f"Photo {node.id} has {ppi:.1f} native PPI; reallocate to a smaller frame for >= {minimum_image_ppi:g} PPI including bleed."
                            )
                        extra_width = b.width_mm - r.width * 420
                        extra_height = b.height_mm - r.height * 297
                        factor = min(
                            (photo["width_px"] * 25.4 / minimum_image_ppi - extra_width)
                            / (r.width * 420),
                            (photo["height_px"] * 25.4 / minimum_image_ppi - extra_height)
                            / (r.height * 297),
                        )
                        if (
                            maximum_image_reduction is not None
                            and factor < 1 - maximum_image_reduction
                        ):
                            raise ValueError(
                                f"Photo {node.id} needs more than {maximum_image_reduction:.0%} frame reduction for native print resolution; recompose with a smaller image."
                            )
                        width, height = r.width * factor, r.height * factor
                        left = (
                            r.x
                            if r.x < 0.0002
                            else (
                                1 - width
                                if abs(r.x + r.width - 1) < 0.0002
                                else r.x + (r.width - width) / 2
                            )
                        )
                        top = (
                            1 - height
                            if abs(r.y + r.height - 1) < 0.0002
                            else (r.y if r.y < 0.0002 else r.y + (r.height - height) / 2)
                        )
                        node.target_region = m.NormalizedRegion(
                            x=left, y=top, width=width, height=height
                        )
                        image_adjustments.append(
                            {
                                "layer_id": node.id,
                                "source_ppi_before": ppi,
                                "uniform_factor": factor,
                                "reason": "Conservative native-source fit for production; no upsampling or new pixels.",
                            }
                        )
            if node.role != "text":
                continue
            treatment = treatments[node.id]
            if treatment.style_role in ("body", "deck") and treatment.layout == "rect":
                r = node.target_region
                x, width = r.x * 420, r.width * 420
                if x < 220 and x + width > 200:
                    if width > 180:
                        raise ValueError(
                            f"Reading frame {node.id} is too wide for a gutter-safe page; partition the source into columns."
                        )
                    left, right = 200 - width, 220
                    target = min((left, right), key=lambda value: abs(value - x))
                    node.target_region = r.model_copy(update={"x": target / 420})
                    reading_adjustments.append(
                        {
                            "layer_id": node.id,
                            "from_x_mm": x,
                            "to_x_mm": target,
                            "reason": "Keep native-sized reading text outside the fold-safe zone.",
                        }
                    )
            style_name = treatment.style_name or role_styles.get(treatment.style_role)
            if style_name not in styles:
                raise ValueError("text references an unknown material style")
            treatment.style_name = style_name
            if treatment.style_role != "headline" or treatment.layout != "rect":
                continue
            text = source.get(node.derived_text_id)
            if text is None:
                raise ValueError("source handle is outside the supplied story")
            if treatment.text_range:
                text = text[treatment.text_range.start_char : treatment.text_range.end_char]
            r = node.target_region
            bounds = m.BoundsMM(
                x_mm=r.x * 420, y_mm=r.y * 297, width_mm=r.width * 420, height_mm=r.height * 297
            )
            original = styles[style_name]

            def measure(size, iteration, original=original, node=node, bounds=bounds, text=text):
                trial = original.model_copy(
                    update={"name": f"fit-measure-{node.id}-{iteration}", "font_size_pt": size}
                )
                engine.fonts.styles[trial.name] = trial
                layer = m.TextLayer(
                    id=node.id,
                    name=node.id,
                    semantic_role="headline",
                    z_index=0,
                    bounds=bounds,
                    text_content=text,
                    style_name=trial.name,
                )
                return engine.layout_paragraph(layer).result

            result = measure(original.font_size_pt, "original")
            lower = treatment.minimum_display_pt or min(18.0, original.font_size_pt)
            if lower > original.font_size_pt:
                raise ValueError(
                    f"display style {node.id} is smaller than its declared display minimum"
                )
            if result.overflow_start_char is None:
                continue
            if measure(lower, "minimum").overflow_start_char is not None:
                probe = m.TextLayer(
                    id=node.id,
                    name=node.id,
                    semantic_role="headline",
                    z_index=0,
                    bounds=m.BoundsMM(x_mm=0, y_mm=0, width_mm=2000, height_mm=2000),
                    text_content=text,
                    style_name=f"fit-measure-{node.id}-minimum",
                )
                natural = engine.layout_paragraph(probe).result.logical_bounds
                raise ValueError(
                    f"display frame {node.id} cannot hold its source at {lower:g}pt; reallocate the frame. "
                    f"Allocated {bounds.width_mm:.1f} x {bounds.height_mm:.1f} mm; native unwrapped "
                    f"line box at that minimum is {natural.width_mm:.1f} x {natural.height_mm:.1f} mm "
                    "before safety padding. Increase width/height or partition source words."
                )
            high = original.font_size_pt
            for step in range(14):
                middle = (lower + high) / 2
                if measure(middle, step).overflow_start_char is None:
                    lower = middle
                else:
                    high = middle
            fitted = original.model_copy(
                update={
                    "name": "native-fit." + node.id,
                    "font_size_pt": max(treatment.minimum_display_pt or 0, round(lower - 0.005, 3)),
                }
            )
            styles[fitted.name] = fitted
            treatment.style_name = fitted.name
            adjustments.append(
                {
                    "layer_id": node.id,
                    "requested_pt": original.font_size_pt,
                    "fitted_pt": fitted.font_size_pt,
                    "reason": "Full native Pango line box must fit the allocated display frame; body typography is unchanged.",
                }
            )
        resolved.typography = ConceptTypography(
            fonts=list(fonts.values()), styles=list(styles.values())
        )
        evidence = {
            "version": VERSION,
            "proposal": resolved.model_dump(mode="json"),
            "display_adjustments": adjustments,
            "image_adjustments": image_adjustments,
            "reading_adjustments": reading_adjustments,
        }
        from pydantic import JsonValue

        from editorial_studio.contracts.models import StrictModel

        class PlanningEvidence(StrictModel):
            value: JsonValue

        asset = store.json_blob(context.project_id, PlanningEvidence(value=evidence))
        tool.output_asset_ids.append(asset.id)
    return resolved
