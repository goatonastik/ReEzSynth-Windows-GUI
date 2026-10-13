# Bounded frame storage

Rendering's **Store clip frames on disk to limit RAM** switch is opt-in and saved
with projects/presets. It applies to both video engines; still-image jobs ignore it.
Old jobs retain their in-memory behavior.

The implementation preserves complete forward/reverse propagation and grouped
keyframe boundaries. It changes where arrays live, without splitting a sequence
into independently synthesized clips. Source/style/mask/edge frames, intermediate
styles, errors, flow, NNF and reconstructed output arrays use job-private NumPy
files. Slices and concatenation share immutable file references. The decoded read
cache retains at most eight arrays and 64 MiB. Arrays larger than that budget are
read for the current operation and are not retained in the cache.

Frame identity travels with each decoded source/style array. Preview routing,
mask matching and directional cache lookups therefore remain valid when an array
is evicted and later reloaded at a different Python object address. Legacy's
whole-clip selection-mask and reconstruction allocations are processed frame by
frame. FuouM's precomputation, sparse-guide rasterization, synthesis passes and
reconstruction use the same bounded storage mechanism.

Native inference, flow correlation, solver matrices and currently active frames
still require memory. Frame/reference lists and sparse tracking coordinates grow
with clip length, and the operating system may cache disk reads. This is a bound
on retained pixel arrays, not a 64 MiB cap on the whole process or on GPU memory.

Temporary `.frame-storage-*` folders are created beside each job's output, so an
SSD with sufficient free space is useful. An I/O failure fails the job. Normal
success and Python exceptions clean up scratch data; a success marker is published
only after cleanup. `frame_storage.json` records the cache peak, number of arrays
and bytes written. Force-killing a worker or losing power can leave its private
scratch folder in the incomplete output. Recovery restarts in a fresh output;
it does not resume or reinterpret those scratch arrays.

For a bounded real check:

```powershell
python -B diagnose_reezsynth_quality.py --video-dir C:\path\to\source_frames --keyframe-dir C:\path\to\styled_keyframes --quality Standard --size 256 144 --stream-frames --bidirectional
python -B diagnose_reezsynth_gui.py --stream-frames --cache-reuse --frames 13
python -B diagnose_reezsynth_gui.py --fuoum --stream-frames --cache-reuse --frames 13
```

See PROJECT_STATUS.md for observed results. Per-frame native synthesis is not
asserted deterministic; regression tests compare exact sequence order, frame
identity, storage values and boundaries with deterministic engine fixtures.
