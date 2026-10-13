# D3: output ownership during startup and project loading

Baseline: `6a8a8fa7a22b8cc9f70312dd07511c70269a5933`, immediately after the
reviewed RGBA and persistence commits.

## Reproduction

An isolated GUI fixture wrote conflicting `last-used.json` groups:

- `output`: custom root `canonical`, batch `chosen_batch`, jobs `chosen_{key:03d}`.
- `render.output_naming`: custom root `stale`, batch `stale_batch`, jobs `stale_{key:03d}`.

After constructing a fresh window, the real `run_rows()` path created its queue
records and job files under `stale/stale_batch`. The failing assertion compared
that actual prepared batch with `canonical/chosen_batch`. Only `start_records()`
was intercepted, after job preparation/writing, so no renderer was launched.

The original application order was directories, output, weights, render, grouped,
application, image. `Options.apply('render', restore_related=True)` applied all
five duplicated naming/location fields after the dedicated output policy.
Even render defaults could overwrite output because render validation synthesized
default output settings when the nested field was absent.

## Ownership map

| Field | Canonical owner / persisted locations | Restore/apply path and order | Effect on destination |
|---|---|---|---|
| `project_dir` | `directories` group and directory presets; project document top level; legacy `last_setup/project_dir` | QSettings first; `Options.apply('directories')` at startup; explicit `open_project()` later | Base for project locations and cache root |
| `keyframe_dir`, `video_dir` | `directories`; project top level; legacy `last_setup/*` | Same ordering as project directory | Bases for key/video folder policies |
| `location` | `output` group / output presets; project `output_naming` | `Options.apply('output')` via `set_project_naming`; project open explicitly applies its saved naming | Chooses `project_renders`, `project`, `custom`, `keys_child`, `video_child`, `keys_parent`, `video_parent` |
| `custom_folder` | Same output owner | Same | Root when `location=custom`; retained but inactive otherwise |
| `batch_enabled` | Same output owner | Same | Chooses direct root or a new batch subfolder |
| `batch_pattern` | Same output owner; legacy QSettings `last_setup/batch_pattern` | QSettings initially; dedicated output policy overrides it; project open explicitly applies its saved pattern | Batch directory name when enabled |
| `job_pattern` | Same output owner; legacy QSettings `last_setup/job_pattern` | Same; used by new scans or explicit Apply to Queue | Generates queue subfolder names, without changing already edited rows |
| `startup.output` | `application.json` startup policy map, **not** the `application` settings group | `Options._restore()` resolves last/defaults/named preset before applying output | Selects all five output behavior fields above |
| `startup.directories`, `startup.render`, other group policies | Same startup policy map | Resolved independently for each group | Directories can alter relative root bases; render no longer changes output ownership |
| Old `render.output_naming` (same five fields) | Previously last-used render group and possibly render presets | Migrated to output only for missing canonical last-used output with last-used output policy; otherwise accepted and discarded by render validation | Historical harmful duplicate; no authority during render apply |
| `rows[*].folder` | Saved project queue definitions; current edited queue row | `open_project()` restores rows after naming; `run_rows()` validates and uses each row | Final per-job directory name, intentionally allowed to differ from the naming template |
| Grouped `selection.folder` / project `grouped_video.folder` | `grouped` group and project document | `Options.apply('grouped')` / explicit project selection restore | Grouped job subfolder under the canonical root/batch |
| Image `folder` / project `image_synthesis.folder` | `image` group and project document | `Options.apply('image')` / image project load | Image job subfolder under the canonical root/batch |
| Image `style`, `target` paths | `image` group / project image settings | Same | Image jobs use their parent directories for key/video-relative output policies |
| `padding` | Derived by `scan_images()`/`build_plan()`; serialized into each job, not an options group | Recomputed on scan/project open/job preparation | `{padding}` in naming templates; frame PNG numeric width |
| `quality`, processing width | `render`; project top level; legacy QSettings setup values | Render restore/project load | May supply explicitly selected naming-template tokens, but never change location/pattern fields |
| Folder histories / naming preview | QSettings history dropdowns / computed display | Histories populate choices; preview computes from current controls | History lists and preview text do not independently select a destination |
| Queue record `output`, `job_path`, `job.json.output`, journal paths | Derived job execution state | Created after resolving canonical root/batch and queue subfolder | Concrete destination; not another startup setting |

