from src.cli.production_daily import run_daily_workflow
from src.cli.production_input import run_input_workflow
from src.cli.production_status import (
    run_add_cash,
    run_set_cash,
    run_set_position,
    run_status,
)
from src.cli.production_sync import run_sync_positions
from src.cli.production_utils import ensure_groups
from src.config.runtime import get_config_file_path


def cmd_production(args):
    """Production workflows: daily signal generation / next-day manual input / tools."""
    from src.production import ConfigManager, ProductionState

    print("\n" + "=" * 70)
    print("PRODUCTION SIGNAL ENGINE")
    print("=" * 70)

    config_mgr = ConfigManager(str(get_config_file_path()))
    prod_cfg = config_mgr.get_production_config()
    state = ProductionState(state_file=prod_cfg.state_file)
    ensure_groups(state, config_mgr, prod_cfg)

    print(
        f"🧭 Runtime: mode={prod_cfg.runtime_mode}, storage={prod_cfg.storage_backend}, state={prod_cfg.state_backend}"
    )
    print(f"  State file: {prod_cfg.state_file}")
    print(f"  Monitor list: {prod_cfg.monitor_list_file}")
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

    if args.input:
        run_input_workflow(args, prod_cfg, state)
        return

    run_daily_workflow(args, prod_cfg, state)
