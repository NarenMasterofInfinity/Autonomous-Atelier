# Autonomous AI Editorial Studio: Implementation Plan v6.0

**Handoff document for the coding agent.**

*This document supersedes v5.0. **Scope of the v6 change:** resolve both P0 findings from the v5 critique (complete typed normative contracts/operation validation, and a technically executable advanced-typography design) plus **only** the P1 observability finding (full LLM/tool logs, token and price accounting, UI, and gateway tests). All other v5 architecture, artistic policies, milestone sequencing and open P1/P2 items are deliberately retained.*

**Companion implementation reference:** `editorial_studio_v6_contracts.py` contains the executable Section 15 Pydantic v2 definitions. The complete source is embedded below so the handoff document is standalone. The code has been compiled and its JSON Schema generation checked in the authoring environment. This is a contract specification, not a claim that the full studio has been implemented.

## 0. How to Use This Document

- **Strict Milestone Execution:** Build strictly in milestone order (Section 10). Do not begin a milestone until the previous one meets its explicit acceptance criteria.
- **Feature Flagging:** Build only what the current milestone requires. Everything marked `FLAG` stays behind a feature flag and is off by default.
- **Unified Gateway Control:** Every external LLM, vision, and image call goes through the gateway (Section 6). No module calls an external API directly.
- **Verification Rule:** Where this document says *verify*, check against live documentation or the real library and report any mismatch. Never silently substitute.
- **Test-Driven Delivery:** Every milestone ships with passing tests (Section 11). A milestone with no passing tests is incomplete.
- **Normative Contracts:** Section 15 (contracts) is normative and is built in M0. No module may pass free-form dictionaries across a boundary. Every agent output must validate against its declared Pydantic schema before the orchestrator acts. Runtime checks also enforce references, renderer capabilities, scene versions, path topology and operation read/write permissions; schema validation alone is not sufficient.

## 1. Goal and Core Principles

**Goal:** Build a Python and Streamlit system that turns stories and photographs into an art-directed, editable publication, targeting the artistic sophistication and visual identity of *Citizen*, *Kinfolk*, *Monocle*, *The Gentlewoman*, *Dazed*, and *Wallpaper\**.

### Core Principles

1. **Conception Before Execution:** Exceptional design requires a clear visual concept and metaphor before selecting layout skills or placing elements.
2. **Taste and Constraint:** High quality stems from editorial constraint, not an overloaded toolbox. Effects must be conceptually justified. Subtraction and restraint are preferred over unmotivated decoration.
3. **Dual-Gate Quality Control:** Technical validity (Execution Critic) and artistic judgment (Artistic Critic) are separate gates. Hard-validity failures auto-reject candidates; artistic quality is evaluated visually on full renders.
4. **Visual-First Composition:** Agents inspect real visual renders across three distinct scales (thumbnails, full spreads, and 1:1 high-resolution detail crops), never raw scene JSON alone.
5. **Unified Facing Canvas:** A facing spread is treated as a single continuous canvas ($420 \times 297\text{ mm}$), split only at print export.
6. **Multi-Mode Spatial Freedom:** The LLM proposes geometry in three modes (**semantic**, **guided**, **freeform**). Deterministic code measures, executes, and validates, but never holds artistic authority.
7. **Technique Over Templates:** Executable skills represent reusable design techniques and dynamic recipes, not rigid static templates.
8. **Justified Asset Generation:** Generate synthetic graphics, masks, or image extensions only when the creative concept explicitly demands them. Raster outputs from `gpt-image-2` are explicitly tagged as raster or vectorized (via `potrace` tracing) before entry into the scene graph.
9. **Full Non-Destructive Editability:** Real vector typography, source images, masks, vector glyph paths, and layers remain non-destructively editable. Destructive operations default to immutable snapshot rollbacks.
10. **Provenance and Placement Accountability:** Every source passage is placed, deferred, or explicitly omitted, with full derived-text provenance preserved.
11. **Observable, Reconcilable Execution:** Every model call is logged and cached by content hash. Ambiguous network states are reconciled via attempt tracking, never assumed free.
12. **Deterministic Orchestration:** The core pipeline is deterministic Python code; AI agents operate strictly within assigned stage contracts.
13. **Transactional Scene Edits:** Every canvas mutation is a `ScenePatch`: validated, applied to a temporary version, visually rendered, and committed or discarded.

## 2. Stack and Configuration

| Component                     | Choice                                            | Reasoning / Protocol                                                                                                                                         |
| ----------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **App Shell**                 | Python & Streamlit                                | Thin viewer only; background worker process handles pipeline execution.                                                                                      |
| **LLM Engine**                | `gpt-6-luna` via OpenAI Responses API             | Reasoning effort explicitly configured in `config.yaml` (`high` for creative roles, `medium`/`low` for extraction). Rates loaded from versioned `config/pricing.yaml`. All call/usage details are captured by Section 6. |
| **Image Generation**          | `gpt-image-2`                                     | Parameters set to medium complexity, medium quality. Text input billed at $2.50 / 1M tokens; image input/output tracked separately.                          |
| **Segmentation**              | `MobileSAM`                                       | Swappable backend behind unified alpha refinement interface.                                                                                                 |
| **Upscaling**                 | `OpenCV dnn_superres`                             | Fallback to Lanczos; model files pinned by hash under `data/models/`.                                                                                        |
| **Image & Vector Processing** | OpenCV, Pillow, Potrace                           | Deterministic transformation, color grading, and raster-to-vector tracing.                                                                                   |
| **Rendering Engine**          | PyCairo, PangoCairo, CairoSVG, fontTools, PyMuPDF | Exact vector/typography rendering engine. PDF output targets high-resolution vector PDF; prepress conversion to PDF/X is handled in post-processing.         |
| **Geometry & Paths**          | `shapely`                                         | Spatial collision, containment, and path intersection logic.                                                                                                 |
| **Persistence & State**       | SQLite (WAL mode) + File Store                    | Versioned scenes, atomic file commits with `fsync` under `data/projects/`.                                                                                   |

## 3. Architecture, Reliability, & Operational Flow

```
[ Streamlit UI ] --(writes commands / reads state)--> [ SQLite DB (WAL Mode) ]
                                                              ^
                                                              | (polls jobs / appends events)
                                                              v
                                              [ Worker Process (Orchestrator) ]
                                                |-- LLM Gateway & Cache
                                                |-- Image Gateway
                                                |-- Hybrid Concept Framework
                                                |-- VisualConceptCompiler
                                                |-- Renderer & Solvers
                                                |-- MobileSAM Worker (Concurrency = 1)

```

### 3.1 Worker Reliability and Persistence Contracts

- **SQLite Single Writer:** WAL mode enabled. Worker process is the single writer for pipeline state; UI writes command rows only. Busy timeout = 5 s. Job leases use heartbeats and 60 s expiry.
- **Atomic File Operations:** Write temporary file, perform `fsync`, and execute atomic rename. Content hash is recorded in SQLite. Startup reconciliation pass quarantines orphan or missing files.
- **Provider Call Attempts:** Pre-submit attempt row logged with `SUBMITTING` state. States transition to `COMPLETED`, `FAILED`, `CANCELLED_AFTER_SUBMIT`, or `AMBIGUOUS`. Ambiguous attempts are reconciled against provider request IDs prior to re-execution.
- **Comparative Stagnation Detection Engine:** Tracks revision history across candidate rounds. Rather than relying on aesthetic scores, stagnation is detected via structured comparative evaluations: if technical defects are resolved but comparative artistic preference fails to show meaningful improvement over 3 rounds, a `RECONCEPT` transition or element subtraction is forced.

## 4. Repository Structure

```
editorial_studio/
  app.py worker.py config.yaml pyproject.toml uv.lock
  contracts/
    models.py                # Discriminated Pydantic contract source of truth
    schemas/                 # Generated JSON Schemas
    operation_registry.py    # 21 approved typed scene mutation operations (20 from v5 + SetOpacityOp)
    capability_matrix.py     # Execution capability coverage matrix
  ui/                        # Streamlit views (Inputs, Spread Studio, Logs, Export)
  core/                      # Orchestrator, state machine, job queue, memory, provenance, stagnation
  llm/                       # Gateways, pricing, attempt tracking, cache, prompts/
  telemetry/                 # Call/attempt/tool records, token normalization, cost calculator, event indexing
  design_system/             # Grids, modular type scales, font_pairings.yaml, styles
  art_direction/             # ArtDirectionBible structures, moodboard & visual proof manager
  concept/                   # ConceptBrief, HybridConcept, VisualConceptCompiler, fidelity checker
  references/                # Reference registry and tag retrieval
  photo/                     # Quality assessment, effective PPI, cropping, OpenCV upscaling, asset feasibility
  segmentation/              # MobileSAM backend, alpha refinement, mask caching
  canvas/                    # Scene graph, ScenePatch API, Pango Cairo renderer, advanced typography, vector tracing
    typography/              # shaping, path layout, shape flow, glyph outlines, copyfit, proofs
  spatial/                   # Spatial Assistant API, solvers (semantic, guided, freeform)
  skills/                    # Skill contracts, registry, builtins, dynamic recipe builder
  critique/                  # Execution Critic, Artistic Critic, and Concept Fidelity Evaluator
  data/                      # References, models, fonts, fixtures, project files
  tests/                     # Unit, visual regression, golden image, E2E benchmark cases

```

