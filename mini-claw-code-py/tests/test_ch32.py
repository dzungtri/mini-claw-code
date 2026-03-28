import asyncio
from collections import deque
from pathlib import Path

import pytest

from mini_claw_code_py import (
    ARTIFACT_MANIFEST_PATH,
    AgentArtifactUpdate,
    HarnessAgent,
    Message,
    MockStreamProvider,
    StopReason,
    ToolCall,
    diff_artifacts,
    load_artifact_manifest,
    render_artifact_prompt_section,
    scan_artifacts,
    write_artifact_manifest,
)
from mini_claw_code_py.types import AssistantTurn


def test_ch32_render_artifact_prompt_section_mentions_outputs_and_file_preference(tmp_path: Path) -> None:
    section = render_artifact_prompt_section(tmp_path / "outputs")

    assert "<artifacts>" in section
    assert "outputs directory" in section.lower()
    assert "files in the outputs directory" in section


def test_ch32_scan_and_diff_artifacts_detects_created_updated_removed(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "story.txt").write_text("v1", encoding="utf-8")
    (outputs / "notes.md").write_text("# hi\n", encoding="utf-8")

    before = scan_artifacts(outputs)
    assert [record.path for record in before] == ["notes.md", "story.txt"]

    (outputs / "story.txt").write_text("v2 updated", encoding="utf-8")
    (outputs / "draft.py").write_text("print('hi')\n", encoding="utf-8")
    (outputs / "notes.md").unlink()

    after = scan_artifacts(outputs)
    delta = diff_artifacts(before, after)

    assert [record.path for record in delta.created] == ["draft.py"]
    assert [record.path for record in delta.updated] == ["story.txt"]
    assert delta.removed == ["notes.md"]


def test_ch32_artifact_manifest_round_trips_records(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "chapter_001.md").write_text("Hello\n", encoding="utf-8")
    records = scan_artifacts(outputs)

    manifest_path = write_artifact_manifest(
        tmp_path,
        outputs_dir=outputs,
        records=records,
    )

    assert manifest_path == tmp_path / ARTIFACT_MANIFEST_PATH
    loaded = load_artifact_manifest(tmp_path)
    assert [record.path for record in loaded] == ["chapter_001.md"]
    assert loaded[0].kind == "md"


@pytest.mark.asyncio
async def test_ch32_harness_tracks_outputs_and_emits_artifact_event(tmp_path: Path) -> None:
    provider = MockStreamProvider(
        deque(
            [
                AssistantTurn(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="write",
                            arguments={
                                "path": "outputs://report.txt",
                                "content": "artifact body",
                            },
                        )
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                AssistantTurn(
                    text="Done.",
                    tool_calls=[],
                    stop_reason=StopReason.STOP,
                ),
            ]
        )
    )
    agent = (
        HarnessAgent(provider)
        .enable_workspace(tmp_path, outputs=tmp_path / "outputs")
        .enable_core_tools()
    )
    queue: asyncio.Queue[object] = asyncio.Queue()
    history = [Message.user("Write the report to outputs.")]

    result = await agent.execute(history, queue)

    assert result == "Done."
    assert (tmp_path / "outputs" / "report.txt").read_text(encoding="utf-8") == "artifact body"
    assert [record.path for record in agent.artifact_catalog().items()] == ["report.txt"]
    assert load_artifact_manifest(tmp_path)[0].path == "report.txt"

    artifact_events: list[AgentArtifactUpdate] = []
    while not queue.empty():
        event = await queue.get()
        if isinstance(event, AgentArtifactUpdate):
            artifact_events.append(event)
    assert len(artifact_events) == 1
    assert artifact_events[0].created == 1
    assert artifact_events[0].updated == 0
    assert artifact_events[0].removed == 0


@pytest.mark.asyncio
async def test_ch32_harness_loads_existing_artifact_manifest_into_catalog(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "poem.txt").write_text("Rose\n", encoding="utf-8")
    write_artifact_manifest(
        tmp_path,
        outputs_dir=outputs,
        records=scan_artifacts(outputs),
    )

    agent = HarnessAgent(MockStreamProvider(deque())).enable_workspace(
        tmp_path,
        outputs=outputs,
    ).enable_core_tools()

    assert agent.artifact_catalog().status_summary() == "Artifacts: 1 tracked file(s)."
    assert "poem.txt" in agent.artifact_catalog().render()
