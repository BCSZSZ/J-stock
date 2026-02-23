# 大规模参数回测性能优化方案

## 执行总结

**当前性能瓶颈**：9个参数组合 × 5年 = 45次回测，耗时约5-10分钟
**优化目标**：支持100+参数组合的大规模网格搜索，耗时控制在30分钟内
**优化策略**：多线程并行 + 数据预加载 + 内存优化

---

## 阶段一：性能瓶颈分析

### 当前架构瓶颈识别

#### 1. 数据加载瓶颈（最严重）

**问题代码**：`portfolio_engine.py` L120-127
```python
for ticker in tickers:
    try:
        data = self._load_stock_data(ticker)  # 每次回测都重复加载
        all_data[ticker] = data
    except Exception as e:
        logger.warning(f"Failed to load {ticker}: {e}")
```

**瓶颈分析**：
- 每次回测都从磁盘加载所有股票的parquet文件（58只股票 × 45次回测 = 2610次磁盘IO）
- `StockDataManager.load_stock_features()` 每次都重新计算技术指标
- parquet读取虽快，但2610次IO累计时间可观

**预估占比**：40-50%的总耗时

---

#### 2. 特征计算重复（次严重）

**问题代码**：`stock_data_manager.py` - `compute_features()`
```python
def compute_features(self, code: str, overwrite: bool = False) -> bool:
    # 每次都检查features，如果缺失就重新计算完整的技术指标
    # 包括EMA, SMA, MACD, RSI, ATR, KDJ, Bollinger Bands等
```

**瓶颈分析**：
- 虽然有缓存机制（parquet），但首次加载或需要更新时计算量大
- 技术指标计算包含滚动窗口（EMA_200, SMA_200等），对长时间序列开销不小
- 拆股检测逻辑在每次计算时都执行

**预估占比**：20-30%的总耗时

---

#### 3. 串行执行（结构性问题）

**问题代码**：`eval_exit_time_bias_grid.py` L58-90
```python
for d in d_values:
    for b in b_values:
        name = build_exit_name(n, r, t, d, b)
        for period, start_date, end_date in periods:
            # 串行执行每个参数组合
            engine = PortfolioBacktestEngine(...)
            result = engine.backtest_portfolio_strategy(...)
```

**瓶颈分析**：
- 三层嵌套循环完全串行
- 不同参数组合之间无依赖关系，可完全并行
- 不同年份之间数据独立，可并行

**预估占比**：结构性瓶颈，解决后可获得N倍加速（N=CPU核心数）

---

#### 4. MarketData构建开销

**问题代码**：`market_data_builder.py` - 每次交易日都构建新对象
```python
for current_date in trading_days:  # 约250天/年 × 5年 = 1250次
    MarketDataBuilder.build_from_dataframes(...)  # 数据切片和复制
```

**瓶颈分析**：
- 每个交易日都构建新的MarketData对象
- 包含数据过滤（`df[df.index <= current_date]`）和复制
- 对于58只股票，每年1250次 × 58 = 72,500次对象创建

**预估占比**：10-15%的总耗时

---

#### 5. 次要瓶颈

- **信号生成**：每日对58只股票评估入场/出场信号（轻量级，影响小）
- **组合管理**：持仓更新、资金分配（影响小）
- **输出写入**：CSV写入（影响小，最后一次性执行）

---

## 阶段二：优化方案设计

### 方案A：多线程并行 + 数据预加载（推荐）

**核心思路**：
1. 预加载全部股票数据到内存（一次性）
2. 多线程并行执行不同参数组合的回测
3. 进程池管理（ProcessPoolExecutor）避免GIL限制

**优势**：
- 实施难度中等
- 性能提升显著（预计5-8倍）
- 兼容现有代码结构

**实施计划**：

#### Step 1: 数据预加载模块

创建 `DataCache` 类，在回测开始前一次性加载所有数据：

```python
class BacktestDataCache:
    """全局数据缓存，避免重复加载"""
    
    def __init__(self, data_root: str):
        self.data_root = Path(data_root)
        self.cache = {}  # {ticker: df_features}
        self.metadata_cache = {}
        
    def preload_tickers(self, tickers: List[str]):
        """预加载所有股票数据到内存"""
        for ticker in tickers:
            try:
                # 加载features（包含所有技术指标）
                features_path = self.data_root / 'features' / f'{ticker}_features.parquet'
                if features_path.exists():
                    df = pd.read_parquet(features_path)
                    self.cache[ticker] = df
                    
                # 加载metadata
                metadata_path = self.data_root / 'metadata' / f'{ticker}_metadata.json'
                if metadata_path.exists():
                    with open(metadata_path) as f:
                        self.metadata_cache[ticker] = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to preload {ticker}: {e}")
    
    def get_features(self, ticker: str) -> pd.DataFrame:
        """从缓存获取数据（无需磁盘IO）"""
        return self.cache.get(ticker)
```

**预期收益**：减少40-50%耗时（消除重复IO）

