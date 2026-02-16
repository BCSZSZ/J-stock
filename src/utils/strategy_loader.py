"""
策略加载工具
提供统一的策略选择和实例化接口
"""

from typing import Any, Dict, List, Tuple

# ==================== 策略映射表 ====================

ENTRY_STRATEGIES = {
    "SimpleScorerStrategy": "src.analysis.strategies.entry.scorer_strategy.SimpleScorerStrategy",
    "EnhancedScorerStrategy": "src.analysis.strategies.entry.scorer_strategy.EnhancedScorerStrategy",
    "MACDCrossoverStrategy": "src.analysis.strategies.entry.macd_crossover.MACDCrossoverStrategy",
    "MACDKDJThreeStageEntry": "src.analysis.strategies.entry.macd_kdj_three_stage_entry.MACDKDJThreeStageEntry",
    "MACDKDJThreeStageEntryA": "src.analysis.strategies.entry.macd_kdj_three_stage_entry.MACDKDJThreeStageEntryA",
    "MACDKDJThreeStageEntryB": "src.analysis.strategies.entry.macd_kdj_three_stage_entry.MACDKDJThreeStageEntryB",
    "BollingerSqueezeStrategy": "src.analysis.strategies.entry.bollinger_squeeze_strategy.BollingerSqueezeStrategy",
    "IchimokuStochStrategy": "src.analysis.strategies.entry.ichimoku_stoch_strategy.IchimokuStochStrategy",
}

EXIT_STRATEGIES = {
    "ATRExitStrategy": "src.analysis.strategies.exit.atr_exit.ATRExitStrategy",
    "ScoreBasedExitStrategy": "src.analysis.strategies.exit.score_based_exit.ScoreBasedExitStrategy",
    "LayeredExitStrategy": "src.analysis.strategies.exit.layered_exit.LayeredExitStrategy",
    "BollingerDynamicExit": "src.analysis.strategies.exit.bollinger_dynamic_exit.BollingerDynamicExit",
    "ADXTrendExhaustionExit": "src.analysis.strategies.exit.adx_trend_exhaustion.ADXTrendExhaustionExit",
    "MACDKDJRuleExit": "src.analysis.strategies.exit.macd_kdj_rule_exit.MACDKDJRuleExit",
    "MACDKDJRuleExitA": "src.analysis.strategies.exit.macd_kdj_rule_exit.MACDKDJRuleExitA",
    "MACDKDJRuleExitB": "src.analysis.strategies.exit.macd_kdj_rule_exit.MACDKDJRuleExitB",
}


# ==================== 策略加载函数 ====================


def load_strategy_class(strategy_name: str, strategy_type: str = "entry"):
    """
    动态加载策略类

    Args:
        strategy_name: 策略名称
        strategy_type: 'entry' 或 'exit'

    Returns:
        策略类（未实例化）

    Raises:
        ValueError: 如果策略名称未知
    """
    if strategy_type == "entry":
        mapping = ENTRY_STRATEGIES
    elif strategy_type == "exit":
        mapping = EXIT_STRATEGIES
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")

    if strategy_name not in mapping:
        available = ", ".join(mapping.keys())
        raise ValueError(
            f"Unknown {strategy_type} strategy '{strategy_name}'. Available: {available}"
        )

    # 动态导入
    module_path, class_name = mapping[strategy_name].rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name)


def create_strategy_instance(
    strategy_name: str, strategy_type: str = "entry", params: Dict[str, Any] = None
):
    """
    创建策略实例

    Args:
        strategy_name: 策略名称
        strategy_type: 'entry' 或 'exit'
        params: 策略参数字典

    Returns:
        策略实例
    """
    strategy_class = load_strategy_class(strategy_name, strategy_type)
    params = params or {}
    return strategy_class(**params)


def get_all_strategy_combinations() -> List[Tuple[str, str]]:
    """
    获取所有Entry×Exit策略组合

    Returns:
        [(entry_name, exit_name), ...] 列表
    """
    combinations = []
    for entry_name in ENTRY_STRATEGIES.keys():
        for exit_name in EXIT_STRATEGIES.keys():
            combinations.append((entry_name, exit_name))
    return combinations


