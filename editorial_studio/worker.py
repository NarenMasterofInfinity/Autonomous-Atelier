"""Run separately from Streamlit: python -m editorial_studio.worker."""

import argparse
import time
from uuid import uuid4

from editorial_studio.contracts.models import ProviderCallRecord
from editorial_studio.core.jobs import (
    BuildCapabilityProofsCommand,
    BuildCreativeSpreadCommand,
    BuildIdentityCommand,
    BuildIssueCommand,
    BuildReferenceCompositionCommand,
    BuildTournamentCommand,
    CreateProofCommand,
    ExportProductionCommand,
    IngestStoryCommand,
    ModelCommand,
    PackageFinalIdentityCommand,
    PatchSceneCommand,
    Queue,
    ReconcileCommand,
    ReviewFinalIdentityCommand,
    ReviewIdentityCommand,
    ReviseIssueCommand,
    RollbackSceneCommand,
    SegmentSubjectCommand,
    StepOutput,
    worker_lock,
)
from editorial_studio.core.storage import Store
from editorial_studio.llm.contracts import CallContext, ProviderFailure
from editorial_studio.llm.gateway import Gateway, UnreconciledCall
from editorial_studio.llm.provider import OpenAIProvider
from editorial_studio.settings import load_settings
from editorial_studio.telemetry.pricing import PricingTable
from editorial_studio.telemetry.redaction import Redactor


def process_one(queue: Queue, gateway: Gateway, worker_id: str, settings) -> bool:
    job = queue.claim(worker_id, settings.lease_seconds)
    if job is None:
        return False
    command = job.command
    pipeline_command = isinstance(
        command.payload,
        (
            IngestStoryCommand,
            SegmentSubjectCommand,
            BuildCreativeSpreadCommand,
            PackageFinalIdentityCommand,
            ReviewFinalIdentityCommand,
            BuildCapabilityProofsCommand,
            BuildTournamentCommand,
            BuildReferenceCompositionCommand,
            BuildIssueCommand,
            ReviseIssueCommand,
            ExportProductionCommand,
        ),
    )
    identity_command = isinstance(command.payload, (BuildIdentityCommand, ReviewIdentityCommand))
    scene_command = not isinstance(command.payload, (ModelCommand, ReconcileCommand))
    step_name = (
        "pipeline_operation"
        if pipeline_command
        else "identity_operation"
        if identity_command
        else "canvas_operation"
        if scene_command
        else "provider_call"
    )
    try:
        with queue.lease(job, settings.lease_seconds, settings.heartbeat_seconds):
            # Recover a committed step without issuing another model call.
            saved = queue.step(command.id, step_name)
            if saved is not None:
                for asset_id in saved.asset_ids:
                    gateway.store.read_blob(command.project_id, asset_id)
            else:
                if scene_command:
                    output = (
                        process_pipeline_command(gateway, command)
                        if pipeline_command
                        else process_identity_command(gateway, command)
                        if identity_command
                        else process_canvas_command(queue, gateway, command)
                    )
                    queue.commit_step(command.id, worker_id, step_name, output)
                elif isinstance(command.payload, ModelCommand):
                    context = CallContext(
                        project_id=command.project_id,
                        run_id=command.id,
                        agent_name="InfrastructureSmoke",
                        stage="M0",
                    )
                    result = gateway.invoke(context, command.payload.request)
                else:
                    result = gateway.reconcile(
                        command.payload.call_id, project_id=command.project_id
                    )
                    original = gateway.store.get("call", result.call_id, ProviderCallRecord)
                    queue.resolve_job(
                        original.run_id,
                        original.project_id,
                        StepOutput(
                            asset_ids=result.generated_artifact_ids,
                            call_id=result.call_id,
                            visible_text=result.visible_text,
                        ),
                    )
                if not scene_command:
                    queue.commit_step(
                        command.id,
                        worker_id,
                        "provider_call",
                        StepOutput(
                            asset_ids=result.generated_artifact_ids,
                            call_id=result.call_id,
                            visible_text=result.visible_text,
                        ),
                    )
        queue.finish(command.id, worker_id)
    except (UnreconciledCall, ProviderFailure) as error:
        ambiguous = isinstance(error, UnreconciledCall) or error.ambiguous
        queue.finish(
            command.id,
            worker_id,
            status="needs_reconciliation" if ambiguous else "failed",
            error=gateway.redactor.text(str(error)),
        )
    except Exception as error:
        queue.finish(
            command.id, worker_id, status="failed", error=gateway.redactor.text(str(error))
        )
    return True


