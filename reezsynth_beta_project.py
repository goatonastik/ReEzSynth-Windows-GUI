"""Strict EBS05 project reader/writer for external EbSynth Beta project interchange.

The format was checked against a Beta-saved project and the independently
published MIT-licensed EbSynth Project Editor. This module does not launch Beta.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, replace
from pathlib import Path


MAGIC = b"EBS05\0"
METADATA = b"V02\0"
FINAL_MARKER = 704
MAX_STRING_BYTES = 1_000_000
MAX_INTERVALS = 100_000
MAX_FLOAT32 = 3.4028234663852886e38


@dataclass(frozen=True)
class Interval:
    key: int
    backward_enabled: bool
    forward_enabled: bool
    backward_stop: int
    forward_stop: int
    output: str

    def validate(self) -> None:
        for name in ("key", "backward_stop", "forward_stop"):
            value = getattr(self, name)
            if not isinstance(value, int) or not 0 <= value <= 0x7FFFFFFF:
                raise ValueError(f"Invalid {name}: {value!r}")
        if self.backward_enabled and self.backward_stop > self.key:
            raise ValueError(f"Backward stop {self.backward_stop} exceeds key {self.key}")
        if self.forward_enabled and self.forward_stop < self.key:
            raise ValueError(f"Forward stop {self.forward_stop} precedes key {self.key}")
        _encode_string(self.output)


@dataclass(frozen=True)
class Project:
    video: str
    mask: str
    keys: str
    mask_enabled: bool
    key_weight: float
    video_weight: float
    mask_weight: float
    mapping: float
    deflicker: float
    diversity: float
    intervals: tuple[Interval, ...]
    detail: int
    gpu: bool
    fps: float

    def validate(self) -> None:
        for path in (self.video, self.mask, self.keys):
            _encode_string(path)
        if not isinstance(self.mask_enabled, bool) or not isinstance(self.gpu, bool):
            raise ValueError("Mask and GPU flags must be boolean")
        if not 1 <= self.detail <= 4:
            raise ValueError("Synthesis detail must be 1 through 4")
        for name in ("key_weight", "video_weight", "mask_weight", "mapping", "deflicker", "diversity"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= MAX_FLOAT32:
                raise ValueError(f"Invalid {name}: {value!r}")
        if not math.isfinite(self.fps) or not 0 < self.fps <= MAX_FLOAT32:
            raise ValueError(f"Invalid frame rate: {self.fps!r}")
        if len(self.intervals) > MAX_INTERVALS:
            raise ValueError("Too many frame intervals")
        if len({interval.key for interval in self.intervals}) != len(self.intervals):
            raise ValueError("Duplicate keyframes in frame intervals")
        for interval in self.intervals:
            interval.validate()


def _encode_string(value: str) -> bytes:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"Invalid path: {value!r}")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Non-ASCII paths are not validated for this Beta build") from exc
    if len(encoded) > MAX_STRING_BYTES:
        raise ValueError("Path is too long")
    return encoded


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    def take(self, size: int) -> bytes:
        end = self.position + size
        if end > len(self.data):
            raise ValueError(f"Truncated EBS05 file at byte {self.position}")
        result = self.data[self.position:end]
        self.position = end
        return result

    def number(self, kind: str):
        return struct.unpack("<" + kind, self.take(struct.calcsize("<" + kind)))[0]

    def boolean(self) -> bool:
        value = self.number("B")
        if value not in (0, 1):
            raise ValueError(f"Invalid boolean at byte {self.position - 1}")
        return bool(value)

    def string(self) -> str:
        size = self.number("i")
        if size < 1 or size > MAX_STRING_BYTES:
            raise ValueError(f"Invalid path length: {size}")
        try:
            return self.take(size).decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("Non-ASCII path encoding is not validated") from exc


def from_bytes(data: bytes) -> Project:
    reader = _Reader(data)
    if reader.take(len(MAGIC)) != MAGIC:
        raise ValueError("Unsupported EbSynth project version; expected EBS05")
    video, mask, keys = (reader.string() for _ in range(3))
    mask_enabled = reader.boolean()
    weights = tuple(reader.number("f") for _ in range(6))
    count = reader.number("i")
    if not 0 <= count <= MAX_INTERVALS:
        raise ValueError(f"Invalid interval count: {count}")
    intervals = []
    for _ in range(count):
        intervals.append(Interval(
            reader.number("i"), reader.boolean(), reader.boolean(),
            reader.number("i"), reader.number("i"), reader.string(),
        ))
    if reader.take(len(METADATA)) != METADATA:
        raise ValueError("Unsupported or missing V02 project metadata")
    detail = reader.number("i")
    gpu = reader.boolean()
    fps = reader.number("f")
    if reader.number("i") != FINAL_MARKER:
        raise ValueError("Incorrect EBS05 final marker")
    if reader.position != len(data):
        raise ValueError("Unexpected data after EBS05 final marker")
    project = Project(video, mask, keys, mask_enabled, *weights, tuple(intervals), detail, gpu, fps)
    project.validate()
    return project


def to_bytes(project: Project) -> bytes:
    project.validate()
    data = bytearray(MAGIC)

    def string(value: str) -> None:
        encoded = _encode_string(value)
        data.extend(struct.pack("<i", len(encoded)))
        data.extend(encoded)

    for path in (project.video, project.mask, project.keys):
        string(path)
    data.extend(struct.pack("<B6fi", int(project.mask_enabled),
        project.key_weight, project.video_weight, project.mask_weight,
        project.mapping, project.deflicker, project.diversity,
        len(project.intervals)))
    for interval in project.intervals:
        data.extend(struct.pack("<iBBii", interval.key,
            int(interval.backward_enabled), int(interval.forward_enabled),
            interval.backward_stop, interval.forward_stop))
        string(interval.output)
    data.extend(METADATA)
    data.extend(struct.pack("<iBfi", project.detail, int(project.gpu), project.fps, FINAL_MARKER))
    # Decimal UI values are rounded to Beta's 32-bit floating-point fields.
    # Compare against that canonical form, while still checking every field.
    canonical = replace(project, **{
        name: struct.unpack("<f", struct.pack("<f", getattr(project, name)))[0]
        for name in ("key_weight", "video_weight", "mask_weight", "mapping",
                     "deflicker", "diversity", "fps")
    })
    if from_bytes(bytes(data)) != canonical:
        raise ValueError("EBS05 project did not round-trip")
    return bytes(data)


def read(path: Path) -> Project:
    return from_bytes(path.read_bytes())


def with_intervals(project: Project, ranges: dict[int, tuple[int, int]], output_root: str) -> Project:
    if set(ranges) != {interval.key for interval in project.intervals}:
        raise ValueError("Range keys must match the project's keyframes")
    updated = tuple(replace(interval,
        backward_enabled=True, forward_enabled=True,
        backward_stop=ranges[interval.key][0],
        forward_stop=ranges[interval.key][1],
        output=rf"{output_root}\key{interval.key}\[##].png",
    ) for interval in project.intervals)
    result = replace(project, intervals=updated)
    result.validate()
    return result


def validate_partition(project: Project, first: int, last: int) -> None:
    """Require every requested frame to have exactly one enabled output interval."""
    project.validate()
    if first < 0 or last < first:
        raise ValueError("Invalid sequence bounds")
    coverage = [0] * (last - first + 1)
    outputs = set()
    for interval in project.intervals:
        start = interval.backward_stop if interval.backward_enabled else interval.key
        stop = interval.forward_stop if interval.forward_enabled else interval.key
        if start < first or stop > last:
            raise ValueError(f"Key {interval.key} exceeds sequence bounds")
        if interval.output in outputs:
            raise ValueError(f"Repeated output path: {interval.output}")
        outputs.add(interval.output)
        for number in range(start, stop + 1):
            coverage[number - first] += 1
    gaps = [first + i for i, count in enumerate(coverage) if count == 0]
    overlaps = [first + i for i, count in enumerate(coverage) if count > 1]
    if gaps or overlaps:
        raise ValueError(f"Frame partition has gaps {gaps[:8]} and overlaps {overlaps[:8]}")
