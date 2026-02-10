from .common import load_config


def cmd_fetch(args):
    """数据抓取命令"""
    from src.data_fetch_manager import main as fetch_main

    config = load_config()

    if args.all:
        print("📥 抓取监视列表中的所有股票数据...")
        fetch_main()
    elif args.tickers:
        print(f"📥 抓取指定股票数据: {', '.join(args.tickers)}")
        import os
        from src.data.pipeline import StockETLPipeline
        from src.data.benchmark_manager import update_benchmarks
        from src.client.jquants_client import JQuantsV2Client
        from dotenv import load_dotenv

        load_dotenv()
        api_key = os.getenv("JQUANTS_API_KEY")

        if not api_key:
            print("❌ 错误: 未找到 JQUANTS_API_KEY")
            return

        client = JQuantsV2Client(api_key)
        benchmark_result = update_benchmarks(client)

        if benchmark_result["success"]:
            print(f"✅ TOPIX已更新: {benchmark_result['topix_records']} 条记录")

        pipeline = StockETLPipeline(api_key)
        summary = pipeline.run_batch(args.tickers, fetch_aux_data=True)

        print(f"\n✅ 数据抓取完成: {summary['successful']}/{summary['total']} 只股票成功")
    else:
        print("❌ 错误: 请指定 --all 或 --tickers")
