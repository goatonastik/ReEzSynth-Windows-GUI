import json
import os
import re
import sys
import time
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


def progress(percent, stage, preview=None):
    message = {
        "percent": max(0, min(99, int(percent))),
        "stage": stage,
    }
    if preview is not None:
        message["preview"] = preview
    print("\n" + PREFIX + json.dumps(message), flush=True)


def validate_video_dimensions(video, keys):
    """Read image headers before creating outputs or starting an original-size job."""
    from PIL import Image
    if not video:
        raise ValueError('No source frames selected.')
    def dimensions(path):
        try:
            with Image.open(path) as image:
                return image.size
        except (OSError, ValueError) as exc:
            raise ValueError(f'Cannot read image dimensions: {path}') from exc
    reference = video[min(video)]
    expected = dimensions(reference)
    for label, images in (('Video frame', video), ('Keyframe', keys)):
        for number, path in sorted(images.items()):
            actual = dimensions(path)
            if actual != expected:
                raise ValueError(
                    f'Original resolution requires matching video and keyframe dimensions.\n'
                    f'{label} {number} ({Path(path).name}): {actual[0]} x {actual[1]}\n'
                    f'Expected: {expected[0]} x {expected[1]} (video {Path(reference).name}).\n'
                    'Use video frames and styled keyframes with matching dimensions.'
                )


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


def validate_edge_guides(folder, video):
    if not str(folder).strip():
        raise ValueError('Select a custom edge-guide directory when custom edge guides are enabled.')
    guides, _ = scan_images(folder, source=True)
    if set(guides) != set(video):
        raise ValueError('Custom edge-guide frame numbers must exactly match the source sequence.')
    from PIL import Image
    for number, path in guides.items():
        with Image.open(path) as guide, Image.open(video[number]) as source:
            if guide.size != source.size:
                raise ValueError(f'Custom edge-guide dimensions differ at frame {number}.')
            guide.verify()
    return guides


def render_job(job_path):
    from reezsynth_engines import LEGACY, FUOUM, validate_engine, write_engine_manifest
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    engine = validate_engine(job.get('render_options', {}).get('engine', LEGACY))
    if engine == FUOUM:
        from reezsynth_fuoum import render_fuoum_job
        return render_fuoum_job(job, progress)
    if getattr(sys.modules.get('ezsynth'), '_frontend_source', None) is not None:
        raise RuntimeError('The engine changed inside a worker. Start a new queue to switch engines.')
    write_engine_manifest(job)
    return _render_legacy_job(job_path)


