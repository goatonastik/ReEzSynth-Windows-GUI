"""Render a review matrix from user frame/keyframe folders for both engines."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

import cv2
import numpy as np

from reezsynth_config import atomic_json, quality_profile, validate_render
from reezsynth_engines import FUOUM, LEGACY, ROOT, prepare_runtime
from reezsynth_jobs import build_plan, validate_masks
from reezsynth_video_plan import plan_grouped_video


def selections(value, choices):
    return choices if value == "both" else (value,)


def plan_cases(args):
    video, keys, padding, _ = build_plan(args.video_dir, args.keyframe_dir)
    if len(keys) < 2:
        raise ValueError("Quality review requires at least two styled keyframes.")
    masks = validate_masks(args.mask_dir, video) if args.mask_dir else {}
    engines = selections(args.engine, ("legacy", "fuoum"))
    qualities = selections(args.quality, ("Standard", "Highest"))
    cases = [dict(engine=engine, quality=quality) for engine in engines for quality in qualities]
    return video, keys, masks, padding, cases


def output_metrics(output, numbers, keys, padding):
    images = {number: cv2.imread(str(output / f"{number:0{padding}d}.png"))
              for number in numbers}
    if any(value is None for value in images.values()):
        raise RuntimeError("One or more expected review frames are missing or unreadable.")
    adjacent = {f"{a}-{b}": float(np.mean(np.abs(images[a].astype(np.float32) -
                                                     images[b].astype(np.float32))))
                for a, b in zip(numbers, numbers[1:])}
    boundaries = {}
    for key in sorted(keys):
        boundaries[str(key)] = dict(
            previous=adjacent.get(f"{key - 1}-{key}"),
            following=adjacent.get(f"{key}-{key + 1}"))
    return dict(mean_adjacent_difference=float(np.mean(list(adjacent.values()))),
                max_adjacent_difference=max(adjacent.values()), boundaries=boundaries)


def verify_vectors(output, numbers, bidirectional):
    root = output / 'flow_vectors'
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    expected = set(zip(numbers, numbers[1:]))
    if bidirectional:
        expected |= {(b, a) for a, b in list(expected)}
    fields = {}
    for record in manifest['artifacts']:
        pair = record['flow_from'], record['flow_to']
        value = np.load(root / record['file'], allow_pickle=False)
        if (pair in fields or record['grid_frame'] != pair[0] or value.ndim != 3 or
                value.shape[2] != 2 or value.dtype.kind != 'f' or not np.isfinite(value).all()):
            raise RuntimeError('Invalid numerical flow field or direction metadata.')
        fields[pair] = value
    if set(fields) != expected:
        raise RuntimeError('Numerical flow exports do not cover the expected directed frame pairs.')
    metrics = dict(directed_flow_pairs=len(fields))
    if bidirectional:
        # Descriptive diagnostic: inverse fields live on different grids, so
        # their difference from -forward is not a ground-truth accuracy score.
        metrics['mean_backward_vs_negated_forward_difference'] = float(np.mean([
            np.abs(fields[a, b] + fields[b, a]).mean() for a, b in zip(numbers, numbers[1:])]))
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-dir", required=True, help="Consecutively numbered source frames.")
    parser.add_argument("--keyframe-dir", required=True, help="Styled frames with matching numbers.")
    parser.add_argument("--mask-dir", default="", help="Optional mask for every source frame.")
    parser.add_argument("--engine", choices=("legacy", "fuoum", "both"), default="both")
    parser.add_argument("--quality", choices=("Standard", "Highest", "both"), default="both")
    parser.add_argument("--bidirectional", action="store_true", help="Use independently estimated FuouM flow directions.")
    parser.add_argument("--fuoum-flow-engine", choices=("RAFT", "NeuFlow"), default="RAFT")
    parser.add_argument("--size", nargs=2, type=int, metavar=("WIDTH", "HEIGHT"),
                        help="Optional exact processing size; default keeps original resolution.")
    parser.add_argument("--fps", type=float, default=24.0)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--fuoum-source", default="")
    parser.add_argument("--fuoum-python", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--plan", action="store_true", help="Validate and print cases without writes/renders.")
    args = parser.parse_args(argv)
    if args.size and min(args.size) < 128:
        parser.error("Processing dimensions must each be at least 128 pixels.")
    if not 0.1 <= args.fps <= 240 or args.timeout < 1:
        parser.error("FPS must be 0.1-240 and timeout must be positive.")
    video, keys, masks, padding, cases = plan_cases(args)
    plan = dict(video_dir=str(Path(args.video_dir).resolve()),
                keyframe_dir=str(Path(args.keyframe_dir).resolve()),
                mask_dir=str(Path(args.mask_dir).resolve()) if args.mask_dir else None,
                frames=len(video), keyframes=sorted(keys), processing_size=args.size,
                fps=args.fps, cases=cases, bidirectional=args.bidirectional,
                fuoum_flow_engine=args.fuoum_flow_engine,
                review_focus=["styled-keyframe boundaries", "occlusion", "fast motion",
                              "fine detail", "temporal stability", "feathered mask edges"])
    if args.plan:
        print(json.dumps(plan, indent=2))
        return 0

    root = (Path(args.output_root).expanduser().resolve() if args.output_root else
            ROOT / "diagnostic_outputs" / ("quality_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")))
    root.mkdir(parents=True, exist_ok=False)
    report = dict(**plan, output=str(root), results=[], passed=False)
    atomic_json(root / "report.json", report)
    engine_names = {"legacy": LEGACY, "fuoum": FUOUM}
    numbers = sorted(video)
    for case in cases:
        label = f"{case['engine']}_{case['quality'].lower()}"
        output = root / label
        output.mkdir()
        engine = engine_names[case["engine"]]
        options = validate_render(dict(quality_profile(case["quality"]), engine=engine,
                                       fuoum_bidirectional_flow=args.bidirectional,
                                       fuoum_flow_engine=args.fuoum_flow_engine,
                                       do_mask=bool(masks), feather=9 if masks else 0))
        application = dict(fuoum_source=args.fuoum_source, fuoum_python=args.fuoum_python)
        runtime = prepare_runtime(options, application)
        grouped = plan_grouped_video(video, keys)
        job = dict(grouped, output=str(output), quality=case["quality"], padding=padding,
                   processing_size=args.size, max_width=0, render_options=options,
                   engine_runtime=runtime, guide_weights={"mask_wgt": 2.0 if masks else 0.0},
                   masks=[[number, str(masks[number])] for number in numbers] if masks else [],
                   exports={"maps": True, "flow": True, "flow_vectors": True},
                   video_export={"enabled": True, "fps": args.fps, "audio": ""})
        job_path = output / "job.json"
        atomic_json(job_path, job)
        started = time.monotonic()
        result = subprocess.run([runtime["python"], "-B", "-X", "utf8", "-u",
                                 str(ROOT / "reezsynth_jobs.py"), str(job_path)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=args.timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (output / "worker.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        if result.returncode or not (output / "COMPLETE.txt").is_file():
            raise RuntimeError(f"{label} failed; see {output / 'worker.log'}")
        metrics = output_metrics(output, numbers, keys, padding)
        metrics.update(verify_vectors(output, numbers, engine == FUOUM and args.bidirectional))
        metrics.update(case, seconds=time.monotonic() - started, output=str(output),
                       video=str(output / "render.mp4"))
        report["results"].append(metrics)
        atomic_json(root / "report.json", report)
        print(json.dumps(metrics), flush=True)
    report["passed"] = True
    atomic_json(root / "report.json", report)
    print("PASS:", root)
    print("Review each render.mp4 around the listed keyframe boundaries; adjacent differences are descriptive, not flicker scores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
