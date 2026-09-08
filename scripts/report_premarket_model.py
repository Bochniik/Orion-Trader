from __future__ import annotations

import argparse
import json
from pathlib import Path


def pct(value):
    return f"{100.0 * float(value):.2f}%"


def main():
    parser = argparse.ArgumentParser(description="Report Orion premarket predictive model holdout metrics.")
    parser.add_argument(
        "artifact",
        nargs="?",
        type=Path,
        default=Path("backend/data/models/premarket_predictive_v2.json"),
    )
    args = parser.parse_args()

    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    targets = payload.get("targets") or {}
    if not targets:
        raise SystemExit("No targets found in model artifact")

    print(f"Model: {payload.get('model_version', 'unknown')}")
    print(f"Artifact: {args.artifact}")
    print()
    print(
        f"{'target':<16} {'test_acc':>9} {'baseline':>9} {'lift':>8} "
        f"{'logloss':>9} {'brier':>8} {'temp':>7} {'cal_ll_delta':>12}"
    )
    print("-" * 96)

    for target, model in targets.items():
        metrics = model.get("metrics") or {}
        test = metrics.get("test") or {}
        before = metrics.get("calibration_before") or {}
        after = metrics.get("calibration_after") or {}
        accuracy = float(test.get("accuracy", 0.0))
        baseline = float(metrics.get("majority_baseline_test_accuracy", 0.0))
        lift = accuracy - baseline
        cal_delta = float(after.get("log_loss", 0.0)) - float(before.get("log_loss", 0.0))
        print(
            f"{target:<16} {pct(accuracy):>9} {pct(baseline):>9} {pct(lift):>8} "
            f"{float(test.get('log_loss', 0.0)):>9.4f} "
            f"{float(test.get('brier', 0.0)):>8.4f} "
            f"{float(metrics.get('temperature', 1.0)):>7.3f} "
            f"{cal_delta:>12.4f}"
        )

    print()
    print("Interpretation:")
    print("  lift = test accuracy - majority-class baseline from the training split")
    print("  positive lift is necessary but not sufficient evidence of predictive edge")
    print("  cal_ll_delta < 0 means temperature calibration improved calibration-set log loss")
    print("  do not deploy a horizon solely because its raw accuracy is high")


if __name__ == "__main__":
    main()
