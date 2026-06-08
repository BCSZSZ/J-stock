"""
J-Stock-Analyzer - 统一CLI入口
提供生产流程、数据抓取、信号生成、回测与策略评估等命令
"""

import argparse
import io
import os
import sys

from src.cli.backtest import cmd_backtest
from src.cli.fetch import cmd_fetch
from src.cli.portfolio import cmd_portfolio
from src.cli.production import cmd_production
from src.cli.signal import cmd_signal
from src.cli.universe import cmd_universe, cmd_universe_sector
from src.utils.strategy_loader import ENTRY_STRATEGIES, EXIT_STRATEGIES


DEFAULT_EVALUATION_OUTPUT_DIR = "strategy_evaluation"


ATR_RATIO_UNBOUNDED_ARG = "none"


def _parse_optional_atr_ratio_bound(value: str) -> float | str:
    normalized = str(value).strip().lower()
    if normalized in {"", "none", "null", "off", "unlimited"}:
        return ATR_RATIO_UNBOUNDED_ARG
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "ATR ratio bound must be a number or 'none'"
        ) from exc


def _cmd_evaluate(args):
    from src.cli.evaluate import cmd_evaluate

    return cmd_evaluate(args)


def _cmd_pos_evaluation(args):
    from src.cli.evaluate import cmd_pos_evaluation

    return cmd_pos_evaluation(args)


def _cmd_walk_forward_evaluate(args):
    from src.cli.evaluate import cmd_walk_forward_evaluate

    return cmd_walk_forward_evaluate(args)


def _cmd_replay_evaluation(args):
    from src.cli.evaluate import cmd_replay_evaluation

    return cmd_replay_evaluation(args)


def _cmd_entry_analysis(args):
    from src.cli.entry_analysis import cmd_entry_analysis

    return cmd_entry_analysis(args)


def _cmd_entry_signal_analysis(args):
    from src.cli.entry_signal_analysis import cmd_entry_signal_analysis

    return cmd_entry_signal_analysis(args)


def _cmd_entry_exit_validation(args):
    from src.cli.entry_exit_validation import cmd_entry_exit_validation

    return cmd_entry_exit_validation(args)


def _add_fill_buffer_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fill-buffer-enabled",
        action="store_true",
        help="启用成交价缓冲：买入按更贵成交、卖出按更便宜成交回测",
    )
    parser.add_argument(
        "--fill-buffer-pct",
        type=float,
        default=0.02,
        help="成交价缓冲比例（默认: 0.02 = 2%%）",
    )


def _add_entry_reference_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--entry-reference-mode",
        choices=["raw_fill", "buffered_fill"],
        default="raw_fill",
        help=(
            "出场信号使用的入场参考价模式: "
            "raw_fill=原始成交参考价（未加buffer）, "
            "buffered_fill=加buffer后的实际成交价"
        ),
    )


def _add_ranking_strategy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ranking-strategies",
        nargs="+",
        default=None,
        help=(
            "信号排序策略（默认: default）。"
            "可选: default, random, score_only, confidence_weighted, "
            "risk_adjusted, composite, momentum, fresh_momentum, volatility_penalty, trend_alignment"
        ),
    )


def _add_momentum_exhaustion_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--momentum-exhaustion-mode",
        choices=["off", "shadow", "enforce"],
        default=None,
        help="Extreme momentum filter mode: off, shadow, or enforce.",
    )
    parser.add_argument(
        "--momentum-exhaustion-max-score",
        type=float,
        default=None,
        help="Filter BUY signals when momentum rank_score is greater than this value.",
    )
    parser.add_argument(
        "--momentum-exhaustion-threshold-method",
        choices=["absolute"],
        default=None,
        help="Momentum exhaustion threshold method. Only absolute is currently supported.",
    )