---

#### Step 2: 并行执行框架

改造 `eval_exit_time_bias_grid.py`，使用多进程并行：

```python
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial

def run_single_backtest(params: dict, cache_data: dict) -> dict:
    """单次回测任务（可并行执行）"""
    d, b, n, r, t, period, start_date, end_date = params.values()
    
    # 从预加载数据构建回测引擎
    engine = PortfolioBacktestEngine(
        data_root="data",
        starting_capital=5_000_000,
        max_positions=5,
        preloaded_data=cache_data  # 传入预加载数据
    )
    
    exit_strategy = MultiViewCompositeExit(...)
    result = engine.backtest_portfolio_strategy(...)
    
    return {
        'period': period,
        'D': d,
        'B': b,
        'result': result
    }

def main_parallel():
    # 1. 预加载数据
    cache = BacktestDataCache('data')
    cache.preload_tickers(tickers)
    cache_data = cache.to_shared_dict()  # 转为可序列化格式
    
    # 2. 生成任务列表
    tasks = []
    for d in d_values:
        for b in b_values:
            for period, start, end in periods:
                tasks.append({
                    'd': d, 'b': b, 'n': n, 'r': r, 't': t,
                    'period': period, 'start_date': start, 'end_date': end
                })
    
    # 3. 并行执行
    results = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(run_single_backtest, task, cache_data): task 
            for task in tasks
        }
        
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
                print(f"✓ Completed: {result['period']} D={result['D']} B={result['B']}")
            except Exception as e:
                print(f"✗ Failed: {e}")
    
    # 4. 聚合结果
    return pd.DataFrame(results)
```

**预期收益**：
- 8核CPU：理论5-7倍加速（考虑开销）
- 16核CPU：理论8-12倍加速

---

#### Step 3: 内存优化

**问题**：预加载58只股票 × 5年数据到内存，可能占用2-3GB

**优化策略**：
1. **按需切片**：只加载回测期间的数据
2. **共享内存**：使用 `multiprocessing.shared_memory` 避免数据复制
3. **数据压缩**：对不常用字段使用 `pd.Categorical` 或 float32

```python
def preload_tickers_optimized(self, tickers: List[str], start_date: str, end_date: str):
    """优化版：只加载必要的日期范围"""
    for ticker in tickers:
        df = pd.read_parquet(features_path)
        
        # 回测需要历史数据（200日均线等），预留buffer
        lookback = pd.Timestamp(start_date) - pd.Timedelta(days=300)
        df = df[(df.index >= lookback) & (df.index <= end_date)]
        
        # 内存优化：降低精度（float64 -> float32）
        float_cols = df.select_dtypes(include=['float64']).columns
        df[float_cols] = df[float_cols].astype('float32')
        
        self.cache[ticker] = df
```

**预期收益**：内存占用减少50%，加载速度提升20%

---

### 方案B：增量计算 + 结果缓存（备选）

**核心思路**：
1. 第一次回测计算完整结果并缓存
2. 后续回测检测参数差异，只重新计算受影响部分

**优势**：
- 对于连续测试非常高效
- 适合参数微调场景

**劣势**：
- 实施复杂度高
- 缓存失效场景多（数据更新、策略修改）
- 不适合大规模网格搜索

**结论**：不推荐作为首选方案

---

### 方案C：分布式计算（长期方案）

**核心思路**：
- 使用 Ray 或 Dask 分布式框架
- 多机并行，适合超大规模回测（1000+组合）

**优势**：
- 理论无上限扩展能力

**劣势**：
- 需要集群环境
- 实施成本高

**结论**：暂不考虑，但保留架构兼容性

---

## 阶段三：实施计划

### Phase 1: 数据预加载（1-2小时）

**任务清单**：
1. ✅ 创建 `src/backtest/data_cache.py` - BacktestDataCache类
2. ✅ 修改 `PortfolioBacktestEngine.__init__()` - 支持 `preloaded_data` 参数
3. ✅ 修改 `PortfolioBacktestEngine._load_stock_data()` - 优先从缓存读取
4. ✅ 单元测试：验证预加载数据的准确性

**验证标准**：
- 单次回测时间不变
- 9组合回测时间减少40%（5分钟 -> 3分钟）

---

### Phase 2: 多进程并行（2-3小时）

**任务清单**：
1. ✅ 创建 `tools/eval_exit_grid_parallel.py` - 并行版本
2. ✅ 实现任务分配逻辑（参数组合 × 年份）
3. ✅ 实现进度监控（tqdm进度条）
4. ✅ 实现异常处理和重试机制
5. ✅ 测试：9组合回测验证正确性

**验证标准**：
- 9组合回测时间减少到1分钟以内（8核CPU）
- 结果与串行版本完全一致

---

### Phase 3: 内存优化（1小时）

**任务清单**：
1. ✅ 实现日期范围过滤（减少无用数据加载）
2. ✅ 实现 float64 -> float32 转换
3. ✅ 监控内存使用（memory_profiler）
4. ✅ 测试：验证精度损失可接受

