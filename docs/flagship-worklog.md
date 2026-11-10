# Flagship: the human scale of space

The current study is [portrait-06](../data/exports/flagship/portrait-06/spread.png), with a [PDF](../data/exports/flagship/portrait-06/spread.pdf), [editable scene](../data/exports/flagship/portrait-06/scene.json), and [verification report](../data/exports/flagship/portrait-06/verification.json). It is an authored composition built through the production compiler and renderer. It addresses the user's request for creative improvement and integrated photography; it does not establish autonomous art direction or advance M8.

## Direction and gates

The 2615 × 3269 NASA original replaces the 512-pixel Eileen Collins fixture. [NASA's source record](https://images-api.nasa.gov/search?nasa_id=S99-00858&media_type=image) identifies the photograph. Citizen's portrait/type interaction (`citizen-14`, in the [reference catalog](../config/references.yaml)) informs scale and depth; its artwork is not reused. The orange suit determines the accent, the portrait extends into the bleed, and one registered foreground silhouette interrupts a small part of the headline. The face and complete words remain readable.

The scene retains independent image and source-bound text layers. The PDF embeds its fonts and retains extractable text. Every source character belongs to one frame, including whitespace between fragments. Inspection covers full spread, thumbnail, reading detail, and compositing edges. Model judgments and software checks support the visual decision; owner approval remains open.

## Baseline

The [M7 portrait](../data/exports/m7-proof/case-1/spread.png) remains the negative comparison. Its execution checks passed, while artistic and fidelity reviews requested revision. Earlier flagship drafts are preserved under `data/exports/flagship/`: portrait-02 shows the first composition and broken helmet mask; portrait-03 retains the failed hole-fill-only attempt; portrait-04 shows recovery after additional segmentation anchors; portrait-05 received the first complete critic acceptance. Portrait-06 applies the cold reader's caption correction and reconciles the saved palette with the actual colors.

## Verification

The full suite passed 224 tests, with seven upstream MobileSAM/timm warnings. The subsequent M7/UI/schema checks passed 47 tests after the planner prompt and copyfit-table update. There are 219 generated schemas; lint and formatting pass. The planner's new prompt has not yet been evaluated in a live autonomous composition.

Portrait-06 has execution, artistic, and fidelity ACCEPT verdicts. Four gateway calls cover two reviewed revisions; no concept-generation or image-generation call was used. The saved PDF measures 420 × 297 mm, embeds five font subsets, and retains all 24 headline, 77 deck/caption, and 925 body characters. Independent PDF rasterization has mean channel difference 1.57/255 from the PNG, with 97.74% of pixels differing by at most 10 in every channel. These are export checks, not aesthetic scores.

The image-only fresh reader judged portrait-05 to stand on its own and requested a clearer subject credit. The final credit uses larger, dark lettering. The model's remaining artistic note is a slightly uneven column ending. Its fidelity note confuses native font inset with a change in text-frame position; the saved frames match the compiled regions. Neither note blocks inspection of this study. The earlier M7 package and its pending R1/final owner review remain intact.

Chrome opened portrait-06 as the default in the actual local app and inspected Spread Studio, Export, and Logs & Telemetry without exceptions, queued jobs, or new model calls. The browser's PDF download matched the committed proof byte-for-byte. The initial browser attempt exposed a stale viewer process; restarting it resolved the mismatch. The [browser record](../data/exports/flagship/portrait-06/browser-check.json) and [screenshot](../data/exports/flagship/portrait-06/studio.png) preserve the successful check. Replaying the saved flagship run also left its four completed provider calls unchanged.

## Lessons and next gate

| Observed failure | Reusable gate |
| --- | --- |
| Image allocation alone did not create a composition. | Establish how the crop, subject, type scale, palette, and reading sequence relate before adding effects. |
| A mask passed numeric checks while breaking the helmet surface. Hole filling alone did not repair exterior-connected gaps. | Inspect opaque dark materials and silhouette edges at native scale. Add positive/negative anchors first; use explicit solid-subject cleanup only when appropriate. Preserve the failed render. |
| One complete derivation per frame constrained typography and columns. | Permit exact source partitions; reject gaps, overlaps, unknown styles, and reading type below the identity floor. Freeze font files, axes, and styles with the scene. |
| The supplied frame diagram was mistaken for expected ink bounds. | Distinguish frame placement from native font inset when reviewing fidelity. Judge visible ink separately. |

Keep and iterate in place. Preserve the compiler, source partitions, pinned typography, registered photo/silhouette frames, and native crop checks. Drop the single-body-frame instruction and obligatory texture. The next creative gate is a new story and photograph composed without these authored coordinates, judged from the actual page before widening to candidate tournaments.

This study is not a holdout: its designer also chose the brief and configuration; the model critics receive the concept rationale. The fresh image-only read removes that rationale but remains one model review, not independent professional evaluation. The baseline also differs in source resolution and copy, so this is not an experiment isolating the compiler's effect. A future generalization claim needs unseen briefs and blind external editorial judgment.

The consistency audit treats [flagship.yaml](../config/flagship.yaml) as the authoring source and saved concepts/scenes as immutable evidence snapshots. Historical milestone counts remain historical. The app's default-project runbook now points to the actual default; no source-of-truth restructuring was needed.
