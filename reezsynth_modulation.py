"""Target-grid guide modulation with explicit group-to-channel expansion."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import hashlib


VIDEO_MODES = ('Off', 'All guides', 'Edge guide', 'Video guide', 'Position guide', 'Warped-style guide')
VIDEO_GUIDES = ('Edge guide', 'Video guide', 'Position guide', 'Warped-style guide')


def require_backend(options, enabled):
    from reezsynth_engines import LEGACY
    if enabled and options.get('engine', LEGACY) == LEGACY and options.get('ebsynth_backend', 'cuda') != 'cuda':
        raise ValueError('Legacy guide modulation requires explicit CUDA. Its CPU backend ignores modulation; Auto may choose CPU.')


def read_map(path, shape, size=None):
    import cv2
    import numpy as np
    value = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
    if value is None or value.dtype != np.uint8 or value.ndim != 2:
        raise ValueError(f'Modulation must be an 8-bit grayscale image: {path}')
    if value.shape != tuple(shape):
        raise ValueError(f'Modulation must match its target dimensions {tuple(shape)[::-1]}: {path}')
    if size is not None and value.shape[::-1] != tuple(size):
        value = cv2.resize(value, tuple(size), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(value)


def pack_maps(guides, maps):
    """Repeat each grayscale map across its guide's channels; blank means full."""
    import numpy as np
    if len(guides) != len(maps) or not guides:
        raise ValueError('Modulation maps must correspond to the supplied guide pairs.')
    if not any(value is not None for value in maps):
        return None
    shape = guides[0][1].shape[:2]
    channels = [1 if pair[1].ndim == 2 else pair[1].shape[2] for pair in guides]
    if not 1 <= sum(channels) <= 24:
        raise ValueError('Modulation requires between 1 and 24 guide channels.')
    blocks = []
    for pair, value, count in zip(guides, maps, channels):
        if pair[1].shape[:2] != shape:
            raise ValueError('Modulation target guide dimensions must match.')
        if value is None:
            value = np.full(shape, 255, np.uint8)
        if not isinstance(value, np.ndarray) or value.dtype != np.uint8 or value.shape != shape:
            raise ValueError('Modulation must be uint8 grayscale on the processed target grid.')
        blocks.append(np.repeat(value[..., None], count, axis=2))
    return np.ascontiguousarray(np.concatenate(blocks, axis=2))


def map_info(path, value):
    return dict(path=str(path), processed_shape=list(value.shape),
                processed_sha256=hashlib.sha256(value.tobytes()).hexdigest())


def channel_layout(guides, labels, selected):
    result, start = [], 0
    for index, (pair, label) in enumerate(zip(guides, labels)):
        count = 1 if pair[1].ndim == 2 else pair[1].shape[2]
        result.append(dict(guide=label, channel_start=start, channel_count=count,
                           modulated=index in selected))
        start += count
    return result


def write_manifest(output, **data):
    from reezsynth_config import atomic_json
    atomic_json(Path(output) / 'modulation_manifest.json', dict(version=1,
        grid='processed_target', dtype='uint8', channel_order='native_guide_concatenation',
        multiplier='value / 255', processing_resize='INTER_AREA', pyramid_resize='engine_native', **data))


def validate_video_maps(options, video):
    if options.get('modulation_guide', 'Off') == 'Off':
        return {}
    require_backend(options, True)
    from reezsynth_jobs import scan_images
    from PIL import Image
    folder = options.get('modulation_dir', '')
    if not folder.strip():
        raise ValueError('Select a modulation directory when video modulation is enabled.')
    maps, _ = scan_images(folder, source=True)
    if set(maps) != set(video):
        raise ValueError('Modulation frame numbers must exactly match the source sequence.')
    for number, path in maps.items():
        with Image.open(video[number]) as source:
            shape = (source.height, source.width)
        read_map(path, shape)
    return maps


class VideoModulation:
    def __init__(self, job, options, numbers, original_shape, size):
        from reezsynth_sequence import array_sequence
        self.mode = options.get('modulation_guide', 'Off')
        self.active = self.mode != 'Off' and len(numbers) > 1
        self.values, self.inputs, self.layouts, self.targets = array_sequence(), [], [], set()
        self.indices = {number: index for index, number in enumerate(numbers)}
        if not self.active:
            return
        require_backend(options, True)
        if self.mode not in VIDEO_MODES:
            raise ValueError('Unknown video modulation guide.')
        entries = job.get('modulation_frames', [])
        if (not isinstance(entries, list) or any(not isinstance(e, list) or len(e) != 2
                or type(e[0]) is not int or not isinstance(e[1], str) for e in entries)
                or [e[0] for e in entries] != numbers):
            raise ValueError('Job modulation frame numbers must match the selected source frames.')
        for number, path in entries:
            value = read_map(path, original_shape[:2], size)
            self.values.append(value)
            self.inputs.append(dict(frame=number, **map_info(path, value)))

    def for_guides(self, guides, target):
        if not self.active:
            return None
        if target not in self.indices or len(guides) < 4:
            raise ValueError('Cannot match modulation to the actual synthesis target/guide layout.')
        value = self.values[self.indices[target]]
        selected = range(len(guides)) if self.mode == 'All guides' else [VIDEO_GUIDES.index(self.mode)]
        maps = [value if index in selected else None for index in range(len(guides))]
        packed = pack_maps(guides, maps)
        labels = list(VIDEO_GUIDES) + [f'Additional guide {i + 1}' for i in range(len(guides) - 4)]
        layout = channel_layout(guides, labels, selected)
        if layout not in self.layouts:
            self.layouts.append(layout)
        self.targets.add(target)
        return packed

    def finish(self, output):
        if self.active:
            if not self.targets:
                raise RuntimeError('Enabled video modulation was never passed to synthesis.')
            write_manifest(output, mode=self.mode, frames=self.inputs,
                           synthesis_targets=sorted(self.targets), layouts=self.layouts)


@contextmanager
def legacy_modulation(eb, modulation):
    """Bind only this runner's native call; retain the byte buffer through return."""
    if modulation is None:
        yield
        return
    import numpy as np
    if modulation.dtype != np.uint8 or modulation.ndim != 3:
        raise ValueError('Native modulation must be uint8 HWC data.')
    runner = eb.runner
    library = runner.libebsynth
    data = np.ascontiguousarray(modulation).tobytes()

    def run(*args):
        values = list(args)
        expected = (values[8], values[7], values[2])
        if modulation.shape != expected:
            raise ValueError('Native modulation dimensions/channel count differ from the guides.')
        values[10] = data
        return library.ebsynthRun(*values)

    runner.libebsynth = SimpleNamespace(ebsynthRun=run)
    try:
        yield
    finally:
        runner.libebsynth = library
