# M8–M10 verification

The user accepted the M7 flagship `portrait-06` and authorized these milestones. That acceptance is stored as `milestone_acceptance / m7-owner-acceptance`, with their exact quote and evidence ID, and exported as [owner acceptance evidence](../data/exports/m8-proof/m7-owner-acceptance.json). Older R1 and final-package review records retain their historical status. New issue and production records have `human_approval: false`.

## Outputs

The default app project is `m8-proof` at <http://127.0.0.1:8501>. The four existing tabs expose tournament inputs/selection, issue pacing/history and revisions, telemetry, and production checks/downloads.

- M8 `m8-live-v3`: [six-candidate PDF](../data/exports/m8-proof/m8-live-v3/candidates.pdf), [contact sheet](../data/exports/m8-proof/m8-live-v3/contact-sheet.png), [selection evidence](../data/exports/m8-proof/m8-live-v3/tournament.json).
- M9 `m9-live-v6`: [twelve-page reader PDF](../data/exports/m9-proof/m9-live-v6/issue.pdf), [contact sheet](../data/exports/m9-proof/m9-live-v6/contact-sheet.png), [issue/history/page map](../data/exports/m9-proof/m9-live-v6/issue.json), [independent geometry check and review disposition](../data/exports/m9-proof/m9-live-v6/verification.json).
- M10 `m10-live-v2`: [production PDF](../data/exports/m10-proof/m10-live-v2/production.pdf), [preflight](../data/exports/m10-proof/m10-live-v2/preflight.json), [source binding](../data/exports/m10-proof/m10-live-v2/export.json).

Production remains a proof, not owner approval. Each export binds an exact issue revision and source fingerprint. The current export binds v6 and passes with **zero hard findings**, twelve A4 trim pages, 3 mm bleed, 24 embedded subset font programs and six photographs at 300.00–560.80 native PPI. One warning asks for inspection of display type entering the fold-safe zone; reading text passes the hard clearance check. The earlier `m10-live-v1` remains a valid proof of issue v3.

## M8: distinct candidates and selection

Two frozen concept directions each produce three spatial variants through the existing typed compiler and renderer. All six candidates must pass execution checks and exceed the structural-distance threshold before entering five anonymous image-based knockout matches. The live minimum pairwise structural distance is 0.06885, against a threshold of 0.035. The winner is `m8-live-v3-c2v1`.

Selection is a model preference. The winner retains an artistic ACCEPT and a fidelity REVISE; its original face/helmet metaphor mismatch is not relabeled as resolved. The tournament therefore correctly remains `revision_required`. Thirty live call records include failed/repaired attempts; the candidate book contains six technically valid selections. Resumption records changed compact-output policy and reuses completed candidates rather than generating them again.

Short source handles map to immutable hashes. Model-supplied filenames/hashes never authorize local font paths. The native planner merges pinned font metadata, fits display type with Pango, preserves the reading-size floor and exact source ranges, and reserves actual source-frame bleed. Slight image-frame corrections are recorded; issue composition may reduce a frame by at most 10% before requiring recomposition. It never enlarges pixels to manufacture print resolution.

## M9: physical pages and visual history

Six stories map to cover wrap 12/1 and facing pairs 2/3 through 10/11. Every rendered spread advances an actual cumulative contact sheet, measured photo-frame union and display ink coverage, and a new Bible version. These measurements describe geometry, not perceived artistic energy. A separate printer map accounts for each page once across three saddle-stitch sheets; the downloadable reader PDF is in page-number order.

Revision inputs freeze their parent, identity and corrected story bindings. Unchanged spreads retain their exact scene versions. Native repairs and authored proposals are identified separately from model composition. Authored proposals still pass source partitioning, the operation registry, native rendering and critics; they never acquire a fabricated provider call or owner approval.

The source essays are original acceptance fixtures, not interviews. Photographs and attribution are pinned in `config/issue_sources.json`; the installer verifies source/derivative hashes. MobileSAM supplies the cover globe alpha, with no new generative image call. Model previews are downsampled separately; production retains native sources.

### Negative evidence and lessons

Issue v1 is retained: a NASA event title misleadingly matched a buffet photograph. The actual pixels must be inspected before a source is assigned a story role. The issue critic caught the mismatch. New issue composition now halts on artistic REPLAN rather than treating a different layout as a fix for the wrong photograph.

Issue v2 corrected the source, cover contrast and reading gutter. Its panorama title still overprinted because a model-generated center-alignment anchor moved two independent title fragments together. Region allocation alone does not prove final placement. V3 removes that contradictory anchor and the stray launch-photo fragment; these two changes are explicitly authored. Its model coherence remains REVISE for panorama continuity and photographic integration, despite a technically valid export. Earlier versions remain available as negative cases.

V4 unifies the panorama title and extends the launch photograph across the fold at native resolution. V5 balances the lunar essay into facing source-bound columns. V6 records the intentionally retained M8 portrait orientation and reviews actual PDF facing pairs together. These repairs are authored, not a claimed autonomous success. A model's suggested enlargement cannot override native resolution; the thin panorama remains a deliberate low-energy gesture.

