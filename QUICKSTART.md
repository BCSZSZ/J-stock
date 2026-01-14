# J-Stock-Analyzer - 快速开始

## 🚀 新的统一 CLI 入口

项目已重构为统一的命令行界面，所有功能通过 `main.py` 访问：

### 📥 1. 数据抓取

```bash
# 抓取监视列表中的所有股票
python main.py fetch --all

# 抓取指定股票
python main.py fetch --tickers 7974 8035 6501
```

### 🎯 2. 生成交易信号（新功能）

```bash
# 生成今日交易信号
python main.py signal 7974

# 生成指定日期的信号
python main.py signal 7974 --date 2026-01-10

# 使用不同的策略组合
python main.py signal 7974 --entry EnhancedScorerStrategy --exit LayeredExitStrategy
```

### 📊 3. 单股票回测

```bash
# 使用默认参数回测
python main.py backtest 7974

# 自定义参数
python main.py backtest 7974 \
  --entry EnhancedScorerStrategy \
  --exit LayeredExitStrategy \
  --start 2022-01-01 \
  --end 2026-01-08 \
  --capital 10000000
```

### 💼 4. 组合投资回测

```bash
# 回测监视列表所有股票
python main.py portfolio --all

# 回测指定股票组合
python main.py portfolio --tickers 7974 8035 6501 8306 6861

# 自定义策略
python main.py portfolio --all \
  --entry SimpleScorerStrategy \
  --exit ATRExitStrategy \
  --start 2021-01-01
```

---

## ⚙️ 配置文件

### `config.json` - 全局配置

```json
{
  "data": {
    "monitor_list_file": "data/monitor_list.txt",
    "data_dir": "data"
  },
  "backtest": {
    "start_date": "2021-01-01",
    "end_date": "2026-01-08",
    "starting_capital_jpy": 5000000,
    "output_dir": "backtest_results"
  },
  "portfolio": {
    "max_positions": 5,
    "max_position_pct": 0.3,
    "min_position_pct": 0.05
  },
  "default_strategies": {
    "entry": "SimpleScorerStrategy",
    "exit": "ATRExitStrategy"
  }
}
```

### `data/monitor_list.txt` - 监视股票列表（简化格式）

```txt
# 每行一个股票代码，# 开头为注释

# 半导体
8035

# 金融
8306

# 游戏
7974
```

---

## 📚 可用策略

### 入场策略（Entry Strategies）

- `SimpleScorerStrategy` - 简单综合打分（技术+机构）
- `EnhancedScorerStrategy` - 增强打分（技术+机构+基本面+波动率）
- `MACDCrossoverStrategy` - MACD 交叉策略

### 出场策略（Exit Strategies）

- `ATRExitStrategy` - ATR 技术出场（止损/追踪/趋势破坏）
- `ScoreBasedExitStrategy` - 分数衰减出场
- `LayeredExitStrategy` - 5 层风险控制出场

---

## 🔧 独立工具

### 策略生成器

```bash
cd tools
python generate_strategies.py
```

生成所有 Entry×Exit 组合的配置文件。

### 分数诊断工具

```bash
cd tools
python check_scores.py
```

检查股票历史得分分布。

---

## 📂 新的项目结构

```
j-stock-analyzer/
├── main.py                    ⭐ 统一CLI入口
├── config.json                ⭐ 简化配置
├── data/
│   └── monitor_list.txt       ⭐ 简化监视列表
│
├── src/
│   ├── data_fetch_manager.py  ⭐ 数据抓取
│   ├── signal_generator.py    ⭐ 策略信号生成
│   │
│   ├── data/                  # 数据管道
│   ├── analysis/              # 策略和指标
│   │   └── strategies/        # 入场+出场策略
│   └── backtest/              # 回测引擎
│
├── tools/                     ⭐ 独立工具
│   ├── generate_strategies.py
│   └── check_scores.py
│
├── start_backtest.py          # 向后兼容（保留）
└── start_portfolio_backtest.py # 向后兼容（保留）
```

---

## 🎁 扩展性

### 添加新的技术指标

```python
# src/analysis/technical_indicators.py
def calculate_my_indicator(data):
    # 实现你的指标
    pass
```

### 添加新的入场策略

```python
# src/analysis/strategies/entry/my_strategy.py
from src.analysis.strategies.base_entry_strategy import BaseEntryStrategy

class MyCustomStrategy(BaseEntryStrategy):
    def generate_signal(self, market_data):
        # 实现你的策略
        pass
```

然后直接使用：

```bash
python main.py backtest 7974 --entry MyCustomStrategy
```

---

## ⚠️ 重要变更

### ✅ 已删除

- ❌ 旧的 `src/analysis/scorers/` 文件夹
- ❌ 旧的 `src/analysis/exiters/` 文件夹
- ❌ 临时测试脚本（test_scorer.py, test_exit.py 等）
- ❌ 复杂的 JSON 配置（backtest_config.json, portfolio_config.json, monitor_list.json）

### ✅ 新增

- ✨ 统一的 `main.py` CLI 入口
- ✨ 简化的配置文件（config.json）
- ✨ 简化的监视列表（monitor_list.txt）
- ✨ 策略信号生成功能（signal 命令）
- ✨ 独立工具目录（tools/）

### ✅ 保留（向后兼容）

- ✅ `start_backtest.py` - 仍可使用
- ✅ `start_portfolio_backtest.py` - 仍可使用
- ✅ 所有策略类保持不变

---

## 📞 帮助

查看所有可用命令：

```bash
python main.py --help
```

查看特定命令的帮助：

```bash
python main.py backtest --help
python main.py portfolio --help
```

---

**更新日期**: 2026-01-14  
**版本**: 2.0 - 统一 CLI 架构
