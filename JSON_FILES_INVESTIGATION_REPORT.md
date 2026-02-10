# JSON文件用途调查报告

**调查日期**: 2026-01-22  
**调查范围**: 根目录下所有JSON文件  
**目的**: 确定哪些文件正在使用，哪些可能是废弃文件

---

## 📊 调查结果总览

| 文件名                    | 状态        | 用途                     | 是否在代码中使用 | 建议操作          |
| ------------------------- | ----------- | ------------------------ | ---------------- | ----------------- |
| **config.json**           | ✅ 活跃     | 系统主配置文件           | 是               | **保留**          |
| **production_state.json** | ✅ 活跃     | 生产环境状态持久化       | 是               | **保留**          |
| **trade_history.json**    | ✅ 活跃     | 交易历史记录             | 是               | **保留**          |
| **all_strategies.json**   | ⚠️ 工具生成 | 策略组合列表（工具输出） | 否               | 移至output/       |
| **STRATEGY_CATALOG.json** | ⚠️ 文档性质 | 策略说明文档（供AI参考） | 否               | 移至docs/         |
| **strategy_presets.json** | ⚠️ 废弃     | 旧版策略预设模板         | 否               | 移至docs/archive/ |

---

## 📁 详细分析

### 1️⃣ **config.json** - 系统主配置文件 ✅

**状态**: **活跃使用中**

**用途**:

- 系统全局配置文件
- 所有CLI命令的默认配置来源
- 包含：回测参数、组合配置、生产环境配置、默认策略等

**代码引用**:

```python
# main.py
def load_config() -> dict:
    config_path = Path('config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# src/production/config_manager.py
class ConfigManager:
    def __init__(self, config_path: str = "config.json"):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
```

**配置结构**:

```json
{
  "data": { "monitor_list_file": "...", "data_dir": "..." },
  "backtest": { "start_date": "...", "end_date": "...", "starting_capital_jpy": 5000000 },
  "portfolio": { "max_positions": 5, "max_position_pct": 0.30 },
  "lot_sizes": { "1321": 1, "default": 100 },
  "default_strategies": { "entry": "SimpleScorerStrategy", "exit": "ATRExitStrategy" },
  "production": { "strategy_groups": [...], "buy_threshold": 65 }
}
```

**建议**: **必须保留**，这是系统核心配置文件

---

### 2️⃣ **production_state.json** - 生产环境状态持久化 ✅

**状态**: **活跃使用中**

**用途**:

- 存储生产环境的投资组合状态
- 跟踪策略组的现金、持仓、交易历史
- 由`ProductionState`类管理，自动读写

**代码引用**:

```python
# src/production/state_manager.py (第266行)
class ProductionState:
    def __init__(self, state_file: str = "production_state.json"):
        self.state_file = state_file
        self._load()

    def save(self):
        """持久化状态到JSON文件"""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state_dict, f, indent=2, ensure_ascii=False)

# main.py - cmd_production()
state = ProductionState(state_file=prod_cfg.state_file)  # 读取配置中的路径
```

**当前内容**:

```json
{
  "last_updated": "2026-01-21T00:00:00",
  "strategy_groups": [
    {
      "id": "group_a",
      "name": "积极进取组",
      "initial_capital": 2000000,
      "cash": 2000000,
      "positions": [] // 空，尚未开始交易
    },
    {
      "id": "group_b",
      "name": "稳健防守组",
      "initial_capital": 2000000,
      "cash": 2000000,
      "positions": []
    }
  ]
}
```

**使用频率**:

- 每次运行`python main.py production`时读取和更新
- Phase 5生产环境的核心状态文件

**建议**: **必须保留**，这是生产环境的状态存储

---

### 3️⃣ **trade_history.json** - 交易历史记录 ✅

**状态**: **活跃使用中**

**用途**:

- 记录所有已完成的交易
- 用于绩效分析和报告生成
- 由`TradeHistoryManager`类管理

**代码引用**:

```python
# src/production/state_manager.py (第457行)
class TradeHistoryManager:
    def __init__(self, history_file: str = "trade_history.json"):
        self.history_file = history_file
        self._load()

    def add_trade(self, trade: CompletedTrade):
        """添加已完成的交易"""
        self.trades.append(trade)
        self._save()

# src/production/trade_executor.py (注释说明)
# Records trades to trade_history.json

# config.json中配置路径
"production": {
  "history_file": "trade_history.json"
}
```

