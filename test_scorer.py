"""
Test script for Stock Scoring Strategies
Compares Simple vs Enhanced strategies across all tickers
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import json
from src.analysis.scorer import SimpleScorer, EnhancedScorer

# All target tickers
TICKERS = ["8035", "8306", "7974", "7011", "6861", "8058", "6501", "4063", "7203", "4568", "6098"]

print(f"\n{'='*80}")
print("Stock Scoring Strategy Comparison")
print(f"{'='*80}\n")

# Initialize both scorers
simple_scorer = SimpleScorer()
enhanced_scorer = EnhancedScorer()

simple_results = []
enhanced_results = []

print("Evaluating all tickers with both strategies...\n")

for ticker in TICKERS:
    try:
        df_features = pd.read_parquet(f'data/features/{ticker}_features.parquet')
        df_trades = pd.read_parquet(f'data/raw_trades/{ticker}_trades.parquet')
        df_financials = pd.read_parquet(f'data/raw_financials/{ticker}_financials.parquet')
        
        with open(f'data/metadata/{ticker}_metadata.json', 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        # Score with both strategies
        simple_result = simple_scorer.evaluate(ticker, df_features, df_trades, df_financials, metadata)
        enhanced_result = enhanced_scorer.evaluate(ticker, df_features, df_trades, df_financials, metadata)
        
        simple_results.append(simple_result)
        enhanced_results.append(enhanced_result)
        
        print(f"[OK] {ticker}: Simple={simple_result.total_score:5.1f} | Enhanced={enhanced_result.total_score:5.1f}")
        
    except Exception as e:
        print(f"[ERR] {ticker}: {e}")

print(f"\n{'='*80}")
print(f"Successfully tested {len(simple_results)}/{len(TICKERS)} tickers")
print(f"{'='*80}\n")

# Comparison Analysis
print("STRATEGY COMPARISON:")
print(f"{'-'*80}")
print(f"{'Ticker':<8} | {'Simple':<10} | {'Enhanced':<12} | {'Delta':<8} | Signal Change")
print(f"{'-'*80}")

for s, e in zip(simple_results, enhanced_results):
    delta = e.total_score - s.total_score
    signal_change = "" if s.signal_strength == e.signal_strength else f"{s.signal_strength} -> {e.signal_strength}"
    print(f"{s.ticker:<8} | {s.total_score:5.1f}/100 | {e.total_score:5.1f}/100 | {delta:+6.1f} | {signal_change}")

print(f"\n{'='*80}")
print("SIMPLE STRATEGY RANKINGS:")
print(f"{'-'*80}")
simple_ranked = sorted(simple_results, key=lambda x: x.total_score, reverse=True)
for i, r in enumerate(simple_ranked, 1):
    flags = f" [!{','.join(r.risk_flags)}]" if r.risk_flags else ""
    print(f"{i:2d}. {r.ticker} | {r.total_score:5.1f}/100 | {r.signal_strength:12s} | "
          f"T:{r.breakdown['Technical']:4.0f} I:{r.breakdown['Institutional']:4.0f} "
          f"F:{r.breakdown['Fundamental']:4.0f} V:{r.breakdown['Volatility']:4.0f}{flags}")

print(f"\n{'='*80}")
print("ENHANCED STRATEGY RANKINGS:")
print(f"{'-'*80}")
enhanced_ranked = sorted(enhanced_results, key=lambda x: x.total_score, reverse=True)
for i, r in enumerate(enhanced_ranked, 1):
    flags = f" [!{','.join(r.risk_flags)}]" if r.risk_flags else ""
    print(f"{i:2d}. {r.ticker} | {r.total_score:5.1f}/100 | {r.signal_strength:12s} | "
          f"T:{r.breakdown['Technical']:4.0f} I:{r.breakdown['Institutional']:4.0f} "
          f"F:{r.breakdown['Fundamental']:4.0f} V:{r.breakdown['Volatility']:4.0f}{flags}")

print(f"\n{'='*80}")
print("STATISTICS:")
print(f"{'='*80}")

simple_avg = sum(r.total_score for r in simple_results) / len(simple_results)
enhanced_avg = sum(r.total_score for r in enhanced_results) / len(enhanced_results)

simple_buys = sum(1 for r in simple_results if 'BUY' in r.signal_strength)
enhanced_buys = sum(1 for r in enhanced_results if 'BUY' in r.signal_strength)

print(f"Average Score:")
print(f"  Simple:   {simple_avg:.2f}/100")
print(f"  Enhanced: {enhanced_avg:.2f}/100")
print(f"  Delta:    {enhanced_avg - simple_avg:+.2f}")

print(f"\nBuy Signals:")
print(f"  Simple:   {simple_buys}/{len(simple_results)} stocks")
print(f"  Enhanced: {enhanced_buys}/{len(enhanced_results)} stocks")

print(f"\n{'='*80}")
print("Legend: T=Technical, I=Institutional, F=Fundamental, V=Volatility")
print(f"{'='*80}\n")
