# Setup and run

All commands below run from the repository root with your virtual environment activated. The dependency lock targets Linux x86_64.

## Quick start after setup

If dependencies, local assets and `.env` are already configured, start here. Open the repository root and activate your virtual environment in both terminals. Keep both terminals open.

**Terminal 1: start the interface**

```bash
python -m editorial_studio.worker --initialize
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open **http://127.0.0.1:8501** in your browser. Initialisation creates storage if needed; it does not call a model.

**Terminal 2: start the worker**

```bash
python -m editorial_studio.worker
```

The interface lets you submit jobs and inspect results. The worker executes those jobs. Run one worker for this data store. For later launches, the initialisation command is optional once storage exists.

## Set up a fresh clone

### 1. Get the source

Install Git and Python first, then:

```bash
git clone https://github.com/NarenMasterofInfinity/Autonomous-Atelier.git
cd Autonomous-Atelier
```

Git contains the application, configuration and tests. Saved projects, reference proofs, photographs, model weights and exports live in ignored local folders and are supplied separately.

### 2. Create a virtual environment and install dependencies

Create and activate a virtual environment using your preferred environment manager. For example, with Python's built-in `venv`:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the native rendering libraries required by [the environment specification](config/render-environment.yaml), including Cairo, Pango, HarfBuzz, GLib/GObject, fontconfig and GEOS. These system libraries are separate from Python packages.

Install the locked Python dependencies into your activated environment:

```bash
python -m pip install uv
UV_PROJECT_ENVIRONMENT="$(python -c 'import sys; print(sys.prefix)')" uv sync --frozen --all-extras --inexact
```

The command targets the environment used by your active Python interpreter. `--frozen` uses the existing lock, `--all-extras` includes rendering, photo processing, segmentation and development tools, and `--inexact` retains unrelated environment packages. See uv's [environment configuration](https://docs.astral.sh/uv/concepts/projects/config/#project-environment-path) and [sync reference](https://docs.astral.sh/uv/reference/cli/#uv-sync).

### 3. Configure provider access

Create `.env` only if it does not already exist:

```bash
if [ ! -f .env ]; then cp .env.example .env; fi
```

Edit it and set your key:

```dotenv
OPENAI_API_KEY=your_api_key_here
# Optional, for a compatible configured endpoint:
# OPENAI_BASE_URL=https://your-provider.example/v1
```

`OPENAI_KEY` is also accepted. Environment variables take precedence over `.env`. Check `text_model` and `image_model` in [config.yaml](config.yaml): they must be available through your provider. Restart the worker after changing credentials or model settings.

Saved-result viewing and local rendering do not need provider calls. Creative generation and model reviews can upload selected copy/images and incur charges. Keep `.env` out of Git.

### 4. Supply fonts and optional workflow assets

Install the base fonts:

```bash
python -m scripts.install_fonts
```

This copies the exact pinned DejaVu files from the workstation's system fonts. If they are missing or have different hashes, supply the matching files declared in [config/fonts.yaml](config/fonts.yaml). Rendering requires these fonts.

Other assets depend on the workflow you use:

| Workflow | Required local files | Configuration or installer |
| --- | --- | --- |
| Subject cutouts | `data/models/mobile_sam.pt` | Supply the MobileSAM `vit_t` checkpoint matching [segmentation.yaml](config/segmentation.yaml); the prepared checkpoint is about 41 MB. |
| FSRCNN image upscaling | `data/models/FSRCNN_x2.pb` | Supply the weights matching [photo_pipeline.yaml](config/photo_pipeline.yaml). |
| Raster-to-vector tracing | `.runtime/potrace/usr/bin/potrace` | Supply the executable matching [artifacts.yaml](config/artifacts.yaml). |
| Authored sample fonts and photographs | `data/flagship/` | Run `python -m scripts.install_flagship_assets`. |
| Extra italic display font | `data/m10a/` | Run `python -m scripts.install_m10a_font`. |
| Additional sample photographs | `data/issue-sources/` | Run `python -m scripts.install_issue_sources`. |

Use the [official MobileSAM project](https://github.com/ChaoningZhang/MobileSAM) for checkpoint distribution. Match configured paths and SHA-256 hashes. Python dependency installation supplies libraries; it does not install these weights, fonts or tracing executables. The sample installers download and check their named assets, without making model calls.

You can ingest stories and build basic identity proofs before installing assets for cutouts, upscaling or tracing. Designs requiring those features need their corresponding assets.

### 5. Initialise and start

Use the two-terminal commands in [Quick start](#quick-start-after-setup). A successful worker startup reports storage reconciliation and then `Worker ready`. The browser should show the studio's four tabs.

## First use

1. In the sidebar, choose a project identifier, such as `my-magazine`. Use that same project while adding its stories and identity.
2. In **Inputs → Ingest a photo story**, enter the title, short introduction, body, author, photographs, source and credit. Click **Queue story ingestion** and let the worker process it.
3. In **Inputs → Provisional identity**, choose a font pairing, palette and references, then click **Build provisional identity**. Inspect the result in **Spread Studio**.
4. Use **Compose a creative spread** or **Explore new layout directions** to try generation. These workflows make provider calls. Inspect their jobs in **Logs & Telemetry** and their saved results in **Spread Studio**.
5. For reference-based composition, first restore or author an editable reference library. **Compose from the editorial reference library** appears when stories, an identity and authored references are available. Turn off **Let the art director choose a preview** for local fitting without model selection/review calls.
6. To build a complete issue, add six distinct stories and use **Build a twelve-page issue**. Inspect the result, then download it from **Export**. Production checking is a separate queued operation.

A fresh clone has no saved authored atlas. The curated reference catalog alone does not create one. [build_m10a_references.py](scripts/build_m10a_references.py) reproduces an existing acceptance project and needs its earlier saved issue; it is not an empty-database bootstrap command. To reuse the existing studio library, restore a consistent copy of its project data and required local assets.

## Verify the installation

Check core imports and the selected interpreter:

```bash
python -c "import sys; import cairo, gi, pymupdf, cv2, streamlit; print(sys.executable)"
python -m pytest tests/test_contracts.py tests/test_m1_typography.py -q
```

After supplying the workflow assets, run the full source suite:

```bash
python -m pytest -q
```

The source tests use fixtures rather than paid provider calls. Some real-asset checks skip when optional files are absent. Scripts named `verify_*` can have different requirements and may make paid calls; read their options before running them.

## Stop, restart and keep your work

Press **Ctrl+C** in each terminal to stop the interface and worker. Start them again with the quick-start commands. The worker handles interrupted jobs and marks uncertain provider submissions for reconciliation; avoid repeatedly resubmitting a job whose external outcome is unknown.

Working data is under `data/projects/` by default: the SQLite database and project blob folders belong together. Keep that data and the fonts/model assets when moving the studio. Take a consistent backup with the worker and UI stopped, including any SQLite sidecar files present. Downloaded exports are copies of results, not a replacement for the editable project store.

## Common fixes

| What you see | What to check |
| --- | --- |
| Environment activation fails | Follow your environment manager's activation instructions and confirm that `python` points to the intended environment. |
| `No module named editorial_studio` | Run from the repository root with your virtual environment active; complete dependency installation for a fresh clone. |
| Cairo, Pango or GI import errors | Check the native environment specification and that `python` belongs to your virtual environment. |
| Font missing or hash mismatch | Run the font installer and supply the exact files in `config/fonts.yaml`. |
| Jobs remain queued | Start the separate worker and confirm both processes use the same checkout and `config.yaml`. |
| Worker lock is already held | Use the existing worker; stop it before starting another worker for the same store. |
| Reference composition controls are absent | Add a story and identity, and restore or author a reference library. |
| Missing checkpoint or tracing executable | Supply the workflow's configured local asset and verify its hash. |
| Provider authentication or unavailable-model error | Check `.env`, endpoint and model names; restart the worker. |
| `needs_reconciliation` | Use **Inputs → Recover a known response** when a response ID was saved; review the call record before retrying. |
| Port 8501 is occupied | Use the running studio, or start the UI with `--server.port 8502` and open that port. |

For the concepts behind these steps, see the [domain architecture](architecture_domain.md) and [technical architecture](architecture_technical.md).
