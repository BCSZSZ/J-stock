"""
生成所有策略组合并保存到 JSON 文件
直接运行即可，输出到 all_strategies.json
"""
import json

# 可用策略
ENTRY_STRATEGIES = [
    ("SimpleScorerStrategy", "Simple scorer"),
    ("EnhancedScorerStrategy", "Enhanced scorer"),
    ("MACDCrossoverStrategy", "MACD crossover")
]

EXIT_STRATEGIES = [
    ("ATRExitStrategy", "ATR technical exit"),
    ("ScoreBasedExitStrategy", "Score-based exit"),
    ("LayeredExitStrategy", "Multi-layered exit")
]

def generate_all_combinations():
    """生成所有 Entry × Exit 组合"""
    combinations = []
    for entry_name, entry_desc in ENTRY_STRATEGIES:
        for exit_name, exit_desc in EXIT_STRATEGIES:
            strategy = {
                "comment": f"{entry_desc} + {exit_desc}",
                "entry": entry_name,
                "exit": exit_name
            }
            combinations.append(strategy)
    return combinations

if __name__ == "__main__":
    # 生成所有组合
    combinations = generate_all_combinations()
    
    # 确保输出目录存在
    import os
    os.makedirs("output/tools", exist_ok=True)
    
    # 保存到文件（新路径）
    output_file = "output/tools/all_strategies.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(combinations, f, indent=2, ensure_ascii=False)
    
    print(f"✅ 已生成 {len(combinations)} 个策略组合")
    print(f"✅ 保存到: {output_file}")
    print("\n注意:")
    print("  现在CLI支持直接指定策略，通常不需要此文件")
    print("  使用 --all-strategies 参数可测试全部策略组合")
    print("\n示例:")
    print("  python main.py backtest 7974 --all-strategies")
    print("  python main.py portfolio --all --entry SimpleScorerStrategy --exit LayeredExitStrategy")
