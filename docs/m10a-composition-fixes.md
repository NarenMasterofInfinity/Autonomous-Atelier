# M10A — Make the references executable

Understood as: diagnose the weak generated spreads, preserve the characteristics of the reference collection the user likes, and implement and verify the composition changes. Picture selection, original copy and the M11/M12 hold stay in place.

## Issues and remedies

| Observed failure | Cause in the current path | Remedy in this pass |
| --- | --- | --- |
| Strong references become conventional photo/text splits | The composer sees screenshots and prose, then invents all geometry again | Captured twelve editable reference programs; the model selects rendered programs instead of redrawing their coordinates |
| Type becomes a label or loses its hierarchy | Copyfit optimizes containment without preserving the reference's display scale | Fit exact word groups against native fonts within a bounded scale interval; reject an incompatible program |
| Words collide, disappear behind a subject, or reverse the reading order | Source coverage checks character presence, not visible reading | Preserve source-ordered title slots; inspect actual rendered text visibility and ink intersections |
| Body moves into photographs | Fold repair shifts frames independently | Keep the program's reserved reading areas; fit or reject, without moving them independently |
| Excess empty space replaces a deliberate composition | The inherited identity asks for open margins and measured grids | Use the selected program's palette, image field, display proportions and reading geography |
| Source resolution shrinks a photographic field | Print sizing is mixed into visual composition | Keep original pixels and the reference geometry; report sampling separately from later print approval |
| Many box arrangements still look alike | Geometric distance does not represent technique | Track actual programs/families and their realized layering, masks, contours and typography |
| A poor set still has a winner | Selection is relative, without an admission gate | Exclude failed adaptations and expose no-admissible-result explicitly |
| Critic detail images miss the typography | One generic crop is used for different decisions | Export native display, reading and image/type-junction crops |
| Fitting changes a one-line title into an unintended block | Containment is checked without preserving line rhythm | Capture native line counts and fit within that rhythm |
| Italic letters crowd an edge despite passing copyfit | Logical advance width differs from visible ink | Fit actual ink bounds, including stroke and an em-relative optical allowance |
| A planet appears once in every image-filled word | Each clipped image independently fits the same complete photograph | Use one registered photographic plane across the letter windows when native source resolution permits it |
| Generic criticism conflicts with the chosen reference language | The critic has no target-style context | Compare the adaptation with its actual source reference, while checking readable copy and visible defects independently |
| A strong spread changes again during magazine assembly | The issue builder recompiles selected geometry and applies image resizing | Route issue composition through admitted reference programs and bind the selected scene unchanged |
| Independently selected pages repeat the same serif treatment | Each story selector optimizes its own favourite without seeing its neighbours | Select the issue sequence jointly from admitted scenes, favouring five families, avoiding adjacent family repeats, then preserving individual model preferences |
| A spread title falls across the wrap fold or onto the back cover | Covers reuse spread topology | Derive a cover-role program before fitting: full headline and principal picture on front/right page 1, reading copy on back/left page 12 |
| Old placement instructions contradict a selected complex reference | Generic issue mandates survive selection of a different composition | Bind the composition mandate to the selected captured program; preserve story order, narrative phases and goals |
| A cover has an apparently unfinished lower block | Moving reading copy to the back exposes the inherited paper colour below the front photograph | Continue a uniform photographic edge into the cover field, without stretching or replacing the image |
| A short paragraph tail is stranded at the next column | Body allocation favours balanced character counts | Prefer a paragraph boundary when both native reading frames can hold the exact text |

## Mechanism

An authored spread becomes a source-free composition program: exact typography, palette, frame relationships, gradients, clipping, contour relationships, rotation and layer order. Original text and photograph bindings are replaced by typed story-input slots. Each title slot captures its native line count and ink overhang; each photo slot captures its ordered input index, crop fraction and face-visibility constraint. The studio fits new copy with native shaping, preserving exact source characters and reading-size floors. It keeps the source composition intact instead of asking a model to redraw it from a screenshot.

The frozen `programs.json` files contain the complete executable proposals and characteristics. These include font faces, sizes, variable axes, tracking, alignment, paint modes, colours, rotations, reading regions, source layer order, actual display ink area, photo/ink overlap and background fraction. Actual alpha-derived contour flow and glyph clipping are recompiled against the target story assets. The source reference's photographs are never silently substituted into another story.

Headline fitting retains at least 72% of each captured display size. The optical allowance is the source overhang plus 0.15 mm and 2% of its em size; this avoids rejecting different letter shapes for harmless optical overshoot. It does not permit text collisions or missing words. Body type keeps the identity floor, with no geometric scaling. Reading frames are not shifted independently. A contrast failure in reading copy can receive one bounded palette-matched backing field, without moving or shrinking the copy.