## 5. Core Subsystems

### 5.1 Coordinates, Scene Graph, and ScenePatch Protocol

- **Units:** Internal scene graph units are strict millimeters ($mm$). Canvas preview and PDF rendering convert $mm$ to points/pixels at compile time ($1\text{ mm} = 2.83465\text{ pt}$).
- **Standard Dimensions:** A4 Page = $210 \times 297\text{ mm}$; Facing Spread = $420 \times 297\text{ mm}$; Outer Bleed = $3\text{ mm}$. Gutter-safe zone default = $10\text{ mm}$ on each side of the fold.
- **Layer Discriminators:** `Layer` is a tagged union of `ImageLayer`, `TextLayer`, `VectorLayer`, `MaskLayer`, and `GroupLayer`. All share typed `BoundsMM`, opacity and blend-mode enums. Geometry uses `PathGeometry` with explicit `M`, `L`, `Q`, `C`, `Z` commands, including multiple subpaths and an even-odd/nonzero fill rule. A bare list of points is not a Bézier path.
- **Scene Patch Transactions:**
  - Emits a `ScenePatch` containing `parent_version`, a **discriminated `RegistryOperation` union**, created layer IDs, modified layer IDs, and explicit dependencies.
  - M0's operation inventory is the v5 set of 20 **plus `SetOpacityOp`**. It uses typed path commands, glyph transforms, gradient stops, filter variants and bounds, rather than `List[List[float]]` / `Dict[str, Any]` parameter escape hatches.
  - Pydantic rejects wrong operation arguments, NaN, unknown fields, negative sizes and opacity outside `[0, 1]`.
  - The trusted executor separately validates referenced assets/layers, operation ordering, path closure for clipping, group cycles, renderer capability and scene ownership. A valid schema is **necessary but not sufficient** for an executable patch.
  - Rejects stale `parent_version` calls without silent merging. Every committed patch generates an inverse patch or references an immutable snapshot.

### 5.2 Art-Direction Bible Engine & Two-Stage Approval (P0 - M2/M7)

- **Stage 1: Provisional Identity Approval (M2):** Establishes font pairings, palette tokens, photographic character, and reference examples using template baseline visual proofs.
- **Stage 2: Final Creative Identity Approval (M7):** After the concept engine and advanced skills are active, the system renders 2–3 diverse representative spreads. The Art Director approves the Bible based on rendered full-spread artwork before authorizing full-issue generation.

### 5.3 Dedicated Creative-Concept Engine & Hybrid Compiler (P0 - M5/M7)

To prevent information loss between sketch generation and scene construction, the system generates a **Hybrid Concept Framework**:

```
[ Story + Photos + ArtDirectionBible ]
                  |
                  v
    [ Creative Concept Generator ]
                  |
                  +---> Generates VisualConcept (metaphors, narrative intent)
                  +---> Generates SpatialConceptGraph (objects, Z-indices, Z-relationships)
                  +---> Generates ConceptSketch (thumbnail visually illustrating layout)
                  +---> Generates ArtifactRequirements (needed masks, vectors, rasters)
                  |
                  v
     [ VisualConceptCompiler ]  <-- (Hybrid Reconciler Engine)
 (Reconciles ConceptSketch against SpatialConceptGraph, maps source asset IDs,
  emits target Scene Graph skeleton & flags unsupported capability details)
                  |
                  v
[ Skill & Spatial Mode Selection -> Scene Construction ]

```

### 5.4 10-Technique Executable Capability Coverage Matrix (P0 - M2 to M5)

Every capability maps to executable operations in `operation_registry.py`. Statuses progress from `unsupported` $\rightarrow$ `planned` $\rightarrow$ `technically_verified` $\rightarrow$ `visually_reviewed` $\rightarrow$ `artistically_verified`.

| Capability ID                  | Required Operation Registry Calls                             | Renderer Support              | Verification Status          |
| ------------------------------ | ------------------------------------------------------------- | ----------------------------- | ---------------------------- |
| **CAP_01: Silhouette Flow**    | `add_path`, `flow_text_into_shape`, `set_clip_stack`          | Pango Shape Wrap + Shapely    | `artistically_verified` (M5) |
| **CAP_02: Depth Type**         | `create_group`, `set_z_index`, `apply_mask`                   | Cairo Layer Z-Stack           | `artistically_verified` (M5) |
| **CAP_03: Custom Lettering**   | `add_path`, `set_glyph_transforms`, `edit_path`               | fontTools + Cairo Path        | `artistically_verified` (M5) |
| **CAP_04: Fragmented Mask**    | `add_path`, `clip_to_path`, `transform_layer`                 | Cairo Clipping Stack          | `artistically_verified` (M5) |
| **CAP_05: Organic Path Flow**  | `add_path`, `text_on_path`, `flow_text_into_shape`            | Pango Layout Path             | `artistically_verified` (M5) |
| **CAP_06: Type Clip Mask**     | `add_text`, `clip_to_path`, `create_group`                    | Cairo Glyph Path Mask         | `artistically_verified` (M5) |
| **CAP_07: Layer Blending**     | `set_blend_mode`, `create_group`, `set_opacity`               | Cairo Blend Modes             | `artistically_verified` (M5) |
| **CAP_08: Gradient Composite** | `gradient_mask`, `set_clip_stack`, `set_blend_mode`           | Cairo Linear/Radial Gradients | `artistically_verified` (M5) |
| **CAP_09: Editorial Collage**  | `add_path`, `clip_to_path`, `gradient_mask`, `set_blend_mode` | Combined Mask/Blend Stack     | `artistically_verified` (M5) |
| **CAP_10: Selective Grading**  | `color_adjust`, `gradient_mask`, `apply_filter`               | OpenCV Tone Adjustment        | `artistically_verified` (M5) |

### 5.5 Photo Pipeline, Effective PPI, & Feasibility Assessment (P1 - M3)

- **Asset Feasibility Assessment (M3):** Computes sharpness, noise, framing, and contrast early. Alerts the Art Director to low-quality source photography so the brief can adjust to a text-led or graphic treatment before composition starts.
- **Effective PPI Protocol:** $\ge 250\text{ PPI}$ (Native approval); $150\text{--}240\text{ PPI}$ ($1:1$ crop visual inspection, optional OpenCV `dnn_superres` upscale); $< 150\text{ PPI}$ (Mandatory stylized treatment or small frame placement).

### 5.6 Advanced Typography Engineering Subsystem (P0 clarification; M1 foundation, M5 advanced)

This is a **dedicated layout and rendering subsystem**, not a thin wrapper around `draw_text`. Cairo/Pango handle shaping, glyph metrics, vector drawing and surfaces; they do **not** automatically solve all arbitrary-shape text flow or path typography. Implement the additional algorithms in Python with deterministic geometry, tests and visual proofs. Preserve all v5 expressive-typography goals and the original M5 milestone (the requested v6 scope does not split M5).

**Inputs:** `TextContent` / provenance ID, font family and exact font hash, style name, typed boundary/path (`PathGeometry`), local transforms, writing direction, optional exclusions, color and output context (preview vs print).

**Outputs:** editable `TextLayer` or `VectorLayer` plus a deterministic `TextLayoutResult` containing shaped glyph runs/clusters, line origins, ink/logical bounds, consumed source offsets, unplaced offsets, path-fit status, applied font fallback and warnings. A text-to-outline operation must retain the original editable text and source provenance alongside the outline representation. Neither visual clipping nor converted outlines should silently discard text.

**Step T0 — Typography foundation (M1):**

1. Pin fonts and rendering libraries by version/hash. Register style families, variable-font axes where applicable, glyph coverage, fallback policy and embedded-font capability.
2. Shape complete text runs using Pango/HarfBuzz before measuring or positioning. Handle language/script direction and ligature clusters as shaped runs; **never place individual Unicode characters by naive fixed-width arithmetic**.
3. Implement `measure_text`, `layout_paragraph`, `fit_text_region`, `get_ink_bounds`, `get_logical_bounds` and `detect_overflow`, with reproducible line breaks at fixed width. Persist `font_hash`, Pango/Cairo versions and layout settings in render metadata.
4. Define named typography styles and copyfit policy with **allowed operations** (edit text through provenance-aware Editor, adjust frame, select alternate style, request repagination). Never shrink body text indefinitely to force a fit.
5. Verify that the preview and PDF use identical shaping and geometry. Add tests for kerning, ligatures, diacritics, mixed numerals/punctuation, font fallback, paragraph overflow, widow/orphan decisions and the target writing systems. Unsupported scripts produce a reviewable warning rather than silent wrong glyphs.

**Step T1 — Text on a path (M5):**

