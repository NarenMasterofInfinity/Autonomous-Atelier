# Implementation progress

Implement the supplied v6 plan using the existing `.env` and conda environment `clinic`. After accepting the M7 flagship, the user authorized implementation and testing of M8, M9 and M10.

**Implementation extends through M10, with M10A improving visual references and typography.** The [M10A work record](m10a-worklog.md) describes the twelve-study atlas, ten visual families, expressive typography and reference-conditioned generation. The [M8–M10 verification record](m8-m10-worklog.md) retains issue and production evidence. M11 and M12 remain on hold.

The [M10A composition fixes](m10a-composition-fixes.md) now capture those references as executable programs, fit exact story copy with native line/ink constraints, and reject hidden/colliding text or incompatible imagery. Eleven admitted compositions across original-copy and changed-copy cases have saved source/export verification. The [revised twelve-page magazine](../data/exports/m10a/program-issue-v3/magazine.pdf) uses five families with no adjacent repeats, preserves all six stories and selected photographs, and fixes cover placement and column paragraph breaks. Final verification passed 254 tests in two batches; the issue verifier records one photographic raster-sampling discrepancy separately. The default studio workflow uses these programs; the earlier free-form trial remains a negative corpus.

The default project is `m10a-references`; `m8-proof` retains the existing issue. The accepted [authored flagship study](flagship-worklog.md) remains in `flagship-proof`. Authored visual benchmarks are separate from autonomous-generation performance. Counts below describe historical milestone acceptance runs.

## M0 acceptance evidence

The live acceptance run in project `m0-live` completed on 9 November 2026 through the configured endpoint and instrumented gateway:

| Check | Observed result |
| --- | --- |
| Reasoning call `5875f8a37bb0407e9a56ec2dda37bb62` | ConceptBrief output passed Pydantic validation. 171 input tokens, 174 output tokens, 39 reasoning tokens, 0 cached tokens, 7.14 seconds. Estimated usage-based cost: $0.0001041. |
| Image call `8a4dbfce710d4e2ca850b374357b855e` | Saved PNG, 42 text-input tokens, 0 image-input tokens, 1756 image-output tokens, 33.76 seconds. Cached usage was absent; cost remains unknown. |
| Cache reuse `6ec6aadc48e04b228f0e378c4aab8022` | No provider attempts, no repeated usage, and zero new estimated charge. |

Requests, visible responses, reported usage, provider/attempt IDs, timing, and generated assets are persisted and accessible from Logs & Telemetry. `scripts/verify_live.py` reproduces the explicit checks; it can incur charges for uncached requests.

The original `m0-smoke` sandbox failures were neither replayed nor relabeled as free. Their historical ambiguity remains in the audit log. The live acceptance run used distinct requests and their own recovered responses. Network-enabled execution confirmed both configured models are available; it did not bypass the replay guard on the earlier requests.

M0's deterministic fixtures and recovery tests passed before M1 began. The normative contracts remain the source of operation parameters; generated schemas and runtime dispatch use those definitions.

## M1 acceptance evidence

The M1 acceptance suite passed **136 tests** in `clinic` (Python 3.13.14). Ruff, generated-schema consistency, and dependency-lock checks pass. At that milestone there were 156 generated schemas, including the 109 normative v6 schemas and typed runtime/canvas extensions.

