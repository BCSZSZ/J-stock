"""
快速测试：1个entry × 2个exit × 5年 = 10个回测

用于验证并行评估系统是否工作正常。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.strategy_evaluator import (
    StrategyEvaluator,
    create_annual_periods,
)


def main():
    print("=" * 80)
    print("🧪 快速测试: 1×2 参数组合")
    print("=" * 80)
    print()

    # 配置
    periods = create_annual_periods([2021, 2022, 2023, 2024, 2025])
    entry_strategies = ["MACDCrossoverStrategy"]
    exit_strategies = [
        "MVX_N9_R3p5_T1p6_D20_B20",  # 最优参数
        "MVX_N9_R3p5_T1p6_D18_B20",  # 对比参数
    ]

    print("测试配置:")
    print(f"  进场策略: {entry_strategies}")
    print(f"  出场策略: {exit_strategies}")
    print("  测试年份: 2021-2025")
    print(f"  总回测数: {len(periods) * len(entry_strategies) * len(exit_strategies)}")
    print()

    # 创建评估器（启用并行+缓存）
    evaluator = StrategyEvaluator(
        verbose=True,
        workers=4,
        use_cache=True,
    )

    # 执行评估
    df_results = evaluator.run_evaluation(
        periods=periods,
        entry_strategies=entry_strategies,
        exit_strategies=exit_strategies,
    )

    # 显示结果
    if not df_results.empty:
        print("\n" + "=" * 80)
        print("📊 测试结果")
        print("=" * 80)

        # 按策略汇总
        summary = (
            df_results.groupby("exit_strategy")
            .agg(
                {
                    "return_pct": "mean",
                    "alpha": "mean",
                    "sharpe_ratio": "mean",
                    "win_rate_pct": "mean",
                }
            )
            .round(2)
        )

        print(summary)
        print()

        # 保存结果
        files = evaluator.save_results(prefix="test_1x2")
        print(f"✅ 结果已保存: {files['raw']}")
    else:
        print("❌ 测试失败：无结果")
        return 1

    print("\n✅ 测试完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