1. Convert the typed `PathGeometry` (M/L/Q/C/Z segments) to a path representation with a numerical **arc-length lookup table**. Subdivide curves adaptively until the length and tangent error are below configurable tolerances.
2. Shape the entire text run with Pango/HarfBuzz, obtaining **glyph advances and shaped-glyph cluster indices**. Do not index geometry by Python string position.
3. For each shaped glyph, compute the cumulative advance and a position along the arc-length parameterization. Position the glyph around the path tangent, apply normal offset and typed `GlyphTransform`, and preserve baseline orientation. Support `side`, `start_offset_mm`, overflow status and paths too short to fit the text.
4. Convert shaped glyphs to vector paths as required for advanced transformations, but keep the source text and mapping in the editable scene. Clip/flip handling is explicit: unintentional upside-down lettering is a warning; intentional rotation is an authored decision.
5. Validate using straight, circular, strongly curved and multi-segment paths. Verify that layout-fit and rendered glyph positions agree at print scale.

**Step T2 — Text flowing inside irregular shapes (M5):**

1. Validate a closed text boundary and optional hole/exclusion paths. Construct horizontal available intervals by intersecting the region with a line band at the current baseline using Shapely. Subtract all exclusions (such as a subject silhouette) and choose a usable interval according to reading order and the concept's intent.
2. Use font ascent/descent and target leading to establish a baseline and maximum line height. Measure and break text into the available interval using Pango shaping and line-breaking; do not approximate glyph widths from character counts.
3. Continue across the successive available line intervals and optional regions. Maintain source-offset provenance, paragraph breaks, hyphenation rules, bidirectional text order, and consumed/unconsumed text. Avoid squeezing a line into a region narrower than the configured minimum measure.
4. Detect traps: dangling one-word lines, islands, tight concavities, small disconnected intervals, impossible widow/orphan control and line-flow collisions. If infeasible, return a **layout failure with reasons** and request a new region or editorial reallocation instead of silently clipping text.
5. Compare the actual rendered text against the computed interval regions and reflow whenever the font, text content, exclusion contour or frame changes.

**Step T3 — Custom glyph geometry and image-filled type (M5):**

1. Extract outlines from the pinned font with fontTools or shaped glyph-path output; account for variable-font axis settings and the shaping results (glyph IDs, not codepoint guesses).
2. Represent each outline as `PathGeometry` with contours, curve control points, close operations and fill rules. Record a mapping from each modified glyph back to the original text layer.
3. Apply `SetGlyphTransformsOp` on shaped glyph indices, not raw character offsets. Implement editable transforms/offsets, vector clipping and image-as-glyph-mask without rasterizing the actual headline unnecessarily.
4. Define explicit decisions for color/texture fills, clipping, subpath holes, overlaps and intentionally cropped letters. Verify the PDF rendering visually and confirm that text provenance survives outlining.

**Acceptance proofs (M1 and M5):**

- M1: baseline paragraph plus headline measured and exported consistently; no unreported overflow; Unicode shaping, diacritics and fallback tests pass in the pinned environment.
- M5: path lettering follows Bézier tangents without broken clusters; shape-wrapped text respects an irregular region and exposes unused copy; custom glyph outline/transform is reproducible; image-clipped type remains visually correct at 1:1 crop and PDF export.
- Visual fixtures include Latin ligatures, punctuation, acute accents, a multi-line editorial paragraph, donut/concave clipping regions, a person-silhouette exclusion, path lettering, upside-down tangent cases and a font without a needed glyph.
- Failures return typed `TypographyFinding`/layout warnings. Rendering never promotes an approximate but unreadable result to approved merely because its geometry is valid.

### 5.7 Visual Artifact Planner & Vectorization Pipeline (P1 - M6)

- **Artifact Integration Contract:** Specifies visual role, target region, color constraints, dependencies, integration method (`clipping`, `masking`, `blending`, `direct`), and provenance.
- **Raster-to-Vector Tracing:** Generated graphic motifs or marks from `gpt-image-2` pass through `potrace` vector tracing when vector asset output is requested.

### 5.8 Dual Critics, Concept Fidelity, & Multi-Scale Inspection (P0 - M7)

- **Inspection Scales:** (1) Full Spread Render ($420\times297\text{ mm}$), (2) Mass Hierarchy Thumbnail, (3) High-Resolution $1:1$ Crop Detail.
- **Evaluators:** Execution Critic (technical flaws), Concept Fidelity Evaluator (sketch realization), Artistic Critic (visual tension, identity fit, restraint).

## 6. Gateway, Observability, and Provenance (P1 observability restored)

**Requirement:** Every LLM/image API call, local tool execution, scene patch, artifact and visible agent decision is traceable from one Streamlit Logs & Telemetry tab. All external model calls must use the instrumented gateway. Local operations (MobileSAM, rendering, SVG/vector generation, image transforms, skill execution) emit structured `ToolExecutionRecord` entries through the same event system. Do not imply that the provider exposes hidden internal reasoning.

### 6.1 Correlation, persistence and invocation hierarchy

For every top-level project run and every operation, store `project_id`, `run_id`, `spread_id` when relevant, `call_id` or `tool_call_id`, `parent_call_id`, `attempt_id` where relevant, agent name, stage, prompt/schema versions and timestamp. Link `WorkflowEvent` records to scene versions, critic decisions and generated-artifact IDs. A call with multiple retry attempts has **one logical call** and multiple attempt records, not multiple untracked charges.

The gateway writes the request attempt **before dispatch**. On completion it saves sanitized request and response payloads (or content-addressed references for large image inputs), provider metadata, usage, billing estimate, schema-validation outcome, errors and image outputs. Redact keys/secrets before persistence. Sensitive uploaded photos and raw user passages remain local to the configured project storage and are viewable only by a user with project access. Never copy hidden chain-of-thought; store only visible model outputs, tool arguments, explanations intentionally emitted by the agents, and any provided reasoning summaries.

### 6.2 Per-call telemetry (normative fields in Section 15)

| Category | Required fields |
|---|---|
| Identity | `call_id`, `project_id`, `run_id`, optional `spread_id`, `parent_call_id`, agent, stage |
| Model/request | provider, API operation, requested model, resolved snapshot (when available), reasoning effort, image complexity/quality, prompt version, schema version, input image/asset hashes |
| Trace | request/response asset references, request hash, visible decision summary, generated artifact IDs, schema-validation errors |
| Attempts | attempt IDs and states, provider request IDs, retries, ambiguous status, cancellation-after-submit |
| Timing | queued/started/ended timestamps, total latency, status, errors, cache hit |
| Text usage | input tokens, **cached-input tokens (subset)**, cache-write tokens where reported, output tokens, **reasoning tokens (subset of output)** |
| Image usage | reported image-input and image-output tokens, any separately reported text-input tokens, output size/quality and generated assets |
| Pricing | pricing version, reported versus estimated cost, certainty flag, billing uncertainty, rate breakdown reference |
| Local tool events | tool name, inputs, produced artifacts, elapsed time, status, any errors |

All usage fields not reported by the provider must remain **null**, never silently zero. Do not derive hidden reasoning tokens from visible text. Keep raw provider usage in a content-addressed JSON record if useful for audit, normalized into the typed `UsageRecord` for UI and accounting.

### 6.3 Cost accounting and double-counting prevention

Cost computation is deterministic and versioned: `config/pricing.yaml` contains dated per-model/per-modality rate entries. Run the M0 live provider/API smoke tests to verify request parameters, usage fields, current prices and available rate components; rates in this document are draft defaults until verified.

- Input-token cost is computed using uncached and cached components **without counting cached tokens twice**. If cache-write billing is applicable, use its separate documented rate.
- Reasoning tokens are a **subset of output tokens** and are not added again to output billing.
- For GPT Image 2, text input, image input and image output are accounted for according to actual supported usage and the matching pricing version; do not double-count image tokens if provider usage presents overlapping categories.
- A cache hit that reuses a locally stored completed response has no new external charge; record it as a new internal reuse event with a link to the original call.
- Attempts that may have been billed but have no recovered response are flagged `billing_uncertain` / `possible_charge_usd`, never recorded as free.
- Display **estimated usage-based cost** and provider-reported usage separately; do not claim per-call billing is an exact final invoice when the provider does not return that information.

Example non-overlapping accounting logic (rates selected from the relevant `price_version`):

```python
uncached_input = input_tokens - cached_input_tokens  # only when both are reported
input_cost = (uncached_input * regular_input_rate + cached_input_tokens * cached_rate) / 1_000_000
output_cost = output_tokens * output_rate / 1_000_000  # includes reasoning tokens
# Separately add supported, non-overlapping image-token and cache-write components.
```

### 6.4 Live Streamlit Logs & Telemetry tab

The UI contains four core tabs as in v5; enhance **only** the existing Logs & Telemetry tab. The tab provides these selectable views:

| View | UI requirements |
|---|---|
| Live run | Chronological events; active stage, agent, tool, streaming status; per-spread trace; success/failure/review transitions |
| Model calls | Filter by project, run, agent, stage, model, status; display input messages and uploaded-image preview/asset IDs, request settings, and visible response |
| Usage and pricing | Total input/output/cached/reasoning/image tokens when reported; estimated spend per call, agent, spread, stage, revision and entire magazine |
| Timing | API latency and total stage duration, local rendering and segmentation time, retry count |
| Generated assets | Prompt, model/settings, associated photo/source IDs, preview, output type, scene placement, provenance and usage/cost |
| Decision journal | Concept/skill selection, accepted/rejected layouts, critic findings, revision reasons and resulting scene version |
| Error and recovery | Timeouts, validation failures, retries, ambiguous calls, cancellation-after-submit, cache/reconciliation details |

