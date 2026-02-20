from src.evaluation import StrategyEvaluator
from src.utils.strategy_loader import EXIT_STRATEGIES
from src.cli.common import load_config


def main():
    exit_strategies = sorted([name for name in EXIT_STRATEGIES.keys() if name.startswith('MVX_')])
    print('exit_strategy_count', len(exit_strategies))

    periods = [('PhaseA_3M', '2025-10-01', '2025-12-31')]
    config = load_config()

    evaluator = StrategyEvaluator(
        data_root='data',
        output_dir=r'G:\My Drive\AI-Stock-Sync\strategy_evaluation',
        verbose=False,
        overlay_config=config,
    )

    df = evaluator.run_evaluation(
        periods=periods,
        entry_strategies=['MACDCrossoverStrategy'],
        exit_strategies=exit_strategies,
    )

    print('results_rows', len(df))
    print('unique_exit', df['exit_strategy'].nunique() if not df.empty else 0)
    files = evaluator.save_results(prefix='phaseA_mvx_3m')
    print('files', files)


if __name__ == '__main__':
    main()
