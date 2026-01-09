"""
Signal Ranker - 买入信号优先级排序
Ranks buy signals when multiple stocks trigger simultaneously
"""
from typing import List, Dict, Tuple
from ..analysis.signals import TradingSignal, SignalAction, MarketData


class SignalRanker:
    """
    当多个股票同时发出买入信号时，决定优先级
    
    支持多种排序策略:
    1. simple_score: 按综合得分排序
    2. confidence_weighted: 按信心度加权得分
    3. risk_adjusted: 按风险调整后得分（得分/波动率）
    """
    
    def __init__(
        self,
        method: str = "simple_score",
        score_weight: float = 0.6,
        confidence_weight: float = 0.2,
        volatility_weight: float = 0.2
    ):
        """
        Args:
            method: 排序方法 ("simple_score", "confidence_weighted", "risk_adjusted")
            score_weight: 得分权重（仅用于composite方法）
            confidence_weight: 信心度权重
            volatility_weight: 波动率权重（负向）
        """
        self.method = method
        self.score_weight = score_weight
        self.confidence_weight = confidence_weight
        self.volatility_weight = volatility_weight
    
    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData]
    ) -> List[Tuple[str, TradingSignal, float]]:
        """
        对买入信号进行排序
        
        Args:
            signals: {ticker: TradingSignal} 字典
            market_data_dict: {ticker: MarketData} 字典
            
        Returns:
            排序后的列表: [(ticker, signal, priority_score), ...]
            按priority_score降序排列
        """
        scored_signals = []
        
        for ticker, signal in signals.items():
            # 只处理买入信号
            if signal.action != SignalAction.BUY:
                continue
            
            # 计算优先级分数
            priority = self._calculate_priority(ticker, signal, market_data_dict)
            scored_signals.append((ticker, signal, priority))
        
        # 按优先级降序排序
        scored_signals.sort(key=lambda x: x[2], reverse=True)
        
        return scored_signals
    
    def _calculate_priority(
        self,
        ticker: str,
        signal: TradingSignal,
        market_data_dict: Dict[str, MarketData]
    ) -> float:
        """
        计算单个信号的优先级分数
        
        Returns:
            优先级分数（越高越优先）
        """
        # 基础分数
        base_score = signal.metadata.get('score', 50.0)
        confidence = signal.confidence
        
        # 获取市场数据
        market_data = market_data_dict.get(ticker)
        
        if self.method == "simple_score":
            # 方法1: 简单按得分排序
            return base_score
        
        elif self.method == "confidence_weighted":
            # 方法2: 得分 × 信心度
            return base_score * confidence
        
        elif self.method == "risk_adjusted":
            # 方法3: 风险调整得分
            if market_data is None:
                return base_score
            
            df = market_data.df_features
            if df.empty or 'ATR' not in df.columns or 'Close' not in df.columns:
                return base_score
            
            # 计算波动率（ATR/Close）
            atr = df['ATR'].iloc[-1]
            close = df['Close'].iloc[-1]
            
            if close == 0:
                return base_score
            
            volatility = atr / close
            
            # 得分除以波动率（低波动更优先）
            risk_adjusted = base_score / (1 + volatility * 10)
            
            return risk_adjusted
        
        elif self.method == "composite":
            # 方法4: 综合评分
            priority = base_score * self.score_weight
            priority += confidence * 100 * self.confidence_weight
            
            # 波动率惩罚
            if market_data is not None:
                df = market_data.df_features
                if not df.empty and 'ATR' in df.columns and 'Close' in df.columns:
                    atr = df['ATR'].iloc[-1]
                    close = df['Close'].iloc[-1]
                    if close > 0:
                        volatility = atr / close
                        # 低波动率加分
                        volatility_bonus = (1 - min(volatility * 10, 1)) * 100
                        priority += volatility_bonus * self.volatility_weight
            
            return priority
        
        else:
            # 默认：简单得分
            return base_score
    
    def get_top_n_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        n: int
    ) -> List[Tuple[str, TradingSignal, float]]:
        """
        获取优先级最高的N个信号
        
        Args:
            signals: 信号字典
            market_data_dict: 市场数据字典
            n: 返回前N个
            
        Returns:
            前N个信号
        """
        ranked = self.rank_buy_signals(signals, market_data_dict)
        return ranked[:n]
