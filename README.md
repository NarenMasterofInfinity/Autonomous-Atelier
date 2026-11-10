# Autonomous Editorial Studio

A local Python and Streamlit implementation of the [v6 plan](docs/implementation-plan-v6.md), implemented through M10 with an M10A visual-quality pass. It generates six-candidate concept tournaments, builds twelve-page issues with visual pacing history, and exports vector production proofs after native-resolution, bleed, fold and font checks.

M10A adds [12 authored reference spreads](data/exports/m10a/m10a-v3/references.pdf) across ten visual families, now captured as executable composition programs. The studio preserves their typography, palette, image/type relationships and reading areas while fitting exact story copy. See the [revised twelve-page magazine](data/exports/m10a/program-issue-v3/magazine.pdf) and its [overview](data/exports/m10a/program-issue-v3/contact-sheet.png). It preserves the original stories and pictures while selecting five visual families with no adjacent family repeats. Other proofs include the [new portrait compositions](data/exports/m10a/program-fit-v5-portrait/contact-sheet.png), [longer-title adaptations](data/exports/m10a/program-fit-v6-new-title/contact-sheet.png), and [lunar adaptations](data/exports/m10a/program-fit-v6-moon/contact-sheet.png). The [issue/fix record](docs/m10a-composition-fixes.md) explains the mechanism and verification. M11 and M12 remain on hold.

The earlier [screenshot-conditioned trial](data/exports/m10a/m10a-studio-v2/candidates.pdf) remains a negative corpus. The new program workflow fits or rejects a captured design rather than redrawing it from a screenshot. Eleven compositions across three source/copy cases pass the source, layout-admission and export checks. These remain visual-review proofs; technical checks and model preference do not establish professional or owner approval.

The accepted M7 benchmark is [The human scale of space](data/exports/flagship/portrait-06/spread.png), also available as a [PDF](data/exports/flagship/portrait-06/spread.pdf) and [editable scene](data/exports/flagship/portrait-06/scene.json). It is an authored composition rendered through the production compiler: registered photography and foreground silhouette, large display words, and two source-bound reading columns. See the [flagship work record](docs/flagship-worklog.md) for verification, references, and remaining limitations. It establishes one visual benchmark; it does not prove autonomous art direction.

**Technical verification is separate from artistic approval.** The user accepted the M7 flagship benchmark and authorized M8–M10. Older representative packages retain their pending review history. Historical M9 issues retain model-generated scenes and authored repairs. The current M10A issue uses reference-program adaptations; owner approval of the new issue or print proof is not inferred. Formal Tier 1/Tier 2 benchmark definitions are absent from the supplied plan.

Open the [six-candidate book](data/exports/m8-proof/m8-live-v3/candidates.pdf) and the [M8–M10 verification record](docs/m8-m10-worklog.md) for current issue and production artifacts. Earlier [M7 representatives](data/exports/m7-proof/representative-spreads.pdf) and [technique proofs](data/exports/m5-proof/techniques.pdf) remain available.

## Run in clinic

This runbook assumes this workstation's configured `clinic` environment and local acceptance data. Generated proofs, fixtures, and weights are ignored by Git; the artifact links refer to this workspace. The native specifications and locks document prerequisites rather than providing a fresh-machine installer.

From the repository root:

```bash
conda activate clinic
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Run the separate worker in another terminal:

```bash
conda activate clinic
python -m editorial_studio.worker
```

The default project is `m10a-references`. Use Inputs → **Compose from the editorial reference library** to fit a story into selected captured designs. The art director can select and review admitted renders; turn that checkbox off for local-only fitting. New results appear first in Spread Studio. **Explore new layout directions** retains the separate experimental tournament. Choose `m8-proof` for the existing issue, `flagship-proof` for the accepted M7 visual study, or `m7-proof` for older representatives. Refreshing, inspecting, and downloading never issue model calls. `python -m editorial_studio.worker --initialize` creates storage without a provider call.

**Build a twelve-page issue** also enables reference-led composition when the library is available. It selects a varied sequence jointly, fits the wrap cover for front/back page roles, and preserves admitted pages through issue assembly; a native recheck does not shrink or recompose those scenes. The print-preflight stage remains separate.

- **Inputs:** upload a photo story with its source and credit; choose a provisional identity; queue creative composition with a direction. Composition sends the selected copy and images to the configured provider and can incur charges.
- **Spread Studio:** inspect source coverage, feasibility maps, cutouts, graph sketches, rendered spreads, overlays, native pixel crops, three critics, technique proofs, and final-review packages. The canvas viewer queues opacity/position/rotation edits and snapshot restoration.
- **Logs & Telemetry:** inspect requests, uploaded image previews, visible responses, usage, estimated cost, timing, local tools, decisions, and recovery. Hidden reasoning is never displayed or inferred.
- **Export:** download vector proofs, candidate books, twelve-page reader PDFs, and editable scenes. Queue a local production check for a selected issue, then download its production PDF and preflight report. Hard findings block the production PDF.

Provisional approval binds its exact three baseline proofs. Final approval additionally binds the identity snapshot, representative scene versions, critic evidence, and all ten technique proofs inside one transaction. It requires a reviewer, note, and technique-approval acknowledgment. Approving despite model revision requests needs an explicit override. Changed or missing evidence cannot pass as the reviewed set.

R1 is M5's renderer checkpoint. Review its ten technique proofs in **Spread Studio → R1 technique proofs**. Provisional approval is recorded under **Identity, proofs, and references**; the final review is recorded under **Final creative identity** after inspecting the representative spreads and their critic findings.

## Implemented subsystems

| Milestone | Behavior |
| --- | --- |
| M0–M2 | Normative contracts, 21-operation validation, durable gateway/worker, continuous canvas, pinned typography, executable design tokens, manual references, provisional identity proofs. |
| M3 | Immutable story revisions and derived-text spans; placement coverage; saliency, face and negative-space maps; sharpness/noise/contrast diagnostics; crop-aware effective PPI; inspected conditional FSRCNN upscaling. |
| M4 | Prompted CPU MobileSAM behind a backend interface; trimap/guided alpha refinement; cutout assets and edge diagnostics; real-photo depth proof. |
| M5 | All 21 execution operations; adaptive Bézier arc-length lettering; shaped-glyph outlines/transforms; irregular flow with holes and exclusions; text masks, Boolean paths, gradients, blending and raster effects; typed spatial anchors; ten technique proofs. |
| M6 | Asset-gap detection, contextual image generation through the gateway, explicit raster/vector classification, Potrace tracing, integration patches, and three inspection scales. |
| M7 | Story-driven concept graphs, graph sketches, compiler/source reconciliation, combinatorial typed recipes, bounded repairs, execution/artistic/fidelity critics, comparative stagnation, representative proof packages, and final identity review controls. |
| M8 | Two concepts × three structurally distinct spatial variants, frozen source/identity inputs, anonymous visual knockout selection, and a six-candidate book. |
| M9 | Six stories mapped to twelve physical pages, cover/printer mapping, cumulative visual history, measured pacing, versioned Bibles, and source-bound issue revisions that retain unchanged scenes. |
| M10 | Snapshot-bound production preflight, native sampling lineage, fold/bleed checks, embedded subset fonts, twelve A4 pages with 3 mm bleed, and normalized PDF-to-canvas raster comparison. |

[Design tokens](config/design_system.yaml), [font pairings](config/font_pairings.yaml), and saved typography snapshots keep font, size, color, spacing, and baseline decisions reproducible. Default body copy is 11 pt. The measured baseline grid has a declared 0.01 mm Pango quantization tolerance. Infeasible text reports its unplaced source offset; it is not silently discarded or shrunk. Shaping coordinates are in layer source space, with saved affine transforms mapping them onto the spread.

New creative scenes enforce their source derivations. A title or body can occupy several frames, with exact ranges that partition every original character once, including whitespace. Custom frozen typography supports different display and reading sizes; reading copy retains the identity floor. Changing source copy requires a provenance-aware editorial revision. Coverage proves exact text in saved layers; readability and intentional occlusion still require visual review.

Concept sketches are blocking diagrams of allocated regions, photographs, and labels. Their text rectangles represent frames, not expected solid ink. Fidelity inspection checks realization against that proposal; it is not an independent design-quality benchmark. Artistic critics are model judgments, not blind professional reviewers. The fictional interview and other acceptance copy are explicitly fixture material.

The [manual catalog](config/references.yaml) retains 20 inspected spread examples and series previews from Pentagram's [Citizen](https://www.pentagram.com/work/citizen), [413](https://www.pentagram.com/work/413), and [Guggenheim](https://www.pentagram.com/work/guggenheim) galleries. They remain study references, with filenames, gallery positions, source URLs, observations, and preview hashes. Automatic reference ingestion and skill generation remain off.

## Environment and verification

Verification uses Python 3.13.14 in `clinic`. [pyproject.toml](pyproject.toml) and [uv.lock](uv.lock) pin Python dependencies; the lock targets Linux x86_64. [Native specifications](config/render-environment.yaml), [rendering-library hashes](config/render-native-lock.yaml), and [font hashes](config/fonts.yaml) describe the tested workstation. A different native build requires revalidation. `python scripts/install_fonts.py` installs the pinned system fonts when available.

MobileSAM uses a pinned upstream revision and a 40.7 MB checkpoint; FSRCNN x2 weights are 39 KB. Neither backend downloads models during UI refresh or inference. Their configuration and hashes live in [segmentation.yaml](config/segmentation.yaml) and [photo_pipeline.yaml](config/photo_pipeline.yaml). Potrace is extracted into `.runtime/potrace/` and hash-checked by [artifacts.yaml](config/artifacts.yaml).

Credentials come from ignored `.env`: `OPENAI_API_KEY` or `OPENAI_KEY`, and optional `OPENAI_BASE_URL`. Other existing variables remain untouched. [config.yaml](config.yaml), [creative.yaml](config/creative.yaml), and [pricing.yaml](config/pricing.yaml) control model settings, bounded repair budgets, prompts, and versioned usage estimates. An enlarged image retains its original sampling-risk assessment; pixel count alone never grants print approval.

```bash
python -m pytest -q
python -m editorial_studio.contracts.export
```

With the separate worker stopped, the proof scripts reproduce saved acceptance work:

```bash
PYTHONPATH=. python scripts/verify_m3.py
PYTHONPATH=. python scripts/verify_m4.py
PYTHONPATH=. python scripts/verify_m5.py
PYTHONPATH=. python scripts/verify_m6.py
PYTHONPATH=. python scripts/verify_m7.py --run-prefix m7-v4 --portrait-run m7-v4-case-1
```

For the authored flagship, the pinned photograph, fonts, and licenses can be installed and verified separately. Rendering is local by default; `--review` enables paid visual-critic calls through the gateway. Use a fresh run ID for each composition revision:

```bash
python -m scripts.install_flagship_assets
python -m scripts.build_flagship --run portrait-local
python -m scripts.verify_flagship --run portrait-local
```

The [flagship configuration](config/flagship.yaml) holds its source copy, layout, font pins, and asset URLs. The render also needs the existing pinned MobileSAM checkpoint and native environment. The local verifier checks the committed artifacts, exact source ranges, embedded PDF fonts, extractable text, physical page size, and PNG/PDF raster agreement. It makes no provider calls.

M3 expects the attributed sample-photo manifest under `data/fixtures/photos/`. M4 needs the pinned local checkpoint. M6 and M7 can incur charges for uncached requests; their saved inputs and completed stages are reused. Bounded repairs preserve the last technically valid revision when a later attempt fails. Earlier mismatched story/photo proofs remain under `data/exports/m7-negative-story-photo/` as negative cases.

Known Responses IDs can be retrieved through the recovery controls. Ambiguous submissions remain blocked from automatic replay. All local data, models, previews, and exports are ignored under `data/` or `.runtime/`; `.env` remains ignored and untracked.

The [M8–M10 record](docs/m8-m10-worklog.md) documents reproduction commands, verification results, negative proofs, and editorial limitations. M11 reference ingestion/skill generation stays flagged off; M12 blind professional evaluation remains unimplemented. Production proofs use RGB and are not PDF/X certification or printer-specific press approval.