`st.fragment(run_every=...)` reads the durable event table and recent call records. Streaming partial text may be shown as **provisional** data; final usage and costs are updated only when an authoritative response or provider usage event arrives. UI refreshes never trigger calls or mutate job execution. Show `unknown` where usage is missing, and clearly label estimates.

### 6.5 Observability acceptance tests (required at M0, extended later)

1. A reasoning call logs input, visible output, model, effort, parent/span IDs, reported input/output/reasoning/cached fields (when returned), latency and estimated cost.
2. An image-generation call logs prompt, request parameters, output asset ID, usage fields available from that API, cost estimate and uncertainty.
3. A local MobileSAM or renderer call logs the exact parent run and produced asset(s) without appearing as a billable LLM call.
4. A cached completed response creates a reuse record with **zero new provider calls** and does not double-count original tokens or cost.
5. Retry and ambiguous-attempt fixtures show all attempts linked to one call, including possible charges; a timeout cannot silently replay a billable request.
6. Incomplete provider usage is displayed as `unknown` rather than `0` or a fabricated exact price.
7. A streamed response shows provisional progress and replaces it with final recorded usage without double-counting.
8. Secrets in requests and output metadata are redacted in stored logs; visible reasoning is limited to explicitly available summaries and emitted decisions.

### 6.6 Provenance is independent of observability

The existing derived-text provenance ledger remains unchanged: source text character offsets are linked to text blocks placed on canvas, with typed edits (`verbatim`, `excerpt`, `condensed`, `paraphrase`, `new_copy`). A log can *reference* these provenance IDs but must not replace the ledger.

## 7. Spread Workflow States

```
[ BRIEF_READY ] --> [ CONCEPTING ] --> [ CONCEPT_COMPILED ] --> [ SOLVING ] --> [ ARTIFACTS ]
       ^                  |                   |                    |                |
       |                  v                   v                    v                v
[ REPLAN / RECONCEPT / RECOMPOSE / REVISE ] <-------------------------- [ RENDERING ]
                                                                             |
                                                                             v
                                                                   [ REVIEW (3 Critics) ]
                                                                             |
                                                                             v
                                                                  [ PRODUCTION_CHECK ] --> [ COMMITTED ]

```

## 8. Concept-First Multi-Candidate Generation (P1 - M8)

- Emits **2 distinct creative concepts** (`ConceptBrief`). For each concept, generates **3 spatial layout variations** ($2 \times 3 = 6$ total candidates). Pairwise visual tournament selects the winning spread.

## 9. Streamlit UI Architecture

- Thin viewer polling SQLite state via `st.fragment(run_every=...)`.
- Tabs: **Inputs**, **Spread Studio** (with $1:1$ crop viewer, diff inspector, and sketch-vs-render overlay), **Logs & Telemetry**, and **Export**.
- **Logs & Telemetry** offers per-call input/output inspection, live event trace, token/cached/reasoning/image-usage breakdown, pricing estimates, generated artifacts, agent decisions, and retry/recovery status as specified in Section 6. Rerendering the UI never issues new paid calls.

## 10. Milestone Execution Plan

### M0: Complete Typed Contracts, 21-Operation Registry, Observability, Infrastructure, & Worker Recovery

- Build complete Pydantic v2 contract schemas in `contracts/models.py` (Section 15), generated JSON Schemas, and the **21-operation** `operation_registry.py`, including typed geometry/path commands, glyph transforms, filter variants, `SetOpacityOp`, ArtDirectionBible/HybridConcept/SkillManifest/PageMap/Artifact/Content contracts, and typed telemetry.
- Validate *all* declared cross-module models, the operation and layer discriminators, plus path topology, asset/layer references and runtime operation permissions. Export JSON Schemas and ensure they match the committed Python definitions.
- Implement API Gateway with pre-call attempt tracking, SQLite WAL worker process, heartbeat leases, and atomic `fsync` persistence with startup reconciliation.
- Implement Section 6's call/attempt/tool/event telemetry, pricing normalization, cost certainty, redacted request/response storage and live Streamlit Logs & Telemetry inspector.
- *Acceptance:* Contract fixtures validate; invalid discriminators, invalid curve paths, unknown fields, impossible bounds, bad op parameters and missing references are rejected. One reasoning call and one image call show actual reported token fields, latency and **usage-based estimated** cost (or `unknown`), plus request/response traces. Simulated cache hit, ambiguous attempt and lost-response recovery do not double-charge. A killed worker resumes without repeating committed steps.

### M1: Continuous Vector Canvas, Tagged Layer Scene Graph, & Renderer

- Implement continuous spread canvas ($420\times297\text{ mm}$), tagged layer union scene graph (`ImageLayer`, `TextLayer`, `VectorLayer`, `MaskLayer`, `GroupLayer`), `ScenePatch` transaction executor, **T0 typography foundation from Section 5.6**, and high-res vector PDF renderer.
- *Acceptance:* Continuous visual render across gutter fold. Patch apply, rollback, and stale-parent rejection verified. Shaping, line breaks, text overflow, font fallback and Unicode/ligature proofs pass in both preview and PDF. Golden-image regression suite passes.

### M2: Design System, Capability Matrix Setup, & Provisional Art-Direction Bible

- Build `font_pairings.yaml`, baseline grid solver, manual reference registry (\~20 curated spreads), initial capability matrix, and `ArtDirectionBible` schema with provisional baseline visual proofs.
- *Acceptance:* Template baseline lays out 3 test stories. Provisional Art-Direction Bibles generate initial layout guidelines.

### M3: Photo Pipeline, Feasibility Assessment, Ingestion, & Provenance Ledger

- Build image analysis maps (saliency, faces, negative space), asset feasibility assessment, effective PPI calculations, conditional OpenCV upscaler, and derived-text provenance ledger.
- *Acceptance:* Asset feasibility assessment successfully flags low-quality images. 10 photo stories ingested with provenance tracking.

### M4: Segmentation Interface & Alpha Refinement Pipeline

- Implement `MobileSAM` backend behind unified segmentation contract. Build OpenCV mask edge refinement and alpha matting pipeline.
- *Acceptance:* Isolated cutouts from complex photo backgrounds; headline placed behind subject; edge quality metric passes.

### M5: Advanced Typography Engineering, Spatial API, & Capability Matrix Verification (Checkpoint R1)

- Implement advanced typography renderer components **T1–T3 from Section 5.6** (`text_on_path`, `flow_text_into_shape`, `custom_glyph_layout`) including shaped-glyph cluster-aware placement, explicit closed/exclusion paths, consumed/unplaced text tracking and font-to-outline provenance.
- Implement Spatial Assistant API, builtin skills, and executable proof for all 10 capability matrix techniques using the typed operation registry.
- *Acceptance (Checkpoint R1):* Rendered proof produced and verified across all 10 matrix techniques. Text-on-curve, irregular flow, clipped type and glyph-transformation fixtures pass at preview, full-spread and 1:1 crop scales. Owner reviews contact sheets to confirm freedom from mechanical artifacts.

### M6: Visual Artifact Planner, Vectorization, & Context Inspection

- Implement visual artifact planner, artifact integration contracts, `potrace` vector tracing pipeline, and contextual `gpt-image-2` asset generation.
- *Acceptance:* Asset gaps automatically detected, generated, classified, placed in scene graph, and visually verified.

### M7: Creative Concept Engine, Hybrid Compiler, Final Bible Approval, Dual Critics, & Dynamic Recipes

- Implement Creative Concept Engine, Hybrid Concept Framework, and `VisualConceptCompiler`.
- Implement Dynamic Combinatorial Recipe generator.
- Implement Dual Critic Framework + Concept Fidelity Evaluator with comparative stagnation detection.
- Render 2–3 diverse representative spreads to achieve **Final Creative Identity Approval** for the `ArtDirectionBible`.
- *Acceptance:* Passes Tier 1 & Tier 2 evaluation benchmarks across Case A, Case B, Case C, and open-ended test cases. Final Art-Direction Bible approved.

### M8: Concept-First Multi-Candidate Engine & Pairwise Tournament

- Build best-of-$N$ candidate generation (2 concepts $\times$ 3 spatial variations = 6 candidates), rotating Composer mandates, and pairwise visual tournament selection.
- *Acceptance:* Pipeline generates distinct candidate spreads from a single input set.

### M9: Issue Architect, Pacing Memory, & Dynamic Visual History

- Build Issue Architect agent, PageMap printer mapping, narrative pacing memory, and dynamic issue contact sheet memory.
- *Acceptance:* Full 12-page magazine issue rendered with coherent design progression and dynamic Bible updates.

### M10: Production Preflight & High-Res PDF Export Engine

- Build preflight checks (bleed, gutter clearance, PPI, font subsetting) and high-res vector PDF export.
- *Acceptance:* Exported PDFs match approved canvas scenes with complete font embedding and zero hard-validity defects.

### M11: Reference Ingestion & Automated Skill Generator (FLAG)

