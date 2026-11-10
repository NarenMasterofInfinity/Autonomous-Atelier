"""Draw the same approved scene beyond trim; never synthesize photographic bleed."""

from io import BytesIO

import cairo

from editorial_studio.canvas.geometry import PT_PER_MM
from editorial_studio.canvas.renderer import LayoutRejected, Renderer
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.contracts.models import Severity


def bleed_pdf(store, project, document, bleed_mm):
    typography = (
        TypographyEngine(FontRegistry(configuration=document.typography))
        if document.typography
        else TypographyEngine()
    )
    renderer = Renderer(store, project, typography)
    layouts = renderer._validate(document)
    failures = [
        finding
        for layout in layouts
        for finding in layout.result.findings
        if finding.severity in (Severity.HIGH, Severity.CRITICAL)
    ]
    if failures:
        raise LayoutRejected("; ".join(f.detail for f in failures))
    output = BytesIO()
    width = (document.scene.width_mm + 2 * bleed_mm) * PT_PER_MM
    height = (document.scene.height_mm + 2 * bleed_mm) * PT_PER_MM
    surface = cairo.PDFSurface(output, width, height)
    surface.set_metadata(cairo.PDF_METADATA_CREATOR, "Autonomous Editorial Studio M10")
    surface.set_metadata(cairo.PDF_METADATA_CREATE_DATE, document.scene.created_at.isoformat())
    context = cairo.Context(surface)
    context.translate(bleed_mm * PT_PER_MM, bleed_mm * PT_PER_MM)
    renderer._draw(context, document)
    surface.finish()
    return output.getvalue()
