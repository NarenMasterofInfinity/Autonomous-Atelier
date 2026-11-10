# M10A — Editorial visual quality

Latest deliverable: the [revised twelve-page magazine](../data/exports/m10a/program-issue-v3/magazine.pdf), preserving the original copy and pictures across five selected visual families. The [composition-fix record](m10a-composition-fixes.md) is the current issue list, mechanism, verification and limitations. M11/M12 remain held.

This record preserves the initial atlas/typography pass and its screenshot-conditioned trial; the linked composition-fix record describes the current implementation.

Understood as: build substantially more authored visual references like the accepted `portrait-06`, repair typography, then evaluate studio generation against the stronger reference collection. The user prioritizes visual quality comparable to publications such as Citizen, accepts the existing source-reference collection, and wants later styles to be addable. Copy, sequence, picture-selection behavior and the M11/M12 hold are preserved.

## Delivery gates

1. Build twelve new authored editorial studies across ten visual families, using real source photographs and exact source-bound copy. Retain the accepted flagship as the baseline. Each study has a full spread, native detail, editable scene, PDF and explicit authorship/review state.
2. Repair the typography controls these studies need: tracking, alignment, per-style variable axes, pinned italic face selection, outline painting and a scale-preserving display fit policy. Preserve native shaping and PNG/PDF agreement.
3. Publish a versioned, extensible manual reference atlas. A technical capability demonstration is not counted as an artistically approved style. No owner approval is inferred.
4. Connect suitable atlas examples to studio composition and run an actual generation trial. Inspect its full spread and native details against the previous output and references. Record weak outcomes rather than claiming that tests establish professional quality.
5. Verify the affected renderer, source coverage, export and UI behavior; retain failed studies and a short lessons record.

This is an implementation pass in the existing `clinic` environment. No automatic M11 website ingestion/skill generation or M12 expert-panel evaluation is activated. Reference study and rendering run locally; any configured-provider trial uses the existing durable gateway and prior public-photo/proof upload authorization.

## Reference collection

The [reference book](../data/exports/m10a/m10a-v3/references.pdf) contains twelve new authored 420 × 297 mm spreads. The [contact sheet](../data/exports/m10a/m10a-v3/contact-sheet.png) shows the collection; each spread's folder retains its PDF, PNG, source-bound editable scene, render metadata and frozen family evidence. The accepted M7 flagship remains a separate benchmark.

The M7 flagship is the user's accepted [portrait-06](../data/exports/flagship/portrait-06/spread.pdf). The earlier generated baseline is retained in the [M8 candidate book](../data/exports/m8-proof/m8-live-v3/candidates.pdf). These let a reader compare authored targets with actual generated layouts.

| Visual family | Studies | Main compositional mechanism |
| --- | --- | --- |
| Foreground depth | 01 | Registered photograph, monumental type, foreground subject |
| Photo overlay | 02, 12 | Type occupies photographic pixels in deliberate contrast zones |
| Monumental type | 03 | Display type establishes the spread's physical structure |
| Editorial serif | 04, 11 | Large serif or true italic, contrasted with measured reading copy |
| Outline hybrid | 05 | Native outlined and solid words share a photographic field |
| Image lettering | 06 | A real terrain photograph fills glyph outlines |
| Contour flow | 07 | Reading text responds to an actual alpha silhouette |
| Editorial collage | 08 | Related photographic crops form a layered composition |
| Reversed field | 09 | Light italic typography inhabits a dark photograph |
| Directional type | 10 | Rotated display changes the reading route |

These are ten manually curated design families, not ten owner-approved styles or automatically learned skills. The original twenty external references from Citizen, 413/Port and Guggenheim remain the source registry. No automatic ingestion or M11 skill generation was added. Family capability IDs describe relevant mechanisms; they do not certify that every listed operation appears in each study.

Four studies (01, 02, 05, 11) have explicit **model visual review**, with reviewer and limitations saved. Eight remain `authored_for_review`; all twelve have `human_approval=false`. A fresh-context visual reader found the launch overlay strongest among the inspected examples. The portrait studies retain a conspicuous fade, detached small title words and some photograph/type clutter. Those findings remain in the reference records. This is a richer starting library, not a claim that the collection has reached Citizen's quality.

## Typography and composition

Native paragraph rendering now supports point tracking, left/center/right alignment, per-style variable axes, fill/stroke combinations and an actual pinned Newsreader italic face. The catalog has five pinned faces, including two variable Newsreader faces. Native and vector outline paths resolve the same per-style axes. Style-sensitive caches now follow typography changes instead of reusing stale glyphs or advances.

