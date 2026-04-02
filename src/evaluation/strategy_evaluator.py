"""
策略综合评价器
按年度、按市场环境评估策略组合表现

Performance Optimization:
- Preloaded data cache to eliminate repeated disk IO
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import time
from collections import defaultdict

import pandas as pd

from src.config.service import load_config
from src.config.runtime import get_config_file_path
from src.overlays import OverlayManager


@dataclass
class AnnualStrategyResult:
    """单个策略在单个年度/时间段的回测结果"""

    period: str  # "2021" 或 "2021-Q1" 或 "2021-01"
    start_date: str  # "2021-01-01"
    end_date: str  # "2021-12-31"
    entry_strategy: str  # "SimpleScorerStrategy"
    exit_strategy: str  # "LayeredExitStrategy"
    entry_filter: str  # "default" / "trend_strict" ...
    return_pct: float  # 策略收益率
    topix_return_pct: Optional[float]  # TOPIX收益率（可能为None）
    alpha: Optional[float]  # 超额收益率（无TOPIX数据时为None）
    sharpe_ratio: float
    max_drawdown_pct: float
    num_trades: int
    win_rate_pct: float
    avg_gain_pct: float
    avg_loss_pct: float
    exit_confirmation_days: int = 1


class MarketRegime:
    """市场环境分类"""

    BEAR_MARKET = "熊市 (TOPIX < 0%)"
    MILD_BULL = "温和牛市 (TOPIX 0-25%)"
    STRONG_BULL = "强劲牛市 (TOPIX 25-50%)"
    SUPER_BULL = "超级牛市 (TOPIX 50-75%)"
    EXTREME_BULL = "极端牛市 (TOPIX > 75%)"

    @staticmethod
    def classify(topix_return: Optional[float]) -> str:
        """根据TOPIX收益率分类市场环境"""
        if topix_return is None:
            return "未知市场环境 (TOPIX数据缺失)"

        if topix_return < 0:
            return MarketRegime.BEAR_MARKET
        elif topix_return < 25:
            return MarketRegime.MILD_BULL
        elif topix_return < 50:
            return MarketRegime.STRONG_BULL
        elif topix_return < 75:
            return MarketRegime.SUPER_BULL
        else:
            return MarketRegime.EXTREME_BULL


class StrategyEvaluator:
    """
    策略综合评价器

    功能：
    1. 批量执行年度/时间段回测
    2. 按市场环境分组分析
    3. 生成Markdown报告和CSV数据

    特点：
    - 不修改任何现有代码，只调用portfolio_engine
    - 支持灵活的时间段指定（整年/季度/月度/自定义）
    - 支持verbose模式和缓存优化
    """

    def __init__(
        self,
        data_root: str = "data",
        output_dir: str = "strategy_evaluation",
        monitor_list_file: Optional[str] = None,
        verbose: bool = False,
        exit_confirmation_days: int = 1,
        overlay_config: Optional[Dict] = None,
        entry_filter_config: Optional[Dict] = None,
        entry_filter_variants: Optional[List[Tuple[str, Dict]]] = None,
        portfolio_overrides: Optional[Dict] = None,
        use_cache: bool = True,
    ):
        """
        Initialize strategy evaluator.

        Args:
            data_root: Root directory for data files
            output_dir: Output directory for results
            verbose: Enable detailed progress output
            overlay_config: Configuration for overlay manager
            entry_filter_config: Entry secondary filter configuration
            entry_filter_variants: Named filter variants for evaluation combinations
            use_cache: Enable data preloading cache for performance (default: True)
        """
        self.data_root = data_root
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[AnnualStrategyResult] = []
        self.verbose = verbose  # 详细输出模式
        self.use_cache = use_cache  # Data cache flag
        self.exit_confirmation_days = max(1, int(exit_confirmation_days))
        self.monitor_list_file = monitor_list_file
        self.entry_filter_config = entry_filter_config or {}
        self.entry_filter_variants = self._normalize_entry_filter_variants(
            entry_filter_variants
        )
        self.portfolio_overrides = portfolio_overrides or {}
        self.overlay_config = overlay_config or {}

        self.overlay_manager = OverlayManager.from_config(
            self.overlay_config,
            data_root=self.data_root,
        )

        # 计时统计（单次run_evaluation内）
        self._timing_counters: Dict[str, float] = defaultdict(float)
        self._timing_counts: Dict[str, int] = defaultdict(int)
        self.last_timing_summary: Dict[str, object] = {}

        # 缓存层（单次运行内有效）
        self._monitor_list_cache = None  # Monitor list 缓存
        self._topix_cache: Dict[Tuple[str, str], Optional[float]] = {}  # TOPIX 缓存
        self._portfolio_limits_cache: Optional[Tuple[int, float]] = None
        self._starting_capital_cache: Optional[int] = None

    def _get_starting_capital(self) -> int:
        """
        Load starting capital from overrides or config.json.

        Priority:
        1) portfolio_overrides.starting_capital_jpy
        2) config.json evaluation.starting_capital_jpy
        3) fallback 8,000,000 JPY
        """
        if self._starting_capital_cache is not None:
            return self._starting_capital_cache

        override_capital = self.portfolio_overrides.get("starting_capital_jpy")
        if override_capital is not None:
            try:
                value = int(override_capital)
                if value > 0:
                    self._starting_capital_cache = value
                    return self._starting_capital_cache
            except Exception:
                pass

        try:
            config = load_config()
            eval_cfg = config.get("evaluation", {})
            value = int(eval_cfg.get("starting_capital_jpy", 8_000_000))
            if value > 0:
                self._starting_capital_cache = value
                return self._starting_capital_cache
        except Exception:
            pass

        self._starting_capital_cache = 8_000_000
        return self._starting_capital_cache

    def _normalize_entry_filter_variants(
        self, variants: Optional[List[Tuple[str, Dict]]]
    ) -> List[Tuple[str, Dict]]:
        if variants:
            normalized: List[Tuple[str, Dict]] = []
            for idx, item in enumerate(variants, 1):
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    continue
                name, cfg = item
                if not isinstance(cfg, dict):
                    continue
                variant_name = str(name).strip() or f"filter_{idx}"
                normalized.append((variant_name, cfg))
            if normalized:
                return normalized

        return [("default", self.entry_filter_config)]

    def _get_portfolio_limits(self) -> Tuple[int, float]:
        """
        Load portfolio limits from config.json once.

        Returns:
            (max_positions, max_position_pct)
        """
        if self._portfolio_limits_cache is not None:
            return self._portfolio_limits_cache

        override_max_positions = self.portfolio_overrides.get("max_positions")
        override_max_position_pct = self.portfolio_overrides.get("max_position_pct")
        if override_max_positions is not None or override_max_position_pct is not None:
            try:
                max_positions = int(
                    override_max_positions if override_max_positions is not None else 7
                )
                max_position_pct = float(
                    override_max_position_pct
                    if override_max_position_pct is not None
                    else 0.18
                )
                self._portfolio_limits_cache = (max_positions, max_position_pct)
                return self._portfolio_limits_cache
            except Exception:
                pass

        try:
            config = load_config()
            portfolio_cfg = config.get("portfolio", {})
            max_positions = int(portfolio_cfg.get("max_positions", 7))
            max_position_pct = float(portfolio_cfg.get("max_position_pct", 0.18))
            self._portfolio_limits_cache = (max_positions, max_position_pct)
            return self._portfolio_limits_cache
        except Exception:
            pass

        self._portfolio_limits_cache = (7, 0.18)
        return self._portfolio_limits_cache

    def run_evaluation(
        self,
        periods: List[Tuple[str, str, str]],
        entry_strategies: List[str] = None,
        exit_strategies: List[str] = None,
    ) -> pd.DataFrame:
        """
        执行批量策略评估（并行优化版本）

        Args:
            periods: [(period_label, start_date, end_date), ...]
                    例如: [("2021", "2021-01-01", "2021-12-31"),
                           ("2022-Q1", "2022-01-01", "2022-03-31")]
            entry_strategies: 入场策略列表（默认全部）
            exit_strategies: 出场策略列表（默认全部）

        Returns:
            DataFrame包含所有回测结果
        """
        from src.utils.strategy_loader import ENTRY_STRATEGIES, EXIT_STRATEGIES

        # 默认使用全部策略
        if entry_strategies is None:
            entry_strategies = list(ENTRY_STRATEGIES.keys())
        if exit_strategies is None:
            exit_strategies = list(EXIT_STRATEGIES.keys())

        def _fmt_hms(total_seconds: float) -> str:
            sec = max(0, int(total_seconds))
            h = sec // 3600
            m = (sec % 3600) // 60
            s = sec % 60
            return f"{h:02d}:{m:02d}:{s:02d}"

        def _log_step(message: str) -> None:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

        _log_step("evaluator: run_evaluation 启动")
        run_started = time.perf_counter()
        self._timing_counters = defaultdict(float)
        self._timing_counts = defaultdict(int)

        def _phase_timer_start() -> float:
            return time.perf_counter()

        def _phase_timer_end(name: str, started: float):
            self._timing_counters[name] += time.perf_counter() - started
            self._timing_counts[name] += 1

        _log_step("evaluator: 开始加载 monitor list")
        phase_started = _phase_timer_start()
        tickers = self._load_monitor_list()
        _phase_timer_end("phase_load_monitor_list", phase_started)
        _log_step(f"evaluator: monitor list 完成 (tickers={len(tickers)})")

        total_backtests = (
            len(periods)
            * len(entry_strategies)
            * len(exit_strategies)
            * len(self.entry_filter_variants)
        )

        # 总是显示的基本信息
        print(f"\n{'=' * 80}")
        print("🎯 策略综合评价")
        print(f"{'=' * 80}")
        print(f"   时间段数量: {len(periods)}")
        print(f"   入场策略: {len(entry_strategies)}个")
        print(f"   出场策略: {len(exit_strategies)}个")
        print(f"   入场过滤器: {len(self.entry_filter_variants)}个")
        print(f"   总回测次数: {total_backtests}")
        print(f"   数据缓存: {'启用' if self.use_cache else '禁用'}")
        print(f"   输出模式: {'详细' if self.verbose else '简洁'}")
        print(f"{'=' * 80}\n")

        # Step 1: Preload data cache (if enabled)
        preloaded_cache = None
        if self.use_cache:
            _log_step("evaluator: 开始预加载数据缓存")
            phase_started = _phase_timer_start()
            print("📦 预加载数据缓存...")
            try:
                from src.backtest.data_cache import BacktestDataCache

                preloaded_cache = BacktestDataCache(data_root=self.data_root)

                # 计算所需的日期范围
                min_date = min(p[1] for p in periods)  # Earliest start_date
                max_date = max(p[2] for p in periods)  # Latest end_date

                include_trades, include_financials, include_metadata = (
                    self._resolve_aux_preload_flags(
                        entry_strategies=entry_strategies,
                        exit_strategies=exit_strategies,
                        entry_mapping=ENTRY_STRATEGIES,
                        exit_mapping=EXIT_STRATEGIES,
                    )
                )

                preloaded_cache.preload_tickers(
                    tickers=tickers,
                    start_date=min_date,
                    end_date=max_date,
                    optimize_memory=True,
                    include_trades=include_trades,
                    include_financials=include_financials,
                    include_metadata=include_metadata,
                )

                memory_dict = preloaded_cache.get_memory_usage()
                total_mb = sum(memory_dict.values())
                print(f"✅ 缓存加载完成: {len(tickers)}只股票, {total_mb:.2f} MB\n")
                print(
                    "   缓存内容: "
                    f"trades={'on' if include_trades else 'off'}, "
                    f"financials={'on' if include_financials else 'off'}, "
                    f"metadata={'on' if include_metadata else 'off'}"
                )
                _log_step(f"evaluator: 数据缓存完成 ({total_mb:.2f} MB)")
            except Exception as e:
                print(f"⚠️  缓存加载失败，继续串行并禁用缓存: {e}\n")
                preloaded_cache = None
                _log_step("evaluator: 缓存加载失败，已禁用缓存")
            _phase_timer_end("phase_preload_cache", phase_started)
        else:
            _log_step("evaluator: 数据缓存关闭")

        # Step 2: Prepare TOPIX cache
        _log_step("evaluator: 开始预加载 TOPIX")
        phase_started = _phase_timer_start()
        print("📊 预加载TOPIX基准数据...")
        for period_label, start_date, end_date in periods:
            cache_key = (start_date, end_date)
            if cache_key not in self._topix_cache:
                self._topix_cache[cache_key] = self._get_topix_return(
                    start_date, end_date
                )
        print("✅ TOPIX数据缓存完成\n")
        _phase_timer_end("phase_preload_topix", phase_started)
        _log_step("evaluator: TOPIX 预加载完成")

        # Step 3: Create task list
        phase_started = _phase_timer_start()
        tasks = []
        for period_label, start_date, end_date in periods:
            topix_return = self._topix_cache.get((start_date, end_date))
            for entry in entry_strategies:
                for exit in exit_strategies:
                    for filter_name, filter_cfg in self.entry_filter_variants:
                        tasks.append(
                            {
                                "period_label": period_label,
                                "start_date": start_date,
                                "end_date": end_date,
                                "entry_strategy": entry,
                                "exit_strategy": exit,
                                "entry_filter": filter_name,
                                "entry_filter_config": filter_cfg,
                                "topix_return": topix_return,
                            }
                        )
        _phase_timer_end("phase_build_tasks", phase_started)
        _log_step(f"evaluator: 任务列表完成 (tasks={len(tasks)})")

        # Step 4: Execute backtests (serial)
        phase_started = _phase_timer_start()
        print(f"🚀 开始执行 {len(tasks)} 个回测任务...", flush=True)
        print("   进度字段: 时间, 完成数/总数, 成功, 失败, 百分比, 已耗时, 吞吐, ETA, 预计完成时刻", flush=True)
        completed = 0
        success_count = 0
        error_count = 0
        run_started_monotonic = time.monotonic()
        last_progress_print = run_started_monotonic

        for task in tasks:
            completed += 1
            progress = (completed / total_backtests) * 100

            if self.verbose:
                print(
                    f"[{completed}/{total_backtests} {progress:.1f}%] "
                    f"{task['entry_strategy']} × {task['exit_strategy']} × {task['entry_filter']}... ",
                    end="",
                    flush=True,
                )

            try:
                result = self._run_single_backtest(
                    period_label=task["period_label"],
                    start_date=task["start_date"],
                    end_date=task["end_date"],
                    entry_strategy=task["entry_strategy"],
                    exit_strategy=task["exit_strategy"],
                    entry_filter_name=task["entry_filter"],
                    entry_filter_config=task["entry_filter_config"],
                    topix_return=task["topix_return"],
                    preloaded_cache=preloaded_cache,
                )

                self.results.append(result)
                success_count += 1

                if self.verbose:
                    alpha_str = (
                        f"{result.alpha:>6.2f}%"
                        if result.alpha is not None
                        else "   N/A "
                    )
                    print(f"✓ Return: {result.return_pct:>6.2f}%, Alpha: {alpha_str}")
            except Exception as e:
                error_count += 1
                if self.verbose:
                    print(f"✗ Error: {str(e)}")

            # 简洁模式：周期性输出进度+ETA，避免长时间无反馈
            if not self.verbose:
                now = time.monotonic()
                should_print = (
                    completed == total_backtests
                    or completed == 1
                    or completed % 10 == 0
                    or (now - last_progress_print) >= 5.0
                )

                if should_print:
                    elapsed_sec = now - run_started_monotonic
                    speed = (completed / elapsed_sec) if elapsed_sec > 0 else 0.0

                    eta_str = "warming-up"
                    finish_str = "warming-up"
                    if completed >= 5 and speed > 0:
                        eta_sec = (total_backtests - completed) / speed
                        eta_str = _fmt_hms(eta_sec)
                        finish_str = (datetime.now() + timedelta(seconds=eta_sec)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )

                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] "
                        f"[{completed}/{total_backtests}] "
                        f"ok={success_count} err={error_count} "
                        f"({progress:.1f}%) "
                        f"elapsed={_fmt_hms(elapsed_sec)} "
                        f"speed={speed:.3f} task/s "
                        f"ETA={eta_str} "
                        f"finish={finish_str}",
                        flush=True,
                    )
                    last_progress_print = now

        _phase_timer_end("phase_execute_tasks", phase_started)

        total_elapsed_sec = time.monotonic() - run_started_monotonic
        avg_sec_per_task = (
            total_elapsed_sec / completed if completed > 0 else 0.0
        )
        print(f"\n{'=' * 80}", flush=True)
        print(f"✅ 评估完成！共 {len(self.results)}/{total_backtests} 个回测成功", flush=True)
        print(
            f"   执行统计: elapsed={_fmt_hms(total_elapsed_sec)}, "
            f"avg={avg_sec_per_task:.2f}s/task, ok={success_count}, err={error_count}",
            flush=True,
        )

        total_phases = [
            "phase_load_monitor_list",
            "phase_preload_cache",
            "phase_preload_topix",
            "phase_build_tasks",
            "phase_execute_tasks",
        ]
        print("\n⏱️ 阶段耗时明细:", flush=True)
        for key in total_phases:
            sec = self._timing_counters.get(key, 0.0)
            pct = (sec / total_elapsed_sec * 100.0) if total_elapsed_sec > 0 else 0.0
            print(f"   - {key}: {sec:.2f}s ({pct:.1f}%)", flush=True)

        per_task_keys = [
            "task_strategy_load",
            "task_monitor_list_load",
            "task_engine_init",
            "task_engine_backtest",
        ]
        if completed > 0:
            print("\n⏱️ 单任务关键子步骤累计:", flush=True)
            for key in per_task_keys:
                sec = self._timing_counters.get(key, 0.0)
                avg = sec / completed
                print(f"   - {key}: total={sec:.2f}s, avg={avg:.4f}s/task", flush=True)

        self.last_timing_summary = {
            "total_elapsed_sec": time.perf_counter() - run_started,
            "completed_tasks": completed,
            "success_count": success_count,
            "error_count": error_count,
            "phase_seconds": {k: float(self._timing_counters.get(k, 0.0)) for k in total_phases},
            "task_step_seconds": {
                k: float(self._timing_counters.get(k, 0.0)) for k in per_task_keys
            },
        }
        print(f"{'=' * 80}\n", flush=True)
        _log_step("evaluator: run_evaluation 结束")

        return self._create_results_dataframe()

    @staticmethod
    def _resolve_aux_preload_flags(
        entry_strategies: List[str],
        exit_strategies: List[str],
        entry_mapping: Dict[str, str],
        exit_mapping: Dict[str, str],
    ) -> Tuple[bool, bool, bool]:
        """
        Determine whether auxiliary datasets should be preloaded based on
        selected strategy modules.
        """

        def _entry_feature_only(name: str) -> bool:
            path = entry_mapping.get(name, "")
            return path.endswith("entry.macd_crossover.MACDCrossoverStrategy")

        def _exit_feature_only(name: str) -> bool:
            path = exit_mapping.get(name, "")
            return "exit.multiview_grid_exit" in path

        if entry_strategies and exit_strategies:
            all_feature_only = all(_entry_feature_only(e) for e in entry_strategies) and all(
                _exit_feature_only(x) for x in exit_strategies
            )
            if all_feature_only:
                return False, False, False

        return True, True, True

    def _run_single_backtest(
        self,
        period_label: str,
        start_date: str,
        end_date: str,
        entry_strategy: str,
        exit_strategy: str,
        entry_filter_name: str,
        entry_filter_config: Dict,
        topix_return: float,
        preloaded_cache=None,
    ) -> AnnualStrategyResult:
        """
        执行单个策略的回测
        调用现有的portfolio_engine（不修改任何现有代码）

        Args:
            preloaded_cache: Optional BacktestDataCache instance for performance
        """
        from src.backtest.portfolio_engine import PortfolioBacktestEngine
        from src.utils.strategy_loader import load_entry_strategy, load_exit_strategy

        # 加载策略实例
        phase_started = time.perf_counter()
        entry = load_entry_strategy(entry_strategy)
        exit_inst = load_exit_strategy(exit_strategy)
        self._timing_counters["task_strategy_load"] += time.perf_counter() - phase_started

        # 加载监视列表
        phase_started = time.perf_counter()
        tickers = self._load_monitor_list()
        self._timing_counters["task_monitor_list_load"] += time.perf_counter() - phase_started

        # 运行回测（调用现有功能，不做任何修改）
        max_positions, max_position_pct = self._get_portfolio_limits()
        phase_started = time.perf_counter()
        engine = PortfolioBacktestEngine(
            data_root=self.data_root,
            starting_capital=self._get_starting_capital(),
            max_positions=max_positions,
            max_position_pct=max_position_pct,
            exit_confirmation_days=self.exit_confirmation_days,
            overlay_manager=self.overlay_manager,
            preloaded_cache=preloaded_cache,  # Pass cache to engine
            entry_filter_config=entry_filter_config,
        )
        self._timing_counters["task_engine_init"] += time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        result = engine.backtest_portfolio_strategy(
            tickers=tickers,
            entry_strategy=entry,
            exit_strategy=exit_inst,
            start_date=start_date,
            end_date=end_date,
            show_signal_ranking=False,
            show_signal_details=False,
            compute_benchmark=False,
        )
        self._timing_counters["task_engine_backtest"] += time.perf_counter() - phase_started

        # 计算alpha：如果没有TOPIX数据，则设为None
        alpha = None
        if topix_return is not None:
            alpha = result.total_return_pct - topix_return

        # 提取结果并构造数据对象
        return AnnualStrategyResult(
            period=period_label,
            start_date=start_date,
            end_date=end_date,
            entry_strategy=entry_strategy,
            exit_strategy=exit_strategy,
            entry_filter=entry_filter_name,
            return_pct=result.total_return_pct,
            topix_return_pct=topix_return,
            alpha=alpha,
            sharpe_ratio=result.sharpe_ratio,
            max_drawdown_pct=result.max_drawdown_pct,
            num_trades=result.num_trades,
            win_rate_pct=result.win_rate_pct,
            avg_gain_pct=result.avg_gain_pct,
            avg_loss_pct=result.avg_loss_pct,
            exit_confirmation_days=self.exit_confirmation_days,
        )

    def _get_topix_return(self, start_date: str, end_date: str) -> Optional[float]:
        """
        计算TOPIX在指定时间段的收益率
        调用现有的benchmark_manager（不修改）
        如果无法获取数据，返回 None
        """
        from src.data.benchmark_manager import BenchmarkManager

        manager = BenchmarkManager(client=None, data_root=self.data_root)

        try:
            result = manager.calculate_benchmark_return(
                start_date=start_date, end_date=end_date, use_cached=True
            )
            return result  # 返回实际结果（可能是None）
        except Exception as e:
            print(f"⚠️ 无法获取TOPIX数据: {e}")
            return None

    def _load_monitor_list(self) -> List[str]:
        """加载监视列表（单次运行内缓存，从 config.json 指定的唯一真源读取）"""
        # 返回缓存（如果存在）
        if self._monitor_list_cache is not None:
            return self._monitor_list_cache

        # 从 config.json 读取配置
        try:
            if self.monitor_list_file:
                monitor_file = Path(self.monitor_list_file)
            else:
                config_path = get_config_file_path()
                if config_path.exists():
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        monitor_file = Path(config["data"]["monitor_list_file"])
                else:
                    # Config 不存在时回退到默认路径
                    monitor_file = Path(self.data_root) / "monitor_list.json"
        except Exception:
            monitor_file = Path(self.data_root) / "monitor_list.json"

        if not monitor_file.exists():
            raise FileNotFoundError(f"监视列表文件不存在: {monitor_file}")

        # JSON format
        if monitor_file.suffix == ".json":
            with open(monitor_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                tickers = []
                if isinstance(data, dict):
                    raw_tickers = data.get("tickers") or data.get("symbols") or data.get("stocks")
                    if isinstance(raw_tickers, list):
                        for item in raw_tickers:
                            if isinstance(item, dict) and item.get("code") is not None:
                                tickers.append(str(item["code"]).strip())
                            elif item is not None:
                                tickers.append(str(item).strip())
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("code") is not None:
                            tickers.append(str(item["code"]).strip())
                        elif item is not None:
                            tickers.append(str(item).strip())
                self._monitor_list_cache = [ticker for ticker in tickers if ticker]
                return self._monitor_list_cache

        # CSV format
        if monitor_file.suffix == ".csv":
            df = pd.read_csv(monitor_file)
            for col in ["code", "Code", "ticker", "Ticker", "symbol", "Symbol"]:
                if col in df.columns:
                    values = [str(v).strip() for v in df[col].tolist() if pd.notna(v)]
                    self._monitor_list_cache = [v for v in values if v]
                    return self._monitor_list_cache
            raise ValueError(
                f"CSV股票池文件缺少代码列（支持 code/Code/ticker/Ticker/symbol/Symbol）: {monitor_file}"
            )

        # TXT format (legacy support)
        tickers = []
        with open(monitor_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    tickers.append(line)
        self._monitor_list_cache = tickers
        return self._monitor_list_cache

    def _create_results_dataframe(self) -> pd.DataFrame:
        """将结果转换为DataFrame"""
        if not self.results:
            return pd.DataFrame()

        return pd.DataFrame([asdict(r) for r in self.results])

    def analyze_by_market_regime(self) -> pd.DataFrame:
        """
        按市场环境分组分析

        Returns:
            按市场环境、策略组合分组的统计结果
        """
        df = self._create_results_dataframe()

        if df.empty:
            return df

        # 添加市场环境分类
        df["market_regime"] = df["topix_return_pct"].apply(MarketRegime.classify)

        # 按市场环境和策略组合分组
        grouped = df.groupby(
            ["market_regime", "entry_strategy", "exit_strategy", "entry_filter"]
        ).agg(
            {
                "return_pct": ["mean", "std", "min", "max"],
                "alpha": ["mean", "std"],
                "sharpe_ratio": "mean",
                "win_rate_pct": "mean",
                "max_drawdown_pct": "mean",
                "period": "count",  # 样本数量
            }
        )

        # 重命名列
        grouped.columns = ["_".join(col).strip() for col in grouped.columns.values]
        grouped = grouped.rename(columns={"period_count": "sample_count"})

        # 按市场环境和平均alpha排序
        grouped = grouped.sort_values(
            ["market_regime", "alpha_mean"], ascending=[True, False]
        )

        return grouped.reset_index()

    def get_top_strategies_by_regime(self, top_n: int = 3) -> Dict[str, pd.DataFrame]:
        """
        找出每种市场环境下表现最好的top N策略

        Args:
            top_n: 每种环境返回的策略数量

        Returns:
            {market_regime: DataFrame of top strategies}
        """
        df = self._create_results_dataframe()

        if df.empty:
            return {}

        df["market_regime"] = df["topix_return_pct"].apply(MarketRegime.classify)

        results = {}
        for regime in sorted(df["market_regime"].unique()):
            regime_df = df[df["market_regime"] == regime]

            # 按alpha排序，取top N
            top_strategies = regime_df.nlargest(top_n, "alpha")[
                [
                    "period",
                    "entry_strategy",
                    "exit_strategy",
                    "entry_filter",
                    "return_pct",
                    "topix_return_pct",
                    "alpha",
                    "sharpe_ratio",
                    "win_rate_pct",
                ]
            ]

            results[regime] = top_strategies

        return results

    def rank_by_target20_goal(self) -> pd.DataFrame:
        """
        Balanced target20 ranking with continuous-hit utility + mean return + stability.

        Core idea:
        - Replace binary hit20 with continuous utility U: clip(return/20, 0, 1)
        - Keep mean return M as a separate dimension
        - Keep no-loss ratio P as a stability anchor
                - Apply risk guardrails with deduction terms (worst year / loss ratio /
                    bull-market losses / average drawdown); no bear-market bonus.

        Returns:
            DataFrame with one row per strategy combo and quantitative ranking metrics.
        """
        df = self._create_results_dataframe()
        if df.empty:
            return pd.DataFrame()

        key_cols = ["entry_strategy", "exit_strategy", "entry_filter"]
        rows = []

        for key, combo_df in df.groupby(key_cols):
            combo_df = combo_df.copy()
            returns = pd.to_numeric(combo_df["return_pct"], errors="coerce").fillna(0.0)
            topix = pd.to_numeric(combo_df["topix_return_pct"], errors="coerce")
            mdd = pd.to_numeric(combo_df["max_drawdown_pct"], errors="coerce").fillna(0.0)

            period_count = int(len(combo_df))
            hit20_rate = float((returns >= 20.0).mean()) if period_count > 0 else 0.0
            shortfall_mean = (
                float((20.0 - returns).clip(lower=0.0).mean()) if period_count > 0 else 20.0
            )
            loss_period_rate = float((returns < 0.0).mean()) if period_count > 0 else 1.0
            worst_period_return = float(returns.min()) if period_count > 0 else -999.0
            mean_return = float(returns.mean()) if period_count > 0 else 0.0
            avg_mdd = float(mdd.mean()) if period_count > 0 else 99.0

            # Continuous hit utility: 20% reaches full score, lower positive returns
            # still get partial credit, non-positive gets no credit.
            soft_hit20_score = (
                float((returns / 20.0).clip(lower=0.0, upper=1.0).mean())
                if period_count > 0
                else 0.0
            )

            # Mean-return component normalized to [0,1] using 30% as saturation point.
            mean_return_component = min(1.0, max(0.0, mean_return / 30.0))

            # Stability component: fewer losing periods is better.
            no_loss_component = 1.0 - loss_period_rate

            bull_mask = topix.notna() & (topix >= 0.0)
            bear_mask = topix.notna() & (topix < 0.0)
            bull_count = int(bull_mask.sum())
            bear_count = int(bear_mask.sum())

            bull_loss_rate = (
                float(((returns < 0.0) & bull_mask).sum()) / bull_count
                if bull_count > 0
                else 0.0
            )
            bear_hit20_rate = (
                float(((returns >= 20.0) & bear_mask).sum()) / bear_count
                if bear_count > 0
                else 0.0
            )

            # Balanced UMP weights (U/M/P): emphasize target-consistency while
            # preserving return level discrimination.
            w_u, w_m, w_p = 0.42, 0.38, 0.20
            base_score = 100.0 * (
                w_u * soft_hit20_score
                + w_m * mean_return_component
                + w_p * no_loss_component
            )

            # Risk guardrails (deduction-based)
            # Worst period penalty: starts once worst period is below 0%.
            if worst_period_return >= 0.0:
                penalty_worst = 0.0
            else:
                penalty_worst = min(30.0, abs(worst_period_return) * 2.0)

            # Loss-ratio penalty: starts above 20% losing periods.
            penalty_loss_ratio = min(
                10.0, max(0.0, loss_period_rate - 0.20) * 40.0
            )

            # Bull-loss penalty: any losing period in bull market is penalized,
            # and the penalty ramps up aggressively.
            penalty_bull_loss = min(25.0, bull_loss_rate * 100.0)

            # Drawdown penalty: starts above 12% average drawdown.
            penalty_avg_mdd = min(8.0, max(0.0, avg_mdd - 12.0) * 0.5)

            # Bear-market bonus is intentionally disabled.
            bonus_bear = 0.0

            risk_penalty_total = (
                penalty_worst
                + penalty_loss_ratio
                + penalty_bull_loss
                + penalty_avg_mdd
            )

            final_score = max(
                0.0,
                min(100.0, base_score + bonus_bear - risk_penalty_total),
            )

            rows.append(
                {
                    "entry_strategy": key[0],
                    "exit_strategy": key[1],
                    "entry_filter": key[2],
                    "period_count": period_count,
                    "hit20_rate": hit20_rate,
                    "soft_hit20_score": soft_hit20_score,
                    "shortfall_mean": shortfall_mean,
                    "loss_period_rate": loss_period_rate,
                    "bull_loss_rate": bull_loss_rate,
                    "bear_hit20_rate": bear_hit20_rate,
                    "worst_period_return": worst_period_return,
                    "avg_mdd": avg_mdd,
                    "mean_return": mean_return,
                    "mean_return_component": mean_return_component,
                    "no_loss_component": no_loss_component,
                    "base_score": base_score,
                    "bonus_bear": bonus_bear,
                    "penalty_worst": penalty_worst,
                    "penalty_loss_ratio": penalty_loss_ratio,
                    "penalty_bull_loss": penalty_bull_loss,
                    "penalty_avg_mdd": penalty_avg_mdd,
                    "risk_penalty_total": risk_penalty_total,
                    "target20_score": final_score,
                }
            )

        rank_df = pd.DataFrame(rows)
        if rank_df.empty:
            return rank_df

        rank_df = rank_df.sort_values(
            [
                "target20_score",
                "soft_hit20_score",
                "mean_return",
                "hit20_rate",
                "loss_period_rate",
                "worst_period_return",
            ],
            ascending=[False, False, False, False, True, False],
        ).reset_index(drop=True)
        rank_df.insert(0, "rank", range(1, len(rank_df) + 1))
        return rank_df

    def rank_by_legacy_goal(self) -> pd.DataFrame:
        """Legacy all-weather ranking based on cross-regime average rank."""
        df = self._create_results_dataframe()
        if df.empty:
            return pd.DataFrame()

        df = df.copy()
        df["market_regime"] = df["topix_return_pct"].apply(MarketRegime.classify)

        strategy_performance = {}
        for regime in df["market_regime"].unique():
            regime_df = df[df["market_regime"] == regime].copy()
            has_alpha = (
                regime_df["alpha"].notna().any()
                and regime_df["topix_return_pct"].notna().any()
            )
            if has_alpha and regime_df["alpha"].sum() != 0:
                regime_df["legacy_rank"] = regime_df["alpha"].rank(ascending=False)
            else:
                regime_df["legacy_rank"] = regime_df["return_pct"].rank(ascending=False)

            for _, row in regime_df.iterrows():
                key = (row["entry_strategy"], row["exit_strategy"], row["entry_filter"])
                if key not in strategy_performance:
                    strategy_performance[key] = []
                strategy_performance[key].append(float(row["legacy_rank"]))

        rows = []
        for key, ranks in strategy_performance.items():
            combo_df = df[
                (df["entry_strategy"] == key[0])
                & (df["exit_strategy"] == key[1])
                & (df["entry_filter"] == key[2])
            ]
            rows.append(
                {
                    "entry_strategy": key[0],
                    "exit_strategy": key[1],
                    "entry_filter": key[2],
                    "avg_rank": float(sum(ranks) / len(ranks)) if ranks else 999.0,
                    "mean_return": float(combo_df["return_pct"].mean()) if not combo_df.empty else 0.0,
                    "mean_alpha": float(combo_df["alpha"].mean()) if not combo_df.empty else 0.0,
                    "mean_sharpe": float(combo_df["sharpe_ratio"].mean()) if not combo_df.empty else 0.0,
                    "mean_win_rate": float(combo_df["win_rate_pct"].mean()) if not combo_df.empty else 0.0,
                }
            )

        out = pd.DataFrame(rows)
        if out.empty:
            return out

        out = out.sort_values(["avg_rank", "mean_return"], ascending=[True, False]).reset_index(drop=True)
        out.insert(0, "rank", range(1, len(out) + 1))
        return out

    @staticmethod
    def _minmax_normalize_series(series: pd.Series, higher_is_better: bool) -> pd.Series:
        s = pd.to_numeric(series, errors="coerce").fillna(0.0)
        s_min = float(s.min())
        s_max = float(s.max())
        span = s_max - s_min
        if span <= 1e-12:
            return pd.Series([0.5] * len(s), index=s.index)
        if higher_is_better:
            return (s - s_min) / span
        return (s_max - s) / span

    def rank_by_risk60_profit40(self) -> pd.DataFrame:
        """
        risk60_profit40_v2 scoring (same metric design as tools/score_strategy_ranking.py):
        - Risk 60%: avg_mdd 35% + worst_year_return 25%
        - Profit 40%: avg_alpha 25% + positive_alpha_ratio 15%
        """
        df = self._create_results_dataframe()
        if df.empty:
            return pd.DataFrame()

        grouped = (
            df.groupby(["entry_strategy", "exit_strategy", "entry_filter"])
            .agg(
                avg_return=("return_pct", "mean"),
                avg_alpha=("alpha", "mean"),
                avg_mdd=("max_drawdown_pct", "mean"),
                worst_year_return=("return_pct", "min"),
                period_count=("period", "nunique"),
                positive_alpha_ratio=("alpha", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean())),
            )
            .reset_index()
        )

        grouped["avg_alpha"] = pd.to_numeric(grouped["avg_alpha"], errors="coerce").fillna(0.0)
        grouped["positive_alpha_ratio"] = pd.to_numeric(
            grouped["positive_alpha_ratio"], errors="coerce"
        ).fillna(0.0)

        grouped["mdd_inverse_norm"] = self._minmax_normalize_series(grouped["avg_mdd"], higher_is_better=False)
        grouped["worst_year_return_norm"] = self._minmax_normalize_series(
            grouped["worst_year_return"], higher_is_better=True
        )
        grouped["avg_alpha_norm"] = self._minmax_normalize_series(grouped["avg_alpha"], higher_is_better=True)
        grouped["positive_alpha_ratio_norm"] = self._minmax_normalize_series(
            grouped["positive_alpha_ratio"], higher_is_better=True
        )

        grouped["risk60_profit40_score"] = (
            grouped["mdd_inverse_norm"] * 0.35
            + grouped["worst_year_return_norm"] * 0.25
            + grouped["avg_alpha_norm"] * 0.25
            + grouped["positive_alpha_ratio_norm"] * 0.15
        )

        grouped = grouped.sort_values(
            ["risk60_profit40_score", "avg_alpha"],
            ascending=[False, False],
        ).reset_index(drop=True)
        grouped.insert(0, "rank", range(1, len(grouped) + 1))
        return grouped

    def save_results(self, prefix: str = "evaluation", ranking_mode: str = "target20"):
        """
        保存结果到文件

        生成：
        1. {prefix}_raw.csv - 原始结果
        2. {prefix}_by_regime.csv - 按市场环境分组
        3. {prefix}_report.md - Markdown报告
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 原始结果CSV
        df = self._create_results_dataframe()
        raw_file = self.output_dir / f"{prefix}_raw_{timestamp}.csv"
        df.to_csv(raw_file, index=False, encoding="utf-8-sig")
        print(f"✅ 原始结果已保存: {raw_file}")

        # 2. 按市场环境分组CSV
        regime_df = self.analyze_by_market_regime()
        regime_file = self.output_dir / f"{prefix}_by_regime_{timestamp}.csv"
        regime_df.to_csv(regime_file, index=False, encoding="utf-8-sig")
        print(f"✅ 市场环境分析已保存: {regime_file}")

        files = {
            "raw": str(raw_file),
            "regime": str(regime_file),
        }

        if ranking_mode == "legacy":
            legacy_rank_df = self.rank_by_legacy_goal()
            legacy_rank_file = self.output_dir / f"{prefix}_legacy_rank_{timestamp}.csv"
            legacy_rank_df.to_csv(legacy_rank_file, index=False, encoding="utf-8-sig")
            print(f"✅ legacy排名已保存: {legacy_rank_file}")
            files["legacy_rank"] = str(legacy_rank_file)

        if ranking_mode == "target20":
            target20_rank_df = self.rank_by_target20_goal()
            target20_rank_file = self.output_dir / f"{prefix}_target20_rank_{timestamp}.csv"
            target20_rank_df.to_csv(target20_rank_file, index=False, encoding="utf-8-sig")
            print(f"✅ 20%目标导向排名已保存: {target20_rank_file}")
            files["target20_rank"] = str(target20_rank_file)

        if ranking_mode == "risk60_profit40":
            risk60_rank_df = self.rank_by_risk60_profit40()
            risk60_rank_file = self.output_dir / f"{prefix}_risk60_profit40_rank_{timestamp}.csv"
            risk60_rank_df.to_csv(risk60_rank_file, index=False, encoding="utf-8-sig")
            print(f"✅ risk60_profit40排名已保存: {risk60_rank_file}")
            files["risk60_profit40_rank"] = str(risk60_rank_file)

        # 4. Markdown报告
        report_file = self.output_dir / f"{prefix}_report_{timestamp}.md"
        self._generate_markdown_report(report_file, ranking_mode=ranking_mode)
        print(f"✅ 报告已保存: {report_file}")
        files["report"] = str(report_file)
        return files

    def _generate_markdown_report(self, output_file: Path, ranking_mode: str = "target20"):
        """生成Markdown格式的评价报告"""
        df = self._create_results_dataframe()

        if df.empty:
            return

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("# 策略综合评价报告\n\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            # 1. 总体概览
            f.write("## 1. 总体概览\n\n")
            f.write(f"- 评估时段数: {df['period'].nunique()}\n")
            f.write(
                f"- 策略组合数: {len(df.groupby(['entry_strategy', 'exit_strategy', 'entry_filter']))}\n"
            )
            f.write(f"- 总回测次数: {len(df)}\n")
            f.write(f"- 入场策略: {', '.join(df['entry_strategy'].unique())}\n")
            f.write(f"- 出场策略: {', '.join(df['exit_strategy'].unique())}\n\n")
            f.write(f"- 入场过滤器: {', '.join(df['entry_filter'].unique())}\n\n")

            # 2. 时段TOPIX表现
            f.write("## 2. 时段TOPIX表现\n\n")
            period_summary = (
                df.groupby("period")
                .agg(
                    {
                        "topix_return_pct": "first",
                        "start_date": "first",
                        "end_date": "first",
                    }
                )
                .reset_index()
            )
            period_summary["market_regime"] = period_summary["topix_return_pct"].apply(
                MarketRegime.classify
            )

            f.write("| 时段 | 日期范围 | TOPIX收益率 | 市场环境 |\n")
            f.write("|------|---------|------------|----------|\n")
            for _, row in period_summary.iterrows():
                topix_str = (
                    f"{row['topix_return_pct']:.2f}%"
                    if pd.notna(row["topix_return_pct"])
                    else "N/A (数据缺失)"
                )
                f.write(
                    f"| {row['period']} | {row['start_date']} ~ {row['end_date']} | "
                    f"{topix_str} | {row['market_regime']} |\n"
                )
            f.write("\n")

            # 3. 按市场环境分类的最优策略
            f.write("## 3. 按市场环境分类的最优策略\n\n")
            df["market_regime"] = df["topix_return_pct"].apply(MarketRegime.classify)

            for regime in sorted(df["market_regime"].unique()):
                regime_df = df[df["market_regime"] == regime].copy()

                # 按 alpha 排序（有TOPIX数据时）或按 return_pct 排序（无TOPIX数据时）
                has_alpha = (
                    regime_df["alpha"].notna().any()
                    and regime_df["topix_return_pct"].notna().any()
                )
                if has_alpha and regime_df["alpha"].sum() != 0:
                    regime_df = regime_df.sort_values("alpha", ascending=False)
                else:
                    regime_df = regime_df.sort_values("return_pct", ascending=False)

                f.write(f"### {regime}\n\n")
                sample_count = len(regime_df)
                periods = regime_df["period"].unique()
                f.write(f"样本数: {sample_count} (时段: {', '.join(periods)})\n\n")

                # 表头：根据是否有TOPIX数据动态调整
                if (
                    regime_df["topix_return_pct"].notna().any()
                    and regime_df["topix_return_pct"].sum() != 0
                ):
                    f.write(
                        "| 排名 | 时段 | 入场策略 | 出场策略 | 入场过滤器 | 收益率 | 超额收益 | 夏普比率 | 胜率 |\n"
                    )
                    f.write(
                        "|------|------|---------|---------|------------|--------|---------|---------|------|\n"
                    )
                    for idx, (_, row) in enumerate(regime_df.iterrows(), 1):
                        alpha_str = (
                            f"{row['alpha']:.2f}%" if pd.notna(row["alpha"]) else "N/A"
                        )
                        f.write(
                            f"| {idx} | {row['period']} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                            f"{row['return_pct']:.2f}% | {alpha_str} | "
                            f"{row['sharpe_ratio']:.2f} | {row['win_rate_pct']:.1f}% |\n"
                        )
                else:
                    f.write(
                        "| 排名 | 时段 | 入场策略 | 出场策略 | 入场过滤器 | 收益率 | 夏普比率 | 胜率 |\n"
                    )
                    f.write(
                        "|------|------|---------|---------|------------|--------|---------|------|\n"
                    )
                    for idx, (_, row) in enumerate(regime_df.iterrows(), 1):
                        f.write(
                            f"| {idx} | {row['period']} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                            f"{row['return_pct']:.2f}% | "
                            f"{row['sharpe_ratio']:.2f} | {row['win_rate_pct']:.1f}% |\n"
                        )
                f.write("\n")

            # 3.5 策略单位列表
            f.write("## 3.5 策略单位性能汇总\n\n")
            f.write(
                "所有策略组合在各时段、各市场环境下的表现对比（按时段和入场策略分组）：\n\n"
            )

            # 按策略组合分组，显示所有时段数据
            strategies = sorted(
                df.groupby(["entry_strategy", "exit_strategy", "entry_filter"])
                .size()
                .index.tolist()
            )

            f.write(
                "| 时段 | 入场策略 | 出场策略 | 入场过滤器 | 收益率 | 超额收益 | 市场环境 |\n"
            )
            f.write(
                "|------|---------|---------|------------|--------|---------|----------|\n"
            )

            for entry_strat, exit_strat, filter_name in strategies:
                combo_df = df[
                    (df["entry_strategy"] == entry_strat)
                    & (df["exit_strategy"] == exit_strat)
                    & (df["entry_filter"] == filter_name)
                ].sort_values("period")
                for _, row in combo_df.iterrows():
                    alpha_str = (
                        f"{row['alpha']:.2f}%" if pd.notna(row["alpha"]) else "N/A"
                    )
                    f.write(
                        f"| {row['period']} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                        f"{row['return_pct']:.2f}% | {alpha_str} | {row['market_regime']} |\n"
                    )
            f.write("\n")

            if ranking_mode == "legacy":
                f.write("## 4. Legacy 全天候排名\n\n")
                legacy_df = self.rank_by_legacy_goal()
                if legacy_df.empty:
                    f.write("无可用legacy排名数据。\n\n")
                else:
                    f.write(
                        "| 排名 | 入场策略 | 出场策略 | 入场过滤器 | 平均排名 | 平均收益率 | 平均超额收益 | 平均夏普 | 平均胜率 |\n"
                    )
                    f.write(
                        "|------|---------|---------|------------|----------|------------|--------------|----------|----------|\n"
                    )
                    for _, row in legacy_df.iterrows():
                        f.write(
                            f"| {int(row['rank'])} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                            f"{row['avg_rank']:.2f} | {row['mean_return']:.2f}% | {row['mean_alpha']:.2f}% | "
                            f"{row['mean_sharpe']:.2f} | {row['mean_win_rate']:.1f}% |\n"
                        )
                    f.write("\n")

            if ranking_mode == "target20":
                f.write("## 4. 年度20%目标导向排名（不以TOPIX涨跌幅为考核基准）\n\n")
                f.write("排序目标：尽量在每个时段达到20%，尽量避免亏损时段；牛市亏损从出现即重罚，最差时段收益<0即开始扣分。\n\n")

                rank_df = self.rank_by_target20_goal()
                if rank_df.empty:
                    f.write("无可用排名数据。\n")
                    return

                f.write(
                    "| 排名 | 入场策略 | 出场策略 | 入场过滤器 | 目标分(0-100) | 达标率(>=20%) | 平均缺口(%) | 亏损时段占比 | 牛市亏损占比 | 熊市达标率 | 最差时段收益(%) |\n"
                )
                f.write(
                    "|------|---------|---------|------------|---------------|---------------|-------------|--------------|--------------|------------|----------------|\n"
                )

                for _, row in rank_df.iterrows():
                    f.write(
                        f"| {int(row['rank'])} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                        f"{row['target20_score']:.2f} | {row['hit20_rate'] * 100:.1f}% | {row['shortfall_mean']:.2f} | "
                        f"{row['loss_period_rate'] * 100:.1f}% | {row['bull_loss_rate'] * 100:.1f}% | "
                        f"{row['bear_hit20_rate'] * 100:.1f}% | {row['worst_period_return']:.2f}% |\n"
                    )

                f.write("\n")
                f.write("### 推荐策略（Top 3）\n\n")

                for _, row in rank_df.head(3).iterrows():
                    f.write(
                        f"- **#{int(row['rank'])} {row['entry_strategy']} × {row['exit_strategy']} × {row['entry_filter']}**"
                        f" | 目标分={row['target20_score']:.2f}, 达标率={row['hit20_rate'] * 100:.1f}%, "
                        f"平均缺口={row['shortfall_mean']:.2f}%, 亏损时段占比={row['loss_period_rate'] * 100:.1f}%, "
                        f"最差时段={row['worst_period_return']:.2f}%\n"
                    )

            if ranking_mode == "risk60_profit40":
                f.write("## 4. Risk60/Profit40 排名（v2）\n\n")
                f.write("评分公式：0.35*mdd_inverse_norm + 0.25*worst_year_return_norm + 0.25*avg_alpha_norm + 0.15*positive_alpha_ratio_norm\n\n")

                rank_df = self.rank_by_risk60_profit40()
                if rank_df.empty:
                    f.write("无可用排名数据。\n")
                    return

                f.write(
                    "| 排名 | 入场策略 | 出场策略 | 入场过滤器 | 60/40得分 | 平均回撤 | 最差年度收益 | 平均Alpha | 正Alpha占比 | 平均收益率 |\n"
                )
                f.write(
                    "|------|---------|---------|------------|----------|----------|--------------|-----------|-------------|------------|\n"
                )

                for _, row in rank_df.iterrows():
                    f.write(
                        f"| {int(row['rank'])} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                        f"{row['risk60_profit40_score']:.4f} | {row['avg_mdd']:.2f}% | {row['worst_year_return']:.2f}% | "
                        f"{row['avg_alpha']:.2f}% | {row['positive_alpha_ratio'] * 100:.1f}% | {row['avg_return']:.2f}% |\n"
                    )

                f.write("\n")
                f.write("### 推荐策略（Top 3）\n\n")
                for _, row in rank_df.head(3).iterrows():
                    f.write(
                        f"- **#{int(row['rank'])} {row['entry_strategy']} × {row['exit_strategy']} × {row['entry_filter']}**"
                        f" | 60/40得分={row['risk60_profit40_score']:.4f}, 平均回撤={row['avg_mdd']:.2f}%, "
                        f"最差年度={row['worst_year_return']:.2f}%, 平均Alpha={row['avg_alpha']:.2f}%\n"
                    )


def create_annual_periods(years: List[int]) -> List[Tuple[str, str, str]]:
    """
    创建年度时间段列表

    Args:
        years: [2021, 2022, 2023, ...]

    Returns:
        [("2021", "2021-01-01", "2021-12-31"), ...]
    """
    return [(str(year), f"{year}-01-01", f"{year}-12-31") for year in years]


def create_monthly_periods(
    year: int, months: List[int] = None
) -> List[Tuple[str, str, str]]:
    """
    创建月度时间段列表

    Args:
        year: 年份
        months: 月份列表（默认1-12）

    Returns:
        [("2021-01", "2021-01-01", "2021-01-31"), ...]
    """
    import calendar

    if months is None:
        months = list(range(1, 13))

    periods = []
    for month in months:
        last_day = calendar.monthrange(year, month)[1]
        periods.append(
            (
                f"{year}-{month:02d}",
                f"{year}-{month:02d}-01",
                f"{year}-{month:02d}-{last_day}",
            )
        )

    return periods


def create_quarterly_periods(years: List[int]) -> List[Tuple[str, str, str]]:
    """
    创建季度时间段列表

    Args:
        years: [2021, 2022, ...]

    Returns:
        [("2021-Q1", "2021-01-01", "2021-03-31"), ...]
    """
    periods = []
    quarters = [
        ("Q1", "01-01", "03-31"),
        ("Q2", "04-01", "06-30"),
        ("Q3", "07-01", "09-30"),
        ("Q4", "10-01", "12-31"),
    ]

    for year in years:
        for q_label, start, end in quarters:
            periods.append((f"{year}-{q_label}", f"{year}-{start}", f"{year}-{end}"))

    return periods