- The continuous canvas renders at 420 × 297 mm without a gutter seam. PNG and PDF share the same shaped layout. PDF raster comparisons, physical page dimensions, embedded fonts, and extractable Unicode text are checked.
- Pango shapes whole runs, preserving ligatures, glyph IDs, UTF-8-to-source offsets, kerning, diacritics, mixed punctuation, Greek, Cyrillic, Arabic direction, and explicit pinned-font fallback. Unsupported scripts produce typed findings. Overflow retains unplaced offsets and prevents commit; copyfit never silently shrinks body type.
- All 13 M1 execution operations have native-render coverage: image/text/path creation, affine transforms, path editing, clips, masks and inversion, z-order, grouping, blending, asset binding, and opacity. The other registered operations remain unsupported for execution and fail before commit.
- Typed companion presentation state preserves transforms, source frames, clips, masks, and stroke widths without changing the normative layer contract. Group geometry updates after member edits. Group operations enforce descendant permissions.
- Scene candidates render before atomic compare-and-swap publication. Stale parents, missing references, invalid output, rendering exceptions, and unsupported operations preserve the live head. Each edit retains its immutable parent snapshot; typed snapshot rollback creates a new version rather than overwriting history.
- A real worker process was killed after a scene commit but before job completion. Restart recognized the committed command, checked all four output artifacts including metadata, and finished without a second render or commit. Missing metadata or other committed assets fail recovery instead of approving incomplete output.
- Streamlit reads stored scenes and queues create/edit/restore commands. UI checks cover the seven telemetry views, canvas inspection, edit submission, and proof downloads. The complete create → edit → restore worker flow uses zero provider calls.

The inspected [proof PNG](../data/exports/m1-proof/spread.png), [vector PDF](../data/exports/m1-proof/spread.pdf), [editable document](../data/exports/m1-proof/scene.json), and [render metadata](../data/exports/m1-proof/render-metadata.json) are local artifacts. `scripts/render_proof.py` reproduces them from the saved live image without another API call. Its technical review is explicit; this fixture does not claim an autonomous artistic verdict.

The golden image was inspected visually before being saved. It detects rendering drift; independent geometry assertions, PDF extraction, native transport checks, and the live gateway run provide separate evidence. No automated result is presented as professional artistic approval.

## M2 acceptance evidence

The full suite passes **178 tests**, with 177 generated schemas. The new tests verify physical grid constraints, source coverage, modular sizes, identity palettes, both native headline pairings, complete paragraph flow, frozen typography, reference integrity, interrupted-build recovery, explicit reviews, stale-proof rejection, and worker/UI commands. Lint, Python formatting, and dependency-lock checks pass.

The current package, identity `c1348a425e3d4a988ebb644c70a79bb8`, contains three rendered 420 × 297 mm spreads: a feature, an essay, and an interview. All fixture title, deck, and body copy is placed and has measured native fit evidence. Reading frames avoid the 10 mm fold-safe zones, retain 11 pt body type, and align to a measured 5 mm rhythm within the declared 0.01 mm Pango quantization tolerance. Paragraph breaks are preferred when flowing between reading regions. The spreads and their combined PDF were visually inspected.

Executable foundations live in `config/design_system.yaml` and `config/font_pairings.yaml`. Each scene stores the compiled font, size, spacing, and color settings; later defaults do not restyle older documents. The initial layout guidelines use these same tokens rather than an independent prose specification. Interrupted builds preserve their rendering resolution and compare the full frozen document before reusing a committed proof.

