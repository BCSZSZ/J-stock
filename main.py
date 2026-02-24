"""
J-Stock-Analyzer - 统一CLI入口
提供生产流程、数据抓取、信号生成、回测与策略评估等命令
"""

import argparse
import io
import os
import sys

from src.cli.backtest import cmd_backtest
from src.cli.evaluate import cmd_evaluate
from src.cli.fetch import cmd_fetch
from src.cli.portfolio import cmd_portfolio
from src.cli.production import cmd_production
from src.cli.signal import cmd_signal
from src.cli.universe import cmd_universe, cmd_universe_sector
from src.utils.strategy_loader import ENTRY_STRATEGIES, EXIT_STRATEGIES

# Force UTF-8 output on Windows (一劳永逸解决 emoji 编码问题)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    os.environ["TQDM_DISABLE"] = "0"
    os.environ["PYTHONIOENCODING"] = "utf-8"


def build_parser() -> argparse.ArgumentParser:
    total_strategy_combinations = len(ENTRY_STRATEGIES) * len(EXIT_STRATEGIES)

    parser = argparse.ArgumentParser(
        description="J-Stock-Analyzer - 日本股票量化分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例用法:\n"
            "  # 生产流程\n"
            "  python main.py production --daily\n"
            "  python main.py production --input\n"
            "  python main.py production --status\n"
            "  python main.py production --sync-positions    # 同步持仓到监视列表\n\n"
            "  # 数据抓取\n"
            "  python main.py fetch --all                    # 抓取监视列表所有股票\n"
            "  python main.py fetch --tickers 7974 8035      # 指定股票\n"
            "  python main.py fetch --all --recompute        # 仅重算特征层\n\n"
            "  # 生成交易信号\n"
            "  python main.py signal 7974                    # 今日信号\n"
            "  python main.py signal 7974 --date 2026-01-10  # 指定日期\n\n"
            "  # 单股票回测\n"
            "  python main.py backtest 7974                  # 默认参数\n"
            "  python main.py backtest 7974 --entry EnhancedScorerStrategy --exit LayeredExitStrategy\n\n"
            "  # 组合投资回测\n"
            "  python main.py portfolio --all                # 监视列表\n"
            "  python main.py portfolio --tickers 7974 8035 6501\n\n"
            "  # 宇宙选股\n"
            "  python main.py universe --top-n 50\n\n"
            "  # 策略综合评价\n"
            "  python main.py evaluate --mode annual --years 2024 2025\n"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    production_parser = subparsers.add_parser(
        "production", help="生产环境每日工作流程 (Phase 5)"
    )
    production_mode = production_parser.add_mutually_exclusive_group()
    production_mode.add_argument(
        "--daily",
        action="store_true",
        help="盘后工作流：抓取数据 + 生成次日信号 + 生成日报（默认）",
    )
    production_mode.add_argument(
        "--input",
        action="store_true",
        help="次日回传工作流：读取信号并录入人工成交",
    )
    production_mode.add_argument(
        "--status",
        action="store_true",
        help="查看生产状态（资金/持仓/历史概览）",
    )
    production_mode.add_argument(
        "--sync-positions",
        action="store_true",
        help="同步持仓到监视列表并抓取缺失数据",
    )
    production_mode.add_argument(
        "--set-cash",
        nargs=2,
        metavar=("GROUP_ID", "AMOUNT"),
        help="工具命令：直接修正某分组现金",
    )
    production_mode.add_argument(
        "--set-position",
        nargs=4,
        metavar=("GROUP_ID", "TICKER", "QTY", "PRICE"),
        help="工具命令：覆盖某分组某股票持仓（管理员修正）",
    )
    production_parser.add_argument(
        "--signal-date",
        help="配合 --input 使用：指定读取信号日期 YYYY-MM-DD（默认最近一份）",
    )
    production_parser.add_argument(
        "--trade-date",
        help="配合 --input 使用：指定成交回传日期 YYYY-MM-DD（默认今天）",
    )
    production_parser.add_argument(
        "--entry-date",
        help="配合 --set-position 使用：指定持仓建仓日期 YYYY-MM-DD（默认今天）",
    )
    production_parser.add_argument(
        "--yes",
        action="store_true",
        help="配合 --input 使用：跳过开始确认提示",
    )
    production_parser.add_argument(
        "--manual",
        action="store_true",
        help="配合 --input 使用：追加手动成交录入（CSV）",
    )
    production_parser.add_argument(
        "--manual-file",
        help="配合 --input --manual 使用：CSV文件路径",
    )
    production_parser.add_argument(
        "--skip-fetch", action="store_true", help="跳过数据抓取步骤"
    )
    production_parser.set_defaults(func=cmd_production)

    fetch_parser = subparsers.add_parser("fetch", help="抓取股票数据")
    fetch_group = fetch_parser.add_mutually_exclusive_group(required=True)
    fetch_group.add_argument(
        "--all", action="store_true", help="抓取监视列表中的所有股票"
    )
    fetch_group.add_argument("--tickers", nargs="+", help="指定股票代码列表")
    fetch_parser.add_argument(
        "--recompute",
        action="store_true",
        help="强制重算特征层（仅重算features，不重复抓取原始数据）",
    )
    fetch_parser.set_defaults(func=cmd_fetch)

    signal_parser = subparsers.add_parser("signal", help="生成交易信号")
    signal_parser.add_argument("ticker", help="股票代码")
    signal_parser.add_argument("--date", help="指定日期 (格式: YYYY-MM-DD, 默认今天)")
    signal_parser.add_argument(
        "--entry", help="入场策略 (默认: config.json 的 default_strategies.entry)"
    )
    signal_parser.add_argument(
        "--exit", help="出场策略 (默认: config.json 的 default_strategies.exit)"
    )
    signal_parser.set_defaults(func=cmd_signal)

    backtest_parser = subparsers.add_parser("backtest", help="单股票回测")
    backtest_parser.add_argument("ticker", help="股票代码")
    backtest_parser.add_argument(
        "--entry",
        nargs="+",
        help="入场策略列表 (默认: config.json 的 default_strategies.entry，支持多个)",
    )
    backtest_parser.add_argument(
        "--exit",
        nargs="+",
        help="出场策略列表 (默认: config.json 的 default_strategies.exit，支持多个)",
    )
    backtest_parser.add_argument(
        "--all-strategies",
        action="store_true",
        help=f"测试所有策略组合 ({total_strategy_combinations}种)",
    )
    backtest_parser.add_argument(
        "--years", type=int, help="仅回测最近x年 (优先于--start，默认: 全量)"
    )
    backtest_parser.add_argument(
        "--start", help="开始日期 (默认: config.json 的 backtest.start_date)"
    )
    backtest_parser.add_argument(
        "--end", help="结束日期 (默认: config.json 的 backtest.end_date)"
    )
    backtest_parser.add_argument(
        "--capital",
        type=int,
        help="起始资金 (默认: config.json 的 backtest.starting_capital_jpy)",
    )
    backtest_parser.set_defaults(func=cmd_backtest)

    portfolio_parser = subparsers.add_parser("portfolio", help="组合投资回测")
    portfolio_group = portfolio_parser.add_mutually_exclusive_group(required=True)
    portfolio_group.add_argument(
        "--all", action="store_true", help="使用监视列表所有股票"
    )
    portfolio_group.add_argument("--tickers", nargs="+", help="指定股票代码列表")
    portfolio_parser.add_argument(
        "--entry",
        nargs="+",
        help="入场策略列表 (默认: config.json 的 default_strategies.entry，支持多个)",
    )
    portfolio_parser.add_argument(
        "--exit",
        nargs="+",
        help="出场策略列表 (默认: config.json 的 default_strategies.exit，支持多个)",
    )
    portfolio_parser.add_argument(
        "--all-strategies",
        action="store_true",
        help=f"测试所有策略组合 ({total_strategy_combinations}种)",
    )
    portfolio_parser.add_argument(
        "--years", type=int, help="仅回测最近x年 (优先于--start，默认: 全量)"
    )
    portfolio_parser.add_argument(
        "--start", help="开始日期 (默认: config.json 的 backtest.start_date)"
    )
    portfolio_parser.add_argument(
        "--end", help="结束日期 (默认: config.json 的 backtest.end_date)"
    )
    portfolio_parser.add_argument(
        "--capital",
        type=int,
        help="起始资金 (默认: config.json 的 backtest.starting_capital_jpy)",
    )
    portfolio_parser.set_defaults(func=cmd_portfolio)

    universe_parser = subparsers.add_parser("universe", help="宇宙选股（从CSV加载）")
    universe_parser.add_argument(
        "--csv-file", type=str, help="CSV文件路径 (默认: data/jpx_final_list.csv)"
    )
    universe_parser.add_argument(
        "--top-n", type=int, default=50, help="选出Top N股票 (默认: 50)"
    )
    universe_parser.add_argument("--limit", type=int, help="仅处理前N支股票（调试用）")
    universe_parser.add_argument("--batch-size", type=int, help="批次大小（默认100）")
    universe_parser.add_argument(
        "--resume", action="store_true", help="从checkpoint断点续传"
    )
    universe_parser.add_argument(
        "--checkpoint", type=str, help="指定checkpoint路径（默认自动生成）"
    )
    universe_parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="跳过数据抓取，直接用现有features做归一化（快速重新评分）",
    )
    universe_parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="并行worker数量（默认: 8）",
    )
    universe_parser.add_argument(
        "--score-model",
        choices=["v1", "v2"],
        default="v1",
        help="打分模型版本（默认: v1）",
    )
    universe_parser.add_argument(
        "--output-dir",
        default="data/universe",
        help="输出目录（默认: data/universe）",
    )
    universe_parser.set_defaults(func=cmd_universe)

    universe_sector_parser = subparsers.add_parser(
        "universe-sector", help="按33板块配额构建代表池（12-15支/板块）"
    )
    universe_sector_parser.add_argument(
        "--csv-file", type=str, help="CSV文件路径 (默认: data/jpx_final_list.csv)"
    )
    universe_sector_parser.add_argument(
        "--sector-col",
        default="33業種区分",
        help="板块列名（默认: 33業種区分）",
    )
    universe_sector_parser.add_argument(
        "--size-col",
        default="規模区分",
        help="规模列名（默认: 規模区分）",
    )
    universe_sector_parser.add_argument(
        "--min-per-sector",
        type=int,
        default=12,
        help="每板块最少入选数（默认: 12）",
    )
    universe_sector_parser.add_argument(
        "--max-per-sector",
        type=int,
        default=15,
        help="每板块最多入选数（默认: 15）",
    )
    universe_sector_parser.add_argument(
        "--candidate-multiplier",
        type=int,
        default=3,
        help="板块内候选扩展倍数（默认: 3）",
    )
    universe_sector_parser.add_argument(
        "--size-balance",
        action="store_true",
        help="启用规模分层平衡抽样",
    )
    universe_sector_parser.add_argument(
        "--limit", type=int, help="仅处理前N支股票（调试用）"
    )
    universe_sector_parser.add_argument(
        "--batch-size", type=int, default=100, help="批次大小（默认100）"
    )
    universe_sector_parser.add_argument(
        "--resume", action="store_true", help="从checkpoint断点续传"
    )
    universe_sector_parser.add_argument(
        "--checkpoint", type=str, help="指定checkpoint路径（默认自动生成）"
    )
    universe_sector_parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="跳过数据抓取，直接用现有features做归一化（快速重新评分）",
    )
    universe_sector_parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="并行worker数量（默认: 8）",
    )
    universe_sector_parser.add_argument(
        "--score-model",
        choices=["v1", "v2"],
        default="v2",
        help="打分模型版本（默认: v2）",
    )
    universe_sector_parser.add_argument(
        "--output-dir",
        default="data/universe",
        help="输出目录（默认: data/universe）",
    )
    universe_sector_parser.add_argument(
        "--write-monitor-list",
        action="store_true",
        help="额外导出monitor_list格式JSON",
    )
    universe_sector_parser.set_defaults(func=cmd_universe_sector)

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="策略综合评价（按年度/市场环境）"
    )
    evaluate_parser.add_argument(
        "--years", nargs="+", type=int, help="年份列表 (例如: 2021 2022 2023)"
    )
    evaluate_parser.add_argument(
        "--mode",
        choices=["annual", "quarterly", "monthly", "custom"],
        default="annual",
        help="评估模式: annual=整年, quarterly=季度, monthly=按月, custom=自定义",
    )
    evaluate_parser.add_argument(
        "--months", nargs="+", type=int, help="月份列表（monthly模式，例如: 1 2 3）"
    )
    evaluate_parser.add_argument(
        "--custom-periods",
        type=str,
        help='自定义时间段（JSON格式）: [["2021-Q1","2021-01-01","2021-03-31"], ...]',
    )
    evaluate_parser.add_argument(
        "--entry-strategies", nargs="+", help="指定入场策略（默认全部）"
    )
    evaluate_parser.add_argument(
        "--exit-strategies", nargs="+", help="指定出场策略（默认全部）"
    )
    evaluate_parser.add_argument(
        "--output-dir",
        default=None,
        help="输出目录（默认: G:\\My Drive\\AI-Stock-Sync\\strategy_evaluation，失败回退到本地strategy_evaluation）",
    )
    evaluate_parser.add_argument(
        "--verbose", action="store_true", help="详细输出模式（显示每个回测的详细进度）"
    )
    evaluate_parser.set_defaults(func=cmd_evaluate)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