- Implement reference breakdown pipeline, recipe DSL compiler, structural novelty evaluator, and Skills Lab review interface.
- *Acceptance:* System ingests reference layout, synthesizes reusable skill package, passes structural checks, and receives human approval.

### M12: Multi-Dimensional Blind Evaluation & Weakest-Spread Gate

- Conduct blind evaluation of full 12-page issues against professional reference publications (*Citizen*, *Kinfolk*, *Monocle*).
- *Acceptance:* Blind human expert panels judge studio output to satisfy all three Tier 3 criteria (Absolute Professional Quality, Comparative Reference Bracket, and Weakest-Spread Quality Gate).

## 10.1 Multi-Dimensional Evaluation Protocols (M12 Gate)

### Tier 3 Evaluation Protocol

Evaluated by a panel of at least 3 independent reviewers with professional print editorial experience across 3 distinct dimensions:

1. **Absolute Professional Quality:** Does the work demonstrate intentional composition, refined typography, and strong image integration without looking like raw text and boxes?
2. **Comparative Reference Bracket:** Does the publication stand comfortably in the same aesthetic quality bracket as *Kinfolk*, *Monocle*, or *Dazed*?
3. **Weakest-Spread Quality Gate:** Evaluates the lowest-scoring spread in a 12-page issue. The publication fails if any single spread falls below professional editorial standards.

## 11. Testing Protocol

- **Deterministic Automated Tests:** Pydantic operation/layer discriminators, invalid and valid path geometry (including Bézier subpaths), typed filter and glyph arguments, missing-reference and layer-ownership checks; geometry/path intersections via `shapely`; continuous canvas rendering; `ScenePatch` transactions; worker recovery; golden-image visual regression comparisons.
- **Typography tests:** Shaping clusters and ligatures, Unicode and font fallback, curve arc length and tangent placement, closed shape/exclusion flow, overflow and unplaced-span reporting, vector text masks and PDF parity (Section 5.6).
- **Observability tests:** All eight Section 6.5 checks; prompt/response visibility, nullable token accounting, pricing version, local-tool time, cached reuse, retries and ambiguous charges, sanitized payloads and UI updates.
- **Qualitative Visual Evaluation:** Multi-scale visual inspection (Thumbnail, Full Spread, 1:1 Detail Crop) and comparative stagnation tracking.

## 12. Preflight & Production Standards

- **Trim Size:** A4 ($210 \times 297\text{ mm}$); Bleed = $3\text{ mm}$; Target PPI $\ge 300$ at placed dimensions. Inner fold safe zone = $10\text{ mm}$ per side. Full font subsetting and embedding in PDF outputs.

## 13. System Target Verification Matrix

| Target ID    | Area                  | Objective                                                             | Verification Method                              |
| ------------ | --------------------- | --------------------------------------------------------------------- | ------------------------------------------------ |
| **Target A** | Depth Typography      | Place typography behind subject cutout without edge artifacts         | Spatial Assistant + `MobileSAM` visual crop test |
| **Target B** | Layout Versatility    | Generate 3 distinct high-quality compositions from 1 story + 3 photos | Best-of-$N$ candidate comparison suite           |
| **Target C** | Issue Coherence       | Maintain visual identity across a 12-page publication                 | Issue Architect multi-spread review              |
| **Target D** | Unseen Generalization | Execute professional layouts on unseen stories without templates      | Zero-shot evaluation run on fresh inputs         |

## 14. Rules for the Coding Agent

1. **Strict Milestone Ordering:** Follow milestone order strictly. Never begin M(N+1) until M(N) acceptance criteria pass completely.
2. **No Unscheduled Features:** Do not introduce unrequested UI tabs, new agent roles, or memory layers ahead of the milestone schedule.
3. **Gateway Routing Only:** All LLM, vision, and image generation requests must flow through the central API Gateway.
4. **No Direct Scene Mutations:** Canvas modifications must be issued as schema-validated `ScenePatch` objects via `operation_registry.py`.
5. **No Blind Code Execution:** The LLM may emit layout geometry, path arrays, and freeform scene API parameters. It must **never** execute arbitrary raw Python code.
6. **Dual Gate Compliance:** Never auto-reject artistic rule breaks. Hard validity is enforced deterministically; artistic quality is evaluated by the Dual Critics on visual renders.
7. **Contract First:** Validate every agent response payload against its Pydantic schema before passing it down the pipeline.
8. **Pluggable Architecture:** Keep segmentation (`MobileSAM`) and upscaling (`dnn_superres`) strictly behind interface abstractions.
9. **Externalized Configuration:** Keep model parameters, pricing tables, and prompt templates in configuration files (`config/`), never hardcoded in logic.
10. **State Atomic Persistence:** Commit state changes to SQLite and disk before advancing workflow steps. Treat ambiguous external calls as billable potential attempts.
11. **Observability Contract:** Instrument every external model call and local tool invocation through the trace/event system. Preserve parent-child call links, request/visible response, actual reported usage, cost estimate/uncertainty and related artifact/decision IDs; expose these in Streamlit without hidden-reasoning claims or double counting.

## 15. Normative Contract Specifications (M0 Source of Truth)

The source below is **normative** and is also delivered as `editorial_studio_v6_contracts.py`. It is Python 3.11+/Pydantic v2 code, not loose pseudocode. It defines the 21 registry operations, typed layer/scene/path/skill/brief/concept/artifact/page models, and detailed telemetry contracts.

**Schema rules:** all contract classes inherit `StrictModel` (`extra="forbid"`, `validate_assignment=True`, `allow_inf_nan=False`). Operation, layer, filter, recipe-value and event unions are discriminated. Basic numerical and structural validators are included. Cross-object validation belongs to the trusted runtime: existence of assets and font hashes; geometry and clipping feasibility; path-layer compatibility; read/write sets; layer ownership; cycles; version conflicts; source-text offsets; renderer capability availability; pricing-field semantics.

**Compiled contract:** an LLM-emitted recipe is validated in two stages: (i) validate the symbolic `RecipeStep` bindings and allowed operation name; (ii) resolve slots against an explicitly typed context and validate the *resulting* operation through the `RegistryOperation` discriminated union. Rejected steps never mutate a live scene. The trusted executor applies `ScenePatch` to a temporary version and commits only on successful validation and rendering.

**Typed operation count:** the original v5 set of 20 plus `SetOpacityOp`. `PathGeometry` supports explicit move, line, quadratic, cubic and close commands, including multiple subpaths and fill rules. Shaped glyph indices are **not** Python character offsets.

