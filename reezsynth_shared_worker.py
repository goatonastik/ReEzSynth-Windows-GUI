import gc
import json
import sys
import time
import traceback
from pathlib import Path

from reezsynth_jobs import render_job


SESSION_PREFIX = "@@REEZSYNTH_SESSION@@"


def send_event(event, **fields):
    message = {"event": event, **fields}
    print(
        "\n" + SESSION_PREFIX + json.dumps(message, ensure_ascii=True),
        flush=True,
    )


def cleanup_worker():
    """Best-effort cleanup before process exit.

    Process exit releases remaining process-owned resources.
    Do not import or initialize CUDA just to perform cleanup.
    """
    print("[Session] Shutdown cleanup starting.", flush=True)

    try:
        gc.collect()
    except Exception as exc:
        print(
            f"[Session] Object cleanup warning: {exc}",
            file=sys.stderr,
            flush=True,
        )

    torch = sys.modules.get("torch")
    cuda = getattr(torch, "cuda", None) if torch is not None else None

    try:
        if cuda is not None and cuda.is_initialized():
            cuda.empty_cache()
            print(
                "[Session] Unused PyTorch GPU cache released.",
                flush=True,
            )
    except Exception as exc:
        # Cleanup must not hide the original render error or block exit.
        print(
            f"[Session] GPU cleanup warning: {exc}",
            file=sys.stderr,
            flush=True,
        )

    print(
        "[Session] Cleanup pass finished; worker exiting. "
        "Remaining process-owned resources are released on exit.",
        flush=True,
    )


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    print(
        "[Session] Persistent worker started; "
        "initialization is handled by each render.",
        flush=True,
    )

    try:
        for line in sys.stdin:
            if not line.strip():
                continue

            command = json.loads(line)
            action = command.get("action")

            if action == "quit":
                print(
                    "[Session] Queue finished; shutdown requested.",
                    flush=True,
                )
                return 0

            if action != "run":
                raise ValueError(f"Unknown worker command: {action}")

            job_path = Path(command["job"]).resolve()
            started = time.perf_counter()

            render_job(job_path)

            # Collect unreachable per-job objects while preserving
            # library caches between renders for performance.
            gc.collect()

            elapsed = time.perf_counter() - started
            print(
                f"[Session] Job wall time: {elapsed:.3f}s",
                flush=True,
            )
            send_event("job_done", job=str(job_path))

        # The GUI should treat EOF as incomplete unless it requested exit.
        print(
            "[Session] Command input closed; shutting down.",
            flush=True,
        )
        return 0

    finally:
        cleanup_worker()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)