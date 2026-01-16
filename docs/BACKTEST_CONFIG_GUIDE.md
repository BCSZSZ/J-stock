# 回测配置使用指南

## 🎯 三种配置策略的方法

### 方法 1：命令行快速测试 ⚡（最简单）

**无需编辑任何配置文件！**

```bash
# 查看所有可用策略
python quick_backtest.py --list

# 单个策略组合
python quick_backtest.py simple atr

# 多个策略组合
python quick_backtest.py simple atr enhanced layered

# 指定股票和日期范围
python quick_backtest.py simple atr --ticker 6501 --start 2023-01-01

# 完整参数示例
python quick_backtest.py enhanced layered --ticker 7203 --start 2021-01-01 --end 2026-01-08 --capital 10000000
```

**策略简称对照表：**

| 简称       | 完整名称               | 类型  |
| ---------- | ---------------------- | ----- |
| `simple`   | SimpleScorerStrategy   | Entry |
| `enhanced` | EnhancedScorerStrategy | Entry |
| `macd`     | MACDCrossoverStrategy  | Entry |
| `atr`      | ATRExitStrategy        | Exit  |
| `score`    | ScoreBasedExitStrategy | Exit  |
| `layered`  | LayeredExitStrategy    | Exit  |

**优点**：

- ✅ 最快速，适合快速测试单个策略
- ✅ 不需要记住完整类名
- ✅ 不需要编辑 JSON 文件
- ✅ 适合临时测试

---

### 方法 2：使用策略预设模板 📋（推荐）

**步骤：**

1. 打开 `strategy_presets.json`，选择一个预设
2. 复制 `strategies` 数组
3. 粘贴到 `backtest_config.json` 的 `strategies` 字段
4. 运行 `python start_backtest.py`

**可用预设：**

#### 1. `all_combinations` - 全部 9 种组合

测试所有 Entry × Exit 组合（3×3=9 种）

#### 2. `score_based` - 评分策略

只测试基于评分的策略：

- SimpleScorerStrategy + ScoreBasedExitStrategy
- EnhancedScorerStrategy + ScoreBasedExitStrategy

#### 3. `technical_only` - 纯技术

纯技术指标策略：

- MACDCrossoverStrategy + ATRExitStrategy

#### 4. `layered_exit` - 多层退出

测试多层退出策略的所有组合

#### 5. `conservative` - 保守策略

EnhancedScorerStrategy + LayeredExitStrategy

#### 6. `aggressive` - 激进策略

SimpleScorerStrategy + ATRExitStrategy

**示例：**

```json
{
  "backtest_config": {
    "tickers": ["7203"],
    "start_date": "2021-01-01",
    "end_date": "2026-01-08",
    "starting_capital_jpy": 5000000,
    "include_benchmark": true,
    "strategies": [
      { "entry": "EnhancedScorerStrategy", "exit": "LayeredExitStrategy" }
    ]
  }
}
```

**优点**：

- ✅ 有预设模板，复制粘贴即可
- ✅ 适合系统性测试多个策略
- ✅ 可保存自定义配置

---

### 方法 3：直接编辑 backtest_config.json ✏️（最灵活）

**基本格式：**

```json
{
  "backtest_config": {
    "tickers": ["7203", "6501"],
    "start_date": "2021-01-01",
    "end_date": "2026-01-08",
    "starting_capital_jpy": 5000000,
    "include_benchmark": true,
    "strategies": [
      {
        "comment": "可选注释",
        "entry": "策略类名",
        "exit": "退出策略类名",
        "entry_params": {},
        "exit_params": {}
      }
    ]
  }
}
```

**可用策略名称：**

**Entry Strategies:**

- `SimpleScorerStrategy`
- `EnhancedScorerStrategy`
- `MACDCrossoverStrategy`

**Exit Strategies:**

- `ATRExitStrategy`
- `ScoreBasedExitStrategy`
- `LayeredExitStrategy`

**添加策略示例：**

```json
"strategies": [
  {
    "comment": "保守策略",
    "entry": "EnhancedScorerStrategy",
    "exit": "LayeredExitStrategy"
  },
  {
    "comment": "激进策略",
    "entry": "SimpleScorerStrategy",
    "exit": "ATRExitStrategy"
  },
  {
    "comment": "纯技术",
    "entry": "MACDCrossoverStrategy",
    "exit": "LayeredExitStrategy",
    "exit_params": {
      "use_score_utils": false
    }
  }
]
```

**优点**：

- ✅ 最灵活，可添加参数
- ✅ 可保存多个配置文件
- ✅ 适合生产环境

---

## 📝 快速参考

### 添加新策略组合

**命令行方式：**

```bash
python quick_backtest.py enhanced layered
```

**配置文件方式：**

```json
{
  "entry": "EnhancedScorerStrategy",
  "exit": "LayeredExitStrategy"
}
```

### 删除策略组合

**命令行方式：**
无需删除，直接运行新的命令

**配置文件方式：**
从 `strategies` 数组中删除对应的对象（注意 JSON 逗号）

### 测试多个股票

**命令行方式：**

```bash
# 只支持单个股票
python quick_backtest.py simple atr --ticker 6501
```

**配置文件方式：**

```json
"tickers": ["7203", "6501", "8035"]
```

---

## 🚀 推荐工作流程

### 快速探索阶段

使用 `quick_backtest.py` 快速测试想法：

```bash
python quick_backtest.py simple atr
python quick_backtest.py enhanced layered
python quick_backtest.py macd score
```

### 系统测试阶段

使用预设模板，编辑 `backtest_config.json`：

1. 从 `strategy_presets.json` 复制预设
2. 修改 `tickers` 和日期范围
3. 运行 `python start_backtest.py`

### 生产运行阶段

保存最优配置到 `backtest_config.json`，定期运行

---

## 💡 技巧

1. **快速对比**：使用 `quick_backtest.py` 一次测试多个策略

   ```bash
   python quick_backtest.py simple atr enhanced layered macd score
   ```

2. **保存配置**：把常用配置保存为不同的 JSON 文件

   ```
   backtest_config_conservative.json
   backtest_config_aggressive.json
   backtest_config_all.json
   ```

3. **查看结果**：所有结果保存在 `backtest_results/` 文件夹

---

## ❓ 常见问题

**Q: 策略名称太长，记不住？**  
A: 使用 `quick_backtest.py`，只需记住简称（simple, enhanced, macd, atr, score, layered）

**Q: 想测试多个策略但不想编辑配置？**  
A: 使用命令行：`python quick_backtest.py simple atr enhanced layered`

**Q: 如何保存自己的常用策略组合？**  
A: 在 `strategy_presets.json` 添加新的预设，或创建新的配置文件

**Q: JSON 格式错误怎么办？**  
A: 使用 `quick_backtest.py` 避免 JSON 编辑，或使用 JSON 验证工具

---

## 📚 延伸阅读

- [FINAL_STRATEGY_ARCHITECTURE.md](FINAL_STRATEGY_ARCHITECTURE.md) - 策略架构详解
- [USAGE_GUIDE.md](USAGE_GUIDE.md) - 完整使用指南