**当前内容**:

```json
{
  "trades": [] // 空，尚未有完成的交易
}
```

**预期格式**（交易记录时）:

```json
{
  "trades": [
    {
      "group_id": "group_a",
      "ticker": "7974",
      "entry_date": "2025-12-15",
      "entry_price": 8200.0,
      "exit_date": "2026-01-15",
      "exit_price": 9100.0,
      "quantity": 100,
      "profit_jpy": 90000,
      "profit_pct": 10.98,
      "strategy": "SimpleScorerStrategy + LayeredExitStrategy"
    }
  ]
}
```

**建议**: **必须保留**，用于交易记录和绩效跟踪

---

### 4️⃣ **all_strategies.json** - 策略组合列表（工具生成） ⚠️

**状态**: **工具输出文件，不被代码直接使用**

**用途**:

- 由`tools/generate_strategies.py`生成的策略组合列表
- 仅用于人工参考，复制到其他配置文件

**生成方式**:

```python
# tools/generate_strategies.py (第38行)
output_file = "all_strategies.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(combinations, f, indent=2, ensure_ascii=False)

print("使用方法:")
print("  1. 打开 all_strategies.json")
print("  2. 复制全部或部分策略")
print("  3. 粘贴到 backtest_config.json 的 strategies 字段")
```

**代码引用**: **无** - 没有任何Python代码读取此文件

**内容**:

```json
[
  {
    "comment": "Simple scorer + ATR technical exit",
    "entry": "SimpleScorerStrategy",
    "exit": "ATRExitStrategy"
  }
  // ... 共9种组合（3 Entry × 3 Exit）
]
```

**问题**:

1. 文件过时：只有3种Entry策略（实际有5种）
2. 从未被代码使用
3. 放在根目录不合适

**建议**:

- **移动至** `output/` 或 `tools/output/`
- 更新工具以生成完整的5×5=25种组合
- 或者直接删除（因为现在CLI支持`--all-strategies`参数）

---

### 5️⃣ **STRATEGY_CATALOG.json** - 策略说明文档 ⚠️

**状态**: **文档性质，不被代码使用**

**用途**:

- 策略的详细说明文档（JSON格式）
- 供AI工具（GitHub Copilot等）参考
- 包含每个策略的逻辑、参数、优缺点等

**代码引用**: **无** - 没有任何Python代码读取此文件

**内容结构**:

```json
{
  "catalog_version": "1.0",
  "generated_date": "2026-01-14",
  "description": "J-Stock Analyzer 现有策略集合 - 用于AI策略生成参考",

  "strategy_architecture": { ... },
  "available_data_sources": { ... },
  "entry_strategies": [ ... ],  // 详细描述每个入场策略
  "exit_strategies": [ ... ]    // 详细描述每个出场策略
}
```

**特点**:

- 495行，非常详细
- 包含每个策略的核心逻辑、参数、优势、劣势
- 纯文档性质，类似于代码注释的结构化版本

**问题**:

1. 信息已过时（只记录了3种Entry和3种Exit）
2. 作为JSON格式不便于人类阅读
3. 放在根目录不合适

**建议**:

- **移动至** `docs/`
- 或转换为Markdown格式（更易读）
- 或更新为完整的5×5策略目录

---

### 6️⃣ **strategy_presets.json** - 旧版策略预设模板 ⚠️

**状态**: **废弃文件，已被CLI参数替代**

**用途**（历史）:

- 旧版回测系统的策略预设模板
- 用于快速选择策略组合
- 需要手动复制到`backtest_config.json`

**代码引用**: **无** - 没有任何Python代码读取此文件

**内容**:

```json
{
  "comment": "策略组合预设模板 - 复制想要的组合到 backtest_config.json",
  "presets": {
    "all_combinations": { ... },
    "score_based": { ... },
    "technical_only": { ... },
    "conservative": { ... },
    "aggressive": { ... }
  },
  "usage": "复制 presets 中的 strategies 数组到 backtest_config.json"
}
```

**为何废弃**:

- 新版CLI支持直接通过参数指定策略：
  ```bash
  python main.py backtest 7974 --entry SimpleScorerStrategy --exit LayeredExitStrategy
  python main.py backtest 7974 --all-strategies  # 测试全部25种
  ```
- 不再需要手动编辑JSON配置文件
- 功能已被`src/utils/strategy_loader.py`替代

