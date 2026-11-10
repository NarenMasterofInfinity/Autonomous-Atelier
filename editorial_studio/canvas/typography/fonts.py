"""Pin font files; restrict Fontconfig to those files before creating the Pango font map."""

import ctypes
import hashlib
import sys
from pathlib import Path
from typing import Literal

import yaml
from fontTools.ttLib import TTFont
from pydantic import Field, model_validator

from editorial_studio.contracts.models import StrictModel
from editorial_studio.settings import ROOT


class FontSpec(StrictModel):
    id: str
    family: str
    path: str
    sha256: str
    fallback: bool = False
    axes: dict[str, float] = Field(default_factory=dict)
    slant: Literal["normal", "italic"] = "normal"


class FontAxis(StrictModel):
    tag: str
    minimum: float
    maximum: float
    default: float


class NativeLibrary(StrictModel):
    filename: str
    sha256: str


class NativeLock(StrictModel):
    libraries: list[NativeLibrary]


def verify_native_libraries() -> list[NativeLibrary]:
    lock = NativeLock.model_validate(
        yaml.safe_load((ROOT / "config/render-native-lock.yaml").read_text())
    )
    for spec in lock.libraries:
        path = Path(sys.prefix) / "lib" / spec.filename
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != spec.sha256:
            raise RuntimeError(
                f"Pinned rendering library mismatch: {spec.filename}; rerun the native acceptance proofs before updating the lock"
            )
    return lock.libraries


class StyleAxis(StrictModel):
    tag: str = Field(pattern=r"^[A-Za-z0-9]{4}$")
    value: float


class TypeStyle(StrictModel):
    name: str
    font_id: str
    font_size_pt: float = Field(gt=0)
    line_spacing: float = Field(default=1.2, ge=1)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    min_paragraph_lines: int = Field(default=2, ge=1)
    baseline_step_mm: float | None = Field(default=None, gt=0)
    tracking_pt: float = Field(default=0, ge=-12, le=48)
    alignment: Literal["left", "center", "right"] = "left"
    font_axes: list[StyleAxis] = Field(default_factory=list)
    paint: Literal["fill", "stroke", "fill_stroke"] = "fill"
    stroke_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    stroke_width_pt: float = Field(default=0, ge=0, le=12)

    @model_validator(mode="after")
    def editorial_controls(self):
        if len({a.tag for a in self.font_axes}) != len(self.font_axes):
            raise ValueError("duplicate per-style font axis")
        if self.paint != "fill" and (not self.stroke_color or self.stroke_width_pt <= 0):
            raise ValueError("outline type requires a color and positive stroke width")
        return self


class FontConfiguration(StrictModel):
    fonts: list[FontSpec]
    styles: list[TypeStyle]


class FontRegistry:
    def __init__(
        self,
        path: Path = ROOT / "config/fonts.yaml",
        *,
        configuration: FontConfiguration | None = None,
    ):
        self.config = FontConfiguration.model_validate(
            configuration.model_dump() if configuration else yaml.safe_load(path.read_text())
        )
        self.fonts = {font.id: font for font in self.config.fonts}
        self.styles = {style.name: style for style in self.config.styles}
        self.coverage = {}
        self.variable_axes = {}
        self.paths = []
        for font in self.config.fonts:
            file = (ROOT / font.path).resolve()
            if not file.exists():
                raise FileNotFoundError(
                    f"Pinned font missing: {file}; run python scripts/install_fonts.py"
                )
            if hashlib.sha256(file.read_bytes()).hexdigest() != font.sha256:
                raise ValueError(f"Font hash mismatch: {font.id}")
            with TTFont(file) as tt:
                if bool(tt["head"].macStyle & 2) != (font.slant == "italic"):
                    raise ValueError(f"Pinned font slant does not match {font.id}")
                self.coverage[font.id] = set(tt.getBestCmap())
                axes = (
                    [
                        FontAxis(
                            tag=axis.axisTag,
                            minimum=axis.minValue,
                            maximum=axis.maxValue,
                            default=axis.defaultValue,
                        )
                        for axis in tt["fvar"].axes
                    ]
                    if "fvar" in tt
                    else []
                )
                self.variable_axes[font.id] = axes
                allowed = {axis.tag: axis for axis in axes}
                for tag, value in font.axes.items():
                    if (
                        tag not in allowed
                        or not allowed[tag].minimum <= value <= allowed[tag].maximum
                    ):
                        raise ValueError(f"Unsupported font axis {tag} for {font.id}")
            self.paths.append(file)
        if any(style.font_id not in self.fonts for style in self.config.styles):
            raise ValueError("Typography style references an unknown pinned font")
        for style in self.config.styles:
            allowed = {a.tag: a for a in self.variable_axes[style.font_id]}
            for axis in style.font_axes:
                if (
                    axis.tag not in allowed
                    or not allowed[axis.tag].minimum <= axis.value <= allowed[axis.tag].maximum
                ):
                    raise ValueError(f"Unsupported per-style axis {axis.tag} for {style.font_id}")

    def configure(self):
        library = Path(sys.prefix) / "lib/libfontconfig.so.1"
        fc = ctypes.CDLL(str(library) if library.exists() else "libfontconfig.so.1")
        fc.FcConfigCreate.restype = ctypes.c_void_p
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        fc.FcConfigSetCurrent.argtypes = [ctypes.c_void_p]
        fc.FcConfigSetCurrent.restype = ctypes.c_int
        fc.FcConfigDestroy.argtypes = [ctypes.c_void_p]
        config = fc.FcConfigCreate()
        if not config:
            raise RuntimeError("Fontconfig configuration allocation failed")
        try:
            for path in self.paths:
                if not fc.FcConfigAppFontAddFile(config, str(path).encode()):
                    raise RuntimeError("Unable to register pinned font")
            if not fc.FcConfigSetCurrent(config):
                raise RuntimeError("Unable to select pinned fonts")
        finally:
            fc.FcConfigDestroy(config)
