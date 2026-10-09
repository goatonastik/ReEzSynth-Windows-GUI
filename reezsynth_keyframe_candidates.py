"""Non-destructive local candidate records for the Keyframe Generator."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


CANDIDATE_DIR = ".reezsynth-candidates"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_size(path: Path, *, png_only: bool = False) -> tuple[int, int]:
    # Keep Pillow's native pixel limit, without silently accepting its warning
    # band or changing the process-wide limit used by other image consumers.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                allowed = {"PNG"} if png_only else {"PNG", "JPEG"}
                if image.format not in allowed:
                    raise ValueError(f"Unsupported image format: {path.name}")
                size = image.size
                image.verify()
                return size
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError(
            f"Image exceeds the supported pixel limit: {path.name}. "
            "It was not imported or resized."
        ) from exc
    except SyntaxError as exc:
        raise ValueError(
            f"Image is damaged or incomplete: {path.name}. "
            "Wait for the image to finish saving, then try again."
        ) from exc


@dataclass(frozen=True)
class CandidateRecord:
    identifier: str
    image_path: Path
    metadata_path: Path
    width: int
    height: int


def import_candidate(
    project_directory: str | Path,
    frame_number: int,
    source_image: str | Path,
    generated_image: str | Path,
    *,
    mode: str,
    drawing_image: str | Path | None = None,
) -> CandidateRecord:
    """Copy a candidate outside the numbered key folder without approving it.

    Image dimensions must already match the source. Resizing a result here would
    hide geometry errors, so the user must correct it in the generation workflow.
    """
    if mode not in {"generate", "modify"}:
        raise ValueError("Mode must be 'generate' or 'modify'.")
    if type(frame_number) is not int or frame_number < 0:
        raise ValueError("Frame number must be a nonnegative integer.")
    source = Path(source_image).expanduser().resolve(strict=True)
    generated = Path(generated_image).expanduser().resolve(strict=True)
    drawing = (Path(drawing_image).expanduser().resolve(strict=True)
               if drawing_image else None)
    if mode == "modify" and drawing is None:
        raise ValueError("Modify mode requires an existing drawing.")
    source_size = _image_size(source)
    generated_size = _image_size(generated, png_only=True)
    if drawing is not None and _image_size(drawing) != source_size:
        raise ValueError("Drawing dimensions differ from the original source frame.")
    if generated_size != source_size:
        raise ValueError(
            f"Generated image is {generated_size[0]} x {generated_size[1]}, "
            f"but the native source is {source_size[0]} x {source_size[1]}. "
            "Generate at native resolution; this import will not resize it."
        )

    if not str(project_directory).strip():
        raise ValueError("Select a project directory before importing a candidate.")
    root = Path(project_directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Project directory does not exist: {root}")
    candidate_root = root / CANDIDATE_DIR
    candidate_root.mkdir(exist_ok=True)
    identifier = uuid.uuid4().hex
    destination = candidate_root / f"frame_{frame_number:06d}_{identifier}.png"
    metadata_path = destination.with_suffix(".json")
    temporary = candidate_root / f".{identifier}.tmp"
    record = {
        "schema": 1,
        "status": "unreviewed",
        "identifier": identifier,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "frame_number": frame_number,
        "width": source_size[0],
        "height": source_size[1],
        "source": {"path": str(source), "sha256": _sha256(source)},
        "drawing": ({"path": str(drawing), "sha256": _sha256(drawing)}
                    if drawing else None),
        "generated": {"sha256": _sha256(generated)},
    }
    try:
        with generated.open("rb") as source_stream, temporary.open("xb") as target:
            shutil.copyfileobj(source_stream, target)
            target.flush()
            os.fsync(target.fileno())
        if _sha256(temporary) != record["generated"]["sha256"]:
            raise ValueError("Candidate image changed during import; try again.")
        if _image_size(temporary, png_only=True) != source_size:
            raise ValueError("Candidate dimensions changed during import; try again.")
        os.replace(temporary, destination)
        # Publishing a record never touches a numbered synthesis key. If the
        # metadata write fails, remove only this new candidate image.
        with metadata_path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
            stream.write("\n")
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        raise
    return CandidateRecord(identifier, destination, metadata_path, *source_size)
