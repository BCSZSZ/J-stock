import argparse
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd


def frange(start: float, stop: float, step: float):
    vals = []
    x = start
    while x <= stop + 1e-12:
        vals.append(round(x, 6))
        x += step
    return vals


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fine scan lambda/w for walk-forward stability.")
    p.add_argument("--raw-csv", required=True)
    p.add_argument(
        "--group-cols",
        nargs="+",
        default=["entry_strategy", "exit_strategy", "entry_filter"],
    )
    p.add_argument("--min-train-years", type=int, default=2)
    p.add_argument("--selection-model", default="risk60_profit40_v2")
    p.add_argument("--center-lambda", type=float, default=0.5)
    p.add_argument("--center-w", type=float, default=0.2)
    p.add_argument("--lambda-span", type=float, default=0.2)
    p.add_argument("--w-span", type=float, default=0.1)
    p.add_argument("--lambda-step", type=float, default=0.05)
    p.add_argument("--w-step", type=float, default=0.02)
    p.add_argument("--output-dir", default="strategy_evaluation")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    lambda_values = frange(
        args.center_lambda - args.lambda_span,
        args.center_lambda + args.lambda_span,
        args.lambda_step,
    )
    w_values = frange(
        args.center_w - args.w_span,
        args.center_w + args.w_span,
        args.w_step,
    )

    results = []
    for lam in lambda_values:
        for w in w_values:
            cmd = [
                ".venv/Scripts/python.exe",
                "tools/walk_forward_stability.py",
                "--raw-csv",
                args.raw_csv,
                "--group-cols",
                *args.group_cols,
                "--min-train-years",
                str(args.min_train_years),
                "--selection-model",
                args.selection_model,
                "--std-penalty",
                f"{lam}",
                "--oos-positive-weight",
                f"{w}",
                "--output-dir",
                args.output_dir,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)

            stability_path = None
            for line in proc.stdout.splitlines():
                if line.startswith("stability_csv="):
                    stability_path = line.split("=", 1)[1].strip()
                    break
            if not stability_path:
                raise RuntimeError("Could not parse stability_csv from walk_forward_stability output")

            df = pd.read_csv(stability_path)
            top = df.iloc[0]
            results.append(
                {
                    "lambda": lam,
                    "w": w,
                    "top_strategy_label": top["strategy_label"],
                    "top_stability": float(top["stability_score"]),
                    "top_oos_utility_mean": float(top["oos_utility_mean"]),
                    "top_oos_utility_std": float(top["oos_utility_std"]),
                    "top_oos_positive_alpha_rate": float(top["oos_positive_alpha_rate"]),
                    "top_oos_return_mean": float(top["oos_return_mean"]),
                    "top_oos_alpha_mean": float(top["oos_alpha_mean"]),
                }
            )

    out = pd.DataFrame(results)
    out = out.sort_values(["top_stability", "top_oos_return_mean"], ascending=[False, False])

    csv_path = out_dir / f"wf_fine_scan_{ts}.csv"
    md_path = out_dir / f"wf_fine_scan_{ts}.md"
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Walk-Forward Fine Scan Report\n\n")
        f.write(f"- raw_csv: {args.raw_csv}\n")
        f.write(f"- selection_model: {args.selection_model}\n")
        f.write(
            f"- lambda grid: [{lambda_values[0]}, {lambda_values[-1]}], step={args.lambda_step}, count={len(lambda_values)}\n"
        )
        f.write(
            f"- w grid: [{w_values[0]}, {w_values[-1]}], step={args.w_step}, count={len(w_values)}\n"
        )
        f.write(f"- total points: {len(out)}\n\n")

        best = out.iloc[0]
        f.write("## Best Point\n\n")
        f.write(f"- lambda: {best['lambda']}\n")
        f.write(f"- w: {best['w']}\n")
        f.write(f"- top_strategy: {best['top_strategy_label']}\n")
        f.write(f"- top_stability: {best['top_stability']:.6f}\n")
        f.write(f"- top_oos_utility_mean: {best['top_oos_utility_mean']:.6f}\n")
        f.write(f"- top_oos_utility_std: {best['top_oos_utility_std']:.6f}\n")
        f.write(f"- top_oos_positive_alpha_rate: {best['top_oos_positive_alpha_rate']:.6f}\n")
        f.write(f"- top_oos_return_mean: {best['top_oos_return_mean']:.6f}\n")
        f.write(f"- top_oos_alpha_mean: {best['top_oos_alpha_mean']:.6f}\n\n")

        f.write("## Top 20\n\n")
        f.write("```csv\n")
        f.write(out.head(20).to_csv(index=False))
        f.write("```\n")

    print(f"fine_scan_csv={csv_path.as_posix()}")
    print(f"fine_scan_md={md_path.as_posix()}")


if __name__ == "__main__":
    main()
