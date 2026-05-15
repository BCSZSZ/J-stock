from main import build_parser
from src.evaluation.strategy_evaluator import StrategyEvaluator


def test_evaluate_parser_accepts_capacity_regime_mode_override() -> None:
    args = build_parser().parse_args(
        ["evaluate", "--capacity-regime-mode", "enforce"]
    )

    assert args.capacity_regime_mode == "enforce"


def test_strategy_evaluator_prefers_capacity_regime_mode_override() -> None:
    evaluator = StrategyEvaluator(capacity_regime_mode_override="enforce")

    assert evaluator._get_capacity_regime_mode() == "enforce"
