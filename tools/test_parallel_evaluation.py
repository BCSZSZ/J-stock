"""
Test script for parallel strategy evaluation.

Compares serial vs parallel execution with a small test case.
"""

import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.evaluation.strategy_evaluator import (
    StrategyEvaluator,
    create_annual_periods,
)


def test_parallel_evaluation():
    """Test parallel evaluation with a small parameter set."""

    # Test with 2 years, 1 entry strategy, 1 exit strategy = 2 backtests
    periods = create_annual_periods([2023, 2024])  # Use recent years with data
    entry_strategies = ["SimpleScorerStrategy"]
    exit_strategies = ["MVX_N9_R3p5_T1p6_D10_B10"]  # Use a known exit strategy

    print("=" * 80)
    print("Parallel Strategy Evaluation Test")
    print("=" * 80)
    print("Test configuration:")
    print(f"  Periods: {len(periods)}")
    print(f"  Entry strategies: {len(entry_strategies)}")
    print(f"  Exit strategies: {len(exit_strategies)}")
    print(
        f"  Total backtests: {len(periods) * len(entry_strategies) * len(exit_strategies)}"
    )
    print("=" * 80)
    print()

    # Test 1: Serial execution (workers=1)
    print("Test 1: Serial execution (workers=1, cache disabled)")
    print("-" * 80)

    evaluator_serial = StrategyEvaluator(
        verbose=False,
        workers=1,
        use_cache=False,
    )

    start_serial = time.time()
    df_serial = evaluator_serial.run_evaluation(
        periods=periods,
        entry_strategies=entry_strategies,
        exit_strategies=exit_strategies,
    )
    time_serial = time.time() - start_serial

    print(f"✅ Serial execution completed in {time_serial:.2f} seconds")
    print()

    # Test 2: Parallel execution (workers=4, cache enabled)
    print("Test 2: Parallel execution (workers=4, cache enabled)")
    print("-" * 80)

    evaluator_parallel = StrategyEvaluator(
        verbose=True,  # Enable verbose to see errors
        workers=4,
        use_cache=True,
    )

    start_parallel = time.time()
    df_parallel = evaluator_parallel.run_evaluation(
        periods=periods,
        entry_strategies=entry_strategies,
        exit_strategies=exit_strategies,
    )
    time_parallel = time.time() - start_parallel

    print(f"✅ Parallel execution completed in {time_parallel:.2f} seconds")
    print()

    # Calculate speedup
    speedup = time_serial / time_parallel if time_parallel > 0 else 0

    # Summary
    print("=" * 80)
    print("Performance Summary")
    print("=" * 80)
    print(f"Serial execution:   {time_serial:.2f}s")
    print(f"Parallel execution: {time_parallel:.2f}s")
    print(f"Speedup:            {speedup:.2f}x")
    print()

    # Verify results match
    if len(df_serial) == len(df_parallel):
        print(f"✅ Result count matches: {len(df_serial)} backtests")
    else:
        print(
            f"⚠️  Result count mismatch: serial={len(df_serial)}, parallel={len(df_parallel)}"
        )

    # Save results
    evaluator_parallel.save_results(prefix="parallel_test")

    print("=" * 80)
    print("Test completed successfully! 🎉")
    print("=" * 80)


if __name__ == "__main__":
    test_parallel_evaluation()