**建议**:

- **移动至** `docs/archive/` 或 `docs/legacy/`
- 或直接删除（功能已被CLI替代）

---

## 🎯 推荐操作

### 立即执行（清理根目录）

```bash
# 1. 移动工具生成文件到output
mkdir -p output/tools
mv all_strategies.json output/tools/

# 2. 移动文档性质文件到docs
mv STRATEGY_CATALOG.json docs/

# 3. 归档废弃文件
mkdir -p docs/archive
mv strategy_presets.json docs/archive/
```

### 可选优化

1. **更新工具** - `tools/generate_strategies.py`
   - 更新为5种Entry × 5种Exit = 25种组合
   - 修改输出路径为`output/tools/`

2. **转换文档格式** - `STRATEGY_CATALOG.json`
   - 转换为Markdown格式，放在`docs/STRATEGY_CATALOG.md`
   - 更容易阅读和维护

3. **添加.gitignore规则**

   ```
   # 生产环境运行时文件（保留但不提交变更）
   production_state.json
   trade_history.json

   # 工具输出
   output/tools/
   ```

---

## 📋 文件保留清单

### ✅ 必须保留（根目录）

| 文件                  | 用途     | 修改频率     |
| --------------------- | -------- | ------------ |
| config.json           | 系统配置 | 手动编辑     |
| production_state.json | 生产状态 | 程序自动更新 |
| trade_history.json    | 交易记录 | 程序自动追加 |

### ⚠️ 建议移动

| 文件                  | 当前位置 | 建议位置      | 原因     |
| --------------------- | -------- | ------------- | -------- |
| all_strategies.json   | 根目录   | output/tools/ | 工具输出 |
| STRATEGY_CATALOG.json | 根目录   | docs/         | 文档性质 |
| strategy_presets.json | 根目录   | docs/archive/ | 已废弃   |

---

## 💡 最佳实践建议

### JSON文件组织原则

1. **配置文件** → 根目录
   - `config.json` - 主配置
   - `.env.example` - 环境变量模板

2. **运行时状态** → 根目录（添加.gitignore）
   - `production_state.json` - 自动更新
   - `trade_history.json` - 自动追加

3. **工具输出** → `output/`
   - `all_strategies.json`
   - 回测结果
   - 信号文件

4. **文档和示例** → `docs/`
   - `STRATEGY_CATALOG.json` 或 `.md`
   - 配置示例
   - 废弃文件归档

5. **数据** → `data/`
   - `monitor_list.json` - 监视列表
   - 特征数据、财务数据等

---

## 🔍 代码搜索证据

### production_state.json 使用证据

```
# 搜索结果：68个匹配
- src/production/state_manager.py: ProductionState类定义
- src/production/config_manager.py: 默认配置
- main.py: cmd_production()中使用
- 多个Phase文档中说明
```

### trade_history.json 使用证据

```
# 搜索结果：3个匹配
- src/production/state_manager.py: TradeHistoryManager类
- src/production/trade_executor.py: 注释说明
- config.json: 配置路径
```

### all_strategies.json 使用证据

```
# 搜索结果：2个匹配（仅在tools/generate_strategies.py）
- 无任何代码读取此文件
- 仅作为工具输出
```

### STRATEGY_CATALOG.json 使用证据

```
# 搜索结果：0个匹配
- 无任何代码引用
- 纯文档性质
```

### strategy_presets.json 使用证据

```
# 搜索结果：0个匹配
- 无任何代码引用
- 功能已被CLI替代
```

---

## 总结

**需要保留的JSON文件（3个）**:

1. ✅ config.json - 系统核心配置
2. ✅ production_state.json - 生产状态持久化
3. ✅ trade_history.json - 交易历史记录

**可以移动的JSON文件（3个）**:

1. ⚠️ all_strategies.json → `output/tools/`
2. ⚠️ STRATEGY_CATALOG.json → `docs/`
3. ⚠️ strategy_presets.json → `docs/archive/`（或删除）

**关键发现**:

- 所有命令确实都使用`config.json`作为主配置
- 生产环境使用两个独立的JSON文件存储运行时状态
- 其他JSON文件都是工具输出或文档，不被代码使用

---

**报告生成时间**: 2026-01-22  
**调查工具**: grep_search, file_search, read_file  
**调查者**: GitHub Copilot