def process_canvas_command(queue, gateway, command):
    from editorial_studio.canvas.demo import proof_document
    from editorial_studio.canvas.executor import Executor
    from editorial_studio.canvas.models import SceneVersion
    from editorial_studio.canvas.renderer import Renderer
    from editorial_studio.canvas.repository import SceneRepository
    from editorial_studio.contracts.operation_registry import RuntimePolicy

    store = gateway.store
    previous = next(
        (
            v
            for v in store.list("scene_version", SceneVersion, command.project_id)
            if v.run_id == command.id
        ),
        None,
    )
    if previous:
        for asset in [
            previous.png_asset_id,
            previous.pdf_asset_id,
            previous.document_asset_id,
            previous.metadata_asset_id,
        ]:
            store.read_blob(command.project_id, asset)
        return StepOutput(
            asset_ids=[
                previous.png_asset_id,
                previous.pdf_asset_id,
                previous.document_asset_id,
                previous.metadata_asset_id,
            ],
            scene_id=previous.scene_id,
            scene_version=previous.version,
        )
    repository = SceneRepository(store, command.project_id)
    executor = Executor(repository, Renderer(store, command.project_id))
    context = CallContext(
        project_id=command.project_id, run_id=command.id, agent_name="CanvasWorker", stage="M1"
    )
    if isinstance(command.payload, CreateProofCommand):
        version = executor.initialize(proof_document(command.payload.scene_id), context)
    elif isinstance(command.payload, PatchSceneCommand):
        document = repository.load(command.payload.patch.target_scene_id)
        ids = {layer.id for layer in document.scene.layers}
        assets = store.assets(command.project_id)
        policy = RuntimePolicy(
            readable_layer_ids=ids,
            writable_layer_ids=ids,
            asset_ids={a.id for a in assets},
            mask_asset_ids={a.id for a in assets if a.media_type.startswith("image/")},
            derived_text_ids={
                layer.derived_text_id
                for layer in document.scene.layers
                if hasattr(layer, "derived_text_id") and layer.derived_text_id
            },
            style_names=(
                {style.name for style in document.typography.styles}
                if document.typography
                else set(executor.renderer.typography.fonts.styles)
            ),
            allowed_operations=executor.supported_operations,
            renderer_operations=executor.supported_operations,
        )
        version = executor.apply(command.payload.patch, policy, context)
    elif isinstance(command.payload, RollbackSceneCommand):
        version = executor.rollback(
            command.payload.scene_id,
            command.payload.restored_version,
            command.payload.expected_parent_version,
            context,
        )
    else:
        raise ValueError("unsupported canvas command")
    return StepOutput(
        asset_ids=[
            version.png_asset_id,
            version.pdf_asset_id,
            version.document_asset_id,
            version.metadata_asset_id,
        ],
        scene_id=version.scene_id,
        scene_version=version.version,
    )


def process_identity_command(gateway, command):
    from editorial_studio.art_direction.models import IdentityReview, ProvisionalIdentity
    from editorial_studio.art_direction.service import (
        build_identity,
        identity_assets,
        review_identity,
    )

    context = CallContext(
        project_id=command.project_id, run_id=command.id, agent_name="IdentityWorker", stage="M2"
    )
    if isinstance(command.payload, BuildIdentityCommand):
        identity = build_identity(
            gateway.store,
            context,
            pairing_id=command.payload.pairing_id,
            reference_ids=command.payload.reference_ids,
            photo_asset_id=command.payload.photo_asset_id,
            palette=command.payload.palette,
        )
    else:
        prior = gateway.store.get("identity_review", command.id, IdentityReview)
        if prior:
            identity = gateway.store.get(
                "identity", command.payload.identity_id, ProvisionalIdentity
            )
            if identity is None or identity.project_id != command.project_id:
                raise PermissionError("review identity belongs to another project")
        else:
            identity = review_identity(
                gateway.store,
                context,
                command.payload.identity_id,
                expected_revision=command.payload.expected_revision,
                actor=command.payload.actor,
                verdict=command.payload.verdict,
                note=command.payload.note,
            )
    assets = identity_assets(identity)
    for asset in assets:
        gateway.store.read_blob(command.project_id, asset)
    return StepOutput(asset_ids=assets, identity_id=identity.id)