The final coherence verdict remains **REVISE**: its rationale recognizes a coherent progression and consistent identity, while requesting stronger cover-title hierarchy. Its additional claim that the launch photograph is entirely on page 5 is contradicted by the frozen scene: a single image extends from x=100 to x=354 mm across the 210 mm spine, occupying 110 mm on page 4 and 144 mm on page 5. The adjacent physical-page raster was inspected and confirms continuity. The raw model score (0.0), verdict and findings are retained without relabeling them as approval. Earlier single-page montage rows also caused a false discontinuity claim; the review preview now keeps each physical facing pair adjacent. This is concrete evidence that visual critics require external checks rather than repeated agreement-seeking calls.

## M10: hard validity and export parity

Preflight rechecks source coverage, frozen document hashes/scene bindings, pinned fonts, native image sampling including affine stretch and enlargement lineage, reading fold clearance, and actual transformed artwork/clip geometry at trim. Hidden parent groups and inherited clips are respected. Plain independent display layers that substantially overprint are hard failures. Bleed continuation is conservatively sampled along actual trim intersections at 0.25 mm, checking the entire outward normal segment; detached artwork cannot satisfy an endpoint while leaving an intervening gap. This is a geometric proof check, not a certification of every possible mask or press process.

Supported enlargement lineage preserves a full source frame at its recorded integer scale; segmentation preserves source dimensions. A cropped derivative without an explicit sampling transform is rejected rather than granted native resolution. Missing/corrupt evidence, unsupported lineage or rendering failure abort publication and are recorded by the worker as failures. Trusted scene defects yield a saved blocked preflight with no production PDF.

The exporter draws the same saved scene beyond trim and vector-crops twelve physical pages. It does not mirror or fabricate photographic bleed. Fonts are embedded/subset, and PDF boxes and each exported trim are independently checked with PyMuPDF. Both source and exported clips are normalized to an A4 origin before raster comparison, avoiding fractional device-pixel phase errors. The fixture test also samples a known photo color inside actual bleed; paper padding cannot satisfy it.

`m10-negative-v2` is retained as a blocked export. A new export ID is used after fixes; old reports are immutable. Source issue, selected image lineage and evidence fingerprint are rechecked before atomic publication. Later enlargement lineage invalidates a cached preflight. These are RGB vector proofs with native photographs, not PDF/X or printer-specific color/separation certification.

## Reproduce

Use `conda activate clinic` and stop the separate worker before acceptance scripts. Model-producing commands can incur charges and upload the selected public photographs and proof previews through the configured gateway. Completed steps are reused; ambiguous submissions require reconciliation.

```bash
python -m scripts.verify_m8 --run m8-live-v3 --resume-policy
python -m scripts.install_issue_sources
python -m scripts.verify_m9_revision
python -m scripts.verify_m9_geometry_revision
python -m scripts.verify_m9_geometry_revision --run m9-live-v4 --parent m9-live-v3 --refine
python -m scripts.verify_m9_moon_revision
python -m scripts.verify_m9_final
python -m scripts.verify_m10 --issue m9-live-v6 --run m10-live-v2
python -m pytest -q
python -m editorial_studio.contracts.export
```

This sequence requires retained local parents: `verify_m9_revision` revises v1 into v2, the default geometry command creates v3 from v2, the refined command creates v4, the moon command creates v5 from v4, and the final command creates v6 from v5. It is a reproduction of this workstation's acceptance state, not a clean-checkout bootstrap. To build a fresh six-story issue from the corrected manifest and an existing tournament, use `python -m scripts.verify_m9 --run m9-fresh-01 --tournament m8-live-v3`. That command requires the completed M8 tournament, its identity/story records, source photographs and pinned fonts/checkpoint; copying PDF exports does not restore those records. The geometry revision scripts preserve model originals and label their authored repairs.

## Verification boundaries

The full technical suite passed **236 tests** in `clinic`, with **243 generated schemas**. That full run preceded the final localized changes to bleed-segment coverage and physical facing-page previews; the six M9/M10 tests passed afterward. The subsequent download-control changes passed all six UI tests. The entire suite was not rerun after those localized changes. Tests cover source characters, native geometry, page order, actual bleed pixels, embedded fonts, stale evidence, missing assets, recovery and publication blocking. Ruff lint/format checks, the 93-package Linux lock check, and installed dependency checks pass. Chrome renders all four tabs without errors; the final `m10-live-v2.pdf` download matches the stored bytes. Issue exports load only the selected reader proof, and download clicks avoid rerunning the app. These are engineering checks, not owner artistic approval.

The worker is running again after a reconciliation scan reporting zero missing, corrupt or quarantined assets and no interrupted model attempts. No model calls or queued jobs remain active. The fresh handoff read found the workstation contract understandable; its minor reproduction and verification-timing gaps are clarified above. No PDF/X, clean-checkout portability, or professional artistic approval is claimed.

The `sip` review included a fresh-context production-code read, a `mandela` validation audit, an `ssotize` consistency audit and a `re0` documentation refresh. The independence audit flags shared model/scorer bias: tournament and issue critics do not constitute external professional ground truth. Technical PDF checks have explicit physical/raster oracles; owner artistic review and M12 blind professional evaluation remain separate. The consistency audit found stale current-status sentences in README/progress, which were updated as implementation documentation; historical milestone counts were preserved. No source-of-truth consolidation or portability claim is made.

M11 remains flagged off. M12 remains unimplemented.
