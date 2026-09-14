# D4: preset failure isolation

Reviewed base: `2090c8b60e6ddab27070ae0c79d00cb079b6c484`.

## Architecture and reproduced failure

The local library is one `presets.json`, not one file per preset. Normal Windows
settings use `%LOCALAPPDATA%/ReEzSynth`; INI-based settings use a `configuration`
directory beside the INI file. Explicit import/export supports JSON and YAML.
The envelope is `format: ReEzSynth-presets`, `version: 1`, with a `groups` mapping
of group names to mappings of preset names to setting objects. The seven groups
are directories, output, weights, render, grouped, application, and image.

`Options.__init__` constructs `PresetStore` eagerly. Previously its nested load
loop called `validate_name()` and `validate_group()` without entry-level catches.
Any rejected entry raised out of the constructor. Options caught that failure,
left `store=None`, and `refresh_presets()` populated only built-in Default items
for every group. Startup policies referencing otherwise valid presets also lost
access to them. A library with valid Paint and Good presets reproduced this for
each of: a string containing malformed JSON, even patch size, unknown fields,
explicit revision mismatch, malformed iteration schedule, undersized processing
dimensions, and a non-object options payload. All seven pre-fix subtests failed.

## Isolation and preservation

PresetStore now keeps both the raw document and a separately validated usable
view. Rejected entries, malformed group collections, and unknown groups are
omitted from that view, with identified diagnostic reasons. Other presets still
load. Case-insensitive duplicate names keep the first valid entry and report the
duplicate; invalid names are reported. No load writes or moves any file.

Explicit save/remove modifies only its target in the raw document. Export and
confirmed import retain rejected content. Unchanged valid legacy payloads also
retain their original field data, rather than acquiring normalization defaults
as a side effect of saving a neighbor. An explicit write can reformat the shared
document, but reading preserves its bytes. Saving over a rejected preset name
requires the existing overwrite confirmation. An invalid collection cannot be
silently replaced by saving a preset into it. In-memory state advances only after
the write succeeds.

The selectors list usable presets and retain Default. Refresh preserves an
existing valid selection. Startup reports each rejected preset in Diagnostics
and shows one count/summary in the status label, without per-preset modals.
After correction, the preset becomes available on the next reload. The summary
clears only if the current status still belongs to this mechanism.

## Compatibility and startup

Central validation remains authoritative. Existing safe normalization still
accepts omitted optional fields, old supported width settings, and schedule
strings. The known obsolete render `output_naming` copy remains ignored under
D3. Arbitrary unknown fields remain schema errors; no heuristic migration was
introduced. Missing required grouped fields remain errors.

Render presets can contain engine identity, engine revision, backend, and
engine-specific parameters. `validate_revision()` already makes an explicit
revision mismatch fatal; that policy now rejects only the affected preset.
Absent revisions still resolve to the pinned revision. A valid FuouM preset can
select FuouM and retain its backend/settings; loading never activates or runs it.

When a startup policy selects a rejected or missing preset, its policy value is
retained. The group restores validated last-used settings if available, otherwise
safe defaults, with an explicit diagnostic. This prevents a debounced save of
fallback defaults from replacing the group's good last-used values. Invalid
last-used fallback data uses the existing `last-used.rejected.json` preservation.
Unrelated groups restore through their own policies as before.

## Whole-file corruption boundary

A missing JSON value/delimiter makes the *shared document* unparseable, even when
two valid preset definitions appear earlier. It is not a malformed standalone
preset file. Such input, invalid top-level structure, or an unsupported envelope
version remains a file-level failure: preserve the file, report it, retain Default
and independent last-used restoration. Guessing entry boundaries or inventing
per-preset files would require a different parser/schema and is outside this fix.
The regression suite distinguishes this case from an invalid entry within a
readable document. No beta assets, rendering semantics, or other repairs changed.

## Validation

All runs used `E:/miniconda3/envs/reezsynth/python.exe -B`.

- Existing preset/options/serialization baseline: 49 tests passed in 10.629s.
- Pre-fix reproduction: one parameterized test failed for all seven invalid-entry
  cases (1.391s), demonstrating that the two valid presets became unavailable.
- Pre-correction focused preset/startup/serialization/GUI/destination run: 93
  tests passed in 19.405s.
- Post-correction focused options/serialization run: 81 tests passed in 19.410s.
- Post-correction full `run_maintained_tests.py`: 381 tests passed in 72.468s. No
  known parallel or preview flakes occurred in this run.
- Twelve new options tests cover usable selectors, preservation during reads and
  explicit writes, failure-safe writes, import/export, revision/migration rules,
  duplicate names and invalid collections, repair/reload, startup fallback,
  last-used isolation, summary ownership, whole-document syntax corruption, and
  user-visible failures for non-serializable rejected neighbors.
  The YAML validation test now expects entry isolation and diagnostics.
