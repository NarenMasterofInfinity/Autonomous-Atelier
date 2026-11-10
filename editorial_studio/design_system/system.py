"""Compile a provisional identity into executable, immutable typography tokens."""

from pathlib import Path

import yaml

from editorial_studio.canvas.typography.fonts import FontConfiguration, FontRegistry, TypeStyle
from editorial_studio.contracts.models import ArtDirectionBible
from editorial_studio.design_system.models import DesignTokens, PairingCatalog
from editorial_studio.settings import ROOT


class DesignSystem:
    def __init__(
        self,
        tokens_path: Path = ROOT / "config/design_system.yaml",
        pairings_path: Path = ROOT / "config/font_pairings.yaml",
        *,
        tokens: DesignTokens | None = None,
        pairing_catalog: PairingCatalog | None = None,
        font_configuration: FontConfiguration | None = None,
    ):
        self.tokens = DesignTokens.model_validate(
            tokens.model_dump() if tokens else yaml.safe_load(tokens_path.read_text())
        )
        self.catalog = PairingCatalog.model_validate(
            pairing_catalog.model_dump()
            if pairing_catalog
            else yaml.safe_load(pairings_path.read_text())
        )
        self.pairings = {p.id: p for p in self.catalog.pairings}
        self.fonts = FontRegistry(configuration=font_configuration)
        for pairing in self.catalog.pairings:
            if not {pairing.headline_font_id, pairing.body_font_id, pairing.detail_font_id} <= set(
                self.fonts.fonts
            ):
                raise ValueError("font pairing references an unpinned font")

    def typography(self, bible: ArtDirectionBible) -> FontConfiguration:
        if bible.font_pairing_id not in self.pairings:
            raise ValueError("unknown Bible font pairing")
        palette = {p.name: p.hex_color for p in bible.palette}
        if len(palette) != len(bible.palette) or not {"paper", "ink", "muted", "accent"} <= set(
            palette
        ):
            raise ValueError("Bible palette is incomplete or duplicated")
        pairing = self.pairings[bible.font_pairing_id]
        scale = self.tokens.type_scale
        specifications = [
            ("headline", pairing.headline_font_id, "headline", "ink", 1.08, 1, None),
            ("deck", pairing.detail_font_id, "deck", "muted", 1.15, 1, None),
            ("body", pairing.body_font_id, "body", "ink", 1, 2, self.tokens.grid.baseline_step_mm),
            ("caption", pairing.detail_font_id, "caption", "muted", 1.15, 1, None),
            ("label", pairing.detail_font_id, "caption", "accent", 1.15, 1, None),
        ]
        styles = [
            TypeStyle(
                name=f"{bible.id}.{role}",
                font_id=font_id,
                font_size_pt=scale.size(size_role),
                color=palette[color_role],
                line_spacing=spacing,
                min_paragraph_lines=min_lines,
                baseline_step_mm=baseline,
            )
            for role, font_id, size_role, color_role, spacing, min_lines, baseline in specifications
        ]
        return FontConfiguration(fonts=self.fonts.config.fonts, styles=styles)
