"""Opt-in owner-footage inspection and bounded transparent FuouM acceptance run."""
import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import json
import cv2
import numpy as np
from reezsynth_jobs import scan_images
from reezsynth_config import atomic_json, validate_render, quality_profile
from reezsynth_engines import FUOUM, prepare_runtime, file_sha256


def inspect(root):
    records = []
    for name, source, keys in [('test-s1', 's1', 's1k'), ('test-s6', 's6', 's6k'), ('test-s9', 's9', 's9k')]:
        frames = scan_images(root / name / source, source=True)[0]
        styles = scan_images(root / name / keys)[0]
        def details(path):
            image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise ValueError(f'Cannot decode {path}')
            return dict(shape=list(image.shape), dtype=str(image.dtype),
                        alpha_range=[int(image[..., 3].min()), int(image[..., 3].max())] if image.ndim == 3 and image.shape[2] == 4 else None)
        record = dict(name=name, frames=frames, styles=styles)
        records.append(record)
        print(json.dumps(dict(name=name, frame_count=len(frames), range=[min(frames), max(frames)],
            source=details(next(iter(frames.values()))), keys={n: details(p) for n, p in styles.items()},
            unmatched_keys=sorted(set(styles) - set(frames))), indent=2), flush=True)
    return records


def contact_sheet(output, frames, start, end):
    from PIL import Image, ImageDraw
    numbers = sorted(set([start, start + (end - start) // 3, start + 2 * (end - start) // 3, end]))
    sheet = Image.new('RGB', (256 * len(numbers), 3 * 280), '#202020')
    draw = ImageDraw.Draw(sheet)
    for column, number in enumerate(numbers):
        source = Image.open(frames[number]).convert('RGB')
        artwork = Image.open(output / f'{number:04}.png').convert('RGBA')
        source = source.resize(artwork.size)
        checker = Image.new('RGBA', artwork.size, '#eeeeee')
        squares = ImageDraw.Draw(checker)
        for y in range(0, artwork.height, 16):
            for x in range(0, artwork.width, 16):
                if (x // 16 + y // 16) % 2:
                    squares.rectangle((x, y, x + 15, y + 15), fill='#c8c8c8')
        panels = [source, Image.alpha_composite(checker, artwork),
                  Image.alpha_composite(source.convert('RGBA'), artwork)]
        for row, (label, panel) in enumerate(zip(['Source', 'Artwork on checkerboard', 'Artwork over source'], panels)):
            panel.thumbnail((256, 256))
            sheet.paste(panel.convert('RGB'), (column * 256, row * 280 + 24))
            draw.text((column * 256 + 5, row * 280 + 5), f'{label}: {number}', fill='white')
    sheet.save(output / 'contact_sheet.jpg')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--full-resolution', action='store_true', help='Render the same short intervals without rescaling.')
    parser.add_argument('--native-keys', action='store_true', help='Exact native-resolution single-key payload checks, not interpolation.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    inputs = root / 'diagnostic_outputs/test-temp'
    records = inspect(inputs)
    if not args.run and not args.native_keys and not args.full_resolution:
        return
    report = root / 'diagnostic_outputs' / ('fuoum_alpha_footage_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    report.mkdir()
    options = validate_render(dict(quality_profile('Standard'), engine=FUOUM, stream_frames=True))
    runtime = prepare_runtime(options, {})
    summaries = []
    for record in records:
        frames, styles = record['frames'], record['styles']
        valid = sorted(set(styles) & set(frames))
        if len(valid) < 2:
            raise ValueError(f'{record["name"]}: need two matched keys')
        start, end = min(zip(valid, valid[1:]), key=lambda pair: pair[1] - pair[0])
        if args.native_keys:
            end = start
        selected_frames = [[n, str(frames[n])] for n in range(start, end + 1)]
        selected_styles = [[n, str(styles[n])] for n in sorted(set([start, end]))]
        hashes = {p: file_sha256(p) for _, p in selected_frames + selected_styles}
        output = report / record['name']; output.mkdir()
        job = dict(type='grouped_video', key=start, style=selected_styles[0][1], frames=selected_frames,
            styles=selected_styles, output=str(output), padding=4, quality='Standard', max_width=0 if args.native_keys or args.full_resolution else 512,
            render_options=options, engine_runtime=runtime, precompute_cache=str(report / 'cache'))
        path = output / 'job.json'; atomic_json(path, job)
        print(f'Rendering {record["name"]}: frames {start}–{end}, Standard, max width {job["max_width"]}, no masks.', flush=True)
        with (output / 'diagnostic.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([runtime['python'], '-B', str(root / 'reezsynth_jobs.py'), str(path)],
                cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=1800,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or not (output / 'COMPLETE.txt').is_file():
            raise RuntimeError(f'Render failed: {output / "diagnostic.log"}')
        outputs = [output / f'{n:04}.png' for n in range(start, end + 1)]
        alpha_ranges = []
        for image_path in outputs:
            image = cv2.imdecode(np.frombuffer(image_path.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None or image.ndim != 3 or image.shape[2] != 4 or image.dtype != np.uint8:
                raise RuntimeError(f'Invalid RGBA output: {image_path}')
            alpha_ranges.append([int(image[..., 3].min()), int(image[..., 3].max())])
            if job['max_width'] == 0:
                source = cv2.imdecode(np.frombuffer(Path(frames[int(image_path.stem)]).read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
                if image.shape[:2] != source.shape[:2]:
                    raise RuntimeError(f'Output was unexpectedly resized: {image_path}')
            if job['max_width'] == 0 and int(image_path.stem) in (start, end):
                original = cv2.imdecode(np.frombuffer(Path(styles[int(image_path.stem)]).read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
                np.testing.assert_array_equal(image, original)
        if hashes != {p: file_sha256(p) for p in hashes}:
            raise RuntimeError('Input files changed')
        if list(output.glob('.frame-storage-*')) or list(output.glob('.fuoum-cache-*')):
            raise RuntimeError('Temporary render storage remains')
        summaries.append(dict(name=record['name'], range=[start, end], output=str(output),
            alpha_ranges=alpha_ranges, input_sha256=hashes, input_unchanged=True,
            exact_native_key=args.native_keys,
            full_resolution=args.full_resolution, max_width=job['max_width'],
            note='Native single-key payload check, not interpolation certification.' if args.native_keys else
                 'Original-resolution short interval, not long-run certification.' if args.full_resolution else
                 'Rescaled short interval, not full-resolution or long-run certification.'))
        atomic_json(report / 'summary.json', summaries)
        contact_sheet(output, frames, start, end)
        print(f'{record["name"]}: completed {len(outputs)} RGBA frames.', flush=True)
    print(f'Retained report: {report}', flush=True)


if __name__ == '__main__':
    main()
