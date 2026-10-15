# Native FuouM YAML interchange

Rendering now provides **Import native FuouM settings…** and **Export native
FuouM project…**. These are separate from Open/Save GUI projects and preset
libraries. Existing frontend JSON/YAML formats and worker JSON jobs are unchanged.
The native schema targets revision `aaa8d06170e6cc59054410aa9c422edd789f7ab2`.

## Import settings into the current GUI project

Choose a native YAML file, review the compatibility details, then confirm.
Supported synthesis, flow-model, edge-method, temporal/sparse, recompute,
guide-weight and reconstruction settings replace the corresponding GUI groups.
FuouM is selected. Native defaults, rather than whichever GUI values happened
to be visible, fill omitted optional fields.

Inputs, the queued row definitions, selected keyframes, output naming, application
runtime paths, presets and image-synthesis settings are not replaced. Native
content/style paths, positional indices, output/cache paths and project name are
reference information only. The import is deliberately **settings-only**, not an
automatic loader for arbitrary native media layouts.

Processing size resets to Original; masks/modulation and auxiliary/video exports
are disabled. Edge tuning and iteration schedules reset to frontend defaults.
The quality label becomes Standard, with the imported synthesis values overriding
that profile; choosing a quality profile afterwards resets its synthesis fields
as usual. Normal blending is selected. Native pipeline fields without GUI
equivalents (including residual-transfer/final-pass settings) are reported when
they differ from the pinned defaults and are not applied. Native debug settings
are not imported. Values outside supported GUI limits are rejected. Values with
more than six decimal places are rounded with an explicit precision notice.

The confirmation defaults to No. Cancellation or validation failure does not
apply the translation. Application failures restore the captured settings groups.
Automatic rendering is disarmed; imports never launch jobs. Imported settings
participate in ordinary last-used persistence and can be saved in a GUI project
or preset. Compatibility details are also written to Diagnostics / Log.

## Export a native project

Select FuouM and scan/rebuild the queue. In Blend / Flow, choose the full source
range and at least one keyframe. Export chooses a YAML filename and asks for a
new absolute native output-folder path. No media is copied, and neither the
native output nor its derived cache folder is created by export.

The exported file includes absolute content/style paths, native zero-based
style positions, a fresh output/cache location, and supported current settings.
For example, GUI keyframe numbers 100 and 102 in source frames 100–102 become
native positions 0 and 2. The native loader renumbers outputs from 00000; GUI
frame-label preservation is not part of the native schema.

Native CLI reads a whole content directory. Subranges are rejected instead of
silently adding frames. The exporter checks that current source-folder contents
and the pinned native natural sort agree with GUI ordering, and that source/style
dimensions match. It rejects existing output/cache locations. Export is
also rejected for transparent styles: the pinned native CLI discards style alpha.
Use the GUI transparent FuouM path instead. Output paths are
independent of GUI queue destinations and are not protected by GUI recovery when
the native CLI is run later.

Guide weights and sparse-anchor weight are divided by GUI key weight, as in the
FuouM adapter; native YAML has no separate key weight. Automatic pyramid depth
(`-1` in the GUI) exports as 32, matching the adapter's capped native request.

Compatibility details identify active GUI features the native schema cannot
represent: processing resize, custom edge guides, advanced edge tuning, iteration
schedules, independently estimated backward flow, disk-backed frame storage,
guide-specific modulation, pre-masking/feathering, additional mask-guide weight,
forward/reverse-only mode, and auxiliary/video exports. Mask directories can be
exported, but masking equivalence is not guaranteed. Recompute flags have different
cache-publication semantics: native recomputation can rewrite its cache while
GUI recomputation preserves shared entries. Experimental native torch does not
include the frontend compatibility implementation.

Details are shown before confirmation, logged, and retained as YAML comments,
which the native parser ignores. This is **not a lossless round trip or a promise
of identical render results**: the GUI uses its own sequence, blending, cache and
compatibility adapters. Export never launches the CLI. Use normal GUI projects
and presets to retain the complete frontend configuration. These absolute-path
documents are not portable media bundles.

## Validation

Safe YAML loading rejects duplicate mapping keys, object constructors, container
aliases, unsupported scalar types, excessive nesting and files over 1 MiB.
Required native sections and fields are validated before translation. Unsupported
fields/sections are reported instead of being silently discarded.

`test_reezsynth_native_yaml.py` covers mappings, native defaults, unsupported-field
reporting, strict values, safe loading, precision, normalized weights, positional
indices, single-key projects, range/cache/order guards, commented-file round trips,
cancelled actions, GUI state preservation and rollback. When the pinned checkout
is available, its schema field names are checked against the projection.

`tools/diagnostics/diagnose_reezsynth_native_yaml.py` creates synthetic inputs, exports YAML and
checks it with the actual pinned Pydantic schema in the FuouM runtime. It imports
supported settings back and verifies no output/cache was created. It does not
render or certify native/frontend visual equivalence.

On 2026-09-26, all 475 maintained tests passed in 85.597s, including 18 native
interchange tests. The actual pinned-schema diagnostic passed and is retained at
`diagnostic_outputs/native_yaml_20260926_140432_288993`. No native render was run.
