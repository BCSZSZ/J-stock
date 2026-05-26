from main import build_parser
from src.evaluation.strategy_evaluator import StrategyEvaluator
from web.api.schemas import EvaluationRunRequest


def test_evaluate_parser_accepts_capacity_regime_mode_override() -> None:
    args = build_parser().parse_args(
        ["evaluate", "--capacity-regime-mode", "enforce"]
    )

    assert args.capacity_regime_mode == "enforce"


def test_shared_evaluation_parsers_accept_ranking_strategies() -> None:
    parser = build_parser()

    for command in ["evaluate", "pos-evaluation"]:
        args = parser.parse_args([command, "--ranking-strategies", "momentum"])

        assert args.ranking_strategies == ["momentum"]


def test_shared_evaluation_parsers_accept_atr_entry_filter_mode() -> None:
    parser = build_parser()

    for command_args in [
        ["evaluate"],
        ["pos-evaluation"],
        ["walk-forward-evaluate", "--years", "2024"],
        ["replay-evaluation", "--report-file", "dummy.md"],
    ]:
        args = parser.parse_args(
            command_args + ["--entry-filter-mode", "atr", "--atr-ratio-max", "none"]
        )

        assert args.entry_filter_mode == "atr"
        assert args.atr_ratio_max == "none"


def test_web_evaluation_request_accepts_atr_entry_filter_mode() -> None:
    request = EvaluationRunRequest(entry_filter_mode="atr")

    assert request.entry_filter_mode == "atr"


def test_strategy_evaluator_prefers_capacity_regime_mode_override() -> None:
    evaluator = StrategyEvaluator(capacity_regime_mode_override="enforce")

    assert evaluator._get_capacity_regime_mode() == "enforce"
