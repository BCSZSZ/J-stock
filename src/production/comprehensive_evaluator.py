"""
Comprehensive Stock Evaluator

Evaluates all monitored stocks against all configured strategies,
producing a complete evaluation table for reporting.
"""

import pandas as pd
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime

from ..analysis.signals import MarketData, SignalAction
from ..data.stock_data_manager import StockDataManager
from ..utils.strategy_loader import load_entry_strategy
from ..data.market_data_builder import MarketDataBuilder
from ..signal_generator import generate_signal_v2


@dataclass
class StockEvaluation:
    """Single stock evaluation against one strategy"""
    ticker: str
    ticker_name: str
    current_price: float
    strategy_name: str
    
    # Entry signal info
    signal_action: str  # "BUY", "HOLD", "SELL"
    score: float  # 0-100
    confidence: float  # 0-1
    reason: str
    
    # Additional technical data
    metadata: Dict = field(default_factory=dict)


@dataclass
class StockComprehensiveEvaluation:
    """Complete evaluation for one stock (all strategies)"""
    ticker: str
    ticker_name: str
    current_price: float
    latest_date: str
    
    # Evaluations from each strategy
    evaluations: Dict[str, StockEvaluation] = field(default_factory=dict)  # strategy_name -> StockEvaluation
    
    # Indicators
    technical_indicators: Dict = field(default_factory=dict)  # EMA_20, RSI, MACD, etc.
    
    @property
    def overall_signal(self) -> str:
        """Determine overall recommendation based on evaluations"""
        buy_count = sum(1 for e in self.evaluations.values() if e.signal_action == "BUY")
        total_strategies = len(self.evaluations)
        
        if buy_count == total_strategies:
            return "STRONG_BUY"
        elif buy_count > total_strategies / 2:
            return "BUY"
        elif buy_count > 0:
            return "WEAK_BUY"
        else:
            return "HOLD"


class ComprehensiveEvaluator:
    """
    Evaluates all monitored stocks against all configured entry strategies.
    """
    
    def __init__(
        self,
        data_manager: StockDataManager,
        strategies_config: List[Dict]  # [{"name": "SimpleScorerStrategy"}, {"name": "IchimokuStochStrategy"}]
    ):
        """
        Initialize evaluator.
        
        Args:
            data_manager: StockDataManager instance
            strategies_config: List of strategy configs with 'name' field
        """
        self.data_manager = data_manager
        self.strategies_config = strategies_config
        
        # Load strategy instances
        self.strategies = {}
        for cfg in strategies_config:
            strategy_name = cfg.get('name')
            if strategy_name:
                try:
                    self.strategies[strategy_name] = load_entry_strategy(strategy_name)
                except Exception as e:
                    print(f"Warning: Failed to load strategy {strategy_name}: {e}")
    
    def evaluate_all_stocks(
        self,
        tickers: List[str],
        current_date: Optional[str] = None,
        verbose: bool = False
    ) -> Dict[str, StockComprehensiveEvaluation]:
        """
        Evaluate all stocks against all strategies.
        
        Args:
            tickers: List of stock tickers (e.g., ["8035", "8306", ...])
            current_date: Evaluation date (default: latest available)
            verbose: Print progress
        
        Returns:
            Dict mapping ticker to StockComprehensiveEvaluation
        """
        results = {}
        
        for idx, ticker in enumerate(tickers, 1):
            if verbose:
                print(f"  [{idx}/{len(tickers)}] Evaluating {ticker}...", end=" ", flush=True)
            
            try:
                # 使用 MarketDataBuilder 统一加载和标准化数据
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=self.data_manager,
                    ticker=ticker,
                    current_date=pd.Timestamp.now()
                )
                
                if market_data is None:
                    if verbose:
                        print("❌ (no data)")
                    continue
                
                # 从 MarketData 对象提取信息
                df_features = market_data.df_features
                metadata = market_data.metadata
                latest_date = market_data.current_date
                latest_row = df_features.iloc[-1] if not df_features.empty else None
                current_price = float(latest_row['Close']) if latest_row is not None else 0
                ticker_name = metadata.get('company_name', ticker) if metadata else ticker
                
                # Create comprehensive evaluation
                comp_eval = StockComprehensiveEvaluation(
                    ticker=ticker,
                    ticker_name=ticker_name,
                    current_price=current_price,
                    latest_date=latest_date.strftime("%Y-%m-%d")
                )
                
                # Extract technical indicators
                comp_eval.technical_indicators = {
                    'EMA_20': float(latest_row.get('EMA_20', 0)) if latest_row is not None else 0,
                    'EMA_50': float(latest_row.get('EMA_50', 0)) if latest_row is not None else 0,
                    'EMA_200': float(latest_row.get('EMA_200', 0)) if latest_row is not None else 0,
                    'RSI': float(latest_row.get('RSI', 0)) if latest_row is not None else 0,
                    'ATR': float(latest_row.get('ATR', 0)) if latest_row is not None else 0,
                    'Volume': float(latest_row.get('Volume', 0)) if latest_row is not None else 0,
                }
                
                # Evaluate with each strategy
                for strategy_name, strategy in self.strategies.items():
                    try:
                        entry_signal = generate_signal_v2(
                            market_data=market_data,
                            entry_strategy=strategy
                        )
                        
                        # Extract score and confidence
                        score = float(entry_signal.metadata.get('score', 0)) if entry_signal.metadata else 0
                        confidence = float(entry_signal.confidence) if entry_signal.confidence else 0
                        
                        # Determine action
                        if entry_signal.action == SignalAction.BUY:
                            signal_action = "BUY"
                        elif entry_signal.action == SignalAction.SELL:
                            signal_action = "SELL"
                        else:
                            signal_action = "HOLD"
                        
                        # Create evaluation
                        eval = StockEvaluation(
                            ticker=ticker,
                            ticker_name=ticker_name,
                            current_price=current_price,
                            strategy_name=strategy_name,
                            signal_action=signal_action,
                            score=score,
                            confidence=confidence,
                            reason=("; ".join(entry_signal.reasons) if entry_signal.reasons else ""),
                            metadata=entry_signal.metadata or {}
                        )
                        
                        comp_eval.evaluations[strategy_name] = eval
                        
                    except Exception as e:
                        if verbose:
                            print(f"  (strategy {strategy_name} error: {str(e)[:30]})", end=" ")
                        continue
                
                results[ticker] = comp_eval
                if verbose:
                    print("✅")
                    
            except Exception as e:
                if verbose:
                    print(f"❌ ({str(e)[:30]})")
                continue
        
        return results
