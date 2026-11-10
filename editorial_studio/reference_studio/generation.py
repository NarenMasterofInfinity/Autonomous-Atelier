"""Explicit M10A composition profile shared by the studio queue and live verifier."""

from editorial_studio.creative.tournament import configuration as base_configuration


def configuration(reference_ids, origin="m10a-references", *, version="m10a-atlas-v2"):
    cfg = base_configuration()
    cfg.update(
        version=version,
        quality_reference=None,
        preserve_display_scale=True,
        minimum_image_ppi=300,
        font_catalog="config/m10a_fonts.json",
        authored_reference_ids=reference_ids,
        authored_reference_project=origin,
        proposal_reasoning_effort="medium",
        proposal_max_output_tokens=18000,
    )
    cfg["direction_prompt"] += (
        "\nUse the authored style examples as actual visual evidence. Develop two strong directions with photographic integration and expressive typography. No bare photograph rectangle beside a detached title. Do not copy coordinates or factual content from references."
    )
    cfg["proposal_prompt"] += (
        "\nM10A: The last input images are authored style examples in editorial_style_examples order. They are not story assets. Use only photo-1/photo-2 etc for actual story content. Typography supports tracking_pt, alignment, font_axes (typed tag/value rows), paint fill/stroke/fill_stroke with stroke_color and stroke_width_pt. Use NewsreaderItalic for true italic. A major display element must be >=90pt and retain at least80% of its intended size; enlarge or rearrange source-bound frames when needed. Use normal color/opacity for reading copy. For depth, source image and alpha subject must use identical frames; place type between them. Body remains >=11pt. Preserve all source characters exactly once. Return compact typography overrides with fonts:[]."
    )
    cfg["proposal_prompt"] += (
        "\nNative sizing evidence: copy.headline.native_display_word_boxes lists actual line boxes for source words in the supplied display, body and italic faces. Match font_id; condensed display measurements do not fit wide serif/italic letters. Samples use the pinned default axes and zero tracking; custom axes or tracking require extra room. Allocate at least those widths/heights plus 2mm padding, converting mm to normalized fractions using width/420 and height/297. Use line_spacing:1 and min_paragraph_lines:1 for isolated display words. Native font line boxes are taller than visible capitals. Only the largest display treatment needs minimum_display_pt; other title words can be smaller, with exact source ranges. Never reuse a cramped rejected frame."
    )
    cfg["mandates"] = [
        "Create decisive photographic typography: large words overlap actual image pixels, using a deliberate contrast zone and keeping face/words recognizable.",
        "Create registered foreground depth: photo atmosphere, a monumental display layer, then the subject in front. Give the letterforms a strong physical relationship to the silhouette.",
        "Explore a substantially different typographic voice or structure: expressive large serif/italic or a solid/outline combination integrated with the photograph. Keep the article measured and readable.",
    ]
    return cfg