def _add_common_evaluation_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach shared arguments used by evaluate and pos-evaluation."""
    parser.add_argument(
        "--buy-fill-mode",
        choices=["next_open", "next_close"],
        default="next_open",
        help="买入成交模式: next_open=次日开盘成交, next_close=次日收盘成交",
    )
    _add_entry_reference_arguments(parser)
    _add_fill_buffer_arguments(parser)
    parser.add_argument(
        "--capacity-regime-mode",
        choices=["off", "enforce"],
        default=None,
        help="evaluation资金容量分层模式: off=关闭, enforce=按资金tier启用动态仓位与流动性约束",
    )
    _add_atr_runtime_override_arguments(parser)
    parser.add_argument(
        "--years", nargs="+", type=int, help="年份列表 (例如: 2021 2022 2023)"
    )
    parser.add_argument(
        "--mode",
        choices=["annual", "quarterly", "monthly", "custom"],
        default="annual",
        help="评估模式: annual=整年, quarterly=季度, monthly=按月, custom=自定义",
    )
    parser.add_argument(
        "--months", nargs="+", type=int, help="月份列表（monthly模式，例如: 1 2 3）"
    )
    parser.add_argument(
        "--custom-periods",
        type=str,
        help='自定义时间段（JSON格式）: [["2021-Q1","2021-01-01","2021-03-31"], ...]',
    )
    parser.add_argument(
        "--include-continuous",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "是否追加一个覆盖全部分段区间的continuous companion run；"
            "默认读取evaluation.include_continuous，缺省关闭"
        ),
    )
    parser.add_argument(
        "--launch-date",
        nargs="+",
        type=str,
        default=None,
        help=(
            "将评估时间窗的开始日裁剪到一个或多个日期（YYYY-MM-DD）。"
            "指定多个日期时，会按所选日期数扩展组合数。"
        ),
    )
    parser.add_argument(
        "--entry-strategies", nargs="+", help="指定入场策略（默认全部）"
    )
    parser.add_argument(
        "--exit-strategies", nargs="+", help="指定出场策略（默认全部）"
    )
    parser.add_argument(
        "--exit-confirm-days",
        type=int,
        default=None,
        help="出场确认天数（连续N天出现SELL才执行，默认读取evaluation.exit_confirmation_days）",
    )
    parser.add_argument(
        "--entry-filter-mode",
        choices=["auto", "off", "atr", "single", "grid"],
        default="auto",
        help="入场过滤器模式: auto=自动, off=关闭, atr=仅ATR%%, single=单组, grid=多组网格",
    )
    parser.add_argument(
        "--entry-filter-name",
        nargs="+",
        help="指定entry_filters中的过滤器名称（single选1个，grid可选多个）",
    )
    parser.add_argument(
        "--list-entry-filters",
        action="store_true",
        help="仅列出可用的entry filter并退出",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"输出目录（默认: {DEFAULT_EVALUATION_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--universe-file",
        nargs="+",
        default=None,
        help="股票池文件路径（支持多个，用于同策略不同股票池比较；支持 json/csv/txt）",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="详细输出模式（显示每个回测的详细进度）"
    )
    parser.add_argument(
        "--enable-overlay",
        action="store_true",
        default=None,
        help="按需启用overlay参与evaluation（默认关闭，仅用于overlay对比研究；详见instruction.md）",
    )
    parser.add_argument(
        "--ranking-mode",
        choices=["legacy", "target20", "risk60_profit40", "prs_train"],
        default=None,
        help=(
            "最终策略排序模式: legacy=旧版跨市场平均排名, "
            "target20=年度20%%目标导向, risk60_profit40=风险60%%/收益40%%, "
            "prs_train=生产稳健训练评分"
        ),
    )
    _add_ranking_strategy_arguments(parser)
    _add_momentum_exhaustion_arguments(parser)


def _add_atr_runtime_override_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--position-sizing-mode",
        choices=["fixed", "atr"],
        default=None,
        help="本次运行仓位模式覆盖: fixed=固定仓位, atr=ATR风险仓位",
    )
    parser.add_argument(
        "--risk-per-trade-pct",
        type=float,
        default=None,
        help="ATR仓位每笔风险占总权益比例，例如0.006表示0.6%%",
    )
    parser.add_argument(
        "--atr-stop-multiple",
        type=float,
        default=None,
        help="ATR仓位初始止损倍数，例如2.0表示2倍ATR",
    )
    parser.add_argument(
        "--atr-ratio-min",
        type=_parse_optional_atr_ratio_bound,
        default=None,
        help="本次运行入场ATR%%下限，例如0.015表示1.5%%；none表示不限制",
    )
    parser.add_argument(
        "--atr-ratio-max",
        type=_parse_optional_atr_ratio_bound,
        default=None,
        help="本次运行入场ATR%%上限，例如0.030表示3.0%%；none表示不限制",
    )


def _add_walk_forward_evaluation_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach arguments for anchored walk-forward evaluation."""
    parser.add_argument(
        "--buy-fill-mode",
        choices=["next_open", "next_close"],
        default="next_open",
        help="买入成交模式: next_open=次日开盘成交, next_close=次日收盘成交",
    )
    _add_entry_reference_arguments(parser)
    _add_fill_buffer_arguments(parser)
    parser.add_argument(
        "--capacity-regime-mode",
        choices=["off", "enforce"],
        default=None,
        help="evaluation资金容量分层模式: off=关闭, enforce=按资金tier启用动态仓位与流动性约束",
    )
    _add_atr_runtime_override_arguments(parser)
    parser.add_argument(
        "--mode",
        choices=["annual", "quarterly"],
        default="annual",
        help="walk-forward 模式: annual=按年滚动, quarterly=按季度滚动（最少训练年份数仍按年解释）",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        required=True,
        help="按年扩展的评估年份列表 (例如: 2021 2022 2023 2024 2025)",
    )
    parser.add_argument(
        "--min-train-years",
        type=int,
        default=2,
        help="每个窗口最少训练年份数（默认: 2）",
    )
    parser.add_argument(
        "--entry-strategies", nargs="+", help="候选入场策略（默认全部）"
    )
    parser.add_argument(
        "--exit-strategies", nargs="+", help="候选出场策略（默认全部）"
    )
    parser.add_argument(
        "--exit-confirm-days",
        type=int,
        default=None,
        help="出场确认天数（连续N天出现SELL才执行，默认读取evaluation.exit_confirmation_days）",
    )
    parser.add_argument(
        "--entry-filter-mode",
        choices=["auto", "off", "atr", "single", "grid"],
        default="auto",
        help="入场过滤器模式: auto=自动, off=关闭, atr=仅ATR%%, single=单组, grid=多组网格",
    )
    parser.add_argument(
        "--entry-filter-name",
        nargs="+",
        help="指定entry_filters中的过滤器名称（single选1个，grid可选多个）",
    )
    parser.add_argument(
        "--list-entry-filters",
        action="store_true",
        help="仅列出可用的entry filter并退出",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"输出目录（默认: {DEFAULT_EVALUATION_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--universe-file",
        nargs="+",
        default=None,
        help="股票池文件路径（支持多个，用于同策略不同股票池比较；支持 json/csv/txt）",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="详细输出模式（显示每个回测的详细进度）"
    )
    parser.add_argument(
        "--enable-overlay",
        action="store_true",
        default=None,
        help="按需启用overlay参与evaluation（默认关闭，仅用于overlay对比研究；详见instruction.md）",
    )
    parser.add_argument(
        "--ranking-mode",
        choices=["legacy", "target20", "risk60_profit40", "prs_train"],
        default=None,
        help=(
            "训练阶段策略排序模式: legacy=旧版跨市场平均排名, "
            "target20=年度20%%目标导向, risk60_profit40=风险60%%/收益40%%, "
            "prs_train=生产稳健训练评分"
        ),
    )
    _add_ranking_strategy_arguments(parser)
    _add_momentum_exhaustion_arguments(parser)


