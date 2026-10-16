"""Strict JSON Lines persistence and replay for backend-independent telemetry."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from resiliant_z.telemetry import TelemetryWindow


def _validate_series(records: Sequence[TelemetryWindow]) -> list[TelemetryWindow]:
    if not records:
        raise ValueError("at least one telemetry record is required")
    identities = {(item.run_id, item.scenario_id, item.backend_id) for item in records}
    if len(identities) != 1:
        raise ValueError("one JSONL stream must contain a single run/scenario/backend")
    ordered = sorted(records, key=lambda item: item.window_start)
    previous_end = None
    for record in ordered:
        start = record.window_start
        end = record.window_end
        if previous_end is not None and start < previous_end:
            raise ValueError(
                "telemetry windows overlap; refusing to persist/replay ambiguous order"
            )
        previous_end = end
    return ordered


def write_telemetry_jsonl(
    path: str | Path,
    records: Sequence[TelemetryWindow],
    *,
    overwrite: bool = False,
) -> Path:
    """Persist a validated series as JSONL. Existing files are protected by default."""
    target = Path(path).expanduser()
    ordered = _validate_series(records)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(record.model_dump_json() + "\n" for record in ordered)

    if not overwrite:
        descriptor: int | None = None
        created = False
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                descriptor = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            if created and target.exists() and not target.is_symlink():
                try:
                    target.unlink()
                except OSError:
                    pass
            raise
        return target

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return target


def load_telemetry_jsonl(path: str | Path) -> list[TelemetryWindow]:
    """Load/replay a full JSONL series or raise on any malformed record."""
    source = Path(path).expanduser()
    loaded: list[TelemetryWindow] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                raise ValueError(
                    f"{source}:{line_number}: blank lines are not valid telemetry JSONL"
                )
            try:
                loaded.append(TelemetryWindow.model_validate_json(line))
            except Exception as exc:
                raise ValueError(
                    f"{source}:{line_number}: invalid telemetry record: {exc}"
                ) from exc
    return _validate_series(loaded)
