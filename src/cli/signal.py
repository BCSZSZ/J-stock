from datetime import datetime
from .common import load_config


def cmd_signal(args):
    """策略信号生成命令"""
    from src.signal_generator import generate_trading_signal

    config = load_config()

    target_date = args.date if args.date else datetime.now().strftime("%Y-%m-%d")

    entry_strategy = args.entry or config["default_strategies"]["entry"]
    exit_strategy = args.exit or config["default_strategies"]["exit"]

    print(f"\n🎯 生成交易信号")
    print(f"   股票代码: {args.ticker}")
    print(f"   日期: {target_date}")
    print(f"   入场策略: {entry_strategy}")
    print(f"   出场策略: {exit_strategy}")
    print("=" * 60)

    signal = generate_trading_signal(
        ticker=args.ticker,
        date=target_date,
        entry_strategy=entry_strategy,
        exit_strategy=exit_strategy,
    )

    if signal:
        print(f"\n✅ 信号生成成功")
        print(f"   动作: {signal['action']}")
        print(f"   置信度: {signal.get('confidence', 'N/A')}")
        if signal.get("reason"):
            print(f"   原因: {signal['reason']}")
    else:
        print(f"\n⚠️ 无交易信号")
