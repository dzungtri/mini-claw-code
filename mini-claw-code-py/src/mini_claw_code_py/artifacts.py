from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


ARTIFACT_MANIFEST_PATH = ".mini-claw/artifacts.json"


@dataclass(slots=True)
class ArtifactRecord:
    path: str
    size_bytes: int
    mtime_ns: int

    @property
    def kind(self) -> str:
        suffix = Path(self.path).suffix.lower()
        return suffix[1:] if suffix.startswith(".") else (suffix or "file")


@dataclass(slots=True)
class ArtifactDelta:
    created: list[ArtifactRecord]
    updated: list[ArtifactRecord]
    removed: list[str]

    def is_empty(self) -> bool:
        return not self.created and not self.updated and not self.removed

    def summary(self) -> str:
        parts: list[str] = []
        if self.created:
            parts.append(f"{len(self.created)} new")
        if self.updated:
            parts.append(f"{len(self.updated)} updated")
        if self.removed:
            parts.append(f"{len(self.removed)} removed")
        if not parts:
            return "No artifact changes."
        return "Artifacts updated: " + ", ".join(parts) + "."


class ArtifactCatalog:
    def __init__(self) -> None:
        self._records: list[ArtifactRecord] = []

    def replace(self, records: list[ArtifactRecord]) -> None:
        self._records = sorted(records, key=lambda record: record.path)

    def items(self) -> list[ArtifactRecord]:
        return list(self._records)

    def is_empty(self) -> bool:
        return not self._records

    def render(self, *, limit: int = 20) -> str:
        if not self._records:
            return "No known artifacts."
        lines = ["Artifacts:"]
        for record in self._records[:limit]:
            lines.append(f"- {record.path} ({record.kind}, {record.size_bytes} bytes)")
        if len(self._records) > limit:
            lines.append(f"- ... and {len(self._records) - limit} more")
        return "\n".join(lines)

    def status_summary(self) -> str:
        if not self._records:
            return "Artifacts: none."
        return f"Artifacts: {len(self._records)} tracked file(s)."


def scan_artifacts(outputs_dir: Path | None) -> list[ArtifactRecord]:
    if outputs_dir is None or not outputs_dir.exists():
        return []
    records: list[ArtifactRecord] = []
    for path in sorted(outputs_dir.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        records.append(
            ArtifactRecord(
                path=str(path.relative_to(outputs_dir)).replace("\\", "/"),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        )
    return records


def diff_artifacts(
    before: list[ArtifactRecord],
    after: list[ArtifactRecord],
) -> ArtifactDelta:
    before_map = {record.path: record for record in before}
    after_map = {record.path: record for record in after}

    created = [record for path, record in after_map.items() if path not in before_map]
    updated = [
        record
        for path, record in after_map.items()
        if path in before_map and _artifact_changed(before_map[path], record)
    ]
    removed = sorted(path for path in before_map if path not in after_map)
    return ArtifactDelta(created=created, updated=updated, removed=removed)


def write_artifact_manifest(
    workspace_root: Path,
    *,
    outputs_dir: Path | None,
    records: list[ArtifactRecord],
) -> Path:
    manifest_path = workspace_root / ARTIFACT_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "outputs_dir": str(outputs_dir) if outputs_dir is not None else None,
        "artifacts": [asdict(record) for record in records],
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def load_artifact_manifest(workspace_root: Path) -> list[ArtifactRecord]:
    manifest_path = workspace_root / ARTIFACT_MANIFEST_PATH
    if not manifest_path.exists():
        return []
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, list):
        return []
    records: list[ArtifactRecord] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        try:
            records.append(
                ArtifactRecord(
                    path=str(item["path"]),
                    size_bytes=int(item["size_bytes"]),
                    mtime_ns=int(item["mtime_ns"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(records, key=lambda record: record.path)


def render_artifact_prompt_section(outputs_dir: Path | None) -> str:
    lines = [
        "<artifacts>",
        "Large generated outputs should prefer files in the outputs directory over long inline chat responses.",
    ]
    if outputs_dir is not None:
        lines.append(f"Outputs directory: {outputs_dir}")
    lines.append("When you create or update output files, mention the artifact paths clearly in your final answer.")
    lines.append("</artifacts>")
    return "\n".join(lines)


def _artifact_changed(before: ArtifactRecord, after: ArtifactRecord) -> bool:
    return before.size_bytes != after.size_bytes or before.mtime_ns != after.mtime_ns
