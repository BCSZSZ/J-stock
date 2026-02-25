from .common import load_config


def cmd_fetch(args):
    """数据抓取命令"""
    from src.data.fetch_universe_builder import build_fetch_universe_file
    from src.data_fetch_manager import run_fetch

    config = load_config()

    if args.all:
        print("📥 抓取监视列表中的所有股票数据...")
        production_cfg = config.get("production", {})
        monitor_list_file = production_cfg.get(
            "monitor_list_file", config["data"]["monitor_list_file"]
        )
        fetch_universe_file = production_cfg.get(
            "fetch_universe_file", r"G:\My Drive\AI-Stock-Sync\state\fetch_universe.json"
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
        )
        if summary:
            print(
                f"\n✅ 数据抓取完成: {summary['successful']}/{summary['total']} 只股票成功"
            )
    elif args.tickers:
        print(f"📥 抓取指定股票数据: {', '.join(args.tickers)}")
        import os

        from dotenv import load_dotenv

        from src.client.jquants_client import JQuantsV2Client
        from src.data.benchmark_manager import update_benchmarks
        from src.data.pipeline import StockETLPipeline

        load_dotenv()
        api_key = os.getenv("JQUANTS_API_KEY")

        if not api_key and not args.recompute:
            print("❌ 错误: 未找到 JQUANTS_API_KEY")
            return

        if not args.recompute:
            client = JQuantsV2Client(api_key)
            benchmark_result = update_benchmarks(client)

            if benchmark_result["success"]:
                print(f"✅ TOPIX已更新: {benchmark_result['topix_records']} 条记录")

        pipeline = StockETLPipeline(api_key)
        summary = pipeline.run_batch(
            args.tickers,
            fetch_aux_data=True,
            recompute_features=args.recompute,
            fix_gaps=args.fix_gaps,
        )

        print(
            f"\n✅ 数据抓取完成: {summary['successful']}/{summary['total']} 只股票成功"
        )
    else:
        print("❌ 错误: 请指定 --all 或 --tickers")