Admission checks compare temporary black/white recolourings through the actual renderer. This measures how much text survives foreground alpha and clipping; separate word masks include ink outside the page. Body/deck need at least 99.5% visible ink, and each title word at least 70%. Text collisions and local contrast have explicit diagnostic gates. Large textured image-lettering contrast can be flagged for review rather than treated as ordinary flat text. These are engineering safeguards, not an aesthetic score.

The adapter also rejects loss of display mass, a substantial loss of actual image/type overlap, and increased empty background coupled with weakened display. It preserves deliberate reference whitespace instead of globally filling every gap.

Programs are proposals, not universal templates. Incompatible copy length, missing alpha, low source detail or failed visibility must produce a recorded rejection. Another compatible family can then be used. No fallback silently shrinks the type or creates a detached two-column layout.

## Results

The complete revised magazine is [program-issue-v3/magazine.pdf](../data/exports/m10a/program-issue-v3/magazine.pdf), with an [overview](../data/exports/m10a/program-issue-v3/contact-sheet.png) and [source/export verification](../data/exports/m10a/program-issue-v3/verification.json). It uses five visual families across six spreads, with no adjacent family repeats: serif cover, foreground-depth opening, serif launch, photo-overlay interlude, image-lettering essay and reversed-field closing. The original six stories, pictures, physical sequence, narrative phases and goals are unchanged. The issue-level model review returned `ACCEPT` with no findings; this remains a model opinion, not owner or professional approval.

A fresh-context reader identified an unfinished-looking cream block below the cover image and a stranded “every detail” at the next launch column. The final pass continues the photograph's uniform black edge through the front cover and keeps the launch paragraph intact. The same reader confirmed both snags resolved with no visible reading blocker in those two revised views. Its remaining note was a faint boundary hairline. The separate cover adaptation review's earlier local white-on-cloud contrast note remains in its saved evidence; acceptance is not a claim of perfect typography.


| Case | Result | Artifacts |
| --- | --- | --- |
| Original portrait, same selected photo and exact copy | Four admissible compositions: depth, monumental, directional and serif; 100% of captured display sizes retained | [Overview](../data/exports/m10a/program-fit-v5-portrait/contact-sheet.png), [PDF](../data/exports/m10a/program-fit-v5-portrait/compositions.pdf) |
| Longer title, “THE PERSONAL SIDE OF EXPLORATION” | Four admissible adaptations on the same portrait/body, preserving reference line rhythm and bounded scale | [Overview](../data/exports/m10a/program-fit-v6-new-title/contact-sheet.png), [PDF](../data/exports/m10a/program-fit-v6-new-title/compositions.pdf) |
| Different lunar photograph and five-word title, “A WORLD BEYOND THE FRAME” | Three admissible compositions from twelve programs; nine rejected for concrete compatibility/readability failures | [Overview](../data/exports/m10a/program-fit-v6-moon/contact-sheet.png), [PDF](../data/exports/m10a/program-fit-v6-moon/compositions.pdf) |

The selected depth composition in the preceding `program-fit-v5-new-title` live run received model `ACCEPT` with a minor right-margin note. Its review used the actual source reference plus full and native display, reading and junction views. This is a reference-aware model opinion, not blind professional evaluation or owner approval. The later v6 runs are local verification runs and do not fabricate a new model review. Earlier standalone and reference-aware critiques remain saved, including `REVISE` results.

A fresh-context model reader found the new portrait board's structural variety stronger than the earlier generated board, and confirmed comfortable native reading detail. It also noted remaining title gaps, occasional face-obscuring treatment and softened photographic detail in some variants. Its image-lettering observation about repeated Earth fragments led to the registered photographic-plane fix. These observations do not make every admissible composition equally strong for every story.

## Verification evidence

The [saved verification report](../data/exports/m10a/program-verification.json) checks eleven admitted compositions across the final cases: exact source reconstruction from saved text layers, fixed frame relationships, body size/transform, headline line counts, physical PDF dimensions, font embedding, raster agreement and pixel-exact native crops. Native source sampling is recorded separately; these are visual proofs, not new M10 print approvals.

The same report audits the six previous generated layouts. It catches the five known mechanical defects: headline collision, body occlusion, title/deck collision, hidden title words and poor outline contrast. It leaves the readable conventional layout mechanically valid. Geometry checks are not asked to certify stylistic ambition.

Final verification passed **254 tests in two batches: 243 core tests and 11 reference-program tests**. All 259 generated schemas match their models. Tests cover different copy/word counts, paragraph-aware partitioning, immutable replay, wrong-project references, no-admissible-result behavior, hidden words, collisions, image-filled source text, shared photo planes, line rhythm, cover page roles, issue-wide family selection and UI queueing without provider calls.

