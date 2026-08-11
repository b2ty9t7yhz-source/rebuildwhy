from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rebuildwhy.cache import CacheStore
from rebuildwhy.errors import ExecutionError, SpecError
from rebuildwhy.executor import Executor
from rebuildwhy.models import Decision
from rebuildwhy.overlays import parse_overlays
from rebuildwhy.planner import Planner
from rebuildwhy.spec import load_pipeline

REPOSITORY_ROOT = Path(__file__).parents[2]


@pytest.fixture
def demo(tmp_path: Path) -> Path:
    destination = tmp_path / "synthetic_mri"
    shutil.copytree(
        REPOSITORY_ROOT / "examples" / "synthetic_mri",
        destination,
        ignore=shutil.ignore_patterns(".rebuildwhy", "outputs", "__pycache__"),
    )
    return destination / "pipeline.yaml"


def decisions(pipeline_path: Path) -> dict[str, Decision]:
    pipeline = load_pipeline(pipeline_path)
    result = Planner(pipeline).plan()
    return {task.task_id: task.decision for task in result.report.tasks}


def test_full_run_then_every_task_is_a_hit(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    assert set(decisions(demo).values()) == {Decision.RUN}

    first = Executor(pipeline).run()
    second = Executor(pipeline).run()

    assert [event.decision for event in first.events] == [Decision.RUN] * 5
    assert [event.decision for event in second.events] == [Decision.HIT] * 5
    assert (pipeline.root / "outputs/report/report.md").read_text().startswith("# Synthetic")


def test_relevant_overlay_is_causal_and_does_not_mutate_source(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    config_path = pipeline.root / "config/pipeline.yaml"
    before = config_path.read_bytes()
    overlays = parse_overlays(
        pipeline,
        set_values=["config/pipeline.yaml#/image/spacing=[1.0,1.0,2.0]"],
    )

    report = Planner(pipeline).plan(overlays).report.to_dict()

    assert config_path.read_bytes() == before
    by_task = {task["task_id"]: task["decision"] for task in report["tasks"]}
    assert by_task == {
        "ingest": "HIT",
        "resample": "RUN",
        "normalize": "MAY_RUN",
        "features": "MAY_RUN",
        "report": "MAY_RUN",
    }
    assert any(reason["code"] == "CONFIG_FIELD_CHANGED" for reason in report["reasons"])
    assert any(
        reason["code"] == "UPSTREAM_ARTIFACT_MAY_CHANGE" and reason["caused_by"]
        for reason in report["reasons"]
    )


def test_irrelevant_overlay_keeps_all_hits_and_json_is_stable(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    overlays = parse_overlays(
        pipeline,
        set_values=['config/pipeline.yaml#/notes/owner="counterfactual"'],
    )

    first = Planner(pipeline).plan(overlays).report.to_dict()
    second = Planner(pipeline).plan(overlays).report.to_dict()

    assert first == second
    assert first["affected_task_ids"] == []
    assert {task["decision"] for task in first["tasks"]} == {"HIT"}


def test_changed_producer_with_same_artifact_keeps_downstream_hits(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    config_path = pipeline.root / "config/pipeline.yaml"
    config_path.write_text(
        config_path.read_text().replace("method: nearest", "method: linear"),
        encoding="utf-8",
    )

    report = Executor(pipeline).run()
    actual = {event.task_id: event.decision for event in report.events}

    assert actual["resample"] is Decision.RUN
    assert actual["normalize"] is Decision.HIT
    assert actual["features"] is Decision.HIT
    assert actual["report"] is Decision.HIT


def test_missing_publication_is_restored_without_execution(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    publication = pipeline.root / "outputs/report"
    publication.unlink()

    assert decisions(demo)["report"] is Decision.RESTORE
    report = Executor(pipeline).run()

    assert report.events[-1].decision is Decision.RESTORE
    assert publication.is_symlink()


def test_corrupt_materialized_bundle_is_restored_from_verified_objects(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    publication = pipeline.root / "outputs/report"
    report_file = publication.resolve() / "report.md"
    report_file.chmod(0o644)
    report_file.write_text("tampered publication", encoding="utf-8")

    assert decisions(demo)["report"] is Decision.RESTORE
    restored = Executor(pipeline).run()

    assert restored.events[-1].decision is Decision.RESTORE
    assert (publication / "report.md").read_text(encoding="utf-8").startswith("# Synthetic")


def test_regular_output_path_is_never_overwritten(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    publication = pipeline.root / "outputs/report"
    publication.unlink()
    publication.mkdir()
    marker = publication / "user-data.txt"
    marker.write_text("preserve me", encoding="utf-8")

    with pytest.raises(SpecError, match="unmanaged") as caught:
        Executor(pipeline).run()

    assert caught.value.code == "OUTPUT_PATH_CONFLICT"
    assert marker.read_text(encoding="utf-8") == "preserve me"


def test_corrupt_object_is_not_reused(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    cache = CacheStore(pipeline.root)
    baseline = cache.load_baseline("ingest")
    assert baseline.record is not None
    manifest = cache.verify_manifest(baseline.record["manifest_digest"])
    object_path = cache.object_path(manifest["files"][0]["digest"])
    object_path.chmod(0o644)
    object_path.write_bytes(b"corrupt")

    report = Planner(pipeline, cache).plan().report.to_dict()
    ingest = next(task for task in report["tasks"] if task["task_id"] == "ingest")

    assert ingest["decision"] == "RUN"
    assert any(reason["code"] == "CACHE_OBJECT_CORRUPT" for reason in report["reasons"])


def test_missing_object_is_not_reused(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    cache = CacheStore(pipeline.root)
    baseline = cache.load_baseline("ingest")
    assert baseline.record is not None
    manifest = cache.verify_manifest(baseline.record["manifest_digest"])
    object_path = cache.object_path(manifest["files"][0]["digest"])
    moved = cache.quarantine / "deliberately-missing-object"
    moved.parent.mkdir(parents=True, exist_ok=True)
    object_path.rename(moved)

    report = Planner(pipeline, cache).plan().report.to_dict()

    assert any(reason["code"] == "CACHE_OBJECT_MISSING" for reason in report["reasons"])


def test_symlinked_cache_object_is_not_reused(demo: Path, tmp_path: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    cache = CacheStore(pipeline.root)
    baseline = cache.load_baseline("ingest")
    assert baseline.record is not None
    manifest = cache.verify_manifest(baseline.record["manifest_digest"])
    object_path = cache.object_path(manifest["files"][0]["digest"])
    external_copy = tmp_path / "external-object"
    object_path.rename(external_copy)
    object_path.symlink_to(external_copy)

    report = Planner(pipeline, cache).plan().report.to_dict()

    assert any(reason["code"] == "CACHE_OBJECT_CORRUPT" for reason in report["reasons"])


def test_incomplete_action_record_is_not_reused(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    cache = CacheStore(pipeline.root)
    baseline = cache.load_baseline("report")
    assert baseline.record is not None
    action_path = cache.action_path(baseline.record["action_key"])
    action_path.write_text('{"complete":false}', encoding="utf-8")

    report = Planner(pipeline, cache).plan().report.to_dict()

    assert any(reason["code"] == "ACTION_RECORD_CORRUPT" for reason in report["reasons"])


def test_symlinked_action_record_is_not_reused(demo: Path, tmp_path: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    cache = CacheStore(pipeline.root)
    baseline = cache.load_baseline("report")
    assert baseline.record is not None
    action_path = cache.action_path(baseline.record["action_key"])
    external_copy = tmp_path / "external-action.json"
    action_path.rename(external_copy)
    action_path.symlink_to(external_copy)

    report = Planner(pipeline, cache).plan().report.to_dict()

    assert any(reason["code"] == "ACTION_RECORD_CORRUPT" for reason in report["reasons"])


def test_action_snapshot_must_match_its_key(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    cache = CacheStore(pipeline.root)
    baseline = cache.load_baseline("report")
    assert baseline.record is not None
    action_path = cache.action_path(baseline.record["action_key"])
    tampered = baseline.record
    tampered["snapshot"]["command"]["argv"].append("tampered")
    action_path.write_text(json.dumps(tampered), encoding="utf-8")

    report = Planner(pipeline, cache).plan().report.to_dict()

    assert any(reason["code"] == "ACTION_RECORD_CORRUPT" for reason in report["reasons"])


def test_changed_command_is_explained(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    raw = yaml.safe_load(demo.read_text(encoding="utf-8"))
    raw["tasks"]["report"]["command"]["argv"].append("--new-argument")
    demo.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    report = Planner(load_pipeline(demo)).plan().report.to_dict()

    assert any(reason["code"] == "COMMAND_CHANGED" for reason in report["reasons"])
    assert (
        next(task for task in report["tasks"] if task["task_id"] == "report")["decision"] == "RUN"
    )


def test_changed_environment_contract_is_explained(
    demo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    monkeypatch.setenv("REBUILDWHY_TEST_MODE", "enabled")
    raw = yaml.safe_load(demo.read_text(encoding="utf-8"))
    raw["tasks"]["report"]["inputs"]["environment"] = ["REBUILDWHY_TEST_MODE"]
    demo.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    report = Planner(load_pipeline(demo)).plan().report.to_dict()

    assert any(reason["code"] == "ENVIRONMENT_CHANGED" for reason in report["reasons"])


def test_missing_source_blocks_before_cache_mutation(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    source = pipeline.root / "data/synthetic_image.json"
    source.rename(pipeline.root / "data/synthetic_image.moved")

    with pytest.raises(SpecError) as caught:
        Planner(pipeline).plan()

    assert caught.value.code == "MISSING_SOURCE_INPUT"
    assert not (pipeline.root / ".rebuildwhy").exists()


def test_missing_required_output_preserves_no_partial_publication(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    report_script = pipeline.root / "example_tasks/report.py"
    report_script.write_text("def main():\n    pass\n\nmain()\n", encoding="utf-8")

    with pytest.raises(ExecutionError) as caught:
        Executor(pipeline).run()

    assert caught.value.code == "REQUIRED_OUTPUT_MISSING"
    assert not (pipeline.root / "outputs/report").exists()
    assert not (pipeline.root / ".rebuildwhy/state/report.json").exists()


def test_failed_rebuild_keeps_previous_publication(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    publication = pipeline.root / "outputs/report"
    old_target = publication.resolve()
    old_text = (publication / "report.md").read_text(encoding="utf-8")
    report_script = pipeline.root / "example_tasks/report.py"
    report_script.write_text("raise SystemExit(17)\n", encoding="utf-8")

    with pytest.raises(ExecutionError) as caught:
        Executor(pipeline).run()

    assert caught.value.code == "COMMAND_FAILED"
    assert publication.resolve() == old_target
    assert (publication / "report.md").read_text(encoding="utf-8") == old_text


def test_failpoint_before_action_record_keeps_previous_publication(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    publication = pipeline.root / "outputs/report"
    old_target = publication.resolve()
    config_path = pipeline.root / "config/pipeline.yaml"
    config_path.write_text(
        config_path.read_text().replace(
            "Synthetic MRI Feature Summary", "Changed title for failpoint"
        ),
        encoding="utf-8",
    )
    proposed = Planner(pipeline).plan().by_task["report"].proposed_action_key
    assert proposed is not None

    def failpoint(name: str) -> None:
        if name == "before_action_record":
            raise RuntimeError("injected publication failure")

    cache = CacheStore(pipeline.root, failpoint=failpoint)
    with pytest.raises(RuntimeError, match="injected"):
        Executor(pipeline, cache).run()

    assert publication.resolve() == old_target
    assert not cache.action_path(proposed).exists()


def test_failpoint_before_publish_leaves_recoverable_action(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    publication = pipeline.root / "outputs/report"
    old_target = publication.resolve()
    config_path = pipeline.root / "config/pipeline.yaml"
    config_path.write_text(
        config_path.read_text().replace(
            "Synthetic MRI Feature Summary", "Changed title for restore"
        ),
        encoding="utf-8",
    )

    def failpoint(name: str) -> None:
        if name == "before_publish":
            raise RuntimeError("injected publish failure")

    cache = CacheStore(pipeline.root, failpoint=failpoint)
    with pytest.raises(RuntimeError, match="injected"):
        Executor(pipeline, cache).run()

    assert publication.resolve() == old_target
    task = Planner(pipeline).plan().by_task["report"]
    assert task.decision is Decision.RESTORE


def test_determinism_check_runs_twice_and_accepts_demo_task(demo: Path) -> None:
    pipeline = load_pipeline(demo)

    report = Executor(pipeline).verify_determinism("features")

    assert report.events[-1].task_id == "features"
    assert report.events[-1].decision is Decision.RUN


def test_determinism_check_rejects_nondeterministic_task(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    features = pipeline.root / "example_tasks/features.py"
    features.write_text(
        "from pathlib import Path\n"
        "import os, secrets\n"
        "from example_tasks.common import context\n"
        "ctx = context()\n"
        "Path(ctx['output_directory'], 'features.json').write_text(secrets.token_hex(8))\n",
        encoding="utf-8",
    )

    with pytest.raises(ExecutionError) as caught:
        Executor(pipeline).verify_determinism("features")

    assert caught.value.code == "NONDETERMINISTIC_OUTPUT"
    assert not (pipeline.root / ".rebuildwhy/state/features.json").exists()


def test_file_overlay_uses_replacement_bytes_without_mutation(demo: Path) -> None:
    pipeline = load_pipeline(demo)
    Executor(pipeline).run()
    source = pipeline.root / "data/synthetic_image.json"
    replacement = pipeline.root / "data/alternate.json"
    replacement.write_text(json.dumps({"dimensions": [1, 1, 1], "voxels": [9]}), encoding="utf-8")
    before = source.read_bytes()
    overlays = parse_overlays(
        pipeline,
        replace_files=["data/synthetic_image.json=data/alternate.json"],
    )

    report = Planner(pipeline).plan(overlays).report.to_dict()

    assert source.read_bytes() == before
    assert (
        next(task for task in report["tasks"] if task["task_id"] == "ingest")["decision"] == "RUN"
    )
    assert any(reason["code"] == "FILE_CONTENT_CHANGED" for reason in report["reasons"])
