import argparse
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .common import load_config


def _load_codes_from_csv(csv_file: str) -> list[str]:
    csv_path = Path(csv_file)
    if not csv_path.exists():
        raise FileNotFoundError(f"未找到CSV文件: {csv_path}")

    df = pd.read_csv(csv_path, encoding="utf-8")
    if "Code" not in df.columns:
        raise ValueError(f"CSV缺少Code列: {csv_path}")

    codes = df["Code"].astype(str).str.strip().str.zfill(4)
    return [code for code in codes.tolist() if code]


def _run_local_batch_fetch(
    tickers: list[str],
    *,
    recompute_features: bool,
    fix_gaps: bool,
    initial_lookback_days: int,
) -> dict[str, object] | None:
    from src.client.jquants_client import JQuantsV2Client
    from src.data.benchmark_manager import update_benchmarks
    from src.data.pipeline import StockETLPipeline

    load_dotenv()
    api_key = os.getenv("JQUANTS_API_KEY")

    if not api_key and not recompute_features:
        print("❌ 错误: 未找到 JQUANTS_API_KEY")
        return None

    if not recompute_features:
        client = JQuantsV2Client(api_key)
        benchmark_result = update_benchmarks(client, data_root="data")

        if benchmark_result["success"]:
            print(f"✅ TOPIX已更新: {benchmark_result['topix_records']} 条记录")

    pipeline = StockETLPipeline(api_key, data_root="data")
    return pipeline.run_batch(
        tickers,
        fetch_aux_data=not recompute_features,
        recompute_features=recompute_features,
        fix_gaps=fix_gaps,
        initial_lookback_days=max(int(initial_lookback_days), 1),
    )


def _print_batch_summary(summary: dict[str, object] | None) -> None:
    if not summary:
        return

    successful = summary.get("successful", 0)
    total = summary.get("total", 0)
    print(f"\n✅ 数据抓取完成: {successful}/{total} 只股票成功")


def cmd_fetch(args: argparse.Namespace) -> None:
    """数据抓取命令"""
    from src.data.fetch_universe_builder import build_fetch_universe_file
    from src.data.sector_metrics_updater import update_sector_metrics
    from src.data_fetch_manager import run_fetch

    config = load_config()

    if args.all_listed and not args.all:
        print("❌ 错误: --all-listed 只能与 --all 一起使用")
        return

    if args.all:
        if args.all_listed:
            try:
                tickers = _load_codes_from_csv(args.csv_file)
            except (FileNotFoundError, ValueError) as exc:
                print(f"❌ 错误: {exc}")
                return

            print("📥 抓取上市列表中的所有股票数据...")
            print(f"  CSV: {args.csv_file}")
            print(f"  股票数: {len(tickers)}")

            summary = _run_local_batch_fetch(
                tickers,
                recompute_features=args.recompute,
                fix_gaps=args.fix_gaps,
                initial_lookback_days=args.initial_lookback_days,
            )
            _print_batch_summary(summary)
            return

        print("📥 抓取监视列表中的所有股票数据...")
        production_cfg = config.get("production", {})
        monitor_list_file = production_cfg.get(
            "monitor_list_file", config["data"]["monitor_list_file"]
        )
        fetch_universe_file = production_cfg.get(
            "fetch_universe_file", "output/state/fetch_universe.json"
        )

        output_file, merged_count, sector_count = build_fetch_universe_file(
            monitor_list_file=monitor_list_file,
            output_file=fetch_universe_file,
            sector_pool_file=production_cfg.get("sector_pool_file"),
        )
        print(
            "  Fetch universe prepared: "
            f"{merged_count} tickers (sector pool contribution: {sector_count})"
        )

        summary = run_fetch(
            monitor_list_file=output_file,
            recompute_features=args.recompute,
            fix_gaps=args.fix_gaps,
            initial_lookback_days=args.initial_lookback_days,
            data_root=config.get("data", {}).get("data_dir", "data"),
        )
        if summary:
            _print_batch_summary(summary)

            lookback_days = int(
                production_cfg.get("sector_metrics_lookback_days", 90)
            )
            min_names = int(production_cfg.get("sector_metrics_min_names", 5))
            metrics_summary = update_sector_metrics(
                sector_pool_file=production_cfg.get("sector_pool_file"),
                data_root=config.get("data", {}).get("data_dir", "data"),
                lookback_days=lookback_days,
                min_names_per_sector=min_names,
            )
            if metrics_summary.get("status") == "ok":
                print("✅ 板块指标更新完成")
                print(f"  Pool: {metrics_summary.get('pool_size')} names")
                print(f"  Sectors: {metrics_summary.get('sector_count')}")
                print(f"  Rows written: {metrics_summary.get('rows_written')}")
                print(f"  Metrics: {metrics_summary.get('metrics_file')}")
            else:
                print("⚠️ 板块指标更新跳过（不中断）")
                print(f"  Reason: {metrics_summary.get('message', 'unknown')}")
    elif args.tickers:
        print(f"📥 抓取指定股票数据: {', '.join(args.tickers)}")
        summary = _run_local_batch_fetch(
            args.tickers,
            recompute_features=args.recompute,
            fix_gaps=args.fix_gaps,
            initial_lookback_days=args.initial_lookback_days,
        )
        _print_batch_summary(summary)
    else:
        print("❌ 错误: 请指定 --all 或 --tickers")
