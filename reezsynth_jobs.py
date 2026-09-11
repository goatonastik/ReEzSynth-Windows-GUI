import json
import os
import re
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PREFIX = "@@REEZSYNTH_PROGRESS@@"
EXTENSIONS = {".png", ".jpg", ".jpeg"}
FRAME_PATTERN = re.compile(r"^(.*?)(\d+)$")


def scan_images(folder, source=False):
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Directory does not exist: {folder}")

    files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in EXTENSIONS
    )

    if not files:
        raise ValueError(f"No PNG/JPEG images found in: {folder}")

    mapping = {}
    prefixes = set()
    padding = 1

    for path in files:
        match = FRAME_PATTERN.fullmatch(path.stem)
        if not match:
            raise ValueError(
                f"Cannot identify a frame number in '{path.name}'. "
                "Use names ending in digits, such as frame_0023.png."
            )

        prefix, digits = match.groups()
        number = int(digits)

        if number > 2147483647:
            raise ValueError(f"Frame number is too large: {path.name}")

        if number in mapping:
            raise ValueError(
                f"Duplicate frame number {number}: "
                f"'{mapping[number].name}' and '{path.name}'."
            )

        mapping[number] = path
        prefixes.add(prefix.casefold())
        padding = max(padding, len(digits))

    numbers = sorted(mapping)

    if source:
        if len(prefixes) != 1:
            raise ValueError(
                "The video directory contains multiple filename prefixes. "
                "Place a single source sequence in this directory."
            )

        for previous, current in zip(numbers, numbers[1:]):
            if current != previous + 1:
                raise ValueError(
                    f"Source sequence has a gap between frames "
                    f"{previous} and {current}. "
                    "This version requires consecutive source frames."
                )

    return {number: mapping[number] for number in numbers}, padding


def validate_folder(name):
    name = str(name).strip()
    path = Path(name)

    if (
        not name
        or path.is_absolute()
        or path.drive
        or not path.parts
        or ".." in path.parts
        or any(character in name for character in '<>:"|?*')
        or any(part.endswith((" ", ".")) for part in path.parts)
    ):
        raise ValueError(
            "Output must be a relative subfolder such as out_023, "
            "without '..' or invalid Windows filename characters."
        )

    return str(path)


def validate_row(row, video, keys):
    for field in ("key", "start", "end"):
        if type(row.get(field)) is not int:
            raise ValueError(f"'{field}' must be an integer.")

    key = row["key"]
    if key not in keys or key not in video:
        raise ValueError(f"Keyframe {key} has no matching source/keyframe file.")

    if not (
        row["start"] in video
        and row["end"] in video
        and row["start"] <= key <= row["end"]
    ):
        raise ValueError(
            f"Invalid range for keyframe {key}: "
            f"{row['start']} <= {key} <= {row['end']} is required."
        )

    for field in ("reverse", "forward"):
        if type(row.get(field)) is not bool:
            raise ValueError(f"'{field}' must be true or false.")

    result = dict(row)
    result["folder"] = validate_folder(row["folder"])
    return result


def build_plan(video_folder, keyframe_folder):
    video, padding = scan_images(video_folder, source=True)
    keys, _ = scan_images(keyframe_folder)

    unmatched = sorted(set(keys) - set(video))
    if unmatched:
        shown = ", ".join(map(str, unmatched[:12]))
        raise ValueError(
            f"Keyframes without matching source frames: {shown}. "
            "Keyframe numbers must match actual source-frame numbers."
        )

    key_numbers = sorted(keys)
    first, last = min(video), max(video)

    rows = []
    for index, key in enumerate(key_numbers):
        rows.append({
            "key": key,
            "start": key_numbers[index - 1] if index else first,
            "end": (
                key_numbers[index + 1]
                if index + 1 < len(key_numbers)
                else last
            ),
            "reverse": True,
            "forward": True,
            "folder": f"out_{key:0{padding}d}",
        })

    return video, keys, padding, rows


def progress(percent, stage):
    message = {
        "percent": max(0, min(99, int(percent))),
        "stage": stage,
    }
    print("\n" + PREFIX + json.dumps(message), flush=True)


def validate_masks(folder, video):
    """Require one readable mask per source frame with matching dimensions."""
    if not str(folder).strip():
        raise ValueError("Select a mask directory when masks are enabled.")
    masks, _ = scan_images(folder, source=True)
    if set(masks) != set(video):
        raise ValueError("Mask frame numbers must exactly match the source sequence.")
    from PIL import Image
    for number, mask in masks.items():
        with Image.open(mask) as mask_image, Image.open(video[number]) as source_image:
            if mask_image.size != source_image.size:
                raise ValueError(f"Mask dimensions differ at frame {number}.")
            mask_image.verify()
    return masks


