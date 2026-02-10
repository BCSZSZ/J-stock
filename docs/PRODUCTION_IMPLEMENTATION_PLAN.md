# Daily Production Trading System - 实装计划

**日期**: 2026-01-21  
**状态**: 待确认后实施

---

## 📋 用户需求确认

### ✅ 已确认需求

1. **命名方案**: 选择方案 A (`python main.py trade prepare/record`)
2. **Q1 - 报告保存**: ✅ 一定要保存文件
3. **Q2 - 重复运行**: ✅ 无脑覆盖（确定数据生成确定信号）
4. **Q3 - 买入建议**: ✅ 显示所有信号 + 考虑现金余额提示
5. **多策略组支持**: ✅ 必须实现

### 🆕 新增需求：多策略组支持

**核心场景**:

```
策略组A: SimpleScorerStrategy + LayeredExitStrategy
  - 初始资金: ¥2,000,000
  - 持仓管理: 独立跟踪

策略组B: EnhancedScorerStrategy + BollingerDynamicExit
  - 初始资金: ¥1,000,000
  - 持仓管理: 独立跟踪
```

**关键点**:

1. 每个策略组有独立的资金池
2. 每个策略组的持仓单独记录（ticker + 策略组ID）
3. 退场时使用该策略组对应的 exit_strategy
4. 同一支股票可以在不同策略组同时持有

---

## 🎯 架构设计

### 配置文件结构（config.json）

```json
{
  "production": {
    "monitor_list_file": "data/production_monitor_list.json",
    "state_file": "production_state.json",
    "signal_file_pattern": "signals_{date}.json",
    "report_file_pattern": "trade_report_{date}.md",
    "history_file": "trade_history.json",
    "max_positions_per_group": 5,
    "max_position_pct": 0.3,
    "buy_threshold": 65,

    "strategy_groups": [
      {
        "id": "group_a",
        "name": "积极进取组",
        "initial_capital": 2000000,
        "entry_strategy": "SimpleScorerStrategy",
        "exit_strategy": "LayeredExitStrategy"
      },
      {
        "id": "group_b",
        "name": "稳健防守组",
        "initial_capital": 1000000,
        "entry_strategy": "EnhancedScorerStrategy",
        "exit_strategy": "BollingerDynamicExit"
      }
    ]
  }
}
```

**字段说明**:

- `strategy_groups[]`: 策略组列表
  - `id`: 策略组唯一标识（不可重复）
  - `name`: 策略组显示名称（中文可读）
  - `initial_capital`: 该策略组初始资金
  - `entry_strategy`: 入场策略类名
  - `exit_strategy`: 出场策略类名

---

### 状态文件结构（production_state.json）

```json
{
  "last_updated": "2026-01-21T20:30:00",
  "strategy_groups": [
    {
      "id": "group_a",
      "name": "积极进取组",
      "cash": 1500000,
      "positions": [
        {
          "ticker": "8035",
          "entry_price": 31500,
          "entry_date": "2025-12-05",
          "entry_score": 75.2,
          "quantity": 100,
          "peak_price": 37200
        },
        {
          "ticker": "7974",
          "entry_price": 5820,
          "entry_date": "2026-01-08",
          "entry_score": 68.5,
          "quantity": 200,
          "peak_price": 6100
        }
      ]
    },
    {
      "id": "group_b",
      "name": "稳健防守组",
      "cash": 950000,
      "positions": [
        {
          "ticker": "8035",
          "entry_price": 32000,
          "entry_date": "2026-01-10",
          "entry_score": 72.1,
          "quantity": 50,
          "peak_price": 37200
        }
      ]
    }
  ]
}
```

**关键点**:

- 支持同一股票在不同策略组持仓（如 8035 在两个组都有）
- 每个策略组独立管理现金和持仓
- 持仓记录 entry_score（用于后续分析）

---

### 信号文件结构（signals_YYYY-MM-DD.json）