```python
"""V6 M0 normative Pydantic contracts for the Autonomous AI Editorial Studio.

Executable companion to Section 15 of Implementation Plan v6.0.
Python 3.11+, Pydantic 2.x.  No arbitrary dictionaries at module boundaries.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class SpatialMode(str, Enum):
    SEMANTIC = "semantic"
    GUIDED = "guided"
    FREEFORM = "freeform"


class EditType(str, Enum):
    VERBATIM = "verbatim"
    EXCERPT = "excerpt"
    CONDENSED = "condensed"
    PARAPHRASE = "paraphrase"
    NEW_COPY = "new_copy"


class CriticVerdict(str, Enum):
    ACCEPT = "ACCEPT"
    REVISE = "REVISE"
    RECOMPOSE = "RECOMPOSE"
    RECONCEPT = "RECONCEPT"
    REPLAN = "REPLAN"


class AttemptState(str, Enum):
    SUBMITTING = "SUBMITTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED_AFTER_SUBMIT = "CANCELLED_AFTER_SUBMIT"
    AMBIGUOUS = "AMBIGUOUS"


class AssetType(str, Enum):
    RASTER = "raster"
    VECTOR = "vector"
    MASK = "mask"
    TEXT_PATH = "text_path"
    COMPOSITE = "composite"


class BlendMode(str, Enum):
    NORMAL = "normal"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    DARKEN = "darken"
    LIGHTEN = "lighten"


class CompositionUnit(str, Enum):
    SINGLE_PAGE = "single_page"
    FACING_SPREAD = "facing_spread"
    MULTI_SPREAD = "multi_spread"
    COVER = "cover"


class PageSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class CoverageStatus(str, Enum):
    UNASSIGNED = "unassigned"
    PLACED = "placed"
    DEFERRED = "deferred"
    OMITTED_APPROVED = "omitted_approved"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CostCertainty(str, Enum):
    REPORTED = "reported"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


# Geometric coordinates are in MILLIMETRES unless the field explicitly says normalized.
class PointMM(StrictModel):
    x_mm: float
    y_mm: float


class NormalizedPoint(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class BoundsMM(StrictModel):
    x_mm: float
    y_mm: float
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)


class NormalizedRegion(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside_canvas(self):
        if self.x + self.width > 1.0000001 or self.y + self.height > 1.0000001:
            raise ValueError("normalized region extends beyond canvas")
        return self


class MoveTo(StrictModel):
    cmd: Literal["M"] = "M"
    p: PointMM


class LineTo(StrictModel):
    cmd: Literal["L"] = "L"
    p: PointMM


class QuadraticTo(StrictModel):
    cmd: Literal["Q"] = "Q"
    control: PointMM
    p: PointMM


class CubicTo(StrictModel):
    cmd: Literal["C"] = "C"
    control1: PointMM
    control2: PointMM
    p: PointMM


class ClosePath(StrictModel):
    cmd: Literal["Z"] = "Z"


PathCommand: TypeAlias = Annotated[
    Union[MoveTo, LineTo, QuadraticTo, CubicTo, ClosePath], Field(discriminator="cmd")
]


class PathGeometry(StrictModel):
    commands: list[PathCommand] = Field(min_length=2)
    fill_rule: Literal["nonzero", "evenodd"] = "nonzero"

    @model_validator(mode="after")
    def validate_subpaths(self):
        open_subpath = False
        had_segment = False
        for i, command in enumerate(self.commands):
            if isinstance(command, MoveTo):
                if open_subpath and not had_segment:
                    raise ValueError(f"empty subpath before index {i}")
                open_subpath = True
                had_segment = False
            elif isinstance(command, ClosePath):
                if not open_subpath or not had_segment:
                    raise ValueError(f"invalid ClosePath at index {i}")
                open_subpath = False
            else:
                if not open_subpath:
                    raise ValueError(f"path segment without MoveTo at index {i}")
                had_segment = True
        if not isinstance(self.commands[0], MoveTo):
            raise ValueError("path must start with MoveTo")
        if open_subpath and not had_segment:
            raise ValueError("final subpath is empty")
        return self


class GlyphTransform(StrictModel):
    # Index into a *shaped glyph run*, not a Python string character index.
    glyph_index: int = Field(ge=0)
    dx_mm: float = 0.0
    dy_mm: float = 0.0
    rotation_deg: float = 0.0
    scale_x: float = Field(default=1.0, gt=0)
    scale_y: float = Field(default=1.0, gt=0)


class GradientStop(StrictModel):
    offset: float = Field(ge=0, le=1)
    opacity: float = Field(ge=0, le=1)


class BlurFilter(StrictModel):
    kind: Literal["blur"] = "blur"
    radius_mm: float = Field(gt=0)


class ShadowFilter(StrictModel):
    kind: Literal["shadow"] = "shadow"
    offset: PointMM
    radius_mm: float = Field(ge=0)
    rgba_hex: str = Field(pattern=r"^#[0-9a-fA-F]{8}$")


class GrainFilter(StrictModel):
    kind: Literal["grain"] = "grain"
    strength: float = Field(ge=0, le=1)
    random_seed: int


class HalftoneFilter(StrictModel):
    kind: Literal["halftone"] = "halftone"
    dot_spacing_mm: float = Field(gt=0)
    angle_deg: float = 0.0


FilterSpec: TypeAlias = Annotated[
    Union[BlurFilter, ShadowFilter, GrainFilter, HalftoneFilter], Field(discriminator="kind")
]


# 21 executable operations: the 20 in v5 plus SetOpacityOp.
class AddImageOp(StrictModel):
    op: Literal["add_image"] = "add_image"
    layer_id: str
    asset_id: str
    bounds: BoundsMM
    rotation_deg: float = 0.0
    opacity: float = Field(default=1.0, ge=0, le=1)


class AddTextOp(StrictModel):
    op: Literal["add_text"] = "add_text"
    layer_id: str
    text_content: str
    style_name: str
    bounds: BoundsMM
    derived_text_id: str | None = None


class TransformLayerOp(StrictModel):
    op: Literal["transform_layer"] = "transform_layer"
    layer_id: str
    dx_mm: float = 0.0
    dy_mm: float = 0.0
    scale_x: float = Field(default=1.0, gt=0)
    scale_y: float = Field(default=1.0, gt=0)
    rotation_deg: float = 0.0


class ClipToPathOp(StrictModel):
    op: Literal["clip_to_path"] = "clip_to_path"
    target_layer_id: str
    path: PathGeometry


class SetZIndexOp(StrictModel):
    op: Literal["set_z_index"] = "set_z_index"
    layer_id: str
    z_index: int


class ApplyMaskOp(StrictModel):
    op: Literal["apply_mask"] = "apply_mask"
    target_layer_id: str
    mask_asset_id: str
    invert: bool = False


class AddPathOp(StrictModel):
    op: Literal["add_path"] = "add_path"
    layer_id: str
    path: PathGeometry
    stroke_color: str | None = None
    fill_color: str | None = None
    stroke_width_mm: float = Field(default=0.5, ge=0)


class EditPathOp(StrictModel):
    op: Literal["edit_path"] = "edit_path"
    layer_id: str
    path: PathGeometry


class BooleanPathOp(StrictModel):
    op: Literal["boolean_path"] = "boolean_path"
    target_layer_id: str
    operand_layer_id: str
    operation_type: Literal["union", "difference", "intersection"]


class TextOnPathOp(StrictModel):
    op: Literal["text_on_path"] = "text_on_path"
    layer_id: str
    text_content: str
    style_name: str
    path: PathGeometry
    side: Literal["left", "right"] = "left"
    start_offset_mm: float = 0.0


class SetGlyphTransformsOp(StrictModel):
    op: Literal["set_glyph_transforms"] = "set_glyph_transforms"
    layer_id: str
    transforms: list[GlyphTransform] = Field(min_length=1)


class FlowTextIntoShapeOp(StrictModel):
    op: Literal["flow_text_into_shape"] = "flow_text_into_shape"
    layer_id: str
    text_content: str
    style_name: str
    boundary: PathGeometry
    exclusion_paths: list[PathGeometry] = Field(default_factory=list)


class SetBlendModeOp(StrictModel):
    op: Literal["set_blend_mode"] = "set_blend_mode"
    layer_id: str
    blend_mode: BlendMode


class CreateGroupOp(StrictModel):
    op: Literal["create_group"] = "create_group"
    group_layer_id: str
    member_layer_ids: list[str] = Field(min_length=1)


class SetClipStackOp(StrictModel):
    op: Literal["set_clip_stack"] = "set_clip_stack"
    target_layer_id: str
    clip_path_layer_ids: list[str]


class ColorAdjustOp(StrictModel):
    op: Literal["color_adjust"] = "color_adjust"
    layer_id: str
    brightness: float = Field(default=0.0, ge=-1, le=1)
    contrast: float = Field(default=1.0, ge=0, le=4)
    saturation: float = Field(default=1.0, ge=0, le=4)


class GradientMaskOp(StrictModel):
    op: Literal["gradient_mask"] = "gradient_mask"
    target_layer_id: str
    gradient_type: Literal["linear", "radial"]
    start: PointMM
    end: PointMM
    stops: list[GradientStop] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_stops(self):
        offsets = [stop.offset for stop in self.stops]
        if offsets != sorted(set(offsets)):
            raise ValueError("gradient stop offsets must be unique and ascending")
        return self


class DisplacementMapOp(StrictModel):
    op: Literal["displacement_map"] = "displacement_map"
    target_layer_id: str
    map_asset_id: str
    scale_mm: float = Field(ge=0)


class ApplyFilterOp(StrictModel):
    op: Literal["apply_filter"] = "apply_filter"
    layer_id: str
    filter: FilterSpec


class BindAssetOp(StrictModel):
    op: Literal["bind_asset"] = "bind_asset"
    layer_id: str
    asset_id: str
    asset_type: AssetType


class SetOpacityOp(StrictModel):
    op: Literal["set_opacity"] = "set_opacity"
    layer_id: str
    opacity: float = Field(ge=0, le=1)


RegistryOperation: TypeAlias = Annotated[Union[
    AddImageOp, AddTextOp, TransformLayerOp, ClipToPathOp, SetZIndexOp,
    ApplyMaskOp, AddPathOp, EditPathOp, BooleanPathOp, TextOnPathOp,
    SetGlyphTransformsOp, FlowTextIntoShapeOp, SetBlendModeOp, CreateGroupOp,
    SetClipStackOp, ColorAdjustOp, GradientMaskOp, DisplacementMapOp,
    ApplyFilterOp, BindAssetOp, SetOpacityOp,
], Field(discriminator="op")]


class BaseLayer(StrictModel):
    id: str
    name: str
    owner_skill_id: str | None = None
    semantic_role: str
    z_index: int
    visible: bool = True
    opacity: float = Field(default=1.0, ge=0, le=1)
    blend_mode: BlendMode = BlendMode.NORMAL
    bounds: BoundsMM


class ImageLayer(BaseLayer):
    layer_type: Literal["image"] = "image"
    asset_id: str
    effective_ppi: float | None = Field(default=None, gt=0)


class TextLayer(BaseLayer):
    layer_type: Literal["text"] = "text"
    text_content: str
    style_name: str
    derived_text_id: str | None = None


class VectorLayer(BaseLayer):
    layer_type: Literal["vector"] = "vector"
    path: PathGeometry
    stroke_color: str | None = None
    fill_color: str | None = None


class MaskLayer(BaseLayer):
    layer_type: Literal["mask"] = "mask"
    mask_asset_id: str
    invert: bool = False


class GroupLayer(BaseLayer):
    layer_type: Literal["group"] = "group"
    member_layer_ids: list[str] = Field(min_length=1)


Layer: TypeAlias = Annotated[
    Union[ImageLayer, TextLayer, VectorLayer, MaskLayer, GroupLayer], Field(discriminator="layer_type")
]


class Scene(StrictModel):
    id: str
    spread_id: str
    version: str
    parent_version: str | None = None
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    layers: list[Layer] = Field(default_factory=list)
    design_language_id: str
    created_at: datetime

    @model_validator(mode="after")
    def unique_layer_ids(self):
        ids = [layer.id for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate layer id")
        return self


class ScenePatch(StrictModel):
    patch_id: str
    parent_version: str
    target_scene_id: str
    operations: list[RegistryOperation] = Field(min_length=1)
    created_layer_ids: list[str] = Field(default_factory=list)
    modified_layer_ids: list[str] = Field(default_factory=list)
    declared_dependencies: list[str] = Field(default_factory=list)
    snapshot_asset_id: str | None = None

    @model_validator(mode="after")
    def no_duplicate_create_modify(self):
        if set(self.created_layer_ids) & set(self.modified_layer_ids):
            raise ValueError("layer cannot be both created and modified")
        return self


class PaletteToken(StrictModel):
    name: str
    hex_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class IssuePhaseDirection(StrictModel):
    phase_name: str
    emotional_role: str
    visual_behavior: str


class ArtDirectionBible(StrictModel):
    id: str
    version: str
    approval_state: Literal["provisional", "final", "revision_required"]
    conceptual_identity: str
    font_pairing_id: str
    palette: list[PaletteToken]
    photographic_character: list[str]
    signature_behaviors: list[str]
    narrative_progression: list[IssuePhaseDirection]
    recurring_motifs: list[str]
    artistic_boundaries: list[str]
    approved_visual_examples: list[str]
    provisional_proof_spread_ids: list[str] = Field(default_factory=list)
    final_proof_spread_ids: list[str] = Field(default_factory=list)


class ConceptBrief(StrictModel):
    id: str
    project_id: str
    spread_id: str
    visual_metaphor: str
    compositional_structure: str
    photography_treatment: str
    narrative_expression: str


class ConceptNode(StrictModel):
    id: str
    role: Literal["image", "text", "subject", "vector", "mask", "texture", "group"]
    source_asset_id: str | None = None
    derived_text_id: str | None = None
    target_region: NormalizedRegion | None = None
    z_order_hint: int | None = None


class ConceptRelationship(StrictModel):
    source_id: str
    target_id: str
    relation: Literal[
        "behind", "above", "overlaps", "avoids", "aligns_to",
        "flows_around", "spans_gutter", "follows_path", "clips_to"
    ]
    rationale: str


class SpatialConceptGraph(StrictModel):
    nodes: list[ConceptNode]
    relationships: list[ConceptRelationship]

    @model_validator(mode="after")
    def valid_edges(self):
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("duplicate concept node ID")
        for rel in self.relationships:
            if rel.source_id not in ids or rel.target_id not in ids:
                raise ValueError("relationship references unknown node")
        return self


class ConceptSketch(StrictModel):
    asset_id: str
    concept_brief_id: str
    aspect_ratio: float = Field(gt=0)
    source_photo_ids: list[str]


class UnsupportedFeature(StrictModel):
    feature: str
    reason: str
    proposed_fallback: str | None = None


class ExtractedVisualElement(StrictModel):
    id: str
    concept_node_id: str
    mapped_layer_id: str | None = None
    mapped_asset_id: str | None = None
    mapping_confidence: float = Field(ge=0, le=1)


class SourceSpan(StrictModel):
    source_block_id: str
    source_revision_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_char <= self.start_char:
            raise ValueError("end_char must exceed start_char")
        return self


class DerivedText(StrictModel):
    id: str
    text: str
    edit_type: EditType
    derived_from: list[SourceSpan] = Field(default_factory=list)
    placed_layer_ids: list[str] = Field(default_factory=list)


class CoverageAssignment(StrictModel):
    span: SourceSpan
    status: CoverageStatus
    assigned_spread_id: str | None = None
    approval_actor: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def omission_approved(self):
        if self.status == CoverageStatus.OMITTED_APPROVED and not self.approval_actor:
            raise ValueError("omission requires approval_actor")
        return self


class TypographyFinding(StrictModel):
    code: Literal[
        "UNSUPPORTED_SCRIPT", "FONT_FALLBACK", "PATH_OVERFLOW", "TEXT_OVERFLOW",
        "UNREADABLE_ORIENTATION", "SHAPE_COLLISION", "UNSATISFIED_WIDOW_ORPHAN",
        "NARROW_LINE_REGION", "GLYPH_MAPPING_FAILURE"
    ]
    severity: Severity
    detail: str


class ShapedGlyphPlacement(StrictModel):
    glyph_index: int = Field(ge=0)
    cluster_start: int = Field(ge=0)
    cluster_end: int = Field(ge=0)
    position: PointMM
    tangent_deg: float = 0.0
    advance_mm: float = Field(ge=0)


class TextLayoutResult(StrictModel):
    text_layer_id: str
    font_hash: str
    ink_bounds: BoundsMM
    logical_bounds: BoundsMM
    writing_direction: Literal["ltr", "rtl", "vertical"]
    consumed_end_char: int = Field(ge=0)
    overflow_start_char: int | None = Field(default=None, ge=0)
    line_count: int = Field(ge=0)
    glyphs: list[ShapedGlyphPlacement] = Field(default_factory=list)
    findings: list[TypographyFinding] = Field(default_factory=list)


class ContentBlock(StrictModel):
    id: str
    source_revision_id: str
    source_text: str
    attached_image_ids: list[str]
    derived_texts: list[DerivedText] = Field(default_factory=list)
    coverage: list[CoverageAssignment] = Field(default_factory=list)


class SpreadBrief(StrictModel):
    project_id: str
    spread_id: str
    composition_unit: CompositionUnit
    assigned_story_ids: list[str]
    assigned_photo_ids: list[str]
    narrative_role: str
    physical_page_numbers: list[int] = Field(min_length=1)
    art_direction_bible_id: str
    reference_ids: list[str] = Field(default_factory=list)
    previous_spread_thumbnail_asset_id: str | None = None
    next_spread_thumbnail_asset_id: str | None = None


class RuleBreakJustification(StrictModel):
    rule: str
    justification: str


class AnchorRelationship(StrictModel):
    source_layer_id: str
    target_layer_id: str
    relationship_type: Literal[
        "behind", "above", "align_left", "align_center", "overlaps", "wrap_around", "avoid"
    ]
    offset_mm: float = 0.0


class SpatialIntent(StrictModel):
    mode: SpatialMode
    primary_solver: str | None = None
    anchor_relationships: list[AnchorRelationship] = Field(default_factory=list)
    custom_paths: list[PathGeometry] = Field(default_factory=list)
    rule_breaks: list[RuleBreakJustification] = Field(default_factory=list)


class SkillSlot(StrictModel):
    name: str
    value_kind: Literal["asset", "layer", "text", "number", "boolean", "point", "path", "region", "color"]
    asset_type: AssetType | None = None
    required: bool = True


class RecipeValueString(StrictModel):
    kind: Literal["string"] = "string"
    value: str


class RecipeValueNumber(StrictModel):
    kind: Literal["number"] = "number"
    value: float


class RecipeValueBoolean(StrictModel):
    kind: Literal["boolean"] = "boolean"
    value: bool


class RecipeValuePoint(StrictModel):
    kind: Literal["point"] = "point"
    value: PointMM


class RecipeValuePath(StrictModel):
    kind: Literal["path"] = "path"
    value: PathGeometry


class RecipeValueSlot(StrictModel):
    kind: Literal["slot_ref"] = "slot_ref"
    slot_name: str


RecipeValue: TypeAlias = Annotated[Union[
    RecipeValueString, RecipeValueNumber, RecipeValueBoolean,
    RecipeValuePoint, RecipeValuePath, RecipeValueSlot,
], Field(discriminator="kind")]


class RecipeArgument(StrictModel):
    parameter_name: str
    value: RecipeValue


# Names are checked against the operation registry at skill-publish time.
OperationName: TypeAlias = Literal[
    "add_image", "add_text", "transform_layer", "clip_to_path", "set_z_index",
    "apply_mask", "add_path", "edit_path", "boolean_path", "text_on_path",
    "set_glyph_transforms", "flow_text_into_shape", "set_blend_mode", "create_group",
    "set_clip_stack", "color_adjust", "gradient_mask", "displacement_map",
    "apply_filter", "bind_asset", "set_opacity",
]


class RecipeStep(StrictModel):
    id: str
    operation_name: OperationName
    arguments: list[RecipeArgument]
    depends_on_step_ids: list[str] = Field(default_factory=list)


class SkillManifest(StrictModel):
    id: str
    version: str
    category: str
    intent: str
    composition_units: list[CompositionUnit]
    suitable_conditions: list[str]
    required_capabilities: list[str]
    parameters: list[SkillSlot]
    inputs: list[SkillSlot]
    outputs: list[SkillSlot]
    dependencies: list[str]
    compatible_skill_ids: list[str]
    incompatible_skill_ids: list[str]
    recipe: list[RecipeStep]
    evaluation_checks: list[str]
    fallbacks: list[str]


class RasterOutputSpec(StrictModel):
    kind: Literal["raster"] = "raster"
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    alpha_required: bool = False


class VectorOutputSpec(StrictModel):
    kind: Literal["vector"] = "vector"
    format: Literal["svg"] = "svg"
    editable_paths_required: bool = True


class MaskOutputSpec(StrictModel):
    kind: Literal["mask"] = "mask"
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)


class TextPathOutputSpec(StrictModel):
    kind: Literal["text_path"] = "text_path"
    format: Literal["svg"] = "svg"


class CompositeOutputSpec(StrictModel):
    kind: Literal["composite"] = "composite"
    editable_layer_ids: list[str] = Field(min_length=1)


ArtifactOutputSpec: TypeAlias = Annotated[
    Union[RasterOutputSpec, VectorOutputSpec, MaskOutputSpec, TextPathOutputSpec, CompositeOutputSpec],
    Field(discriminator="kind"),
]


class ArtifactRequest(StrictModel):
    id: str
    asset_type: AssetType
    visual_role: str
    generation_spec: str
    target_region: NormalizedRegion
    color_constraints: list[str]
    preferred_generation_method: str
    # This may refer to a symbolic scene slot before an actual layer is created.
    target_layer_dependency_id: str
    integration_method: Literal["clipping", "masking", "blending", "direct"]
    output: ArtifactOutputSpec
    provenance_notes: str
    visual_acceptance_checks: list[str] = Field(default_factory=list)


class HybridConceptOutput(StrictModel):
    concept_brief: ConceptBrief
    spatial_concept_graph: SpatialConceptGraph
    sketch: ConceptSketch
    artifact_requirements: list[ArtifactRequest]
    required_capabilities: list[str]


class ConceptCompilerOutput(StrictModel):
    concept_brief_id: str
    target_scene_skeleton: Scene
    extracted_visual_elements: list[ExtractedVisualElement]
    unsupported_features: list[UnsupportedFeature]


class PhysicalPage(StrictModel):
    number: int = Field(ge=1)
    side: PageSide
    spread_id: str | None = None
    folio_text: str | None = None
    is_cover: bool = False


class PageMap(StrictModel):
    project_id: str
    pages: list[PhysicalPage] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_page_numbers(self):
        nums = [p.number for p in self.pages]
        if len(nums) != len(set(nums)):
            raise ValueError("duplicate physical page number")
        return self


class CritiqueFinding(StrictModel):
    category: str
    severity: Severity
    description: str
    actionable_fix: str
    target_layer_ids: list[str] = Field(default_factory=list)


class RuleBreakEvaluation(StrictModel):
    rule: str
    accepted: bool
    reason: str


class ReviewDecision(StrictModel):
    verdict: CriticVerdict
    execution_findings: list[CritiqueFinding]
    artistic_findings: list[CritiqueFinding]
    concept_fidelity_findings: list[CritiqueFinding]
    rule_break_evaluations: list[RuleBreakEvaluation]
    target_edit_instructions: str | None = None
    stagnation_detected: bool = False


class AttemptRecord(StrictModel):
    attempt_id: str
    call_id: str
    request_hash: str
    state: AttemptState
    provider_request_id: str | None = None
    model_snapshot: str
    reconciliation_status: str
    submitted_at: datetime | None = None
    ended_at: datetime | None = None
    possible_charge_usd: float | None = Field(default=None, ge=0)


class UsageRecord(StrictModel):
    # Usage values that are not reported by a provider remain null, not zero.
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    text_input_tokens: int | None = Field(default=None, ge=0)
    image_input_tokens: int | None = Field(default=None, ge=0)
    image_output_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def nested_counts(self):
        if self.input_tokens is not None and self.cached_input_tokens is not None:
            if self.cached_input_tokens > self.input_tokens:
                raise ValueError("cached input token count cannot exceed input tokens")
        if self.output_tokens is not None and self.reasoning_tokens is not None:
            if self.reasoning_tokens > self.output_tokens:
                raise ValueError("reasoning token count cannot exceed output tokens")
        return self


class CostRecord(StrictModel):
    certainty: CostCertainty
    pricing_version: str
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    reported_cost_usd: float | None = Field(default=None, ge=0)
    billing_uncertain: bool = False
    rate_breakdown_asset_id: str | None = None


class ProviderCallRecord(StrictModel):
    call_id: str
    project_id: str
    run_id: str
    spread_id: str | None = None
    parent_call_id: str | None = None
    agent_name: str
    stage: str
    provider: str
    api_operation: str
    model_requested: str
    model_snapshot: str | None = None
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None
    image_complexity: str | None = None
    image_quality: str | None = None
    prompt_version: str
    schema_version: str
    request_hash: str
    request_payload_asset_id: str | None = None
    response_payload_asset_id: str | None = None
    visible_decision_summary: str | None = None
    attempt_ids: list[str]
    status: Literal["queued", "streaming", "completed", "failed", "ambiguous", "cancelled"]
    started_at: datetime
    ended_at: datetime | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    usage: UsageRecord | None = None
    cost: CostRecord
    generated_artifact_ids: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    error_summary: str | None = None
    cache_hit: bool = False


class ToolExecutionRecord(StrictModel):
    tool_call_id: str
    project_id: str
    run_id: str
    spread_id: str | None = None
    parent_call_id: str | None = None
    tool_name: str
    input_asset_id: str | None = None
    output_asset_ids: list[str] = Field(default_factory=list)
    status: Literal["started", "completed", "failed", "cancelled"]
    elapsed_ms: float | None = Field(default=None, ge=0)
    error_summary: str | None = None


class StageEvent(StrictModel):
    kind: Literal["stage"] = "stage"
    from_stage: str
    to_stage: str
    reason: str | None = None


class CallEvent(StrictModel):
    kind: Literal["call"] = "call"
    call_id: str
    attempt_id: str | None = None
    new_status: str


class ArtifactEvent(StrictModel):
    kind: Literal["artifact"] = "artifact"
    artifact_id: str
    action: Literal["created", "replaced", "validated", "rejected"]


class SceneEvent(StrictModel):
    kind: Literal["scene"] = "scene"
    scene_id: str
    scene_version: str
    patch_id: str | None = None


class DecisionEvent(StrictModel):
    kind: Literal["decision"] = "decision"
    decision_id: str
    verdict: CriticVerdict


EventPayload: TypeAlias = Annotated[
    Union[StageEvent, CallEvent, ArtifactEvent, SceneEvent, DecisionEvent],
    Field(discriminator="kind"),
]


class WorkflowEvent(StrictModel):
    event_id: str
    project_id: str
    run_id: str
    spread_id: str | None = None
    parent_event_id: str | None = None
    timestamp: datetime
    payload: EventPayload


# Agent-specific outputs can wrap the contracts above (for example:
# Editor -> SpreadBrief; Art Director -> ConceptBrief/ArtDirectionBible;
# Composer -> HybridConceptOutput/ScenePatch; Critic -> ReviewDecision).
# Tool validation is separate from model-level validation. At runtime the
# executor resolves bindings, validates every RegistryOperation, then enforces
# read/write sets, layer ownership, asset existence and scene-version checks.
```

