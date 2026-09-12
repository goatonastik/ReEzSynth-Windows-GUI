"""Qt-free planning and validation for grouped video jobs."""
import importlib.util


BLEND_DEFAULTS = dict(only_mode="none", use_gpu=False, use_lsqr=True,
                      use_poisson_cupy=False, poisson_maxiter=None,
                      fuoum_poisson_solver='lsqr', fuoum_poisson_grad_weight_l=2.5,
                      fuoum_poisson_grad_weight_ab=.5)
GROUPED_DEFAULTS = dict(start=None, end=None, keyframes=None, folder="grouped_video")


def validate_blend_options(data=None):
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - set(BLEND_DEFAULTS):
        raise ValueError("Invalid blending options.")
    result = dict(BLEND_DEFAULTS, **data)
    if 'fuoum_poisson_solver' not in data:
        result['fuoum_poisson_solver'] = 'lsqr' if result['use_lsqr'] else 'lsmr'
    if result["only_mode"] not in ("none", "forward", "reverse"):
        raise ValueError("Video mode must be normal blending, forward only or reverse only.")
    for name in ("use_gpu", "use_lsqr", "use_poisson_cupy"):
        if type(result[name]) is not bool:
            raise ValueError(f"{name} must be true or false.")
    maximum = result["poisson_maxiter"]
    if maximum is not None and (type(maximum) is not int or not 1 <= maximum <= 2147483647):
        raise ValueError("Poisson iteration limit must be a positive integer or null.")
    if result["use_poisson_cupy"] and not result["use_gpu"]:
        raise ValueError("CuPy Poisson reconstruction requires GPU blending to be enabled.")
    if result['fuoum_poisson_solver'] not in ('lsqr', 'lsmr', 'cg', 'amg', 'seamless', 'disabled'):
        raise ValueError('Unknown FuouM Poisson solver.')
    for name in ('fuoum_poisson_grad_weight_l', 'fuoum_poisson_grad_weight_ab'):
        value = result[name]
        if type(value) not in (int, float) or not 0 <= value <= 10000:
            raise ValueError(f'{name} must be a number between 0 and 10000.')
    return result


def check_blend_dependencies(options, probe=None):
    """Reject a nominal CuPy install that cannot execute on this GPU."""
    if options["only_mode"] == "none" and options["use_gpu"]:
        if importlib.util.find_spec("cupy") is None:
            raise ValueError("GPU blending requires CuPy, which is not installed. Disable GPU blending to use CPU reconstruction.")
        if probe is None:
            def probe():
                import cupy as cp
                # Allocation/reduction can succeed on an unsupported CUDA architecture;
                # force the repeat kernel used by the blending path itself.
                return cp.repeat(cp.asarray([1], dtype=cp.float32), 2).sum().item()
        try:
            probe()
        except Exception as exc:
            raise ValueError('GPU blending requires a usable CuPy/CUDA kernel on this GPU. '
                             'Update or remove CuPy, or disable GPU blending. '
                             f'CuPy reported: {exc}') from exc


def validate_grouped_selection(data=None):
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - set(GROUPED_DEFAULTS):
        raise ValueError("Invalid grouped-video selection.")
    result = dict(GROUPED_DEFAULTS, **data)
    for field in ("start", "end"):
        value = result[field]
        if value is not None and (type(value) is not int or not 0 <= value <= 2147483647):
            raise ValueError("Grouped frame endpoints must be nonnegative integers or null.")
    if (result["start"] is None) != (result["end"] is None):
        raise ValueError("Set both grouped frame endpoints, or use the full source range.")
    if result["start"] is not None and result["start"] > result["end"]:
        raise ValueError("Grouped range start must not exceed its end.")
    selected = result["keyframes"]
    if selected is not None:
        if not isinstance(selected, list) or any(type(n) is not int or n < 0 for n in selected):
            raise ValueError("Grouped keyframes must be a list of frame numbers or null.")
        if len(selected) != len(set(selected)):
            raise ValueError("Grouped keyframes contain duplicates.")
        result["keyframes"] = sorted(selected)
    if not isinstance(result["folder"], str) or not result["folder"].strip():
        raise ValueError("A grouped output folder is required.")
    result["folder"] = result["folder"].strip()
    return result


def synthesis_work(start, end, keyframes, only_mode="none"):
    """Count native synthesis calls using the upstream sequence boundary rules."""
    keys = sorted(keyframes)
    segments = []
    if start < keys[0]:
        segments.append((start, keys[0], False))
    segments.extend((a, b, True) for a, b in zip(keys, keys[1:]))
    if keys[-1] < end:
        segments.append((keys[-1], end, False))
    work = 0
    for index, (first, last, blend) in enumerate(segments):
        distance = last - first
        # EzsynthBase advances the start of later reverse-only blend segments.
        if blend and only_mode == "reverse" and index > 0:
            distance -= 1
        work += distance * (2 if blend and only_mode == "none" else 1)
    return work


def plan_grouped_video(video, keys, selection=None, blend_options=None):
    selection = validate_grouped_selection(selection)
    options = validate_blend_options(blend_options)
    numbers = sorted(video)
    if not numbers or any(b != a + 1 for a, b in zip(numbers, numbers[1:])):
        raise ValueError("Grouped video requires consecutive source frames.")
    start = numbers[0] if selection["start"] is None else selection["start"]
    end = numbers[-1] if selection["end"] is None else selection["end"]
    if start not in video or end not in video:
        raise ValueError("Grouped range endpoints must exist in the source sequence.")
    selected = sorted(keys) if selection["keyframes"] is None else selection["keyframes"]
    if len(selected) < 2:
        raise ValueError("Select at least two styled keyframes for a grouped video.")
    for number in selected:
        if number not in keys or number not in video or not start <= number <= end:
            raise ValueError(f"Selected keyframe {number} must exist and lie inside the grouped range.")
    return dict(type="grouped_video", key=selected[0], style=str(keys[selected[0]]),
                styles=[[n, str(keys[n])] for n in selected],
                frames=[[n, str(video[n])] for n in numbers if start <= n <= end],
                blend_options=options,
                synthesis_work=synthesis_work(start, end, selected, options["only_mode"]))