```json
{
  "date": "2026-01-21",
  "generated_at": "2026-01-21T20:30:00",
  "strategy_groups": [
    {
      "group_id": "group_a",
      "group_name": "积极进取组",
      "entry_strategy": "SimpleScorerStrategy",
      "exit_strategy": "LayeredExitStrategy",
      "cash_available": 1500000,
      "buy_signals": [
        {
          "ticker": "4568",
          "score": 78.5,
          "signal_strength": "STRONG_BUY",
          "current_price": 5230,
          "suggested_quantity": 100,
          "estimated_cost": 523000,
          "reason": "技术面强势，机构持续买入",
          "breakdown": {
            "technical": 85.0,
            "institutional": 75.0,
            "fundamental": 80.0,
            "volatility": 72.0
          }
        }
      ],
      "sell_signals": [
        {
          "ticker": "7974",
          "action": "SELL_50%",
          "urgency": "MEDIUM",
          "current_price": 6100,
          "current_quantity": 200,
          "suggested_quantity": 100,
          "reason": "技术面走弱",
          "profit_loss_pct": 4.8,
          "holding_days": 13
        }
      ]
    },
    {
      "group_id": "group_b",
      "group_name": "稳健防守组",
      "entry_strategy": "EnhancedScorerStrategy",
      "exit_strategy": "BollingerDynamicExit",
      "cash_available": 950000,
      "buy_signals": [...],
      "sell_signals": [...]
    }
  ]
}
```

---

### 报告文件示例（trade_report_2026-01-21.md）

```markdown
# 交易策略报告

**日期**: 2026-01-21  
**生成时间**: 2026-01-21 20:30:00

---

## 策略组 A: 积极进取组

**策略**: SimpleScorerStrategy → LayeredExitStrategy  
**可用现金**: ¥1,500,000

### 📊 当前持仓（2只）

| 股票 | 数量 | 入场价  | 当前价  | 盈亏%  | 持有天数 | 入场日期   |
| ---- | ---- | ------- | ------- | ------ | -------- | ---------- |
| 8035 | 100  | ¥31,500 | ¥37,200 | +18.1% | 47天     | 2025-12-05 |
| 7974 | 200  | ¥5,820  | ¥6,100  | +4.8%  | 13天     | 2026-01-08 |

**总市值**: ¥4,940,000  
**浮动盈亏**: +¥680,000 (+16.0%)

---

### 📈 买入信号（2个）

#### 1. 4568 第一三共 - 78.5分 (STRONG_BUY)

- **当前价**: ¥5,230
- **建议数量**: 100股
- **预估成本**: ¥523,000 ✅ 现金充足
- **理由**: 技术面强势，机构持续买入，ROE改善
- **分数详情**:
  - 技术面: 85.0
  - 机构流: 75.0
  - 基本面: 80.0
  - 波动性: 72.0

#### 2. 7011 三菱重工 - 71.2分 (BUY)

- **当前价**: ¥2,180
- **建议数量**: 200股
- **预估成本**: ¥436,000 ✅ 现金充足
- **理由**: EMA金叉，防卫订单增长

**💰 现金余额检查**: ¥1,500,000 - ¥959,000 = ¥541,000 剩余

---

### 🔴 卖出建议（1个）

#### 1. 7974 任天堂 - SELL_50% (MEDIUM)

- **当前价**: ¥6,100
- **持有数量**: 200股
- **建议卖出**: 100股
- **预估收入**: ¥610,000
- **盈亏**: +4.8% (持有13天)
- **理由**: 技术面走弱，跌破EMA20

---

## 策略组 B: 稳健防守组

**策略**: EnhancedScorerStrategy → BollingerDynamicExit  
**可用现金**: ¥950,000

### 📊 当前持仓（1只）

| 股票 | 数量 | 入场价  | 当前价  | 盈亏%  | 持有天数 | 入场日期   |
| ---- | ---- | ------- | ------- | ------ | -------- | ---------- |
| 8035 | 50   | ¥32,000 | ¥37,200 | +16.3% | 11天     | 2026-01-10 |

**总市值**: ¥1,860,000  
**浮动盈亏**: +¥260,000 (+16.3%)

---

### 📈 买入信号（3个）

...

### 🔴 卖出建议（0个）

无卖出建议

---

## 📋 汇总统计

| 策略组     | 现金           | 持仓市值       | 总资产         | 浮动盈亏   |
| ---------- | -------------- | -------------- | -------------- | ---------- |
| 积极进取组 | ¥1,500,000     | ¥4,940,000     | ¥6,440,000     | +16.0%     |
| 稳健防守组 | ¥950,000       | ¥1,860,000     | ¥2,810,000     | +16.3%     |
| **合计**   | **¥2,450,000** | **¥6,800,000** | **¥9,250,000** | **+16.1%** |

---

✅ 信号文件已保存: `signals_2026-01-21.json`
```