Display treatments can declare a minimum size. The planner rejects an undersized frame instead of quietly weakening a large title. The M10A profile preserves at least 80% of the largest intended display size and supplies native word dimensions at four headline sizes. Failed-fit feedback includes the allocated frame and required unwrapped line box. After the trial exposed repeated serif-fit errors, the studio profile `m10a-atlas-v2` also added 90/180 pt measurements for the paired body and italic faces. Native-fit tests cover those per-face samples. The saved live trial retains its original headline-only material table; its inputs were not changed during generation. Source coverage, reading-size floors and the frozen original copy remain enforced.

Raster-derived silhouettes now normalize pixel necks and discard degenerate line specks before shape flow. Authored vector-path validation remains strict. This fixed a real Earth-alpha contour failure encountered while building the references.

## Studio connection in the first trial

The studio's six-candidate form exposes reviewed authored references. The worker freezes the selected evidence and supplies its rendered images, composition rules, suitability and limitations to the configured provider. It withholds authored coordinates. Reference images are separate from authorized story-photo handles and cannot become story assets through the compiler.

The live trial uses the same portrait story and photograph as the earlier issue. Its four style examples are studies 01, 02, 05 and 11. It runs the existing two-concept, six-variation tournament through the durable gateway, with native 300 PPI constraints and bounded repairs. Picture selection was not changed. The existing provisional identity still contains measured-grid/open-margin guidance; this is retained as a known influence rather than edited inside a frozen experiment.

The first run, `m10a-studio-v1`, exhausted three bounded attempts before rendering: large title frames were too small for the native line boxes. Its proposals and errors are retained. The second run, `m10a-studio-v2`, added measured word dimensions and actionable fit feedback. Neither critic preference nor technical acceptance constitutes expert-house or owner approval.

## Generation result

The [six-candidate PDF](../data/exports/m10a/m10a-studio-v2/candidates.pdf), [contact sheet](../data/exports/m10a/m10a-studio-v2/contact-sheet.png), [tournament evidence](../data/exports/m10a/m10a-studio-v2/tournament.json) and [technical verification](../data/exports/m10a/m10a-studio-v2/verification.json) are saved. Individual candidate folders contain the full render, PDF, scene, compiled concept, render metadata and critic review.

The run completed six candidates and five comparisons through 27 instrumented calls: one concept-direction call, nine composition calls including three repairs, twelve critic calls and five comparisons. Its minimum geometric separation was 0.1466, exceeding the existing 0.035 diversity threshold. All six preserve exact source partitions, embed their PDF fonts, use 420 × 297 mm PDFs, and meet at least 300 native source PPI. Replaying the finished verifier exported and checked the evidence with **zero new provider calls**.

**All six received artistic `REVISE`.** The selected [serif spread](../data/exports/m10a/m10a-studio-v2/m10a-studio-v2-c1v3/spread.pdf) is the least disrupted reading arrangement, but retains a detached image/title split and substantial empty space. The tournament state is `revision_required`, with no owner approval. Own inspection of all six full spreads agreed that the generated set has not reached the authored atlas, much less established professional-house quality.

A separate fresh-context model reader found the selected spread understandable on its own, with readable body columns and a clear hierarchy. It also noticed the widely separated title words and collisions/hidden lettering elsewhere on the candidate board. That supports the selected spread's basic readability; it does not establish the more ambitious image/type integration target or professional approval.

| Candidate | Visible issue retained in the negative corpus |
| --- | --- |
| c1v1 | HUMAN and THE collide; the main arrangement remains a photograph beside a title. |
| c1v2 | The second reading column is obscured by the foreground portrait. |
| c1v3, selected | Serif hierarchy reads more clearly, but image/type integration and use of space remain weak. |
| c2v1 | Title reading order is fragmented; HUMAN collides with the deck. |
| c2v2 | The foreground subject hides most of HUMAN and other title words. |
| c2v3 | Large serif/outline words cross the image with uneven contrast and a disjointed title sequence. |

The reference/typography foundation is delivered; **M10A visual acceptance remains open**. More reference screenshots alone will not close this gap. The next composition pass must realize a selected family's actual relationships, protect visible title words and reading copy, and replace the inherited open-margin direction with the intended visual identity. Technical text presence and geometric diversity cannot substitute for those checks. This remains M10A work; M11/M12 are still on hold.

## Verification of the initial atlas pass

The [artifact verification report](../data/exports/m10a/m10a-v3/verification.json) checks all twelve source partitions, transitive proof bindings, execution verdicts, physical PDF dimensions, embedded fonts and PNG/PDF rendering. Raw pixel diagnostics are retained. The initial 144 DPI near-pixel threshold failed on the detailed globe photograph (0.9128 within ten channel levels). After isolating image-resampling differences between Cairo and MuPDF, the check added a common 72 DPI box-filtered comparison while retaining the raw mean-error limit and diagnostics. This is an investigated rendering regression check, not a preregistered independent benchmark or an aesthetic score.