def process_pipeline_command(gateway, command):
    from editorial_studio.photos.pipeline import ingest_story

    context = CallContext(
        project_id=command.project_id, run_id=command.id, agent_name="PhotoWorker", stage="M3"
    )
    if isinstance(command.payload, IngestStoryCommand):
        result = ingest_story(gateway.store, context, command.payload.story)
    elif isinstance(command.payload, SegmentSubjectCommand):
        from editorial_studio.segmentation.service import segment

        context.stage = "M4"
        result = segment(gateway.store, context, command.payload.prompt)
    elif isinstance(command.payload, BuildCreativeSpreadCommand):
        from editorial_studio.creative.service import build_creative_spread

        context.stage = "M7"
        context.agent_name = "CreativeWorkflow"
        result = build_creative_spread(
            gateway,
            context,
            command.payload.story_id,
            command.payload.identity_id,
            mandate=command.payload.mandate,
        )
    elif isinstance(command.payload, BuildCapabilityProofsCommand):
        from editorial_studio.spatial.proofs import build_capability_proofs

        context.stage = "M5"
        proofs = build_capability_proofs(gateway.store, context)
        return StepOutput(
            asset_ids=[
                asset
                for proof in proofs
                for asset in (
                    proof.png_asset_id,
                    proof.pdf_asset_id,
                    proof.document_asset_id,
                    proof.metadata_asset_id,
                    proof.thumbnail_asset_id,
                    proof.crop_asset_id,
                )
            ]
        )
    elif isinstance(command.payload, BuildReferenceCompositionCommand):
        from editorial_studio.reference_studio.service import build_compositions, composition_assets

        context.stage = "M10A"
        context.agent_name = "ReferenceProgramComposer"
        result = build_compositions(
            gateway,
            context,
            command.payload.story_id,
            command.payload.identity_id,
            command.payload.reference_ids,
            origin=command.payload.reference_project,
            art_director=command.payload.art_director,
        )
        return StepOutput(
            asset_ids=composition_assets(gateway.store, result)
            + [gateway.store.json_blob(command.project_id, result).id]
        )
    elif isinstance(command.payload, BuildTournamentCommand):
        from editorial_studio.creative.tournament import build_tournament, tournament_assets
        from editorial_studio.reference_studio.generation import (
            configuration as atlas_configuration,
        )

        context.stage = "M8"
        context.agent_name = "CandidateTournament"
        result = build_tournament(
            gateway,
            context,
            command.payload.story_id,
            command.payload.identity_id,
            mandate=command.payload.mandate,
            continuation_configuration=atlas_configuration(
                command.payload.authored_reference_ids, command.payload.authored_reference_project
            )
            if command.payload.authored_reference_ids
            else None,
        )
        return StepOutput(
            asset_ids=tournament_assets(gateway.store, result)
            + [gateway.store.json_blob(command.project_id, result).id]
        )
    elif isinstance(command.payload, (BuildIssueCommand, ReviseIssueCommand)):
        from editorial_studio.creative.issue import build_issue, issue_assets, revise_issue

        context.stage = "M9"
        context.agent_name = "IssueArchitect"
        result = (
            revise_issue(
                gateway,
                context,
                command.payload.issue_id,
                command.payload.expected_evidence_fingerprint,
                command.payload.corrections,
            )
            if isinstance(command.payload, ReviseIssueCommand)
            else build_issue(
                gateway,
                context,
                command.payload.story_ids,
                command.payload.identity_id,
                tournament_ids=command.payload.tournament_ids,
                reference_ids=command.payload.reference_ids,
                reference_project=command.payload.reference_project,
                reference_art_director=command.payload.reference_art_director,
                prepared_composition_ids=command.payload.prepared_composition_ids,
            )
        )
        return StepOutput(
            asset_ids=issue_assets(gateway.store, result)
            + [gateway.store.json_blob(command.project_id, result).id]
        )
    elif isinstance(command.payload, ExportProductionCommand):
        from editorial_studio.production.service import export_production

        context.stage = "M10"
        result = export_production(
            gateway.store,
            context,
            command.payload.issue_id,
            expected_evidence_fingerprint=command.payload.expected_evidence_fingerprint,
        )
        assets = [
            result.issue_snapshot_asset_id,
            result.preflight_asset_id,
            gateway.store.json_blob(command.project_id, result).id,
        ]
        if result.pdf_asset_id:
            assets.append(result.pdf_asset_id)
        return StepOutput(asset_ids=assets)
    elif isinstance(command.payload, PackageFinalIdentityCommand):
        from editorial_studio.creative.identity import package_identity

        context.stage = "M7"
        result = package_identity(
            gateway.store,
            context,
            command.payload.identity_id,
            command.payload.spread_ids,
            command.payload.capability_proof_ids,
        )
    elif isinstance(command.payload, ReviewFinalIdentityCommand):
        from editorial_studio.creative.identity import approve_final_identity
        from editorial_studio.creative.models import FinalIdentityPackage

        context.stage = "M7"
        prior = gateway.store.get("final_identity_review", command.id, FinalIdentityPackage)
        if prior:
            if prior.project_id != command.project_id:
                raise PermissionError("review belongs to another project")
            result = prior
        else:
            result = approve_final_identity(
                gateway.store,
                context,
                command.payload.package_id,
                expected_revision=command.payload.expected_revision,
                actor=command.payload.actor,
                note=command.payload.note,
                verdict=command.payload.verdict,
                reviewed_techniques=command.payload.reviewed_techniques,
                override_critic_recommendations=command.payload.override_critic_recommendations,
            )
    else:
        raise ValueError("unsupported pipeline command")
    asset = gateway.store.json_blob(command.project_id, result)
    assets = [asset.id]
    for name in (
        "png_asset_id",
        "pdf_asset_id",
        "document_asset_id",
        "metadata_asset_id",
        "proof_book_asset_id",
        "contact_sheet_asset_id",
        "mask_asset_id",
        "alpha_asset_id",
        "cutout_asset_id",
        "source_asset_id",
    ):
        value = getattr(result, name, None)
        if value:
            assets.append(value)
    from editorial_studio.creative.evidence import creative_assets, package_assets
    from editorial_studio.creative.models import CreativeSpread, FinalIdentityPackage

    if isinstance(result, CreativeSpread):
        assets.extend(creative_assets(gateway.store, result))
    elif isinstance(result, FinalIdentityPackage):
        assets.extend(package_assets(gateway.store, result))
    return StepOutput(asset_ids=sorted(set(assets)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process one queued command then exit")
    parser.add_argument(
        "--initialize", action="store_true", help="Create storage, no provider calls"
    )
    args = parser.parse_args()
    settings = load_settings()
    store = Store(settings.data_root)
    if args.initialize:
        print("Storage initialized; no provider calls made.")
        return
    with worker_lock(store):
        report = store.reconcile()
        print(
            f"Reconciliation: {len(report.missing_asset_ids)} missing, "
            f"{len(report.corrupt_asset_ids)} corrupt, {len(report.quarantined_paths)} quarantined"
        )
        gateway = Gateway(
            store,
            OpenAIProvider(settings),
            PricingTable.load(settings.pricing_path),
            Redactor([settings.api_key.get_secret_value()]),
        )
        recovered = gateway.recover_submitting()
        print(
            f"Worker ready; {recovered} interrupted attempts marked for reconciliation", flush=True
        )
        queue, worker_id = Queue(store), uuid4().hex
        while True:
            processed = process_one(queue, gateway, worker_id, settings)
            if args.once:
                return
            if not processed:
                time.sleep(0.5)


if __name__ == "__main__":
    main()