---

## 🔧 技术实现要点

### 1. 模块结构

```
src/production/
├── __init__.py
├── state_manager.py          # 状态管理（加载/保存/更新）
├── signal_generator.py       # 信号生成（调用 scorer/exiter）
├── report_builder.py         # 报告生成（Markdown格式）
└── trade_recorder.py         # 交易录入（交互式CLI）
```

### 2. 关键类设计

#### StateManager

```python
class StrategyGroupState:
    id: str
    name: str
    cash: float
    positions: List[Position]

    def get_position(self, ticker: str) -> Optional[Position]
    def add_position(self, ticker, price, quantity, score, date) -> None
    def update_position(self, ticker, price, quantity) -> None
    def remove_position(self, ticker) -> None

class ProductionState:
    strategy_groups: List[StrategyGroupState]
    last_updated: datetime

    def get_group(self, group_id: str) -> StrategyGroupState
    def load_from_file(path: str) -> ProductionState
    def save_to_file(self, path: str) -> None
    def initialize_from_config(config: dict) -> ProductionState
```

#### SignalGenerator

```python
class SignalGenerator:
    def __init__(self, data_manager, state_manager):
        self.data_manager = data_manager
        self.state_manager = state_manager

    def generate_signals_for_group(
        self,
        group: StrategyGroupState,
        entry_strategy: BaseScorer,
        exit_strategy: BaseExiter,
        monitor_tickers: List[str],
        buy_threshold: float
    ) -> Tuple[List[BuySignal], List[SellSignal]]:
        """为单个策略组生成信号"""
        ...
```

---

## 📝 待确认问题清单

### 🔴 高优先级（影响架构）

**Q1: 策略组之间的股票冲突处理**

- **场景**: 策略组A和B都对同一股票（如7974）生成买入信号
- **选项**:
  - A: 允许（两个组可以同时持有同一股票）✅ 推荐
  - B: 禁止（只能一个组持有）
  - C: 提示警告，由用户决定

**Q2: record 命令的策略组指定**

- **场景**: 用户买入/卖出时，需要指定是哪个策略组的操作
- **选项**:
  - A: 交互时询问：`请选择策略组: 1) group_a  2) group_b`
  - B: 命令行参数：`python main.py trade record --group group_a`
  - C: 自动匹配：如果持仓只在一个组，自动识别

**Q3: 部分卖出的 entry_price 处理**

- **场景**: 持有100股，卖出50股，剩余50股的 entry_price 如何处理
- **选项**:
  - A: FIFO（保持原价）
  - B: 加权平均（如有多次买入）
  - ✅ **推荐 A**（简单，符合会计惯例）

### 🟡 中优先级（影响用户体验）

**Q4: 买入建议的现金余额提示方式**

- **当前设计**: 显示所有信号 + 每个信号标注是否现金充足
- **是否需要调整**?
  - A: 保持当前设计 ✅ 推荐
  - B: 只显示现金范围内的信号
  - C: 按分数排序，标注"优先推荐前N个"

**Q5: 报告文件格式**

- **当前设计**: Markdown 格式
- **是否需要其他格式**?
  - A: 仅 Markdown ✅ 推荐
  - B: 同时生成 HTML（浏览器查看）
  - C: 同时生成 Excel（用于记账）

**Q6: 错误输入处理（record 命令）**

- **场景**: 用户输入卖出数量 > 持仓数量
- **选项**:
  - A: 立即报错，重新输入该条 ✅ 推荐
  - B: 完成所有输入后统一校验
  - C: 支持 `undo` 撤销上一条

