# M3–M7 implementation record

Understood as: implement milestones M3 through M7 from the supplied v6 plan, test each subsystem, and verify the combined workflow in the existing `clinic` environment. Small model downloads and the configured gateway are authorized. Final human creative-identity approval is a recorded review action, not an approval the coding agent may fabricate.

The implementation will retain the normative contracts, command queue, immutable assets, transactional canvas publication, and gateway telemetry. The build will progress through photo ingestion/provenance, segmentation, advanced typography, artifact integration, then concepts/critics/final identity review. Acceptance evidence and any unmet external review gates are recorded here as each stage runs.

## M3

Five targeted tests pass, including real FSRCNN x2 inference and queue execution with zero provider calls. The live local proof ingested ten attributed upstream sample-photo stories into `m3-proof`; the manifest and complete source bindings are exported in `data/exports/m3-proof/ingestion.json`. Low-sharpness/low-contrast fixtures are flagged, crop-aware PPI is verified, and enlarged output retains the original sampling risk. These are acceptance stories, not user publication content. FSRCNN weights are 38,973 bytes and SHA-256 pinned.

Lesson for subsequent stages: source copy does not count as placed merely because it was ingested or derived. Coverage needs explicit placement or an editorial assignment. Keep sampling risk separate from enhanced pixel count.

## M4

MobileSAM `vit_t` ran on CPU against the astronaut sample using a point and box prompt. Its checkpoint is 40,728,226 bytes and SHA-256 pinned. The saved cutout, alpha, depth-typography PNG/PDF, source scene and diagnostics are under `data/exports/m4-proof/`. Predicted IoU was 0.987; this is model confidence, not measured ground-truth IoU. Foreground occupied 40.7% of the image, and edge diagnostics passed. A separate known-circle test verifies silhouette IoU above 0.98 after edge refinement. M3/M4 targeted tests: ten passed, including real dependency/hash validation.

Fresh-reader corrections: changed photo attachments now create distinct content blocks; interrupted verbatim derivation repairs on reuse; upscaler results retain actual backend identity. Coverage now requires a rendered scene with matching provenance and complete derived copy, rather than trusting arbitrary layer IDs.

Lesson for subsequent stages: structural validity and edge diagnostics cannot stand in for artistic review or independently annotated real-photo accuracy. Retain the source, mask and cutout and expose the crop for review.

## M5

All 21 typed registry operations now execute through the transactional renderer. The seven advanced typography/spatial tests pass, covering independently computed Bézier length/tangents, shaped ligatures, irregular region/hole containment, complete consumed-source offsets, reported overflow, glyph transforms, all ten technique proofs, Boolean paths, radial gradients, displacement, blur, shadow and halftone. M1 canvas regressions passed alongside the new typography tests (27 tests at that checkpoint).

The ten-spread vector proof book, full spreads, contact sheet, 1:1 pixel crops, editable scenes, render metadata and glyph-to-source outlines are exported under `data/exports/m5-proof/`. R1 technical proofs pass; owner/artistic approval remains explicitly pending. Continued implementation through M7 follows the user's requested scope and does not manufacture that approval.

Lesson for subsequent stages: a proof must exercise the named capability's actual operations and use enough content to reach its exclusions. Geometric validity and synthetic technique studies are not professional artistic acceptance.

## M6

Twelve artifact/SDK transport tests pass. Potrace tracing is compared against the source raster independently; the known ring fixture preserves its hole and exceeds 0.97 IoU. Actual SDK fixtures check multipart contextual edits and Responses image-content blocks. Image inputs must match their project-scoped immutable asset hashes before any provider action.

After the user explicitly approved the external test uploads, live contextual image-edit call `6b2c4dee23ea44d191523395ef5c56e9` completed through the configured gateway. Its generated motif was traced at 0.99235 raster agreement, classified as an editable vector, and placed through a typed scene patch. The full vector spread, source motif, traced SVG, thumbnail and pixel crop are in `data/exports/m6-proof/`. Artistic acceptance remains reviewable rather than inferred from tracing fidelity.

Lesson for subsequent stages: compare source and trace after applying the complete SVG coordinate transform. Keep model confidence, vectorization fidelity, scene execution and artistic quality as separate evidence.

## M7

The concept compiler resolves typed graphs against project assets and exact headline/deck/body derivations, emits a blocking sketch and executable recipe, and preserves unsupported features as failures. Typed recipe modules carry dependencies and incompatibility checks. The worker records bounded attempts and retains the latest technically valid revision when a later repair fails. Three critics remain separate: deterministic execution checks, a visual artistic pass, and a sketch/render fidelity pass. Comparative preferences, not changing scalar scores, drive stagnation detection.