There is no output-location copy in legacy QSettings: only directory paths and
the two naming patterns are restored there. `last_queue_journal` identifies an
explicit recovery operation, not an output startup-policy owner.

## Correction and compatibility

`Options.snapshot('render', include_related=True)` no longer captures output;
`persist()` no longer injects its duplicate. `validate_group('render')` continues
to accept the legacy key but omits it from its validated result, without creating
default output settings. Applying render settings cannot change output controls,
regardless of group order or `restore_related`.

Before startup applies any groups, a legacy `last-used.render.output_naming` is
promoted into a missing `last-used.output` only when `startup.output` is absent or
`last`. Dedicated output data wins even when invalid (normal safe-default/error
handling applies); explicit defaults or preset policies also win when no dedicated
last-used payload exists. Legacy render presets stay loadable but cannot select an
output destination. The next successful persist writes only the dedicated owner.

Existing project serialization already has one top-level `output_naming` owner;
`render_options` contains only render parameters. That structure remains intact.
Explicit project loading still restores the project's saved output destination,
overriding the startup state as intended.

No schema version change, rendering behavior change, or cross-file transaction
change is involved. Snapshot remains raw, group validation remains centralized,
and invalid output state still retains its previous saved group independently.

## Regression coverage

- Conflicting startup values checked through final queue records and `job.json`.
- Both direct apply orders, render defaults, and reversed startup group order.
- All nine combinations of output/render last/defaults/named-preset policies.
- Legacy render-only output migration, persistence and restart.
- Invalid obsolete duplicate cannot invalidate an otherwise valid render group.
- Raw naming snapshot and absence of a second output copy in render snapshots.
- Older naming payloads receive established location defaults.
- Project save/load keeps one owner and generates jobs under its saved custom root.
- Existing persistence isolation, failed writes, raw schedules and widget tests.

## Validation

All runs used the `reezsynth` environment's Python with `-B`.

- Before the fix, the new destination-conflict reproduction failed as expected
  (1 test, 0.656s). Existing options/GUI/serialization baseline: 87 tests in
  31.815s, with the two parallel-worker options failures listed below.
- Final focused run: `test_reezsynth_options.PresetTests`,
  `test_reezsynth_destinations`, `test_reezsynth_gui`,
  `test_reezsynth_serialization`, `test_reezsynth_grouped`,
  `test_reezsynth_image`: **102 tests passed in 28.796s**.
- Full `run_maintained_tests.py`: **368 tests in 97.985s, 3 failures**:
  - `test_reezsynth_options.IntegrationTests.test_close_parallel_queue_reaps_all_workers`
  - `test_reezsynth_options.IntegrationTests.test_parallel_workers_overlap_cancel_and_restart`
  - `test_reezsynth_preview.ProcessPreviewTests.test_frames_arrive_before_completion_shared_isolated_and_parallel`
    (parallel subtest only).
- Isolated options rerun: 66 tests in 31.757s, same two failures.
- Isolated preview rerun: 12 tests in 13.710s, same parallel-subtest failure.

These known resource-sensitive tests expect two concurrent workers. The logs
showed only 3.3-3.5 GiB free GPU memory, a 3.2 GiB safety reserve, and a 1.9 GiB
per-worker estimate, so the existing scheduler admitted one worker alone. The
two options failures also reproduced before production changes. No scheduler,
lifecycle, preview, or flaky-test changes were made to force a passing run.
