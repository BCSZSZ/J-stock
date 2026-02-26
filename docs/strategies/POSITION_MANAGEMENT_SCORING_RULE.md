# 仓位管理统一评分规则（V2，长期默认版）

更新时间：2026-02-27  
适用范围：`pos-evaluation` 输出的多仓位组合横向比较（同策略、同时间窗、同 filter 设置）

---

## 1. 目标

V2 只服务于一个目标：

> 选出“可长期使用”的仓位管理参数，而不是“某一年最高收益”的激进参数。

因此，V2 以“跨年稳健性”优先，收益效率次之。

---

## 2. 输入数据口径

输入文件：每个组合对应的 `position_eval_*_raw_*.csv`（年度粒度）。

年度字段：

- `return_pct`
- `alpha`
- `sharpe_ratio`
- `max_drawdown_pct`
- `num_trades`

约束：

- 只允许在同一批实验内比较（同年份区间、同策略、同 filter）
- 不使用同批 min-max 归一化，改为固定锚点评分（避免候选变化导致历史分数漂移）

---

## 3. 评分结构（两阶段）

### 3.1 阶段A：逐年评分（Year Score）

先对每一年计算 0-100 的年度得分，再做跨年聚合。

固定锚点评分函数：

- `clip01(x) = min(max(x, 0), 1)`
- `score = clip01((x - L) / (U - L)) * 100`

年度分项（均为 0-100）：

- `score_alpha_y = clip01((alpha_y - (-10)) / (30 - (-10))) * 100`
- `score_sharpe_y = clip01((sharpe_y - 0.0) / (2.5 - 0.0)) * 100`
- `score_return_y = clip01((return_y - (-5)) / (25 - (-5))) * 100`
- `score_dd_y = clip01((35 - maxdd_y) / (35 - 8)) * 100`（回撤越小越高）

年度总分：

`year_score = 0.35*score_alpha_y + 0.30*score_sharpe_y + 0.20*score_dd_y + 0.15*score_return_y`

### 3.2 阶段B：跨年聚合（Long-term Score）

基于全部 `year_score` 再计算长期得分。

跨年分项：

- `score_median_year`: 年度得分中位数（越高越好）
- `score_worst_year`: 年度得分最差值（越高越好）
- `score_stability`: 年收益标准差的锚点评分（越低越好）
  - `score_stability = clip01((25 - std(return_pct)) / (25 - 8)) * 100`
- `score_consistency`: 年度一致性
  - `score_consistency = 70 * pos_year_ratio + 30 * pos_alpha_ratio`
- `score_tail_risk`: 最差年度回撤锚点评分（越低越好）
  - `score_tail_risk = clip01((30 - maxdd_worst) / (30 - 10)) * 100`
- `score_turnover`: 交易强度轻度惩罚（软约束）
  - `score_turnover = clip01(1 - abs(trades_mean - 220) / 120) * 100`

---

## 4. V2 总分公式

权重（满分 100）：

- `score_median_year`: 40%
- `score_worst_year`: 20%
- `score_stability`: 15%
- `score_consistency`: 10%
- `score_tail_risk`: 10%
- `score_turnover`: 5%

`total_score_v2 = 0.40*score_median_year + 0.20*score_worst_year + 0.15*score_stability + 0.10*score_consistency + 0.10*score_tail_risk + 0.05*score_turnover`

---

## 5. 解释与使用建议

- V2 明确抑制“均值好看但某一年崩坏”的参数：最差年和尾部回撤占 30%。
- V2 避免了同批 min-max 的漂移问题：采用固定锚点可跨批次复现。
- 交易强度只占 5%，仅做部署可执行性约束，不主导排名。

推荐决策：

- 默认参数：`total_score_v2` 第一且 `score_worst_year >= 55`
- 若第一与第二分差 < 2 分：并行观察 1-3 个月再定
- 若某组合 `score_tail_risk < 40`：只归为进攻配置，不作为长期默认