The manual registry has 20 distinct, visually inspected spread examples and spread-series previews from the primary [Citizen](https://www.pentagram.com/work/citizen), [413](https://www.pentagram.com/work/413), and [Guggenheim](https://www.pentagram.com/work/guggenheim) design galleries. Entries retain exact image names, gallery indices, URLs, tags, observations, credit, and local preview hashes. These are study references, not publication assets; no automated reference breakdown or skill generation was enabled.

The capability matrix reports actual basic-operation availability and missing advanced operations. All ten technique-verification states remain planned. Native operation support is not treated as artistic verification.

The [three-spread vector PDF](../data/exports/m2-proof/baseline-proofs.pdf), [contact sheet](../data/exports/m2-proof/contact-sheet.png), [provisional Bible](../data/exports/m2-proof/provisional-bible.json), and [guidelines](../data/exports/m2-proof/layout-guidelines.json) are available locally. The proofs reuse the saved M0 architectural image; M2 made no new provider calls. Source-copy reports, editable scenes, PNGs, and render measurements are stored beside each proof.

The saved Bible is provisional and its review remains pending. The UI records an explicit reviewer, note, verdict, and exact proof versions. Proof freshness is checked again inside the transaction that records a review. Missing or subsequently changed proofs cannot pass review, duplicate recovery cannot record the approval twice, and M2 cannot mark an identity final. Older interim packages remain readable as history; incomplete packages require rebuilding before review. M7's final creative-identity approval remains separate.

These three stories are acceptance fixtures. They do not establish generalization to unseen stories or professional artistic quality; those require the later concept/critic/evaluation milestones.

## Verified library and API decisions

- The official [GPT-6 Luna documentation](https://developers.openai.com/api/docs/models/gpt-6-luna) and the real endpoint support the configured Responses API reasoning effort. [GPT Image 2](https://developers.openai.com/api/docs/models/gpt-image-2) remains the requested image model. The installed SDK accepts medium quality but has no image `complexity` argument; no invented parameter is sent.
- [Pricing](https://developers.openai.com/api/docs/pricing) is externalized and versioned. Estimates use only reported, non-overlapping token categories. A custom endpoint's commercial rates may differ and must be configured separately.
- PyCairo 1.29.1, Cairo 1.18.4, PyGObject 3.54.5, Pango 1.56.4, fontTools 4.68.0, and PyMuPDF 1.27.2.2 were tested. Fonts and native rendering libraries are pinned by hash. Exact native build specifications are recorded in [render-environment.yaml](../config/render-environment.yaml).
- The installed GI binding cannot expose the glyph-info array correctly. The adapter therefore consumes the pinned Pango version's [layout serialization](https://docs.gtk.org/Pango/method.Layout.serialize.html) and normalizes it into stable typed glyph records. Pango explicitly does not guarantee that serialization across versions; it is not stored as the editable scene or treated as a portable format.
- M1 external clip references must share a parent group. Cross-group geometry is rejected until a later implementation supports it explicitly. Advanced path typography, shape flow, glyph outlines, Boolean paths, gradients, and photo effects are now implemented. Cross-parent clip references remain unsupported.

The fresh-context handoff review found metadata recovery coverage, renderer-capability authority, and ancestor group-bound updates worth tightening. These were fixed and tested. The documentation is a runbook for this configured workstation; its native hash lock deliberately requires revalidation on a different build.

## M3–M7 verification

The photo pipeline, source ledger, MobileSAM backend, advanced typography/spatial operations, contextual artifact pipeline, concept compiler, typed recipes, critics, and final-review controls are implemented. The [M3–M7 record](m3-m7-worklog.md) contains stage evidence, live-call history, fresh-reader corrections, and verification boundaries.

The representative [three-spread PDF](../data/exports/m7-proof/representative-spreads.pdf), [contact sheet](../data/exports/m7-proof/contact-sheet.png), [candidate Bible](../data/exports/m7-proof/candidate-bible.json), and [review package](../data/exports/m7-proof/final-review-package.json) are available locally. The [ten-technique proof book](../data/exports/m5-proof/techniques.pdf) and [real-silhouette flow proof](../data/exports/m5-proof/subject-flow/spread.pdf) cover the advanced renderer. The source scenarios use attributed public photos and explicitly original fixture copy.

The full suite passes **217 tests** in `clinic` (Python 3.13.14). There are **215 generated schemas**, all 21 operations execute, lint/formatting pass, the 93-package Linux lock is consistent, and installed dependencies have no broken requirements. Chrome and Streamlit checks cover the actual stored M7 project without triggering calls or writes.

All three representatives pass execution checks, preserve source derivations, and have recorded artistic/fidelity revision requests. The final package is pending, not approved. Formal Tier 1/Tier 2 datasets and gates are undefined in the supplied plan; no assertion is made that those unspecified benchmarks passed. R1 artistic review and final identity approval are still required before claiming M7 artistic acceptance.

## Remaining scope

M11 reference/skill ingestion remains flagged off, and M12 blind professional evaluation is unimplemented. Model critics and technical checks do not establish professional artistic or press approval.
