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
    
    # 保存到文件
    output_file = "all_strategies.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(combinations, f, indent=2, ensure_ascii=False)
    
    print(f"✅ 已生成 {len(combinations)} 个策略组合")
    print(f"✅ 保存到: {output_file}")
    print("\n使用方法:")
    print(f"  1. 打开 {output_file}")
    print("  2. 复制全部或部分策略")
    print("  3. 粘贴到 backtest_config.json 的 strategies 字段")
    print("  4. 运行 python start_backtest.py")
