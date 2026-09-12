"""Run the dependency-light maintained regression suite (no real GPU renders)."""
import argparse
import os
import sys
import unittest


MODULES = (
    "test_reezsynth_gui",
    "test_reezsynth_lifecycle",
    "test_reezsynth_worker",
    "test_reezsynth_options",
    "test_reezsynth_render_adapter",
    "test_reezsynth_grouped",
    "test_reezsynth_artifacts",
    "test_reezsynth_destinations",
    "test_reezsynth_image",
    "test_reezsynth_setup",
    "test_reezsynth_polish",
    "test_reezsynth_preview",
    "test_reezsynth_raft",
    "test_reezsynth_cli_benchmark",
    "test_reezsynth_serialization",
    "test_reezsynth_engines",
    "test_reezsynth_fuoum_setup",
    "test_reezsynth_provenance",
    "test_reezsynth_queue_recovery",
    "test_reezsynth_precompute_cache",
    "test_reezsynth_video_export",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Print module names without running tests.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(MODULES))
        return 0
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
