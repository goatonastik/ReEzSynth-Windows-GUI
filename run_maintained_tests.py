"""Run the dependency-light maintained regression suite (no real GPU renders)."""
import argparse
import os
import sys
import unittest


MODULES = (
    "tests.test_reezsynth_fuoum_alpha",
    "tests.test_reezsynth_native_yaml",
    "tests.test_reezsynth_comparison",
    "tests.test_reezsynth_recompute",
    "tests.test_reezsynth_edges",
    "tests.test_reezsynth_gui",
    "tests.test_reezsynth_lifecycle",
    "tests.test_reezsynth_worker",
    "tests.test_reezsynth_options",
    "tests.test_reezsynth_render_adapter",
    "tests.test_reezsynth_alpha",
    "tests.test_reezsynth_grouped",
    "tests.test_reezsynth_artifacts",
    "tests.test_reezsynth_destinations",
    "tests.test_reezsynth_image",
    "tests.test_reezsynth_setup",
    "tests.test_reezsynth_polish",
    "tests.test_reezsynth_preview",
    "tests.test_reezsynth_raft",
    "tests.test_reezsynth_cli_benchmark",
    "tests.test_reezsynth_serialization",
    "tests.test_reezsynth_engines",
    "tests.test_reezsynth_fuoum_setup",
    "tests.test_reezsynth_provenance",
    "tests.test_reezsynth_queue_recovery",
    "tests.test_reezsynth_precompute_cache",
    "tests.test_reezsynth_video_export",
    "tests.test_reezsynth_sequence",
    "tests.test_reezsynth_iterations",
    "tests.test_reezsynth_modulation",
    "tests.test_reezsynth_torch_backend",
    "tests.test_reezsynth_torch_repairs",
    "tests.test_reezsynth_synthetic_inputs",
    "tests.test_reezsynth_packaging",
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
