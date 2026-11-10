"""M2 baseline proofs: measured copy flow, exact source coverage, and fixed body size."""

from uuid import uuid4

from editorial_studio.canvas.models import CanvasDocument
from editorial_studio.canvas.typography.engine import TypographyEngine
from editorial_studio.canvas.typography.fonts import FontRegistry
from editorial_studio.contracts import models as m
from editorial_studio.core.storage import utcnow
from editorial_studio.design_system.grid import BaselineGrid
from editorial_studio.design_system.models import (
    BaselineLayoutReport,
    BaselineStory,
    TextFitEvidence,
    TextPlacement,
)
from editorial_studio.design_system.system import DesignSystem


class BaselineCopyfitError(ValueError):
    def __init__(self, report: BaselineLayoutReport):
        location = (
            f" at body character {report.unplaced_body_start}"
            if report.unplaced_body_start is not None
            else ""
        )
        super().__init__(
            f"Story {report.story_id} needs reallocation for {', '.join(report.unplaced_fields) or 'body'} "
            f"{location}; body size was preserved"
        )
        self.report = report


class BaselineComposer:
    def __init__(self, system: DesignSystem, bible: m.ArtDirectionBible):
        self.system, self.bible = system, bible
        self.grid = BaselineGrid(system.tokens.grid)
        self.typography = system.typography(bible)
        self.engine = TypographyEngine(FontRegistry(configuration=self.typography))

    def compose(
        self, story: BaselineStory, scene_id: str
    ) -> tuple[CanvasDocument, BaselineLayoutReport]:
        grid = self.grid
        s = grid.spec
        if s.columns_per_page != 3:
            raise ValueError("M2 baseline recipes require three columns per page")
        palette = {p.name: p.hex_color for p in self.bible.palette}
        reading_span = self.system.tokens.body_span_columns
        layers = []
        placements = []
        baselines = []
        fits = []

        def fit_evidence(field, layer, layout):
            return TextFitEvidence(
                field=field,
                layer_id=layer.id,
                source_char_count=len(layer.text_content),
                consumed_end_char=layout.result.consumed_end_char,
                overflow_start_char=layout.result.overflow_start_char,
            )

        def measure_frontmatter(field, layer):
            measured = self.engine.layout_paragraph(layer)
            fits.append(fit_evidence(field, layer, measured))
            if measured.result.overflow_start_char is not None:
                raise BaselineCopyfitError(
                    BaselineLayoutReport(
                        story_id=story.id,
                        scene_id=scene_id,
                        placements=placements,
                        baseline_step_mm=s.baseline_step_mm,
                        baseline_origin_mm=s.baseline_origin_mm,
                        body_baselines_mm=[],
                        text_fit=fits,
                        unplaced_fields=[field],
                    )
                )

        def text(layer_id, content, role, bounds):
            layer = m.TextLayer(
                id=layer_id,
                name=layer_id.replace("-", " ").title(),
                semantic_role=role,
                z_index=10,
                text_content=content,
                style_name=f"{self.bible.id}.{role}",
                bounds=bounds,
            )
            layers.append(layer)
            return layer

        def title(column, top, height):
            layer = text("headline", story.title, "headline", grid.region(column, 3, top, height))
            measure_frontmatter("title", layer)
            placements.append(
                TextPlacement(
                    field="title", layer_id="headline", start_char=0, end_char=len(story.title)
                )
            )

        def deck(column, top, height):
            layer = text("deck", story.deck, "deck", grid.region(column, 3, top, height))
            measure_frontmatter("deck", layer)
            placements.append(
                TextPlacement(field="deck", layer_id="deck", start_char=0, end_char=len(story.deck))
            )

        def image(column, top, height):
            bounds = grid.region(column, 3, top, height)
            if story.photo_asset_id:
                layers.append(
                    m.ImageLayer(
                        id="lead-image",
                        name="Lead image",
                        semantic_role="lead",
                        z_index=0,
                        asset_id=story.photo_asset_id,
                        bounds=bounds,
                    )
                )
            else:
                x, y, w, h = bounds.x_mm, bounds.y_mm, bounds.width_mm, bounds.height_mm
                layers.append(
                    m.VectorLayer(
                        id="graphic-study",
                        name="Original graphic study",
                        semantic_role="graphic",
                        z_index=0,
                        bounds=bounds,
                        fill_color=palette["accent"],
                        opacity=0.18,
                        path=m.PathGeometry(
                            commands=[
                                m.MoveTo(p=m.PointMM(x_mm=x, y_mm=y)),
                                m.LineTo(p=m.PointMM(x_mm=x + w, y_mm=y)),
                                m.LineTo(p=m.PointMM(x_mm=x + w, y_mm=y + h)),
                                m.LineTo(p=m.PointMM(x_mm=x, y_mm=y + h)),
                                m.ClosePath(),
                            ]
                        ),
                    )
                )

        if story.layout == "feature":
            image(0, 20, 160)
            title(3, 40, 65)
            deck(3, 115, 35)
            regions = [grid.region(3, reading_span, 165, 110)]
            text(
                "byline",
                f"{story.section.upper()}\n{story.author}",
                "label",
                grid.region(0, 3, 200, 25),
            )
        elif story.layout == "essay":
            title(0, 35, 65)
            deck(3, 40, 45)
            regions = [
                grid.region(0, reading_span, 120, 155),
                grid.region(3, reading_span, 110, 165),
            ]
            text(
                "byline",
                f"{story.section.upper()} / {story.author}",
                "label",
                grid.region(0, 3, 105, 10),
            )
        else:
            title(0, 40, 65)
            deck(0, 115, 40)
            image(3, 20, 135)
            regions = [
                grid.region(0, reading_span, 175, 100),
                grid.region(3, reading_span, 175, 100),
            ]
        consumed = 0
        for index, region in enumerate(regions):
            if consumed >= len(story.body):
                break
            layer = m.TextLayer(
                id=f"body-{index + 1}",
                name=f"Reading column {index + 1}",
                semantic_role="body",
                z_index=10,
                text_content=story.body[consumed:],
                style_name=f"{self.bible.id}.body",
                bounds=region,
            )
            report = self.engine.layout_paragraph(layer)
            if not report.lines:
                continue
            delta = grid.snap(report.lines[0].baseline_mm) - report.lines[0].baseline_mm
            layer.bounds = m.BoundsMM(
                x_mm=region.x_mm,
                y_mm=region.y_mm + delta,
                width_mm=region.width_mm,
                height_mm=region.height_mm - delta,
            )
            report = self.engine.layout_paragraph(layer)
            count = report.result.consumed_end_char
            if (
                self.system.tokens.prefer_paragraph_breaks
                and index < len(regions) - 1
                and count < len(story.body) - consumed
            ):
                boundary = story.body[consumed : consumed + count].rfind("\n\n")
                if boundary > 0:
                    count = boundary + 2
            # A fragment ending at a paragraph break can itself create an extra
            # empty line. Re-measure until the exact source fragment fits.
            while count > 0:
                layer.text_content = story.body[consumed : consumed + count]
                fragment = self.engine.layout_paragraph(layer)
                if fragment.result.overflow_start_char is None:
                    break
                count = fragment.result.consumed_end_char
            if count == 0:
                continue
            layers.append(layer)
            fits.append(fit_evidence("body", layer, fragment))
            placements.append(
                TextPlacement(
                    field="body", layer_id=layer.id, start_char=consumed, end_char=consumed + count
                )
            )
            consumed += count
            baselines.extend(line.baseline_mm for line in fragment.lines)
            if any(not grid.on_baseline(line.baseline_mm) for line in fragment.lines):
                raise ValueError("native text baselines did not match the declared grid")
        report = BaselineLayoutReport(
            story_id=story.id,
            scene_id=scene_id,
            placements=placements,
            unplaced_body_start=consumed if consumed < len(story.body) else None,
            baseline_step_mm=s.baseline_step_mm,
            baseline_origin_mm=s.baseline_origin_mm,
            baseline_tolerance_mm=s.baseline_tolerance_mm,
            body_baselines_mm=baselines,
            text_fit=fits,
            unplaced_fields=["body"] if consumed < len(story.body) else [],
        )
        if report.unplaced_body_start is not None:
            raise BaselineCopyfitError(report)
        text(
            "folio",
            f"{story.id.upper()} / {story.section.upper()}",
            "caption",
            m.BoundsMM(x_mm=s.outer_margin_mm, y_mm=280, width_mm=180, height_mm=10),
        )
        scene = m.Scene(
            id=scene_id,
            spread_id=scene_id,
            version=uuid4().hex,
            width_mm=s.width_mm,
            height_mm=s.height_mm,
            design_language_id=self.bible.id,
            created_at=utcnow(),
            layers=layers,
        )
        document = CanvasDocument.from_scene(scene)
        document.background_color = palette["paper"]
        document.typography = self.typography.model_copy(deep=True)
        return document, report