The issue integration test builds twelve physical pages from six admitted program compositions, verifies every selected scene is reused unchanged, and rechecks a reference page without recomposing it. The fixture provider makes only the two architecture/coherence calls; there are no free-form layout-composition calls. The original M9/M10 behavior remains tested when the reference route is not selected.

Chrome verified the actual form, gallery and native-view controls. It downloaded the final 112,172,562-byte twelve-page reader PDF byte-for-byte, with the new issue selected by default, zero submitted jobs and zero provider calls. The worker resumed after provider activity ended, reporting zero missing/corrupt assets and zero interrupted attempts.

The final issue verifier reconstructs exact source characters from saved scenes, checks selected-program bindings, body size, title line rhythm, native crops, embedded fonts, twelve A4 physical pages and cover front/back placement. Five spreads meet the original native raster-agreement thresholds. The launch photograph does not: its 144-dpi mean pixel difference is 3.367 and its 72-dpi fraction within 10 levels is 93.83%. This remains an explicit raster review item, not a strict pass. A separate 36-dpi geometry comparison reaches 96.36%; fine photographic sampling differs between Cairo's preview and the PDF rasterizer. Native image-detail equivalence is not asserted. The original three-case verification retains its stricter raster thresholds.

This is a regression/compatibility matrix built during implementation, not an independently sampled holdout. The designer and scorer share implementation decisions; model review is not an expert panel. The outside design target is the user's positive judgment of the reference collection. Original negatives, intermediate v1–v5 proofs, raw critiques and rejected candidates remain available.

## Use and extend

Open the local studio's Inputs tab and choose **Compose from the editorial reference library**. Select the story, reading identity and reference programs. Art-direction selection is enabled by default; disabling it keeps the run local. The model chooses among admitted rendered compositions and critiques the selected result; it never supplies unconstrained page coordinates. The exploratory free-form tournament remains separately labeled.

New composition results appear first in Spread Studio, with native views and captured characteristics. Export selects one run at a time so accumulated proof books are not all loaded on every refresh. A result with no admissible candidate has no selected program or proof book.

**Build a twelve-page issue** enables the editorial reference library by default when it is available. The architect plans page roles first. Cover-role programs move the full headline and principal photography to front page 1 and reserve back page 12 for reading; incompatible contour/glyph treatments are rejected instead of flattened. After native admission, the issue selector chooses a varied sequence jointly, preserves every selected source scene, and assembles the physical pages. The five-family preference is an explicit design policy, not a claim that five is an aesthetic optimum. Prepared composition studies can be reused after project/story/identity and allowed-reference-subset checks; a changed page role is fitted separately. A story with no admissible program stops the build rather than silently switching to an unconstrained layout. Existing issue pages are preserved during a non-regenerating native recheck. The strict print preflight remains separate.

From `clinic`, with the background worker stopped:

```bash
python -m scripts.verify_m10a_programs --run a-new-run --story portrait
python -m scripts.verify_m10a_programs --run another-run --story moon --title 'A WORLD BEYOND THE FRAME' --live-choice
python -m scripts.verify_m10a_program_outputs --audit-previous
python -m scripts.verify_m10a_issue --run a-new-issue
python -m scripts.verify_m10a_issue_output --run a-new-issue
python -m pytest -q
```

`--live-choice` enables the configured-provider selection/review calls. The issue-build script also makes paid selection/review calls; its saved-output verifier is local. The acceptance script restricts inputs to generated essay fixtures and the pinned NASA sample inputs. Saved completed runs replay without new provider calls. Use new run IDs for changed inputs. Restart the worker with `python -m editorial_studio.worker` afterward.

To add a style, author a valid source-bound reference, add it to an atlas and capture it through the same program mechanism. There are no per-story geometry branches in the fitter. Dedicated fitters are still required for text-on-path or individual-glyph layouts outside the captured rectangular/contour-flow cases. Narrow image textures can retain separate letter windows when a shared plane would fall below the existing native-resolution floor; those cases get a review flag. Automatic external-reference ingestion and the professional panel remain M11/M12 work and stay on hold.

## Lessons retained

The magazine adds two lessons: select neighbouring pages together, and derive a cover role before fitting copy. Native word-count balance must also yield to a clean paragraph boundary when it fits. Continue iterating on this mechanism rather than restarting the renderer.

The main change is executable design intent: preserve proven relationships, fit the content, then admit or reject the rendered result. Keep the authored library, native typography, exact source contracts and negative corpus. Retire screenshot-only conditioning as the default reference-transfer method. Do not confuse preserving a style with inventing a new one, and do not equate a model preference with publication approval.
