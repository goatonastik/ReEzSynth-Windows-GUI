"""Validated, atomic rendered-frame video export; no source-video importing."""
import json
import math
from pathlib import Path
import subprocess


DEFAULTS = {'enabled': False, 'fps': 24.0, 'audio': ''}


def ffmpeg_executable():
    try:
        import imageio_ffmpeg
        executable = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError('Rendered-video export requires imageio-ffmpeg. Run setup_reezsynth.ps1.') from exc
    if not executable.is_file():
        raise RuntimeError(f'Rendered-video FFmpeg executable is missing: {executable}')
    return executable


def validate_video_export(data=None, *, check_audio=False):
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError('Invalid rendered-video export settings.')
    result = dict(DEFAULTS, **data)
    if type(result['enabled']) is not bool:
        raise ValueError('Rendered-video export enabled must be true or false.')
    fps = result['fps']
    if type(fps) not in (int, float) or not math.isfinite(fps) or not .1 <= fps <= 240:
        raise ValueError('Rendered-video frame rate must be between 0.1 and 240 FPS.')
    result['fps'] = float(fps)
    if not isinstance(result['audio'], str):
        raise ValueError('Rendered-video audio path must be text.')
    result['audio'] = result['audio'].strip().strip('"')
    if check_audio and result['enabled'] and result['audio']:
        audio = Path(result['audio']).expanduser().resolve()
        if not audio.is_file():
            raise ValueError(f'Rendered-video audio file is missing: {audio}')
        result['audio'] = str(audio)
    return result


def export_rendered_video(output, numbers, padding, settings, *, run=subprocess.run,
                          ffmpeg_exe=None):
    settings = validate_video_export(settings, check_audio=True)
    if not settings['enabled']:
        return None
    output = Path(output).resolve()
    numbers = list(numbers)
    if not numbers or numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        raise ValueError('Rendered-video export requires consecutive ordered frame numbers.')
    if type(padding) is not int or padding < 1:
        raise ValueError('Rendered-video frame padding must be a positive integer.')
    missing = [output / f'{number:0{padding}d}.png' for number in numbers
               if not (output / f'{number:0{padding}d}.png').is_file()]
    if missing:
        raise ValueError(f'Rendered-video frame is missing: {missing[0]}')
    if ffmpeg_exe is None:
        ffmpeg_exe = ffmpeg_executable()
    final = output / 'render.mp4'
    temporary = output / 'render.part.mp4'
    temporary.unlink(missing_ok=True)
    pattern = output / f'%0{padding}d.png'
    command = [str(ffmpeg_exe), '-hide_banner', '-loglevel', 'error', '-y',
               '-framerate', format(settings['fps'], '.12g'), '-start_number', str(numbers[0]),
               '-i', str(pattern)]
    if settings['audio']:
        command += ['-i', settings['audio'], '-map', '0:v:0', '-map', '1:a:0?',
                    '-af', 'apad', '-t', format(len(numbers) / settings['fps'], '.12g')]
    command += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-movflags', '+faststart']
    command += ['-frames:v', str(len(numbers))]
    command += (['-c:a', 'aac'] if settings['audio'] else ['-an']) + [str(temporary)]
    try:
        completed = run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if completed.returncode or not temporary.is_file() or temporary.stat().st_size == 0:
            detail = (completed.stderr or completed.stdout or 'no output file').strip()
            raise RuntimeError('Rendered-video export failed: ' + detail[-2000:])
        temporary.replace(final)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    metadata = dict(version=1, file=final.name, fps=settings['fps'], frames=len(numbers),
                    first_frame=numbers[0], last_frame=numbers[-1],
                    audio=settings['audio'] or None)
    metadata_path = output / 'rendered_video.json'
    metadata_temporary = output / 'rendered_video.json.tmp'
    metadata_temporary.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    metadata_temporary.replace(metadata_path)
    return final