Some authored screen studies use original photography below 300 PPI at their selected frame sizes; the report gives the actual values. They are not M10 print-approved proofs. The studio trial enforces the separate native 300 PPI condition. Source-bound editable scenes retain every character; outlined typography can become PDF paths rather than extractable PDF text.

Chrome opened the actual atlas, displayed all twelve studies and downloaded the complete 111,496,827-byte reference book byte-for-byte, with no UI exception. After restarting the server to load its new module, Chrome also verified the reference-selection form. The atlas is the default studio project.

After generation completed, Chrome displayed the saved tournament and downloaded its six-candidate PDF byte-for-byte. The studio server and background worker are running again, with no queued or running commands left by the verification pass.

The complete suite passed **241 tests** (7 upstream library warnings) in `clinic` after the main implementation changes. Subsequent typography, tournament and UI checks passed together (16 tests), including new worker-transport and per-face measurement regressions; the distinct passing test count is 243. There are 247 exported schemas. Ruff lint and formatting pass. Reference-only conditioning tests reject unreviewed/cross-project evidence, preserve story-photo handles and withhold scene coordinates. Worker tests cover both selected references and the legacy empty-selection path. Chrome also confirmed that the existing `m8-proof` magazine and production-export views remain readable.

Across the twelve atlas proofs, raw PNG/PDF mean channel error ranges from 1.171 to 2.855/255; the worst common-72-DPI fraction within ten channel levels is 0.9445. Native source resolution reaches as low as 152.8 PPI in an authored study, reinforcing that the atlas is a visual study collection rather than a cleared production issue.

## Reproduce and extend

Use `conda activate clinic`, then run these from the repository root:

```bash
python -m scripts.install_m10a_font
python -m scripts.build_m10a_references --run m10a-v3
python -m scripts.verify_m10a_references
python -m scripts.verify_m10a_generation --run m10a-studio-v2
python -m pytest -q
```

The first command verifies or downloads the small hash-pinned italic font. The builder and reference verifier make no model calls. The generation verifier uses the configured provider and can incur charges; completed work is resumed from saved evidence. Run builders and live trials with the background worker stopped so its recovery scan cannot mistake an active provider attempt for an interrupted process. Never replay an ambiguous submission.

On this workstation, provider settings come from the repository's existing `.env`, read through `load_settings`; no credentials belong in proof exports. Stop the worker with Ctrl+C in its terminal before running a live verifier. After it finishes, restart with `python -m editorial_studio.worker`. Open the atlas with `python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501`, visit `http://127.0.0.1:8501`, and choose Spread Studio. The default project is `m10a-references`. The [main runbook](../README.md) describes other projects and UI actions.

Add a versioned family in `config/editorial_families.yaml`, bind it to existing external-reference IDs and relevant capabilities, author a source-bound proof, and add it to a new atlas version. Review its actual rendered spread before admitting it to generation conditioning. The authoring module is an explicit implementation of studies, not a generic automatic style extractor. Changes to composition should use a new run/version; existing negative studies are preserved in `m10a-v1` and `m10a-v2`.

## Lessons for the next visual pass

- **Operation coverage masquerading as art direction:** a renderer can support complex effects while generation repeatedly chooses detached image/title rectangles. Gate new families on an authored full spread, native details and explicit visual review; count technical proofs separately.
- **Point sizes without physical allocation:** the first trial repeatedly proposed large type in cramped frames. Supply measured font line boxes and reject undersized frames, rather than accepting a smaller title as a repair.
- **Source coverage without reading hierarchy:** exact characters alone cannot prove that a split title reads in order or that lettering belongs to the photograph. Inspect complete title sequence and photographic integration in actual renders before promoting a generated result.
- **Geometric distance without design variety:** the six candidates exceed the existing distance threshold while repeating conventional image/text separation or introducing unreadable overlaps. Require a selected family's visible compositional relationships before treating a candidate as a useful variation.
- **A self-confirming quality score:** the builder, critics and selector share a model ecosystem. Preserve raw renders and independent source/geometry checks, and leave professional and owner judgment explicit. A tournament winner is only the preferred candidate within that set.
- **A detail crop that misses the decision:** several trial critiques explicitly could not judge body detail because the supplied crop showed the flag or photo edge. The next quality pass needs native crops of the display, reading copy and image/type junction; uninspected detail must remain unassessed.
