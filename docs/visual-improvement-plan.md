# Magazine visual improvement plan

## Brief and boundary

Improve the appearance of the existing twelve-page magazine: more accomplished typography, stronger compositions, purposeful image–type overlap, depth and other editorial techniques already visible in the saved references. Keep the source copy, story order and page count fixed. Evaluate each physical page and facing pair for its visual role. White-space percentage is diagnostic, not an optimization target.

Use the existing 20 references as the starting collection. The user confirmed that this collection is sufficient and asked for an extensible system. M11 automatic reference ingestion/skill generation and M12 formal blind professional evaluation remain on hold. This is a proposed refinement of the current design and selection pipeline. No implementation or magazine regeneration is part of this planning pass.

## Verified inventory

| Item | Current state | What the count establishes |
| --- | --- | --- |
| Executable renderer operations | 21 | Image/text/vector creation, transforms, clips, masks, layer order, groups, paths, glyph transforms, irregular text flow, gradients, blends, color and raster effects. |
| Named technique families | 10 | Silhouette Flow, Depth Type, Custom Lettering, Fragmented Mask, Organic Path Flow, Type Clip Mask, Layer Blending, Gradient Composite, Editorial Collage and Selective Grading. |
| Technique evidence | 10 saved technical proofs | All are marked `technically_verified`. These demonstrate mechanics, not ten professionally finished editorial styles. |
| Saved references | 20 examples from three project galleries | Citizen: 10; 413/Port: 4; Guggenheim: 6. Entries contain previews, tags and short observations. |
| Pinned font families | 4 | DejaVu Serif, DejaVu Sans, Anton and Newsreader. |
| Configured font combinations | 2 baseline pairings plus the issue's custom pairing | The issue uses Anton/Newsreader with DejaVu Sans details. These combinations are not complete design styles. |
| Reusable, reference-derived editorial style packages | No established, visually qualified library | Existing examples have not been developed into a collection of parameterized compositions with real-photo demonstrations and selection rules. |
| Accepted authored visual benchmark | 1 | `flagship-proof / portrait-06`, distinct from autonomous generation. |
| Advanced technique use in the current issue | Almost none | All six finished spreads use rectangular text layout and one image layer each. The cover uses a prepared globe cutout. All six proposals declare an empty capability list. |

Evidence: [operation registry](../editorial_studio/contracts/operation_registry.py), [capability families](../editorial_studio/contracts/capability_matrix.py), [technical proofs](../data/exports/m5-proof/proofs.json), [reference catalog](../config/references.yaml), [font pairings](../config/font_pairings.yaml), [current issue](../data/exports/m9-proof/m9-live-v6/issue.json), and [accepted authored benchmark](flagship-worklog.md).

## Why the present choices are conservative

1. The recipe generator packages operations after the composition has been proposed. It does not choose among visually demonstrated editorial techniques before layout.
2. The current best-of-six diversity check measures region differences. Six rearrangements of a portrait rectangle and a title can pass without exploring depth, contour flow, overlay or different typographic voices.
3. M8/M9 use the authored flagship as a quality image; they do not retrieve and present suitable actual catalog references for every spread.
4. The type style interface exposes font, size, leading, color and baseline spacing. Font-axis and individual-glyph support exist, but tracking, alignment, per-style weight/italic choices, outline painting and deliberate display line breaks are not exposed as a coherent normal typography interface.
5. Display copyfit currently reduces the requested size to fit the allocated rectangle. It can shrink a failed large headline toward 18 pt, preserving technical fit while losing its intended visual force.
6. The final proposals use almost none of the available advanced mechanisms. Basic mechanical demos do not show the composer how to execute a convincing editorial result.
7. Visual critiques can remain REVISE while a technically valid issue advances. Some later corrections were authored. The same configured model also generates and judges, so its preferences cannot certify professional quality.

## Proposed starting library: ten visual families

These are targets for curation and proof, not a claim that ten finished styles already exist. A family is a flexible set of relationships and parameters, not fixed coordinates. Several can share renderer capabilities; one composition may combine a primary family and a supporting treatment.

