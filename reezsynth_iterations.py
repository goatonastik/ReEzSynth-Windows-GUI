"""Validated, finest-anchored iteration schedules for the two pinned engines."""
from contextlib import contextmanager
from ctypes import c_int
from pathlib import Path


SCHEDULE_FIELDS = ('searchvote_schedule', 'patchmatch_schedule')


def validate_schedule(value):
    if (not isinstance(value, list) or len(value) > 32
            or any(type(item) is not int or not 1 <= item <= 1000 for item in value)):
        raise ValueError('Iteration schedules need at most 32 integers from 1 to 1000; [] uses the scalar.')
    return list(value)


def parse_schedule(text):
    if not text.strip():
        return []
    try:
        return validate_schedule([int(item.strip()) for item in text.split(',')])
    except ValueError as exc:
        raise ValueError('Enter comma-separated iteration counts from 1 to 1000, or leave blank.') from exc


def expand_schedule(value, scalar, levels):
    value = validate_schedule(value)
    if type(levels) is not int or not 1 <= levels <= 33:
        raise ValueError('Synthesis requires a positive usable pyramid depth.')
    if not value:
        return [scalar] * levels
    return ([value[0]] * max(0, levels - len(value)) + value)[-levels:]


def active(options):
    return any(options.get(name) for name in SCHEDULE_FIELDS)


def resolve(options, levels):
    return dict(levels=levels, searchvote=expand_schedule(options.get('searchvote_schedule', []),
                 options['searchvoteiters'], levels),
                patchmatch=expand_schedule(options.get('patchmatch_schedule', []),
                 options['patchmatchiters'], levels))


class ScheduleRecorder:
    """Retain each distinct resolved mapping, bounded by the native depth limit."""
    def __init__(self, output=None):
        self.output = Path(output) if output is not None else None
        self.plans = []

    def record(self, plan):
        if plan in self.plans:
            return
        self.plans.append(plan)
        print(f"[Iterations] Coarse to fine: search/vote={plan['searchvote']}; "
              f"patch-match={plan['patchmatch']}", flush=True)
        if self.output is not None:
            from reezsynth_config import atomic_json
            atomic_json(self.output / 'iteration_schedule.json', dict(version=1,
                order='coarse_to_fine', alignment='finest',
                missing_coarse_levels='repeat_first', excess_coarse_entries='drop',
                resolved=self.plans))


@contextmanager
def legacy_schedule(eb, options, recorder):
    """Override only this runner's C-int arrays, after native depth clamping."""
    if not active(options):
        yield
        return
    runner = eb.runner
    original = runner.validate_per_levels

    def per_levels(*args, **kwargs):
        levels, _, _, stop = original(*args, **kwargs)
        plan = resolve(options, levels)
        recorder.record(plan)
        return (levels, (c_int * levels)(*plan['searchvote']),
                (c_int * levels)(*plan['patchmatch']), stop)

    runner.validate_per_levels = per_levels
    try:
        yield
    finally:
        runner.validate_per_levels = original


def fuoum_synthesize(engine, style, guides, options, recorder, *, synthesize=None, **kwargs):
    """Apply scalar counts to each real backend level; reset on every frame."""
    synthesize = synthesize or engine.run
    if not active(options):
        return synthesize(style, guides=guides, **kwargs)
    minimum = min(*style.shape[:2], *guides[0][1].shape[:2])
    maximum = next((level + 1 for level in range(32, -1, -1)
                    if minimum * 2.0 ** -level >= 2 * options['patchsize'] + 1), 0)
    requested = 32 if options['pyramidlevels'] == -1 else options['pyramidlevels']
    levels = min(requested, maximum)
    plan = resolve(options, levels)
    expected = levels + int(options['extrapass3x3'])
    original = engine.backend.run_level
    calls = 0

    def run_level(*args, **kwargs):
        nonlocal calls
        if calls >= expected:
            raise RuntimeError('FuouM made more pyramid calls than the validated iteration schedule.')
        index = min(calls, levels - 1)  # The optional final 3x3 pass uses finest counts.
        values = list(args)
        for position, name, count in ((10, 'search_vote_iters', plan['searchvote'][index]),
                                      (11, 'patch_match_iters', plan['patchmatch'][index])):
            if position < len(values):
                values[position] = count
            else:
                kwargs[name] = count
        calls += 1
        return original(*values, **kwargs)

    engine.backend.run_level = run_level
    try:
        result = synthesize(style, guides=guides, **kwargs)
        if calls != expected:
            raise RuntimeError(f'FuouM made {calls} pyramid calls; expected {expected}.')
        recorder.record(plan)
        return result
    finally:
        engine.backend.run_level = original
