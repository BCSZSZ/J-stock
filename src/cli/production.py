from src.production.config_manager import ProductionConfig
from src.cli.production_daily import run_daily_workflow
from src.cli.production_input import run_input_workflow
from src.cli.production_price_check import run_signal_price_check_command
from src.cli.production_status import (
    run_add_cash,
    run_set_cash,
    run_set_position,
    run_status,
)
from src.cli.production_sync import run_sync_positions
from src.cli.production_utils import ensure_groups
from src.config.runtime import get_config_file_path


def _apply_stock_pool_override(args, config_mgr, prod_cfg: ProductionConfig) -> None:
    pool_id = str(getattr(args, "pool_id", "") or "").strip()
    if not pool_id:
        return

    if args.input or args.status or args.sync_positions or args.set_cash or args.add_cash:
        raise ValueError("--pool-id is only supported for production daily runs in phase 1")
    if args.set_position or getattr(args, "check_price", None):
        raise ValueError("--pool-id is only supported for production daily runs in phase 1")

    selected_pool = config_mgr.resolve_stock_pools([pool_id])[0]
    prod_cfg.monitor_list_file = selected_pool.monitor_list_file
    if selected_pool.sector_pool_file:
        prod_cfg.sector_pool_file = selected_pool.sector_pool_file
    setattr(prod_cfg, "selected_stock_pool_id", selected_pool.id)
    setattr(prod_cfg, "selected_stock_pool_label", selected_pool.label)


def _validate_daily_only_runtime_overrides(args) -> None:
    runtime_flags = (
        "position_sizing_mode",
        "risk_per_trade_pct",
        "atr_stop_multiple",
        "atr_ratio_min",
        "atr_ratio_max",
        "momentum_exhaustion_mode",
        "momentum_exhaustion_max_score",
        "momentum_exhaustion_threshold_method",
        "industry_filter_mode",
        "max_buy_per_industry_per_day",
        "max_total_positions_per_industry",
        "industry_reference_file",
    )
    if not any(getattr(args, name, None) is not None for name in runtime_flags):
        return
    if args.input or args.status or args.sync_positions or args.set_cash or args.add_cash:
        raise ValueError("Runtime override flags are only supported for production daily runs")
    if args.set_position or getattr(args, "check_price", None):
        raise ValueError("Runtime override flags are only supported for production daily runs")


def cmd_production(args):
    """Production workflows: daily signal generation / next-day manual input / tools."""
    from src.production import ConfigManager, ProductionState

    print("\n" + "=" * 70)
    print("PRODUCTION SIGNAL ENGINE")
    print("=" * 70)

    config_mgr = ConfigManager(str(get_config_file_path()))
    prod_cfg = config_mgr.get_production_config()
    _apply_stock_pool_override(args, config_mgr, prod_cfg)
    _validate_daily_only_runtime_overrides(args)
    state = ProductionState(state_file=prod_cfg.state_file)
    ensure_groups(state, config_mgr, prod_cfg)

    print(
        f"🧭 Runtime: mode={prod_cfg.runtime_mode}, storage={prod_cfg.storage_backend}, state={prod_cfg.state_backend}"
    )
    print(f"  State file: {prod_cfg.state_file}")
    print(f"  Monitor list: {prod_cfg.monitor_list_file}")
    if getattr(prod_cfg, "selected_stock_pool_id", None):
        print(
            "  Stock pool override: "
            f"{getattr(prod_cfg, 'selected_stock_pool_id')}"
            f" ({getattr(prod_cfg, 'selected_stock_pool_label', '')})"
        )
    print(f"  Signal pattern: {prod_cfg.signal_file_pattern}")

    if args.status:
        run_status(prod_cfg, state)
        return

    if args.sync_positions:
        run_sync_positions(prod_cfg, state)
        return

    if args.set_cash:
        run_set_cash(args, prod_cfg, state)
        return

    if args.add_cash:
        run_add_cash(args, prod_cfg, state)
        return

    if args.set_position:
        run_set_position(args, state)
        return

    if getattr(args, "check_price", None):
        run_signal_price_check_command(args, prod_cfg, state)
        return

    if args.input:
        run_input_workflow(args, prod_cfg, state)
        return

    run_daily_workflow(args, prod_cfg, state)