def render_job(job_path):
    os.environ["TQDM_DISABLE"] = "1"

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    progress(0, "Loading libraries")

    import cv2
    import numpy as np

    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    from reezsynth_artifacts import validate_exports, artifact_records, save_artifacts
    exports = validate_exports(job.get("exports"))
    auxiliary_maps, auxiliary_flows = [], []
    entries = job["frames"]
    numbers = [entry[0] for entry in entries]
    count = len(entries)
    key = job["key"]
    key_position = numbers.index(key)
    output = Path(job["output"])
    from reezsynth_video_plan import plan_grouped_video, check_blend_dependencies
    grouped = job.get("type") == "grouped_video"
    if job.get("type") not in (None, "grouped_video"):
        raise ValueError("Unsupported render job type.")
    style_entries = [[key, job["style"]]]
    blend_options = dict(use_gpu=False, use_poisson_cupy=False)
    expected = count - 1
    if grouped:
        style_entries = job["styles"]
        if numbers != sorted(set(numbers)) or len(dict(style_entries)) != len(style_entries):
            raise ValueError("Grouped frames must be ordered and keyframes must be unique.")
        plan = plan_grouped_video(dict(entries), dict(style_entries),
                                  blend_options=job.get("blend_options"))
        style_entries = plan["styles"]
        blend_options = plan["blend_options"]
        check_blend_dependencies(blend_options)
        expected = plan["synthesis_work"]

    def read_image(path, grayscale=False):
        path = Path(path)
        data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
        if data.size == 0:
            raise ValueError(f"Empty image: {path}")

        image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Cannot decode image: {path}")
        return image

    print(f"Keyframe: {key}", flush=True)
    print(f"Source range: {numbers[0]} to {numbers[-1]}", flush=True)
    print(f"Frames in this job: {count}", flush=True)
    print(f"Keyframe position within job: {key_position}", flush=True)

    frames = []
    original_shape = None
    size = None

    for index, (_, path) in enumerate(entries):
        image = read_image(path)

        if original_shape is None:
            original_shape = image.shape
            height, width = image.shape[:2]
            limit = job["max_width"]
            scale = min(1.0, limit / width) if limit else 1.0
            size = (
                max(1, round(width * scale)),
                max(1, round(height * scale)),
            )

            if count > 1 and min(size) < 128:
                raise ValueError(
                    "Processing width and height must both be at least "
                    "128 pixels for this RAFT configuration."
                )

        if image.shape != original_shape:
            raise ValueError(f"Source frame dimensions differ: {path}")

        if image.shape[1::-1] != size:
            image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)

        frames.append(image)
        progress(10 * (index + 1) / count, f"Loading {index + 1}/{count}")

    styles = []
    for number, path in style_entries:
        style = read_image(path)
        if style.shape != original_shape:
            raise ValueError(f"Keyframe {number} dimensions do not match the original source frames.")
        if style.shape[1::-1] != size:
            style = cv2.resize(style, size, interpolation=cv2.INTER_AREA)
        styles.append(style)

    print("Processing size:", size, flush=True)

    from reezsynth_config import PREVIEW, STANDARD, RENDER, validate_render, validate_weights
    options = dict(RENDER, **(STANDARD if job["quality"] == "Standard" else PREVIEW))
    options.update(job.get("render_options", {}))
    options = validate_render(options)
    weights = validate_weights(job.get("guide_weights"))
    masks = []
    if options["do_mask"]:
        entries_mask = job.get("masks", [])
        if [entry[0] for entry in entries_mask] != numbers:
            raise ValueError("Job mask frame numbers must match its source frames.")
        for number, path in entries_mask:
            mask = read_image(path, grayscale=True)
            if mask.shape != original_shape[:2]:
                raise ValueError(f"Mask dimensions differ at frame {number}.")
            if mask.shape[::-1] != size:
                mask = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
            masks.append(mask)

    if count == 1:
        results = [style]
        if masks:
            mask = masks[0]
            if options["feather"]:
                radius = options["feather"]
                mask = cv2.GaussianBlur(mask, (radius, radius), 0)
            alpha = mask.astype(np.float32)[:, :, None] / 255.0
            results = [(style * alpha + frames[0] * (1 - alpha)).astype(np.uint8)]
        progress(90, "Keyframe copy")
    else:
        progress(10, "Initializing engine")

        import torch
        from ezsynth.aux_classes import RunConfig
        from ezsynth.main_ez import EzsynthBase

        if not torch.cuda.is_available():
            raise RuntimeError("PyTorch CUDA is unavailable.")

        print("GPU:", torch.cuda.get_device_name(0), flush=True)

        config = RunConfig(
            **{name: value for name, value in options.items() if name != "edge_method"},
            **{name: weights[name] / weights['key_wgt'] for name in ('edg_wgt', 'img_wgt', 'pos_wgt', 'wrp_wgt')},
            **blend_options,
        )

        runner = EzsynthBase(
            style_frs=styles,
            style_idxes=[numbers.index(n) for n, _ in style_entries],
            img_frs_seq=frames,
            cfg=config,
            edge_method=options["edge_method"],
            raft_flow_model_name="sintel",
            flow_arch="RAFT",
            do_mask=options["do_mask"],
            msk_frs_seq=masks or None,
        )

        # Requires the backend-forwarding edits from the earlier diagnostics.
        runner.eb.backend = runner.eb.backends["cuda"]
        print("Requested EbSynth backend: CUDA", flush=True)

        completed = 0
        original_run = runner.eb.run
        mask_lookup = {}
        if masks and weights['mask_wgt']:
            for source_sequence in (getattr(runner, 'img_frs_seq', frames),
                                    getattr(runner, 'masked_frs_seq', []) or []):
                for source_frame, mask in zip(source_sequence, masks):
                    mask_lookup[id(source_frame)] = mask

        def tracked_run(*args, **kwargs):
            nonlocal completed
            if mask_lookup:
                guides = list(kwargs['guides'])
                source, target, _ = guides[1]
                if id(source) not in mask_lookup or id(target) not in mask_lookup:
                    raise RuntimeError('Cannot match mask guides to source frames.')
                guides.append((mask_lookup[id(source)], mask_lookup[id(target)],
                               weights['mask_wgt'] / weights['key_wgt']))
                kwargs['guides'] = guides
            result = original_run(*args, **kwargs)
            completed += 1
            progress(
                15 + (65 if grouped else 75) * completed / expected,
                f"Synthesis {completed}/{expected}",
            )
            if grouped and completed == expected:
                progress(80, "Finalizing synthesis and blending")
            return result

        runner.eb.run = tracked_run
        progress(15, f"Synthesis 0/{expected}")

        try:
            if any(exports.values()):
                results, auxiliary_maps, auxiliary_flows = runner.run_sequences_full(return_flow=exports["flow"])
            else:
                results, _ = runner.run_sequences()
        finally:
            runner.eb.run = original_run

        if completed != expected:
            raise RuntimeError(
                f"Expected {expected} synthesis calls, received {completed}."
            )

    if len(results) != count:
        raise RuntimeError(
            f"Expected {count} output frames, received {len(results)}."
        )

    progress(90, f"Saving 0/{count}")

    for index, (number, image) in enumerate(zip(numbers, results)):
        if image.shape != frames[index].shape or not np.isfinite(image).all():
            raise RuntimeError(f"Invalid output image for frame {number}.")

        image = np.clip(image, 0, 255).astype(np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise RuntimeError(f"Could not encode frame {number}.")

        name = f"{number:0{job['padding']}d}.png"
        destination = output / name
        temporary = output / (name + ".part")
        temporary.write_bytes(encoded.tobytes())
        temporary.replace(destination)

        progress(
            90 + 9 * (index + 1) / count,
            f"Saving {index + 1}/{count}",
        )

    if any(exports.values()):
        progress(99, "Saving auxiliary outputs")
        records = artifact_records(numbers, [n for n, _ in style_entries], blend_options.get("only_mode", "none"))
        save_artifacts(output, exports, records, auxiliary_maps, auxiliary_flows)

    (output / "COMPLETE.txt").write_text(
        f"Keyframe: {key}\n"
        f"Range: {numbers[0]} to {numbers[-1]}\n"
        f"Saved frames: {count}\n",
        encoding="utf-8",
    )

    progress(99, "Finishing")
    print(f"COMPLETE: keyframe {key}, {count} frames -> {output}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python reezsynth_jobs.py job.json")

    try:
        render_job(sys.argv[1])
    except Exception:
        traceback.print_exc()
        sys.exit(1)