| Family | Visible design behavior | Existing support and likely work |
| --- | --- | --- |
| Photographic type overlay | Large light or dark display type sits directly on the image, positioned against suitable photographic areas. | Layering exists; add image-aware text placement, contrast inspection and explicit integration relationships. |
| Foreground depth | Type passes behind a person or object, while remaining readable in front of the background photograph. | Segmentation, alpha assets and layer ordering exist. Package exact registration, occlusion limits and edge inspection. |
| Monumental condensed type | Large words act as the principal visual structure, with deliberate line breaks, tight composition and controlled edge treatment. | Anton, native shaping and glyph transforms exist. Add display line-break, tracking, alignment and scale-preservation controls. |
| Large editorial serif | Oversized serif display, contrasting italic/weight accents and a carefully arranged secondary type hierarchy. | Newsreader and font-axis support exist. Expose appropriate axes/styles and assess whether additional pinned faces are actually needed. |
| Solid/outline type | Filled and outlined letterforms interact with a photograph or color field. | Glyph paths and vector strokes exist; expose a reusable text-outline treatment and preserve glyph/source evidence. |
| Image-filled lettering | Photographic content is visible inside large letterforms, integrated with the remaining image. | Technical Type Clip Mask proof exists. Develop a real-photo composition and edge/readability checks. |
| Contour composition | Text flows around a silhouette; selected display words can follow a curve or horizon. | Silhouette Flow and Organic Path Flow exist. Add clear suitability and placement rules rather than arbitrary curves. |
| Editorial collage | Related crops and graphic shapes form one composition with a strong typographic anchor. | Clips, groups, paths and blending exist. Package coherent crop relationships, shared anchors and controlled layering. |
| Reversed photographic field | White or colored type, photographic shadow and dark/color fields form an integrated page. | Basic paint, opacity and gradient mechanisms exist. Add local contrast and print-detail inspection. |
| Directional composition | Vertical, rotated, split or unusually aligned display type organizes the page around the photograph. | Affine and glyph transforms exist. Expose deliberate alignment and source-safe word grouping. |

Specific existing starting references include Citizen `citizen-14` for type around/over a portrait, `citizen-12` for outline/color treatment, `citizen-16` and `citizen-20` for directional display; 413 `413-05` and `413-07` for compressed display and directional fields; Guggenheim `guggenheim-05` and `guggenheim-07` for angled and image-crossing type. These examples suggest relationships to study; they do not by themselves prove a reusable style.