### 15.1 Generate JSON Schemas and validate implementation

Implement the registry as a mapping from each operation discriminator to its Pydantic class. Runtime operations must share this registry; no parallel string-dispatch table with divergent parameter definitions. Export JSON Schemas with `TypeAdapter` for discriminated unions; schema generation alone does not constitute renderer support.

```python
from pydantic import TypeAdapter
from editorial_studio_v6_contracts import RegistryOperation, Layer, ScenePatch, ProviderCallRecord

operation_schema = TypeAdapter(RegistryOperation).json_schema()
layer_schema = TypeAdapter(Layer).json_schema()
patch_schema = ScenePatch.model_json_schema()
call_schema = ProviderCallRecord.model_json_schema()
```

### 15.2 Contract acceptance before declaring M0 done

- Generate and commit schemas for every cross-module type and reject extra/unknown fields.
- Verify operation names and dispatch handlers form an exact one-to-one set, including `set_opacity`.
- Verify non-finite coordinates, negative bounds, invalid opacity, missing path MoveTo, malformed ClosePath, unsorted gradient stops, duplicated layer IDs and unknown operation names are rejected.
- Verify positive geometry, compound closed paths, multi-layer ScenePatches and valid filtered operations are accepted.
- Validate runtime references and scene ownership; a Pydantic-valid operation referencing a missing layer must still fail before commit.
- Verify all token classes and cost fields have nullable missing-data semantics; cached/reasoning token categories cannot exceed their parent categories.
- Confirm prompt/response asset references in telemetry open from Streamlit and do not leak secrets.
- Keep a reference fixture for an actual traced run: ingestion → agent plan → rendered scene → review verdict → exported artifact, with per-step events and logged usage.

### 15.3 Scope intentionally deferred from v5 critique

The following other P1/P2 topics were **not changed in v6** because this revision is specifically limited to P0 issues and P1 observability: dividing M5 into sub-checkpoints, expanded scene-anchored artifact planning beyond required typed fields, multi-resolution/tiled rendering strategy, concept-fidelity interpretation, weakest-spread editorial-role scoring, and SQLite write-ownership/heartbeat wording. They remain as described in v5 or may be addressed in subsequent implementation work without changing v6's contracts.
