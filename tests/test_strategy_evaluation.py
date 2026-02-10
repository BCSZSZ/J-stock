"""
策略评价系统测试脚本
快速验证系统功能
"""
from src.evaluation import (
    StrategyEvaluator,
    create_annual_periods,
    create_monthly_periods,
    create_quarterly_periods
)

def test_small_evaluation():
    """
    测试：2个月 × 25个策略 = 50次回测
    用于验证系统功能
    """
    print("\n" + "="*80)
    print("🧪 策略评价系统 - 快速测试")
    print("="*80)
    print("测试配置:")
    print("  时间段: 2024年1月 + 2025年1月 (2个月)")
    print("  策略: 全部25组 (5入场 × 5出场)")
    print("  预计回测次数: 2 × 25 = 50")
    print("  预计耗时: ~10-15分钟")
    print("="*80 + "\n")
    
    # 创建测试时间段（2个月）
    periods = []
    periods.extend(create_monthly_periods(2024, months=[1]))  # 2024年1月
    periods.extend(create_monthly_periods(2025, months=[1]))  # 2025年1月
    
    print("📅 测试时间段:")
    for label, start, end in periods:
        print(f"   {label}: {start} ~ {end}")
    print()
    
    # 创建评价器
    evaluator = StrategyEvaluator(
        data_root='data',
        output_dir='strategy_evaluation_test'
    )
    
    # 运行评估（使用全部25个策略）
    df_results = evaluator.run_evaluation(
        periods=periods,
        entry_strategies=None,  # 全部入场策略
        exit_strategies=None    # 全部出场策略
    )
    
    # 保存结果
    files = evaluator.save_results(prefix='test_evaluation')
    
    print(f"\n{'='*80}")
    print(f"✅ 测试完成！")
    print(f"{'='*80}")
    print(f"📄 原始结果: {files['raw']}")
    print(f"📊 市场环境分析: {files['regime']}")
    print(f"📝 综合报告: {files['report']}")
    print(f"{'='*80}\n")
    
    # 显示快速摘要
    print("📊 快速摘要:")
    print(f"   总回测次数: {len(df_results)}")
    print(f"   平均收益率: {df_results['return_pct'].mean():.2f}%")
    print(f"   平均超额收益: {df_results['alpha'].mean():.2f}%")
    print(f"   最佳策略: {df_results.loc[df_results['alpha'].idxmax(), 'entry_strategy']} × "
          f"{df_results.loc[df_results['alpha'].idxmax(), 'exit_strategy']} "
          f"({df_results['alpha'].max():.2f}% alpha)")
    print()


def test_full_evaluation():
    """
    完整评估：5年 × 25个策略 = 125次回测
    用于生产环境
    """
    print("\n" + "="*80)
    print("🎯 策略评价系统 - 完整评估")
    print("="*80)
    print("评估配置:")
    print("  时间段: 2021-2025 (5年完整数据)")
    print("  策略: 全部25组 (5入场 × 5出场)")
    print("  预计回测次数: 5 × 25 = 125")
    print("  预计耗时: ~2-4小时")
    print("="*80 + "\n")
    
    response = input("⚠️  这将运行125次回测，需要2-4小时。继续？(y/N): ")
    if response.lower() != 'y':
        print("已取消")
        return
    
    # 创建年度时间段
    periods = create_annual_periods([2021, 2022, 2023, 2024, 2025])
    
    print("\n📅 评估时间段:")
    for label, start, end in periods:
        print(f"   {label}: {start} ~ {end}")
    print()
    
    # 创建评价器
    evaluator = StrategyEvaluator(
        data_root='data',
        output_dir='strategy_evaluation'
    )
    
    # 运行完整评估
    df_results = evaluator.run_evaluation(
        periods=periods,
        entry_strategies=None,
        exit_strategies=None
    )
    
    # 保存结果
    files = evaluator.save_results(prefix='full_evaluation')
    
    print(f"\n{'='*80}")
    print(f"✅ 完整评估完成！")
    print(f"{'='*80}")
    print(f"📄 原始结果: {files['raw']}")
    print(f"📊 市场环境分析: {files['regime']}")
    print(f"📝 综合报告: {files['report']}")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--full':
        test_full_evaluation()
    else:
        print("\n使用方法:")
        print("  python test_strategy_evaluation.py           # 快速测试 (2个月, ~15分钟)")
        print("  python test_strategy_evaluation.py --full    # 完整评估 (5年, ~2-4小时)")
        print()
        
        response = input("运行快速测试？(Y/n): ")
        if response.lower() != 'n':
            test_small_evaluation()
