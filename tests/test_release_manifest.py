from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_reliability_lab.release import (  # noqa: E402
    ReleaseGateConfig,
    ReleaseSuiteManifest,
    ReleaseThresholds,
)
from agent_reliability_lab.scenarios import DEFAULT_SCENARIO_DIR  # noqa: E402


TRAIN_PATHS = tuple(sorted(DEFAULT_SCENARIO_DIR.glob("*.json")))
REGRESSION_PATH = ROOT / "data/release/regression/northwind_lockout_v1.json"
HOLDOUT_PATH = ROOT / "data/release/holdout/northwind_mfa_v1.json"


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_builds_disjoint_repeated_suites(self) -> None:
        manifest = _manifest()

        regression = manifest.regression_suite()
        holdout = manifest.holdout_suite()

        self.assertEqual(regression.repeat_count, 10)
        self.assertEqual(holdout.repeat_count, 10)
        self.assertEqual(regression.scenario_paths, (REGRESSION_PATH,))
        self.assertEqual(holdout.scenario_paths, (HOLDOUT_PATH,))
        self.assertEqual(manifest.all_paths, (*TRAIN_PATHS, REGRESSION_PATH, HOLDOUT_PATH))

    def test_manifest_rejects_empty_duplicate_overlapping_and_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.json"
            cases = (
                {"train_paths": ()},
                {"regression_paths": ()},
                {"holdout_paths": ()},
                {"train_paths": (TRAIN_PATHS[0], TRAIN_PATHS[0])},
                {"holdout_paths": (REGRESSION_PATH,)},
                {"holdout_paths": (missing,)},
                {"regression_repeat_count": 0},
                {"holdout_repeat_count": True},
            )
            for overrides in cases:
                values = {
                    "version": "release-v1",
                    "train_paths": TRAIN_PATHS,
                    "regression_paths": (REGRESSION_PATH,),
                    "holdout_paths": (HOLDOUT_PATH,),
                    "regression_repeat_count": 10,
                    "holdout_repeat_count": 10,
                }
                values.update(overrides)
                with self.subTest(overrides=overrides):
                    with self.assertRaises(ValueError):
                        ReleaseSuiteManifest(**values)

    def test_thresholds_validate_rates_and_safety_limit(self) -> None:
        self.assertEqual(ReleaseThresholds().min_regression_pass_rate, 1.0)
        for kwargs in (
            {"min_regression_pass_rate": -0.1},
            {"min_holdout_pass_rate": 1.1},
            {"max_safety_failures": -1},
            {"require_all_eligible": "yes"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    ReleaseThresholds(**kwargs)

    def test_config_fixes_worst_case_rollouts_and_rejects_over_budget(self) -> None:
        config = ReleaseGateConfig(
            baseline_candidate_id="cand_openai_degraded_v1",
            release_candidate_id="cand_child",
            manifest=_manifest(),
            max_total_rollouts=30,
            persist_runs=False,
        )

        self.assertEqual(config.worst_case_rollout_count, 30)
        self.assertFalse(config.persist_runs)

        with self.assertRaises(ValueError):
            ReleaseGateConfig(
                baseline_candidate_id="cand_openai_degraded_v1",
                release_candidate_id="cand_child",
                manifest=_manifest(),
                max_total_rollouts=29,
            )


def _manifest() -> ReleaseSuiteManifest:
    return ReleaseSuiteManifest(
        version="release-v1",
        train_paths=TRAIN_PATHS,
        regression_paths=(REGRESSION_PATH,),
        holdout_paths=(HOLDOUT_PATH,),
        regression_repeat_count=10,
        holdout_repeat_count=10,
    )


if __name__ == "__main__":
    unittest.main()
