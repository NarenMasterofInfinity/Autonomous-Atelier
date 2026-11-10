"""Deterministic facing-page columns and baseline snapping in millimetres."""

import math

from editorial_studio.contracts.models import BoundsMM
from editorial_studio.design_system.models import GridColumn, GridSpec


class BaselineGrid:
    def __init__(self, spec: GridSpec):
        self.spec = GridSpec.model_validate(spec.model_dump())

    @property
    def columns(self) -> list[GridColumn]:
        s = self.spec
        width = (
            s.page_width_mm
            - s.outer_margin_mm
            - s.fold_safe_mm
            - (s.columns_per_page - 1) * s.column_gap_mm
        ) / s.columns_per_page
        result = []
        for side, start in [
            ("left", s.outer_margin_mm),
            ("right", s.page_width_mm + s.fold_safe_mm),
        ]:
            for index in range(s.columns_per_page):
                result.append(
                    GridColumn(
                        index=len(result),
                        side=side,
                        bounds=BoundsMM(
                            x_mm=start + index * (width + s.column_gap_mm),
                            y_mm=s.top_margin_mm,
                            width_mm=width,
                            height_mm=s.height_mm - s.top_margin_mm - s.bottom_margin_mm,
                        ),
                    )
                )
        return result

    def region(self, start_column: int, span: int, top_mm: float, height_mm: float) -> BoundsMM:
        columns = self.columns
        if start_column < 0 or span < 1 or start_column + span > len(columns):
            raise ValueError("invalid column span")
        selected = columns[start_column : start_column + span]
        if len({c.side for c in selected}) != 1:
            raise ValueError("text regions cannot cross the fold-safe area")
        if (
            top_mm < self.spec.top_margin_mm - 1e-7
            or top_mm + height_mm > self.spec.height_mm - self.spec.bottom_margin_mm + 1e-7
        ):
            raise ValueError("text region extends beyond vertical margins")
        return BoundsMM(
            x_mm=selected[0].bounds.x_mm,
            y_mm=top_mm,
            width_mm=selected[-1].bounds.x_mm
            + selected[-1].bounds.width_mm
            - selected[0].bounds.x_mm,
            height_mm=height_mm,
        )

    def snap(self, y_mm: float) -> float:
        if not math.isfinite(y_mm):
            raise ValueError("baseline must be finite")
        s = self.spec
        return (
            s.baseline_origin_mm
            + math.ceil((y_mm - s.baseline_origin_mm - 1e-9) / s.baseline_step_mm)
            * s.baseline_step_mm
        )

    def on_baseline(self, y_mm: float, tolerance_mm: float | None = None) -> bool:
        # Pango line heights are integer Pango units; tiny rounding error
        # accumulates across long paragraphs. Declare the physical tolerance.
        tolerance_mm = self.spec.baseline_tolerance_mm if tolerance_mm is None else tolerance_mm
        steps = (y_mm - self.spec.baseline_origin_mm) / self.spec.baseline_step_mm
        return abs(steps - round(steps)) * self.spec.baseline_step_mm <= tolerance_mm