### 🟢 低优先级（可后续迭代）

**Q7: 历史交易文件的回测支持**

- **未来功能**: 基于 trade_history.json 回测实际交易表现
- **当前**: 仅记录，不做分析
- **确认**: 是否需要预留字段？

**Q8: 策略组动态增删**

- **场景**: 用户想增加策略组C或删除策略组B
- **选项**:
  - A: 直接修改 config.json + production_state.json ✅ 当前设计
  - B: 提供 CLI 命令管理策略组
  - C: 不支持（重新初始化）

---

## 🎯 实现步骤（确认后执行）

### Phase 1: 配置和数据结构（1-2小时）

- [ ] 设计多策略组 config.json 结构
- [ ] 设计多策略组 production_state.json 结构
- [ ] 设计多策略组 signals.json 结构
- [ ] 创建示例配置文件

### Phase 2: 状态管理模块（2-3小时）

- [ ] 实现 `StrategyGroupState` 类
- [ ] 实现 `ProductionState` 类
- [ ] 实现状态加载/保存逻辑
- [ ] 实现首次初始化逻辑
- [ ] 单元测试

### Phase 3: 信号生成模块（2-3小时）

- [ ] 实现 `SignalGenerator` 类
- [ ] 实现买入信号生成（多策略组）
- [ ] 实现卖出信号生成（多策略组）
- [ ] 数据加载复用现有 pipeline
- [ ] 单元测试

### Phase 4: 报告生成模块（1-2小时）

- [ ] 实现 `ReportBuilder` 类
- [ ] 实现 Markdown 报告模板
- [ ] 实现多策略组汇总表
- [ ] 实现现金余额检查提示

### Phase 5: CLI 实现 - prepare 命令（2-3小时）

- [ ] main.py 添加 `trade` 命令
- [ ] 实现 `trade prepare` 子命令
- [ ] 集成状态管理、信号生成、报告生成
- [ ] 终端输出美化
- [ ] 测试完整流程

### Phase 6: CLI 实现 - record 命令（3-4小时）

- [ ] 实现 `TradeRecorder` 类
- [ ] 实现交互式买入输入
- [ ] 实现交互式卖出输入
- [ ] 实现策略组选择逻辑
- [ ] 实现状态更新和历史追加
- [ ] 实现输入校验
- [ ] 测试边界情况

### Phase 7: 集成测试（1-2小时）

- [ ] 测试首次运行 prepare
- [ ] 测试后续运行 prepare（覆盖）
- [ ] 测试 record 买入
- [ ] 测试 record 卖出
- [ ] 测试多策略组独立性
- [ ] 测试同股票多策略组持仓

### Phase 8: 文档和部署（1小时）

- [ ] 更新 README
- [ ] 编写使用指南
- [ ] 准备示例数据
- [ ] 部署到生产环境

**总预计时间**: 13-20 小时

---

## 🚨 风险和复杂度评估

### 高复杂度部分

1. **多策略组状态管理**: 需要仔细设计数据结构，避免混乱
2. **record 命令的策略组识别**: 用户体验需要友好
3. **同股票多策略组持仓**: 逻辑复杂，需要充分测试

### 可简化方案（如实现困难）

#### 简化方案 1: 单策略组先行

- 先实现单策略组版本
- 验证完整流程可行性
- 再扩展到多策略组

#### 简化方案 2: 策略组 ID 显式输入

```bash
# record 时明确指定策略组
python main.py trade record --group group_a
```

避免交互式选择的复杂度

#### 简化方案 3: 禁止同股票多策略组

- 简化逻辑：同一股票只能在一个策略组持有
- 降低数据管理复杂度

---

## ✅ 下一步行动

1. **用户确认以上待定问题**（Q1-Q8）
2. **选择实现方案**（完整版 vs 简化版）
3. **开始 Phase 1 实现**

---

**注意事项**:

- 该计划假设多策略组为核心功能
- 如果实现过程中遇到困难，可以随时调整为简化方案
- 建议先实现 Phase 1-2，验证架构可行性后再继续