def _add_replay_evaluation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--report-file",
        nargs="+",
        required=True,
        help="作为 replay 锚点的日报文件路径（本地 Markdown 文件，支持一次指定多个）",
    )
    parser.add_argument(
        "--buy-fill-mode",
        choices=["next_open", "next_close"],
        default="next_open",
        help="买入成交模式: next_open=次日开盘成交, next_close=次日收盘成交",
    )
    _add_entry_reference_arguments(parser)
    _add_fill_buffer_arguments(parser)
    parser.add_argument(
        "--capacity-regime-mode",
        choices=["off", "enforce"],
        default=None,
        help="evaluation资金容量分层模式: off=关闭, enforce=按资金tier启用动态仓位与流动性约束",
    )
    _add_atr_runtime_override_arguments(parser)
    parser.add_argument(
        "--entry-strategies", nargs="+", help="指定入场策略（默认读取evaluation默认配置）"
    )
    parser.add_argument(
        "--exit-strategies", nargs="+", help="指定出场策略（默认读取evaluation默认配置）"
    )
    parser.add_argument(
        "--exit-confirm-days",
        type=int,
        default=None,
        help="出场确认天数（连续N天出现SELL才执行，默认读取evaluation.exit_confirmation_days）",
    )
    parser.add_argument(
        "--entry-filter-mode",
        choices=["auto", "off", "atr", "single", "grid"],
        default="auto",
        help="入场过滤器模式: auto=自动, off=关闭, atr=仅ATR%%, single=单组, grid=多组网格",
    )
    parser.add_argument(
        "--entry-filter-name",
        nargs="+",
        help="指定entry_filters中的过滤器名称（single选1个，grid可选多个）",
    )
    parser.add_argument(
        "--list-entry-filters",
        action="store_true",
        help="仅列出可用的entry filter并退出",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"输出目录（默认: {DEFAULT_EVALUATION_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--universe-file",
        nargs="+",
        default=None,
        help="股票池文件路径（支持多个，用于 replay universe 比较；支持 json/csv/txt）",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="详细输出模式（显示每个回测的详细进度）"
    )
    parser.add_argument(
        "--enable-overlay",
        action="store_true",
        default=None,
        help="按需启用overlay参与evaluation（默认关闭，仅用于overlay对比研究；详见instruction.md）",
    )
    parser.add_argument(
        "--ranking-mode",
        choices=["legacy", "target20", "risk60_profit40", "prs_train"],
        default=None,
        help=(
            "最终策略排序模式: legacy=旧版跨市场平均排名, "
            "target20=年度20%%目标导向, risk60_profit40=风险60%%/收益40%%, "
            "prs_train=生产稳健训练评分"
        ),
    )
    _add_ranking_strategy_arguments(parser)