The live verification used original copy in `config/m7_stories.yaml` with the approved public portrait, coffee, launch, and lunar sample images. Final package `m7-v4-final-package` contains three technically valid, structurally distinct spreads; measured geometric distances are approximately 0.3404, 0.5271, and 0.4466. Every source title/deck/body derivation is bound to a saved rendered text layer, native text overflow is absent, and the combined three-page 420 × 297 mm PDF contains embedded fonts and extractable text. The full proof set, sketches, recipes, source mappings, render metadata, critic reports, and candidate Bible are in `data/exports/m7-proof/`.

All three final representatives have execution ACCEPT and artistic/fidelity REVISE. These verdicts remain visible. The Bible is provisional, the final review is unrecorded, and R1 proofs remain technically verified rather than artistically approved. An approving reviewer must address the findings or explicitly override the model recommendations with a review note. No professional-quality or final-artistic acceptance is claimed.

Final-review transactions bind the publication identity snapshot, scene versions, critic records, and ten real capability proofs. They recheck evidence inside the write transaction, require provisional approval, reject stale/missing evidence, and track which package owns the canonical final Bible. A rejected older package cannot revoke another package's publication. Interrupted artifact integration and creative rendering recover committed work without another render or provider call.

The run retained 55 uncached M6/M7 provider calls: 53 completed and two known incomplete responses, with no unresolved submissions. The first two concept responses exhausted a 7,000-token allowance without returning JSON; a retry mistakenly reused the frozen budget. The corrected runs use explicit stage budgets and reasoning settings. Successful structured plans that failed source/capability/geometry checks remain in the attempt history; they were not relabeled as successful compositions.

### Verification boundaries and lessons

- Initial fixtures paired architecture/table copy with unrelated space photos. Critics rejected that mismatch. Those proofs remain in `data/exports/m7-negative-story-photo/`; the final fixtures match story and photography. Asset/story incompatibility should trigger replanning, not cosmetic layout changes.
- Required capability names are now constrained to the ten registered IDs. Native headline advances and copyfit measurements are supplied to concept planning. Grain preserves source color; monochrome is a separate authored treatment.
- Fresh-reader review found stale identity approval, insufficient evidence binding, ignored cached input changes, unsupported-concept recovery, and unresolved vector clip targets. The implementation now validates those paths and records explicit critic overrides. Provenance-bound text edits cannot retain an incompatible derivation.
- The blocking sketch is generated from the same proposal. Its fidelity score measures realization of that proposal, not independent artistic merit. The artistic and fidelity calls use the same model family; they do not constitute a blind expert panel.
- Physical geometry, source strings, an analytically known Bézier, source-mask tests, native PDF rasterization, and actual SDK transport fixtures provide independent technical checks. The three live cases are acceptance fixtures, not an unseen-story generalization benchmark.
- The supplied plan names Tier 1/Tier 2 and Case A/B/C without defining their benchmark datasets or scoring gates. The local case names describe our proofs; they do not establish passage of an unspecified benchmark. Owner R1 review and final creative approval remain open product gates.

The real Chrome browser opened the four-tab M7 studio, inspected the creative view, exports, and telemetry, and saved `data/exports/m7-proof/studio.png`. There were no browser exceptions, newly queued commands, or new provider calls from viewing. The stored-data Streamlit test also loaded all four tabs and 45 image previews without exceptions. Dependency lock and installed-package compatibility checks pass. The final suite passes 217 tests; 215 generated schemas, lint, Python formatting, and the 93-package dependency lock also pass. Seven warnings come from upstream MobileSAM/timm registry/deprecation messages.

### Verified upstream interfaces

[MobileSAM](https://github.com/ChaoningZhang/MobileSAM/tree/f706ad9c4eb7f219c00d9050e46328518ffb65d2) supplies the pinned `vit_t` predictor and checkpoint. [OpenCV dnn_superres](https://docs.opencv.org/4.13.0/d5/d29/tutorial_dnn_superres_upscale_image_single.html) supplies the conditional FSRCNN implementation. [Potrace](https://potrace.sourceforge.net/potrace.1.html) supplies SVG tracing; its group coordinate transform is applied explicitly before scene conversion. [Pango's empty glyph constant](https://docs.gtk.org/Pango/const.GLYPH_EMPTY.html) and [fontTools BasePen](https://fonttools.readthedocs.io/en/latest/pens/basePen.html) inform source-preserving outlines. The installed SDK and official [vision](https://developers.openai.com/api/docs/guides/images-vision) and [image-generation](https://developers.openai.com/api/docs/guides/image-generation) interfaces were exercised through HTTP fixtures and the configured live endpoint.