def get_strategy_combinations_from_lists(
    entry_names: List[str], exit_names: List[str]
) -> List[Tuple[str, str]]:
    """
    根据指定的入场和出场策略列表生成所有组合

    Args:
        entry_names: 入场策略名称列表
        exit_names: 出场策略名称列表

    Returns:
        [(entry_name, exit_name), ...] 列表

    Raises:
        ValueError: 如果策略名称无效
    """
    # 验证策略名称
    for name in entry_names:
        if name not in ENTRY_STRATEGIES:
            available = ", ".join(ENTRY_STRATEGIES.keys())
            raise ValueError(f"Unknown entry strategy '{name}'. Available: {available}")

    for name in exit_names:
        if name not in EXIT_STRATEGIES:
            available = ", ".join(EXIT_STRATEGIES.keys())
            raise ValueError(f"Unknown exit strategy '{name}'. Available: {available}")

    # 生成组合
    combinations = []
    for entry_name in entry_names:
        for exit_name in exit_names:
            combinations.append((entry_name, exit_name))
    return combinations


def parse_strategy_config(config: dict) -> Tuple[object, object]:
    """
    解析策略配置并返回实例化的策略对象

    Args:
        config: 策略配置字典，格式如下：
               {
                   "entry": "SimpleScorerStrategy",
                   "exit": "ATRExitStrategy",
                   "entry_params": {},  # optional
                   "exit_params": {}    # optional
               }

    Returns:
        (entry_strategy_instance, exit_strategy_instance)
    """
    entry_name = config.get("entry")
    exit_name = config.get("exit")
    entry_params = config.get("entry_params", {})
    exit_params = config.get("exit_params", {})

    if not entry_name or not exit_name:
        raise ValueError("Config must contain 'entry' and 'exit' strategy names")

    entry_instance = create_strategy_instance(entry_name, "entry", entry_params)
    exit_instance = create_strategy_instance(exit_name, "exit", exit_params)

    return entry_instance, exit_instance


def get_available_strategies() -> Dict[str, List[str]]:
    """
    获取所有可用策略列表

    Returns:
        {'entry': [...], 'exit': [...]}
    """
    return {
        "entry": list(ENTRY_STRATEGIES.keys()),
        "exit": list(EXIT_STRATEGIES.keys()),
    }


def print_available_strategies():
    """打印所有可用策略"""
    strategies = get_available_strategies()

    print("\n可用的入场策略 (Entry Strategies):")
    for i, name in enumerate(strategies["entry"], 1):
        print(f"  {i}. {name}")

    print("\n可用的出场策略 (Exit Strategies):")
    for i, name in enumerate(strategies["exit"], 1):
        print(f"  {i}. {name}")

    total_combinations = len(strategies["entry"]) * len(strategies["exit"])
    print(f"\n总共 {total_combinations} 个策略组合")


# ==================== 便捷函数 ====================


def load_entry_strategy(name: str, params: Dict[str, Any] = None):
    """加载入场策略实例"""
    return create_strategy_instance(name, "entry", params)


def load_exit_strategy(name: str, params: Dict[str, Any] = None):
    """加载出场策略实例"""
    return create_strategy_instance(name, "exit", params)


if __name__ == "__main__":
    # 测试
    print_available_strategies()

    # 测试加载
    print("\n\n测试加载策略...")
    entry = load_entry_strategy("SimpleScorerStrategy")
    exit_strat = load_exit_strategy("ATRExitStrategy")
    print(f"✓ 成功加载: {entry.__class__.__name__}, {exit_strat.__class__.__name__}")

    # 测试所有组合
    print(f"\n\n所有策略组合 ({len(get_all_strategy_combinations())}个):")
    for i, (entry_name, exit_name) in enumerate(get_all_strategy_combinations(), 1):
        print(f"  {i}. {entry_name} × {exit_name}")