# Force UTF-8 output on Windows (一劳永逸解决 emoji 编码问题)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        line_buffering=True,
        write_through=True,
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer,
        encoding="utf-8",
        line_buffering=True,
        write_through=True,
    )
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
            "  python main.py walk-forward-evaluate --years 2021 2022 2023 2024 2025 --min-train-years 2\\\n"
            "      --entry-strategies MACDCrossoverStrategy MACDPreCross2BarLiteComboEntry\\\n"
            "      --exit-strategies MVX_N3_R3p25_T1p6_D21_B20p0 --entry-filter-mode off\n"
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
        "--add-cash",
        nargs=2,
        metavar=("GROUP_ID", "AMOUNT"),
        help="工具命令：为某分组增减现金（正数入金，负数出金）",
    )
    production_mode.add_argument(
        "--set-position",
        nargs=4,
        metavar=("GROUP_ID", "TICKER", "QTY", "PRICE"),
        help="工具命令：覆盖某分组某股票持仓（管理员修正）",
    )
    production_mode.add_argument(
        "--check-price",
        choices=["all", "today"],
        metavar="SCOPE",
        help="工具命令：审计并修正 signal_entry_price 锚点（all|today）",
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
        "--aws-profile",
        dest="aws_profile",
        default=None,
        help="配合 --input 使用：完成后自动将 state 上传至 S3（需在 config 中配置 ops_s3_prefix）",
    )
    production_parser.add_argument(
        "--skip-fetch",
        "--no-fetch",
        dest="skip_fetch",
        action="store_true",
        help="跳过数据抓取步骤（兼容参数: --no-fetch）",
    )
    production_parser.add_argument(
        "--pool-id",
        default=None,
        help="可选：仅对本次 daily 运行生效的股票池 ID（来自 stock_pools catalog）",
    )
    _add_atr_runtime_override_arguments(production_parser)
    _add_momentum_exhaustion_arguments(production_parser)
    production_overlay_mode = production_parser.add_mutually_exclusive_group()
    production_overlay_mode.add_argument(
        "--enable-overlay",
        dest="production_overlay",
        action="store_true",
        help="启用 overlay 参与 production 信号计算（项目策略：默认关闭，详见 instruction.md）",
    )
    production_overlay_mode.add_argument(
        "--disable-overlay",
        dest="production_overlay",
        action="store_false",
        help="禁用 overlay 参与 production 信号计算",
    )
    production_parser.set_defaults(func=cmd_production, production_overlay=None)

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
    fetch_parser.add_argument(
        "--fix-gaps",
        action="store_true",
        help="补齐历史缺口：按约5年窗口重抓OHLC并合并去重（非仅增量）",
    )
    fetch_parser.add_argument(
        "--all-listed",
        action="store_true",
        help="与 --all 一起使用：抓取 CSV 上市列表中的所有股票",
    )
    fetch_parser.add_argument(
        "--csv-file",
        default="data/jpx_final_list.csv",
        help="上市股票 CSV 文件路径（默认: data/jpx_final_list.csv）",
    )
    fetch_parser.add_argument(
        "--initial-lookback-days",
        type=int,
        default=1825,
        help="冷启动/补缺口抓取的初始历史天数（默认: 1825）",
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
    _add_fill_buffer_arguments(backtest_parser)
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
    _add_fill_buffer_arguments(portfolio_parser)
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
        choices=["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8"],
        default="v1",
        help="打分模型版本（默认: v1）",
    )
    universe_parser.add_argument(
        "--output-dir",
        default="data/universe",
        help="输出目录（默认: data/universe）",
    )
    universe_parser.add_argument(
        "--atr-ratio-min",
        type=float,
        default=None,
        help="可选：ATR_Ratio 下限覆盖（默认沿用 1.5%%）",
    )
    universe_parser.add_argument(
        "--atr-ratio-max",
        type=float,
        default=None,
        help="可选：ATR_Ratio 上限覆盖（默认沿用 5.0%%）",
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
        default=9,
        help="每板块最少入选数（默认: 9）",
    )
    universe_sector_parser.add_argument(
        "--max-per-sector",
        type=int,
        default=12,
        help="每板块最多入选数（默认: 12）",
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
        choices=["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8"],
        default="v2",
        help="打分模型版本（默认: v2）",
    )
    universe_sector_parser.add_argument(
        "--output-dir",
        default=r"G:\My Drive\AI-Stock-Sync\universe",
        help="输出目录（默认: G:\\My Drive\\AI-Stock-Sync\\universe）",
    )
    universe_sector_parser.add_argument(
        "--atr-ratio-min",
        type=float,
        default=None,
        help="可选：ATR_Ratio 下限覆盖（默认沿用 1.5%%）",
    )
    universe_sector_parser.add_argument(
        "--atr-ratio-max",
        type=float,
        default=None,
        help="可选：ATR_Ratio 上限覆盖（默认沿用 5.0%%）",
    )
    universe_sector_parser.add_argument(
        "--write-monitor-list",
        action="store_true",
        help="额外导出monitor_list格式JSON",
    )
    universe_sector_parser.set_defaults(func=cmd_universe_sector)

    evaluate_parser = subparsers.add_parser(
        "evaluate", aliases=["evaluation"], help="策略综合评价（按年度/市场环境）"
    )
    _add_common_evaluation_arguments(evaluate_parser)
    evaluate_parser.set_defaults(func=_cmd_evaluate)

    walk_forward_parser = subparsers.add_parser(
        "walk-forward-evaluate",
        aliases=["walk-forward-evaluation"],
        help="Anchored walk-forward 策略评价（扩展训练窗 + 下一年测试）",
    )
    _add_walk_forward_evaluation_arguments(walk_forward_parser)
    walk_forward_parser.set_defaults(func=_cmd_walk_forward_evaluate)

    replay_evaluate_parser = subparsers.add_parser(
        "replay-evaluation",
        help="从某个历史 report 状态继续回放到最新可用数据日",
    )
    _add_replay_evaluation_arguments(replay_evaluate_parser)
    _add_momentum_exhaustion_arguments(replay_evaluate_parser)
    replay_evaluate_parser.set_defaults(func=_cmd_replay_evaluation)

    entry_analysis_parser = subparsers.add_parser(
        "entry-analysis",
        help="Entry signal analysis without exit logic (all BUY signals + fixed forward returns)",
    )
    entry_analysis_parser.add_argument(
        "--entry-strategies",
        nargs="+",
        help="入场策略列表（默认读取 evaluation.default_entry_strategies）",
    )
    entry_analysis_parser.add_argument(
        "--universe-file",
        nargs="+",
        default=None,
        help="股票池文件路径（支持 json/csv/txt，可多个）",
    )
    entry_analysis_parser.add_argument("--start", help="开始日期 YYYY-MM-DD")
    entry_analysis_parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    entry_analysis_parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="年份列表；指定后覆盖 --start/--end，例如 2024 2025",
    )
    entry_analysis_parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=[3, 5, 10],
        help="前向收益交易日窗口（默认: 3 5 10）",
    )
    entry_analysis_parser.add_argument(
        "--primary-horizon",
        type=int,
        default=5,
        help="报告排序主窗口（默认: 5）",
    )
    entry_analysis_parser.add_argument(
        "--indicator-columns",
        nargs="+",
        default=None,
        help="要附加的 feature 列；默认 RSI/EMA/ATR/ADX/MACD 等已有指标",
    )
    entry_analysis_parser.add_argument(
        "--rules-json",
        help="分组规则 JSON 字符串或文件路径；未指定时使用 preset rules",
    )
    entry_analysis_parser.add_argument(
        "--preset-rules",
        default="none",
        help="可选批量聚合规则集：default/rsi_adx_ema/none（默认: none，只生成 BUY signal dataset）",
    )
    entry_analysis_parser.add_argument(
        "--label-mode",
        choices=["signal_close", "next_open"],
        default="signal_close",
        help="前向收益标签起点：signal_close 或 next_open（默认: signal_close）",
    )
    entry_analysis_parser.add_argument(
        "--min-samples",
        type=int,
        default=30,
        help="聚合 bucket 最小样本数（默认: 30）",
    )
    entry_analysis_parser.add_argument(
        "--no-joint",
        action="store_true",
        help="只输出单指标 marginal 聚合，不输出多指标 joint 聚合",
    )
    entry_analysis_parser.add_argument(
        "--no-save-candidates",
        action="store_true",
        help="兼容旧参数；Entry Analysis dataset 模式始终保存 BUY candidate 明细 CSV",
    )
    entry_analysis_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅扫描前 N 个 ticker（调试/冒烟用）",
    )
    entry_analysis_parser.add_argument(
        "--data-root",
        default="data",
        help="数据根目录（默认: data）",
    )
    entry_analysis_parser.add_argument(
        "--output-dir",
        default=None,
        help="输出目录（默认: entry_analysis 或 config.entry_analysis.output_dir）",
    )
    entry_analysis_parser.set_defaults(func=_cmd_entry_analysis)

    entry_signal_analysis_parser = subparsers.add_parser(
        "entry-signal-analysis",
        help="Production-style entry signal quality analysis without portfolio constraints",
    )
    entry_signal_analysis_parser.add_argument(
        "--entry-strategies",
        nargs="+",
        help="入场策略列表（默认读取 production 主策略 entry）",
    )
    entry_signal_analysis_parser.add_argument(
        "--universe-file",
        nargs="+",
        default=None,
        help="股票池文件路径（支持 json/csv/txt，可多个；默认读取 production monitor list）",
    )
    entry_signal_analysis_parser.add_argument("--start", help="开始日期 YYYY-MM-DD")
    entry_signal_analysis_parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    entry_signal_analysis_parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="年份列表；指定后覆盖 --start/--end，例如 2024 2025",
    )
    entry_signal_analysis_parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=[1, 3, 5],
        help="前向收益交易日窗口（默认: 1 3 5）",
    )
    entry_signal_analysis_parser.add_argument(
        "--primary-horizon",
        type=int,
        default=5,
        help="兼容字段：默认主比较窗口；未指定 --primary-horizons 时使用（默认: 5）",
    )
    entry_signal_analysis_parser.add_argument(
        "--primary-horizons",
        nargs="+",
        type=int,
        default=None,
        help="详细比较窗口列表；指定后会为每个 horizon 生成完整的中位数/分位数/分组比较段落",
    )
    entry_signal_analysis_parser.add_argument(
        "--label-mode",
        choices=["signal_close", "next_open"],
        default="next_open",
        help="前向收益标签起点：signal_close 或 next_open（默认: next_open）",
    )
    entry_signal_analysis_parser.add_argument(
        "--ranking-strategy",
        default=None,
        help="信号排序策略（默认读取 production.signal_ranking_strategy，缺省 momentum）",
    )
    entry_signal_analysis_parser.add_argument(
        "--entry-filter-mode",
        choices=["auto", "off", "atr", "single", "grid"],
        default="auto",
        help="入场过滤器模式；auto 优先使用 production.entry_filter",
    )
    entry_signal_analysis_parser.add_argument(
        "--entry-filter-name",
        nargs="+",
        default=None,
        help="指定 evaluation.filters.variants 中的过滤器名称",
    )
    _add_atr_runtime_override_arguments(entry_signal_analysis_parser)
    _add_momentum_exhaustion_arguments(entry_signal_analysis_parser)
    entry_signal_analysis_parser.add_argument(
        "--tail-guard-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否启用 daily tail guard（默认读取 production.tail_guard）",
    )
    entry_signal_analysis_parser.add_argument(
        "--tail-guard-max-rank",
        type=int,
        default=None,
        help="覆盖 tail guard max_rank（默认读取 production.tail_guard.max_rank）",
    )
    entry_signal_analysis_parser.add_argument(
        "--tail-guard-rank-limit-mode",
        choices=["max", "min"],
        default=None,
        help="tail guard 合成方式：max=max(max_rank, 正分数数量)，min=min(max_rank, 正分数数量)",
    )
    entry_signal_analysis_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅扫描前 N 个 ticker（调试/冒烟用）",
    )
    entry_signal_analysis_parser.add_argument(
        "--data-root",
        default="data",
        help="数据根目录（默认: data）",
    )
    entry_signal_analysis_parser.add_argument(
        "--output-dir",
        default=None,
        help="输出目录（默认: entry_signal_analysis 或 config.entry_signal_analysis.output_dir）",
    )
    entry_signal_analysis_parser.set_defaults(func=_cmd_entry_signal_analysis)

    entry_exit_validation_parser = subparsers.add_parser(
        "entry-exit-validation",
        help="Signal-level Entry x Exit validation without portfolio/capital constraints",
    )
    entry_exit_validation_parser.add_argument(
        "--entry-strategies",
        nargs="+",
        help="入场策略列表（默认读取 production strategy_groups entry）",
    )
    entry_exit_validation_parser.add_argument(
        "--exit-strategies",
        nargs="+",
        help="退场策略列表（默认读取 production strategy_groups exit）",
    )
    entry_exit_validation_parser.add_argument(
        "--universe-file",
        nargs="+",
        default=None,
        help="股票池文件路径（支持 json/csv/txt，可多个；默认读取 production monitor list）",
    )
    entry_exit_validation_parser.add_argument("--start", help="开始日期 YYYY-MM-DD")
    entry_exit_validation_parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    entry_exit_validation_parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="年份列表；指定后覆盖 --start/--end，例如 2024 2025",
    )
    entry_exit_validation_parser.add_argument(
        "--horizons",
        nargs="+",
        type=int,
        default=[3, 5, 7, 9, 11],
        help="固定持有期对照窗口（默认: 3 5 7 9 11）",
    )
    entry_exit_validation_parser.add_argument(
        "--primary-horizon",
        type=int,
        default=5,
        help="报告主对照窗口（默认: 5）",
    )
    entry_exit_validation_parser.add_argument(
        "--execution-mode",
        choices=["next_open", "signal_close"],
        default="next_open",
        help="信号执行口径：next_open=次交易日开盘成交, signal_close=信号日收盘成交",
    )
    entry_exit_validation_parser.add_argument(
        "--signal-scope",
        choices=["all", "selected"],
        default="all",
        help="模拟范围：all=所有BUY信号, selected=仅日内排名选中信号",
    )
    entry_exit_validation_parser.add_argument(
        "--ranking-strategy",
        default=None,
        help="信号排序策略（默认读取 production.signal_ranking_strategy，缺省 momentum）",
    )
    entry_exit_validation_parser.add_argument(
        "--entry-filter-mode",
        choices=["auto", "off", "atr", "single", "grid"],
        default="auto",
        help="入场过滤器模式；auto 优先使用 production.entry_filter",
    )
    entry_exit_validation_parser.add_argument(
        "--entry-filter-name",
        nargs="+",
        default=None,
        help="指定 evaluation.filters.variants 中的过滤器名称",
    )
    _add_atr_runtime_override_arguments(entry_exit_validation_parser)
    _add_momentum_exhaustion_arguments(entry_exit_validation_parser)
    entry_exit_validation_parser.add_argument(
        "--tail-guard-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否启用 daily tail guard（默认读取 production.tail_guard）",
    )
    entry_exit_validation_parser.add_argument(
        "--tail-guard-max-rank",
        type=int,
        default=None,
        help="覆盖 tail guard max_rank（默认读取 production.tail_guard.max_rank）",
    )
    entry_exit_validation_parser.add_argument(
        "--tail-guard-rank-limit-mode",
        choices=["max", "min"],
        default=None,
        help="tail guard 合成方式：max=max(max_rank, 正分数数量)，min=min(max_rank, 正分数数量)",
    )
    entry_exit_validation_parser.add_argument(
        "--max-holding-trading-days",
        type=int,
        default=60,
        help="未触发退出时的最大持有交易日上限（默认: 60）",
    )
    entry_exit_validation_parser.add_argument(
        "--partial-exit-policy",
        choices=["first_sell_full_exit"],
        default="first_sell_full_exit",
        help="部分卖出处理策略；MVP默认首个SELL视为完整退出",
    )
    entry_exit_validation_parser.add_argument(
        "--min-samples",
        type=int,
        default=30,
        help="报告警告使用的组合最小样本数（默认: 30）",
    )
    entry_exit_validation_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅扫描前 N 个 ticker（调试/冒烟用）",
    )
    entry_exit_validation_parser.add_argument(
        "--data-root",
        default="data",
        help="数据根目录（默认: data）",
    )
    entry_exit_validation_parser.add_argument(
        "--output-dir",
        default=None,
        help="输出目录（默认: entry_exit_validation 或 config.entry_exit_validation.output_dir）",
    )
    entry_exit_validation_parser.set_defaults(func=_cmd_entry_exit_validation)

    pos_evaluate_parser = subparsers.add_parser(
        "pos-evaluation", help="仓位参数批量评价（读取evaluation-position.json）"
    )
    _add_common_evaluation_arguments(pos_evaluate_parser)
    pos_evaluate_parser.add_argument(
        "--position-file",
        default="evaluation-position.json",
        help="仓位组合配置文件路径（默认: evaluation-position.json）",
    )
    pos_evaluate_parser.add_argument(
        "--profile-name",
        nargs="+",
        help="仅运行指定仓位组合名称（可多个）",
    )
    pos_evaluate_parser.add_argument(
        "--overlay-modes",
        nargs="+",
        choices=["off", "on"],
        default=None,
        help="pos-evaluation叠加维度：一次运行多个overlay模式（off/on）",
    )
    pos_evaluate_parser.set_defaults(func=_cmd_pos_evaluation)

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