**验证标准**：
- 内存占用 < 2GB（58只股票）
- 回测结果差异 < 0.01%

---

### Phase 4: 生产验证（1小时）

**任务清单**：
1. ✅ 100组合大规模回测测试
2. ✅ 性能对比报告（串行 vs 并行）
3. ✅ 稳定性测试（连续运行5次）
4. ✅ 文档更新（README + 使用说明）

**验证标准**：
- 100组合回测 < 30分钟
- 无内存泄漏
- 无数据不一致

---

## 阶段四：性能预估

### 当前性能（串行）

| 场景 | 组合数 | 耗时 | 备注 |
|------|--------|------|------|
| D/B网格 (3×3) | 9 | ~5分钟 | 实测 |
| N/R网格 (4×5) | 20 | ~11分钟 | 推算 |
| 完整网格 (N/R/T/D/B) | 243 | ~2.2小时 | 推算 |

### 优化后性能（预估）

| 优化阶段 | 加速比 | 9组合耗时 | 100组合耗时 | 243组合耗时 |
|----------|--------|-----------|-------------|-------------|
| 原始 | 1x | 5分钟 | 56分钟 | 2.2小时 |
| + 数据预加载 | 1.8x | 2.8分钟 | 31分钟 | 1.2小时 |
| + 8核并行 | 6x | 0.5分钟 | 5.6分钟 | 13.5分钟 ⭐ |
| + 内存优化 | 7x | 0.4分钟 | 4.8分钟 | 11.6分钟 |
| + 16核并行 | 10x | 0.3分钟 | 3.4分钟 | 8.2分钟 |

**关键指标**：
- ✅ 243组合从2.2小时降至11.6分钟（11倍加速）
- ✅ 100组合控制在5分钟内
- ✅ 支持1000+组合的超大规模搜索（1小时内）

---

## 阶段五：风险评估

### 技术风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 多进程序列化开销 | 中 | 使用共享内存或pickle优化 |
| 内存不足（大规模数据） | 低 | 按需加载 + float32压缩 |
| 结果不一致（浮点精度） | 低 | 单元测试验证，容差设为0.01% |
| GIL限制（Python） | 低 | 使用multiprocessing而非threading |

### 兼容性风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 现有代码破坏 | 低 | 保留串行版本，新增并行版本 |
| Windows vs Linux差异 | 中 | 统一使用ProcessPoolExecutor |
| 依赖库版本 | 低 | requirements.txt锁定版本 |

### 维护风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 代码复杂度上升 | 中 | 清晰注释 + 架构文档 |
| 调试难度增加 | 中 | 保留详细日志，支持串行模式 |

---

## 阶段六：实施优先级

### 必须实现（MVP）

1. ✅ **数据预加载**：收益最大，风险最小
2. ✅ **多进程并行**：核心功能，必须实现

### 高优先级

3. ✅ **内存优化**：支持更大规模回测
4. ✅ **进度监控**：用户体验提升

### 中优先级

5. ⏳ **异常重试**：提升鲁棒性
6. ⏳ **结果校验**：确保数据一致性

### 低优先级

7. ⏳ **分布式扩展**：未来扩展预留
8. ⏳ **GPU加速**：技术探索

---

## 阶段七：架构改动评估

### 需要修改的文件

| 文件 | 改动程度 | 风险 | 说明 |
|------|----------|------|------|
| `src/backtest/data_cache.py` | 🆕新建 | 低 | 独立模块 |
| `src/backtest/portfolio_engine.py` | 🔧中等 | 中 | 增加preloaded_data支持 |
| `tools/eval_exit_grid_parallel.py` | 🆕新建 | 低 | 新并行版本 |
| `tools/eval_exit_time_bias_grid.py` | 不改 | 无 | 保留串行版本 |
| `src/data/stock_data_manager.py` | 🔧轻微 | 低 | 增加批量加载方法 |
| `src/evaluation/strategy_evaluator.py` | 不改 | 无 | 无依赖 |

### 向后兼容性

✅ **完全兼容**：
- 串行版本完全保留
- 新增可选参数（preloaded_data）
- 现有脚本无需修改

---

## 总结与建议

### 推荐方案

**采用方案A（多线程并行 + 数据预加载）**：
- 实施周期：1个工作日
- 性能提升：6-10倍
- 风险等级：低
- 维护成本：低

### 实施步骤

1. **今天**：实施Phase 1（数据预加载）
2. **今天**：实施Phase 2（多进程并行）
3. **明天**：实施Phase 3-4（优化和验证）

### 投入产出比

- **投入**：8小时开发 + 2小时测试
- **产出**：
  - 243组合回测：2.2小时 -> 11.6分钟
  - 支持1000+组合大规模搜索
  - 显著提升研究效率

### 立即开始

**第一步**：创建 `src/backtest/data_cache.py`，实现数据预加载

**是否开始实施？** 我已准备好完整的代码实现。
