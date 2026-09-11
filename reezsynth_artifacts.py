"""Optional exports and metadata for the engine's flattened auxiliary results."""
import json
from pathlib import Path

EXPORT_DEFAULTS = dict(maps=False, flow=False)


def validate_exports(data=None):
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - set(EXPORT_DEFAULTS):
        raise ValueError('Unknown auxiliary export options.')
    result = dict(EXPORT_DEFAULTS, **data)
    if any(type(value) is not bool for value in result.values()):
        raise ValueError('Auxiliary export options must be true or false.')
    return result


def artifact_records(numbers, keys, mode='none'):
    """Mirror sequence boundary trimming, retaining original frame numbers.

    Both pass directions compute optical flow from the lower to higher frame.
    Blended maps compare offset forward/backward errors; they are not raw errors
    or a one-to-one map of final output frames.
    """
    keys = sorted(keys)
    segments = []
    if numbers[0] < keys[0]:
        segments.append((numbers[0], keys[0], 'reverse'))
    segments.extend((a, b, 'blend') for a, b in zip(keys, keys[1:]))
    if keys[-1] < numbers[-1]:
        segments.append((keys[-1], numbers[-1], 'forward'))
    records = []
    for index, (start, end, kind) in enumerate(segments):
        shifted = index > 0 and mode == 'reverse' and kind == 'blend'
        if shifted:
            start += 1
        direction = mode if kind == 'blend' and mode != 'none' else kind
        entries = []
        for ordinal, lower in enumerate(range(start, end)):
            record = dict(sequence=index, sequence_start=start, sequence_end=end,
                sequence_ordinal=ordinal, synthesis_direction=direction,
                flow_from=lower, flow_to=lower + 1,
                map_kind='selection_mask' if direction == 'blend' else 'synthesis_error')
            if direction == 'blend':
                record.update(forward_error_frame=lower + 1, backward_error_frame=lower)
            else:
                record['error_frame'] = lower + 1 if direction == 'forward' else lower
            entries.append(record)
        if index > 0 and not shifted:
            previous = segments[index - 1][2]
            if previous == 'reverse' or (previous == 'blend' and
                    (mode == 'forward' or (mode == 'reverse' and kind == 'forward'))):
                entries = entries[1:]
        records.extend(entries)
    return records


def save_artifacts(output, options, records, maps, flows):
    """Save requested results before COMPLETE; never quantize numerical maps."""
    import cv2
    import numpy as np
    options = validate_exports(options)
    if not any(options.values()):
        return
    for enabled, values, label in ((options['maps'], maps, 'maps'), (options['flow'], flows, 'flows')):
        if enabled and len(values) != len(records):
            raise RuntimeError(f'Expected {len(records)} auxiliary {label}, received {len(values)}.')
    root = Path(output) / 'auxiliary'
    root.mkdir(exist_ok=True)
    manifest = dict(version=1, scope='engine results after sequence boundary trimming',
        flow_format='BGR color visualization; not numerical optical flow',
        map_format='NumPy array, original dtype and values; selection masks are not synthesis errors',
        requested=options, artifacts=[])
    for index, record in enumerate(records):
        entry = dict(record)
        for enabled, values, label in ((options['maps'], maps, record['map_kind']),
                                       (options['flow'], flows, 'flow')):
            if not enabled:
                continue
            array = np.asarray(values[index])
            if array.ndim not in (2, 3) or array.size == 0 or array.dtype.kind not in 'buif' or not np.isfinite(array).all():
                raise RuntimeError(f'Invalid auxiliary {label} at index {index}.')
            name = f'{index:06d}_{label}' + ('.png' if label == 'flow' else '.npy')
            destination = root / name
            temporary = root / (name + '.part')
            if label == 'flow':
                if array.ndim != 3 or array.shape[2] != 3 or array.dtype != np.uint8:
                    raise RuntimeError('Flow visualization must be an 8-bit three-channel image.')
                ok, encoded = cv2.imencode('.png', array)
                if not ok:
                    raise RuntimeError('Could not encode flow visualization.')
                temporary.write_bytes(encoded.tobytes())
            else:
                with temporary.open('wb') as stream:
                    np.save(stream, array, allow_pickle=False)
            temporary.replace(destination)
            entry[label] = dict(file=name, shape=list(array.shape), dtype=str(array.dtype))
        manifest['artifacts'].append(entry)
    temporary = root / 'manifest.json.part'
    temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    temporary.replace(root / 'manifest.json')