Primary galleries: [Citizen](https://www.pentagram.com/work/citizen), [413](https://www.pentagram.com/work/413), [Guggenheim](https://www.pentagram.com/work/guggenheim).

## Work sequence and reviewable outputs

### 1. Build a manual style atlas

Study the saved references in detail and create one style card for each of the ten starting families. Each card names the applicable reference IDs, the visible principle, suitable asset conditions, typography behavior, layering relationships, adjustable parameters, failure examples and required capabilities. Label renderer support as available, needing an adapter, or needing a new primitive.

Output: a reference-to-technique matrix and a ten-card atlas. The atlas must explicitly distinguish executable behavior from an aspiration. Technical demos and any failed visual proofs remain visible.

### 2. Make typography controllable

Add explicit controls for tracking, text alignment, weight/italic and variable-font settings, intended display line breaks, and solid/outline treatment. Support tight display leading with separate reading-type safeguards. Keep source text and native shaping authoritative; a display break or visual case treatment must preserve source mapping.

Change headline fit from a shrink-first policy to: preserve intended display scale; try word-group reflow, additional source-bound frames and frame reallocation; report failure if the visual brief cannot survive. Each display brief states its intended scale and permitted reduction. Large headline size is selected from the actual font, word lengths and physical page, rather than one universal size.

Output: a typography specimen sheet on the current headlines, plus native/PDF proofs for every newly introduced control. Use current fonts first. Add a pinned face only when a demonstrated visual gap requires it.

### 3. Prove the families on real editorial material

Replace the synthetic-gradient technique demonstrations as the composer's visual examples with convincing real-photo compositions using the current copy and photographs. Develop one strong example per family and stress-check each reusable family against a second different brief/photo before labeling it reusable.

The initial checkpoint covers four families: photographic overlay, foreground depth, monumental condensed type and large editorial serif. Qualify this subset first; all ten families do not need to be finished before redesign can begin. Remaining families enter later as their proofs clear review. Each spread still needs at least three suitable, qualified families before its six-candidate comparison. If that is impossible, stop that pair and report the missing suitability/proof rather than adding an unsuitable effect to meet a quota. Other pairs can proceed. If a family remains unconvincing, revise or leave it unavailable to selection; working operations are insufficient for promotion.

Output: a rendered atlas with full spreads, physical-page views and native detail crops. This is the stage where complex techniques earn entry into the generator's selectable collection. Track `draft`, `mechanically_verified`, `visually_demonstrated`, `selectable`, `needs_rework` and `retired`. Software checks establish mechanical verification. Real-photo and second-brief evidence plus a named visual review establish selectable status; record the reviewer, verdict and exact proof versions. An agent's review never becomes owner approval. A failed second-brief check returns a family to `needs_rework` and excludes it from generation. Owner review of the initial specimen/proof sheet is one batch checkpoint, distinct from final spread selection.

### 4. Select visual treatments before coordinates

For each current spread, retrieve a small suitable set of style cards using photo properties, title geometry and available capabilities. Choose a visual brief: the leading photographic region, display scale, word groups, image/type relationship, permitted occlusion and desired graphic contrast. Pass actual relevant reference and style-proof images to the composer.

Keep the existing two concepts × three variations structure, but require the six candidates to span at least three substantive composition families. Candidate differences must be visible in technique, type structure or image integration. Coordinate distance remains only a duplicate check. Strong simpler designs can still compete; there is no requirement to stack effects on every page.

Output: six candidates for each facing pair/cover wrap, with concise visible decision records. The full-issue stage therefore compares 36 candidates, after the reusable-family proof gate has cleared.

### 5. Select by rendered design quality

Assess typography, composition, image integration, deliberate use of space and finish. Compare anonymous candidates without the composers' explanatory rationales. Inspect each candidate in its physical facing pair, each constituent page, and relevant native crops. Compare the finalists directly with the current corresponding spread and the selected reference examples.

Technical checks continue to enforce exact copy, valid masks, native sampling, typography fidelity and bleed. Intentional display overlap and readable partial occlusion need explicit treatment and visual evidence; they must not be confused with accidental collisions or unreadable titles. A white-space ratio, operation count, family label or aggregate model score cannot pass a design by itself.

If every candidate is weak, regenerate the visual concept. Do not automatically retain a weak bracket winner. A successful pair must give both physical pages a deliberate compositional role. Record disagreements and owner selection; model preference does not claim professional authority. Formal M12 evaluation stays on hold.

Output: one visually reviewed selection per pair, with its comparison evidence and unresolved issues. Each weak pair can block the redesigned issue from being presented as visually finished.

### 6. Redesign and verify this issue

Apply the selected compositions while keeping the current copy, sequence and twelve-page mapping. Review all six pairs together for a consistent visual identity without changing the story order. Retain a before/after proof book. Re-run source, native typography, bleed, PPI, embedding and exact-scene PDF parity checks on the selected revisions.

Output: the redesigned twelve-page issue, editable scenes, before/after contact sheets, design decisions and a new production proof. Technical checks and artistic judgments remain separately labeled.

## Starting directions for the present issue

These are candidate directions to test, not mandatory final layouts.

| Pages | Candidate direction |
| --- | --- |
| 12/1 | A substantially stronger FROM HERE wordmark interacting with the globe; compare type in front, type behind the globe, and an image-filled display treatment. Treat the back cover deliberately as well. |
| 2/3 | Develop foreground depth beyond the simple portrait rectangle: compare registered subject/type layering, oversized serif display and a confident photographic overlay. Preserve face and complete-title recognition. |
| 4/5 | Retain the working across-fold launch photograph; test large display against the sky/plume and a stronger vertical typographic gesture. Keep the rocket and essential plume recognizable. |
| 6/7 | Use the Earthrise horizon as an organizing edge for large light/dark typography; compare direct photographic overlay with a serif composition. |
| 8/9 | Remove the authored 18 mm strip as a fixed design decision. Test monumental type with integrated terrain, letterform image masks and a different native crop of the existing source. Source resolution and clean edges constrain execution, not the style family chosen in advance. |
| 10/11 | Develop a darker photographic field with confident reversed or contrasting serif type; use the illuminated edge to position lettering. |

## Extensibility contract

A manually curated style entry should declare:

- Stable ID, version, family and reference IDs.
- Visual principle and asset suitability conditions.
- Required capabilities and supported contract versions.
- Parameterized typography, crop, geometry and layering relationships.
- Intended display scale, word/subject visibility rules and failure conditions.
- Proof examples, negative examples and review status.

Existing renderer operations remain the execution boundary. New styles composed from supported operations should be addable through catalog entries and proofs. New fonts require pinned files and native verification. A genuinely new rendering behavior requires an explicit primitive/adapter implementation and tests; the catalog cannot claim unsupported behavior works. No arbitrary executable model-generated code is introduced.

Use a typed, versioned `EditorialStyleCard` with discriminated parameter types (bounded numeric range, enum and normalized region), explicit operation/capability identifiers and a renderer-contract version. Reject unknown IDs, unsupported contract versions, out-of-range parameters and missing proof/font bindings before a candidate is dispatched. Adapters may translate supported parameters into the existing typed concept/operation contracts; they must not execute code embedded in a card. A representative proposed entry is:

```yaml
id: foreground-depth-poster
version: 1
family: foreground_depth
status: draft
reference_ids: [citizen-14]
renderer_contract: editorial-operations-v1
required_capabilities: [CAP_02]
eligibility:
  registered_foreground_cutout: true
parameters:
  headline_size_pt: {type: number, minimum: 90, maximum: 220}
  display_font: {type: enum, values: [Anton, Newsreader]}
layer_order: [background_photo, headline, foreground_subject]
protected_features: [face, title_word_recognition]
proof_ids: []
```

This is a schema illustration, not an installed style or a universal type-size rule. The empty proof list and draft status make it ineligible. The required contract version must match an explicitly supported registry version; future migrations are recorded, not inferred. Owner approval is a separate evidence-bound field, never implied by selectable status.

Retrieve a few relevant cards per spread rather than putting the entire growing library into every prompt. Version style cards and freeze the selected versions with each candidate, so later library changes cannot silently restyle saved scenes. References, technique definitions, font choices and final compositions remain distinct objects.

## Acceptance and validation limits

The first implementation checkpoint is the typography specimen sheet plus real-photo proofs of the four initial families. It must show a convincing visual improvement before the full issue redesign begins. Review this sheet together; the remaining six families can follow without blocking an issue pair that already has three suitable selectable families. Owner review is on concrete rendered outputs, with exact reference/proof bindings; implementation does not start in this planning pass.

A family name, percentage of occupied paper, successful operation call or technical test count is not an artistic acceptance criterion. Shared generator/judge model bias remains a risk, so preserve anonymous visual comparisons, direct reference comparisons, visible evidence and owner choice. These controls improve review; they do not establish independent professional evaluation or guarantee that a page is top-class.

Engineering validation includes native/PDF parity of new typography controls, intended source partitions after display reflow, foreground registration, actual mask/clip execution, preservation of the existing bleed pipeline and rejection of unsupported style requests. Broaden regression testing where new primitives or schema changes warrant it.

## Planning audit

This plan is grounded in the current catalog, code contracts and saved issue/technique proofs. The consistency audit distinguishes existing technical capability from the proposed visually qualified library; no existing completion or owner-approval record is changed. Reference techniques are identified from the saved previews and the primary project galleries. No portability or blind-professional-evaluation claim is made. The validation review treats model judgments as subjective evidence rather than independent ground truth.