def _render_legacy_job(job_path):
    os.environ["TQDM_DISABLE"] = "1"

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    progress(0, "Loading libraries")

    import cv2
    import numpy as np

    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    if job.get('type') == 'image_synthesis':
        from reezsynth_image import render_image_job
        return render_image_job(job, progress)
    from reezsynth_artifacts import validate_exports, artifact_records, save_artifacts
    from reezsynth_video_export import ffmpeg_executable, validate_video_export
    from reezsynth_config import validate_processing_settings
    processing = validate_processing_settings(job)
    exports = validate_exports(job.get("exports"))
    video_export = validate_video_export(job.get('video_export'), check_audio=True)
    video_ffmpeg = ffmpeg_executable() if video_export['enabled'] else None
    auxiliary_maps, auxiliary_flows = [], []
    entries = job["frames"]
    numbers = [entry[0] for entry in entries]
    count = len(entries)
    key = job["key"]
    key_position = numbers.index(key)
    output = Path(job["output"])
    from reezsynth_preview_transport import PreviewPublisher
    preview_publisher = PreviewPublisher(output)
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
            requested = processing['processing_size']
            if requested is not None:
                size = tuple(requested)
            else:
                limit = processing['max_width']
                scale = min(1.0, limit / width) if limit else 1.0
                size = (max(1, round(width * scale)), max(1, round(height * scale)))

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

    from reezsynth_config import (RENDER, quality_profile, validate_flow_model_available,
                                  validate_render, validate_weights, validate_synthesis_dimensions)
    options = dict(RENDER, **quality_profile(job["quality"]))
    options.update(job.get("render_options", {}))
    options = validate_render(options)
    if count > 1:
        validate_synthesis_dimensions(options['patchsize'], size)
        validate_flow_model_available(options['flow_model'], options['flow_arch'])
    weights = validate_weights(job.get("guide_weights"))
    print('[Settings] ' + json.dumps(dict(quality=job['quality'], processing_size=list(size),
        render_options=options, guide_weights=weights, blend_options=blend_options,
        exports=exports), sort_keys=True), flush=True)
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

    edge_guides = []
    if options['custom_edge_guides']:
        entries_edge = job.get('edge_guides', [])
        if [entry[0] for entry in entries_edge] != numbers:
            raise ValueError('Job custom edge-guide frame numbers must match its source frames.')
        for number, path in entries_edge:
            guide = read_image(path, grayscale=True)
            if guide.shape != original_shape[:2]:
                raise ValueError(f'Custom edge-guide dimensions differ at frame {number}.')
            if guide.shape[::-1] != size:
                guide = cv2.resize(guide, size, interpolation=cv2.INTER_AREA)
            edge_guides.append(guide)

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

        cuda_available = torch.cuda.is_available()
        if not cuda_available:
            if options['ebsynth_backend'] == 'cuda':
                raise RuntimeError('PyTorch CUDA is unavailable. Choose CPU or Auto EbSynth backend to use CPU optical flow.')
            if options['memory_efficient_raft']:
                raise RuntimeError('Memory-efficient RAFT correlation requires CUDA. Disable it for CPU optical flow.')
            if options['edge_method'] != 'Classic':
                raise RuntimeError('PST and PAGE edge detectors require CUDA. Choose Classic for CPU optical flow.')
            if blend_options.get('use_gpu'):
                raise RuntimeError('GPU blending requires CUDA. Disable GPU blending for CPU rendering.')
            print('Optical flow device: CPU', flush=True)
        else:
            print('Optical flow GPU:', torch.cuda.get_device_name(0), flush=True)
        if options['memory_efficient_raft']:
            from reezsynth_raft import require_alt_cuda_corr
            require_alt_cuda_corr()

        config = RunConfig(
            **{name: value for name, value in options.items()
               if name not in ("edge_method", "custom_edge_guides", "memory_efficient_raft",
                               "flow_arch", "flow_model", "ebsynth_backend", "engine",
                               "temporal_nnf", "sparse_features") and not name.startswith('fuoum_')},
            **{name: weights[name] / weights['key_wgt'] for name in ('edg_wgt', 'img_wgt', 'pos_wgt', 'wrp_wgt')},
            **{name: value for name, value in blend_options.items() if not name.startswith('fuoum_')},
        )

        runner = EzsynthBase(
            style_frs=styles,
            style_idxes=[numbers.index(n) for n, _ in style_entries],
            img_frs_seq=frames,
            cfg=config,
            edge_method=options["edge_method"],
            raft_flow_model_name=options["flow_model"],
            flow_arch=options["flow_arch"],
            do_mask=options["do_mask"],
            msk_frs_seq=masks or None,
            do_compute_edge=not options['custom_edge_guides'],
        )
        if edge_guides:
            runner.edge_guides = edge_guides

        # Requires the backend-forwarding edits from the earlier diagnostics.
        runner.eb.backend = runner.eb.backends[options["ebsynth_backend"]]
        print(f"Requested EbSynth backend: {options['ebsynth_backend'].upper()}", flush=True)

        completed = 0
        original_run = runner.eb.run
        frame_lookup = {}
        style_lookup = {}
        for sequence in (getattr(runner, 'img_frs_seq', frames),
                         getattr(runner, 'masked_frs_seq', None) or []):
            frame_lookup.update((id(image), number) for number, image in zip(numbers, sequence))
        for sequence in (getattr(runner, 'style_frs', styles),
                         getattr(runner, 'style_masked_frs', None) or []):
            style_lookup.update((id(image), number) for (number, _), image in zip(style_entries, sequence))
        native_seconds = 0.0
        loop_started = last_finished = time.perf_counter()
        mask_lookup = {}
        if masks and weights['mask_wgt']:
            for source_sequence in (getattr(runner, 'img_frs_seq', frames),
                                    getattr(runner, 'masked_frs_seq', []) or []):
                for source_frame, mask in zip(source_sequence, masks):
                    mask_lookup[id(source_frame)] = mask

        def tracked_run(*args, **kwargs):
            nonlocal completed, native_seconds, last_finished
            if mask_lookup:
                guides = list(kwargs['guides'])
                source, target, _ = guides[1]
                if id(source) not in mask_lookup or id(target) not in mask_lookup:
                    raise RuntimeError('Cannot match mask guides to source frames.')
                guides.append((mask_lookup[id(source)], mask_lookup[id(target)],
                               weights['mask_wgt'] / weights['key_wgt']))
                kwargs['guides'] = guides
            native_started = time.perf_counter()
            preparation_seconds = native_started - last_finished
            result = original_run(*args, **kwargs)
            native_elapsed = time.perf_counter() - native_started
            native_seconds += native_elapsed
            completed += 1
            preview = None
            frame_label = ''
            # The video guide identifies the actual target array and the style
            # argument identifies its keyframe, even for reversed/grouped passes.
            guides = kwargs.get('guides', [])
            if args and len(guides) > 1:
                origin = style_lookup.get(id(args[0]))
                target = frame_lookup.get(id(guides[1][1]))
                if origin is not None and target is not None:
                    direction = 'Backward' if target < origin else 'Forward'
                    preview = preview_publisher.publish(origin, direction, target, result[0])
                    frame_label = f' key={origin} frame={target} {direction.lower()}'
            progress(
                15 + (65 if grouped else 75) * completed / expected,
                f"Synthesis {completed}/{expected}",
                preview=preview,
            )
            print(f'[Timing] Frame {completed}/{expected}{frame_label}: '
                  f'between calls (flow/guides/blending) {preparation_seconds:.3f}s; '
                  f'EbSynth {native_elapsed:.3f}s', flush=True)
            last_finished = time.perf_counter()
            if grouped and completed == expected:
                progress(80, "Finalizing synthesis and blending")
            return result

        runner.eb.run = tracked_run
        progress(15, f"Synthesis 0/{expected}")

        try:
            from reezsynth_raft import correlation_mode
            with correlation_mode(options['memory_efficient_raft']):
                if any(exports.values()):
                    results, auxiliary_maps, auxiliary_flows = runner.run_sequences_full(return_flow=exports["flow"])
                else:
                    results, _ = runner.run_sequences()
        except RuntimeError as exc:
            if "cuda out of memory" in str(exc).lower():
                print(
                    f"[Memory] GPU memory exhausted at {size[0]} x {size[1]}. "
                    "RAFT optical flow can require more memory than the GPU's total capacity "
                    "at high resolutions. Try a smaller Processing size such as 720p "
                    "or 512 1:1. This also reduces output resolution; "
                    "the application will not silently resize or retry this job. "
                    "Fewer frames or worker reuse will not reduce the per-frame-pair "
                    "RAFT correlation allocation. Keep parallel rendering off while testing.",
                    flush=True,
                )
            raise
        finally:
            runner.eb.run = original_run
            print(f'[Timing] Synthesis loop {time.perf_counter() - loop_started:.3f}s; '
                  f'native EbSynth {native_seconds:.3f}s; preview capture {preview_publisher.seconds:.3f}s', flush=True)

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
            preview=preview_publisher.publish(key, 'Keyframe', key, image, stage='final') if count == 1 else None,
        )

    if any(exports.values()):
        progress(99, "Saving auxiliary outputs")
        records = artifact_records(numbers, [n for n, _ in style_entries], blend_options.get("only_mode", "none"))
        save_artifacts(output, exports, records, auxiliary_maps, auxiliary_flows)

    if video_export['enabled']:
        progress(99, 'Encoding rendered video')
        from reezsynth_video_export import export_rendered_video
        export_rendered_video(output, numbers, job['padding'], video_export,
                              ffmpeg_exe=video_ffmpeg)

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
