# ComfyUI cancellation and candidate approval checkpoint

Inspected 2026-10-14. This is an implementation contract, not a claim that
cancellation or numbered-key assignment is available. No live job was submitted
or cancelled during this inspection.

## External-server cancellation

The inspected local ComfyUI source has `POST /api/jobs/{job_id}/cancel`.
Its running-job interrupt checks the ID and signals under the queue mutex;
pending removal also matches the ID, but removes only the first match. Duplicate
IDs are permitted by submission, so this alone is not ownership isolation.
If the pending job starts during the
request, the handler attempts the same guarded interrupt. A running job that
finishes before the interrupt does not cause the next job to be interrupted
in the inspected sequential worker: `execution.py:733` resets the flag in
`execute_async`, and `main.py:587` starts one prompt worker. The interrupt flag
is still process-global. These observations do not establish isolation for a
modified backend with concurrent prompt workers. Queue pop and insertion into
the running set share the condition lock (`execution.py:1267-1280`).

However, the response contains only `{"cancelled": true|false}`. True means
either dequeue or interrupt dispatch, not that execution has finished. Queued
removal leaves no terminal history. False and subsequent **status GET** 404 responses cannot
distinguish completion, eviction, restart, an unsupported route, or a lost job.
Normalized active-job status also omits the workflow ownership markers.

Therefore keep cancellation disabled for unverified external servers. The
installed files and their version do not prove which code a running endpoint
loaded. Never substitute global `/interrupt`, queue clearing, model unloading,
or process termination. Users can stop status monitoring with its existing
checkbox and cancel in ComfyUI; explain that ReEzSynth retains its reservation
until verified terminal evidence or the existing explicit rendering-only escape.
Specifically, deleting a queued job in ComfyUI can leave recovery unresolved
indefinitely. The existing escape does cover a generation reservation: after
the user confirms external work is stopped and other controllers are closed,
it releases only this process's guard and disables generation until restart.
It does not clear the durable reservation; restarting retries recovery. A
durable user-attested abandonment operation is separate future work, not a
backend-confirmed cancellation and not part of this approval slice.

The CPU probe in ignored diagnostics exercised seven dispatch cases against
functions extracted from the installed source. It did not test the HTTP server,
thread synchronization, GPU interruption, or a live server's identity. The
mutex and missing queued-history behavior were established by source inspection.
These are external-source probes, not additions to the maintained ReEzSynth
test count. Rechecked SHA-256 hashes for this inspection:

- `server.py`: `4b910e3579db59053d0fea97b241ae1a99528c6d7fb152f34640a995bcab50d0`
- `execution.py`: `c47ebc80efb350568ee3d33b03efaf0fb27fc32ca723bfd9aa10ed591fdf75f2`
- `comfy_execution/jobs.py`: `e57ac4235dd1f85807b7f443ce7667bb2c3310dcf8299082e6595afa01dab322`

The first two are unchanged from the October 9 inspection.

## Requirements before enabling targeted cancellation

Use a validated owned backend or a reviewed optional backend adapter with:

- A process-instance identity bound to submission and recovery, with capability
  negotiation. An endpoint, version string, route, or disk hash alone is not
  sufficient. This is compatibility verification, not protection from a malicious
  local administrator.
- Server-side atomic matching of the prompt UUID and frozen ownership markers
  supplied with cancellation, under the same lock as cancellation. The adapter
  must reject duplicate/ambiguous identities before any mutation, and prevent
  concurrent duplicate admission. Client-side checks followed by an ID-only
  request cannot provide this. An owned-job status route should return only
  that job's verified markers; no raw shared-queue download is required.
- A validated single-prompt execution guarantee, or a per-job interrupt token
  whose effect cannot reach another prompt. Do not infer this from an API name.
  An interrupt request has no guaranteed time-to-effect; the UI must not promise
  immediate cancellation or a completion estimate.
- A durable terminal cancellation record for queued removal. Record removal and
  its evidence as one recoverable operation; a receipt alone is insufficient
  after a lost response. Retain terminal evidence across process restarts or
  report an explicitly unresolved prior instance.
- Separate persisted cancellation-request state from execution state. Commit
  intent before sending, serialize with session submission/recovery, and target
  only the frozen reservation. Do not release the GPU guard on acknowledgement,
  timeout, missing history, or an unsupported response.
- Bounded loopback transport with redirects/proxies disabled. Never retry an
  uncertain mutation automatically; any retry must use the same request identity
  against a protocol that guarantees idempotency.
- Reconciliation that accepts completion winning a cancellation race, retains
  verified failure/completion, and never labels a successful result cancelled
  merely because cancellation was requested.

These requirements introduce backend work. They do not authorize changing the
user's installed ComfyUI or loading extensions into its running process. Defer
that integration until the managed/adapter backend slice; it need not block
candidate review and approval.

## Next implementation: explicit candidate approval

Implement a CPU-only approval layer before numbered-key publication:

1. Start with saved schema-3 ComfyUI candidates. Validate completion record,
   provenance hashes, image decoding, original dimensions, intended frame and
   owning project. Older import formats remain usable as unreviewed candidates
   until their own verified approval adapters exist.
   Existing candidate intake has no numbered-key publication path. Use realistic
   schema-3 fixtures produced by the existing save pipeline for this CPU slice;
   live model quality and end-to-end acceptance remain separate.
2. Show the exact saved candidate for review. Freeze image/provenance hashes,
   project and intended source-frame identity in the review action. Changed UI
   selections or edited files must invalidate approval, not retarget it.
3. Record an explicit user approval separately and durably, bound to those
   hashes. Preserve the immutable unreviewed candidate/provenance. Approval alone
   must not create or overwrite a synthesis key or start rendering.
4. Test stale previews, wrong project/frame, changed bytes, malformed records,
   redirected folders, interrupted approval writes and concurrent approval.
   Keep all tests CPU-only until a separate live-quality session.

Numbered-key assignment is a subsequent reviewed slice. It must derive the
filename from the actual source sequence mapping, reject ambiguous mapping and
source/key directory overlap, and revalidate the approved bytes at publication.
Create missing keys without overwriting a concurrent file. Replacing an existing
key needs explicit confirmation of that exact existing version and a durable
backup. A journal must distinguish prepared, published and reconciled states;
never claim the image write and metadata write form one atomic transaction.
Block assignment during rendering, freeze the destination, and rescan only after
successful publication. Windows replacement/concurrency semantics require their
own tests before enabling replacement. Do not use an existence check followed by
unconditional `os.replace` as a no-overwrite guarantee.
Flush the backup and journal before replacement, and handle Windows sharing
violations without deleting either the existing key or its backup.

## Model handoff

Sol can implement and test the bounded approval-only slice above, followed by
independent Claude review and corrections before exact-file staging and commit.
Return to Astra for backend identity/cancellation
integration or crash-safe numbered-key replacement. No GPU work is needed for
approval implementation.
