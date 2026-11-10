"""Run local print preflight on a frozen, completed issue and export its evidence."""

import argparse

from editorial_studio.core.jobs import Command, ExportProductionCommand, Queue, worker_lock
from editorial_studio.core.storage import Store
from editorial_studio.creative.issue_models import IssueResult
from editorial_studio.llm.contracts import CallContext
from editorial_studio.llm.gateway import Gateway
from editorial_studio.production.models import ProductionPreflight
from editorial_studio.production.service import export_production
from editorial_studio.settings import ROOT, load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.worker import process_one


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", default="m9-live-v6")
    parser.add_argument("--run", default="m10-live-v2")
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    ctx = CallContext(
        project_id="m8-proof", run_id=args.run, agent_name="ProductionAcceptance", stage="M10"
    )
    with worker_lock(store):
        issue = store.get("issue", args.issue, IssueResult)
        queue = Queue(store)
        jobs = queue.list()
        if not any(j.command.id == args.run for j in jobs):
            if any(j.status in ("running", "queued") for j in jobs):
                raise RuntimeError(
                    "Finish existing queued work before this isolated local acceptance"
                )
            queue.submit(
                Command(
                    id=args.run,
                    project_id=ctx.project_id,
                    payload=ExportProductionCommand(
                        issue_id=issue.id, expected_evidence_fingerprint=issue.evidence_fingerprint
                    ),
                )
            )
        job = next(j for j in queue.list() if j.command.id == args.run)
        if job.status == "queued":

            class LocalOnlyProvider:
                namespace = "local-production"

                def execute(self, *args):
                    raise AssertionError("production export must never call a model")

            process_one(
                queue,
                Gateway(store, LocalOnlyProvider(), PricingTable.load(settings.pricing_path)),
                "m10-acceptance",
                settings,
            )
        job = next(j for j in queue.list() if j.command.id == args.run)
        if job.status != "completed":
            raise RuntimeError(f"Production worker {job.status}: {job.error}")
        result = export_production(
            store, ctx, issue.id, expected_evidence_fingerprint=issue.evidence_fingerprint
        )
        target = ROOT / "data/exports/m10-proof" / args.run
        target.mkdir(parents=True, exist_ok=True)
        (target / "export.json").write_text(result.model_dump_json(indent=2))
        (target / "preflight.json").write_bytes(
            store.read_blob(ctx.project_id, result.preflight_asset_id)
        )
        if result.pdf_asset_id:
            (target / "production.pdf").write_bytes(
                store.read_blob(ctx.project_id, result.pdf_asset_id)
            )
        report = store.get("production_preflight", result.id, ProductionPreflight)
        print(report.model_dump_json(indent=2), flush=True)
        print(result.model_dump_json(indent=2), flush=True)
        if not report.passed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
