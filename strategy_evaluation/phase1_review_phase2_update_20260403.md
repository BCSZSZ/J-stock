# Phase1结果复盘与Phase2修订建议（2026-04-03）

## 1. 目的

- 复盘本次 Phase1 Expanded Coarse Grid 的实际结果。
- 以当前后续流程实际使用的 `target20` 作为主比较口径。
- 用 `risk60_profit40_v2` 做交叉校验，避免只看单一冠军组合。
- 本文只整理 review 结论和 Phase2 修订方案，暂不生成或修改任何 Phase2 脚本。

## 2. 本次使用的结果文件

- Raw CSV: `G:\My Drive\AI-Stock-Sync\strategy_evaluation\strategy_evaluation_raw_20260403_162046.csv`
- Target20 Rank CSV: `G:\My Drive\AI-Stock-Sync\strategy_evaluation\strategy_evaluation_target20_rank_20260403_162046.csv`
- Markdown Report: `G:\My Drive\AI-Stock-Sync\strategy_evaluation\strategy_evaluation_report_20260403_162046.md`

## 3. 主比较方法

- 主排序口径: `target20`
  - 原因: 当前 Phase2 准备逻辑直接读取 `target20` 排名结果来筛选下一轮候选。
- 交叉校验口径: `risk60_profit40_v2`
  - 目的: 检查冠军是否只是在 `target20` 下偶然领先，还是在风险收益平衡下也稳定成立。

## 4. 核心结论

### 4.1 Entry侧已经明显收敛，不应再按原计划平均分配预算

- 原 redesign 文档里保留的旧中心是 `E20/E50 + low spread + A0`。
- 这次 Phase1 的结果显示，Entry 主线已经明显转向 `S20/E50`，即 `FS20` 系列。
- `target20` 下前 20 名组合全部落在 `FS20` 系列，说明 coarse 阶段下 entry 不再是高不确定性区域。

定量摘要：

| 维度 | 结果 |
|------|------|
| `S20` 家族平均 `target20_score` | `66.38` |
| `E20` 家族平均 `target20_score` | `49.66` |
| `A0` 平均 `target20_score` | `59.09` |
| `A1` 平均 `target20_score` | `56.95` |
| Spread `0.0` 平均 `target20_score` | `59.09` |
| Spread `0.2` 平均 `target20_score` | `57.75` |
| Spread `0.1` 平均 `target20_score` | `57.22` |

结论：

- `FS20` 明显强于 `FE20`。
- `A0` 仍优于 `A1`，但 `A1` 不能完全删除，因为 `FS20` 下仍有竞争力。
- Spread 上 `0.0 / 0.1 / 0.2` 差距不大，说明下一阶段更适合做中步长 refinement，而不是继续大范围扩 entry 家族。

### 4.2 Exit侧的冠军点在 MDX，但 MVX 仍应保留为支线

- `target20` 的冠军簇集中在 `MDX_C3_R3p2` 附近，`T1p5` 和 `T1p6` 都很强。
- `target20` 前 10 名全部是 `MDX_C3_*_T1p6`。
- 但如果看 exit family 的整体均值，`MVX` 的平均 `target20_score` 反而高于 `MDX`。

定量摘要：

| 维度 | 结果 |
|------|------|
| `MVX` family mean `target20_score` | `61.99` |
| `MDX` family mean `target20_score` | `54.05` |
| Exit mean #1 | `MDX_C3_R3p2_T1p5_D18_O75p0` -> `84.76` |
| Exit mean #2 | `MDX_C3_R3p2_T1p6_D18_O75p0` -> `82.25` |
| Exit mean #3 | `MDX_C2_R3p2_T1p5_D18_O75p0` -> `79.29` |
| Exit mean #4 | `MDX_C2_R3p2_T1p6_D18_O75p0` -> `78.72` |
| Best MVX anchor | `MVX_N10_R3p6_T1p7_D18_B20p0` |

结论：

- `MDX` 给出了更尖锐的冠军区。
- `MVX` 虽然没有拿下总冠军，但仍有较宽的中高分区域，不应在 Phase2 被完全删掉。

### 4.3 当前最优组合与风险收益交叉验证结果

主比较下的最优组合：

- Entry: `MACX_FS20_SE50_P0p0_A0_C0p58`
- Exit: `MDX_C3_R3p2_T1p6_D18_O75p0`
- `target20_score = 87.58`
- 五年平均收益 `30.47%`
- 最差年度收益 `+2.57%`
- 平均回撤 `11.12%`

交叉校验结果：

- `risk60_profit40_v2` 的头名是同一条 `FS20 + MDX_C3_R3p2` 主线，只是 `T1p6` 切到 `T1p5`。
- `target20` 与 `risk60_profit40_v2` 的 Top20 重叠数为 `15/20`。

解释：

- 两种方法都指向同一条主线，说明这不是单一评分函数偶然造成的结果。
- 真正需要继续比较的，不是 `FS20` vs `FE20`，而是 `MDX` 冠军点和 `MVX` 次优宽平台之间的后续 refinement 价值。

## 5. Target20前10名的五年具体收益

说明：

- 下表按照本次 `target20` 排名前 10 名列出 2021-2025 各年收益。
- 可以看到前 10 名里存在明显重复簇，这是因为多组 `FS20` coarse 变体在本轮上得到完全相同的年序列结果。

| 排名 | Entry | Exit | Score | 2021 | 2022 | 2023 | 2024 | 2025 | 五年均值 | 最差年 | 平均MDD |
|------|-------|------|------:|-----:|-----:|-----:|-----:|-----:|---------:|-------:|--------:|
| 1 | `MACX_FS20_SE50_P0p0_A0_C0p58` | `MDX_C3_R3p2_T1p6_D18_O75p0` | 87.58 | 87.56% | 2.57% | 19.58% | 8.29% | 34.36% | 30.47% | 2.57% | 11.12% |
| 2 | `MACX_FS20_SE50_P0p0_A1_C0p58` | `MDX_C3_R3p2_T1p6_D18_O75p0` | 87.58 | 87.56% | 2.57% | 19.58% | 8.29% | 34.36% | 30.47% | 2.57% | 11.12% |
| 3 | `MACX_FS20_SE50_P0p1_A0_C0p58` | `MDX_C3_R3p2_T1p6_D18_O75p0` | 87.58 | 87.56% | 2.57% | 19.58% | 8.29% | 34.36% | 30.47% | 2.57% | 11.12% |
| 4 | `MACX_FS20_SE50_P0p2_A0_C0p58` | `MDX_C3_R3p2_T1p6_D18_O75p0` | 87.58 | 87.56% | 2.57% | 19.58% | 8.29% | 34.36% | 30.47% | 2.57% | 11.12% |
| 5 | `MACX_FS20_SE50_P0p0_A0_C0p58` | `MDX_C3_R3p4_T1p6_D18_O75p0` | 87.56 | 83.05% | 3.31% | 19.82% | 8.31% | 33.77% | 29.65% | 3.31% | 11.28% |
| 6 | `MACX_FS20_SE50_P0p0_A1_C0p58` | `MDX_C3_R3p4_T1p6_D18_O75p0` | 87.56 | 83.05% | 3.31% | 19.82% | 8.31% | 33.77% | 29.65% | 3.31% | 11.28% |
| 7 | `MACX_FS20_SE50_P0p1_A0_C0p58` | `MDX_C3_R3p4_T1p6_D18_O75p0` | 87.56 | 83.05% | 3.31% | 19.82% | 8.31% | 33.77% | 29.65% | 3.31% | 11.28% |
| 8 | `MACX_FS20_SE50_P0p2_A0_C0p58` | `MDX_C3_R3p4_T1p6_D18_O75p0` | 87.56 | 83.05% | 3.31% | 19.82% | 8.31% | 33.77% | 29.65% | 3.31% | 11.28% |
| 9 | `MACX_FS20_SE50_P0p0_A0_C0p58` | `MDX_C3_R3p6_T1p6_D18_O75p0` | 87.35 | 83.77% | 2.97% | 19.68% | 8.55% | 32.83% | 29.56% | 2.97% | 11.12% |
| 10 | `MACX_FS20_SE50_P0p0_A1_C0p58` | `MDX_C3_R3p6_T1p6_D18_O75p0` | 87.35 | 83.77% | 2.97% | 19.68% | 8.55% | 32.83% | 29.56% | 2.97% | 11.12% |

补充观察：

- 前 10 名里只有 3 个 exit 变体，且全部属于 `MDX_C3_*_T1p6`。
- 前 20 名里 entry 只剩 4 个核心 `FS20` 变体，说明 entry 已经非常集中。

## 6. 如果当前自动选择逻辑不改，会发生什么

按当前 Phase2 准备逻辑预览，Round1 会倾向选出：

- Entry:
  - `MACX_FS20_SE50_P0p1_A0_C0p58`
  - `MACX_FS20_SE50_P0p2_A0_C0p58`
  - `MACX_FS20_SE50_P0p0_A0_C0p58`
  - `MACX_FS20_SE50_P0p0_A1_C0p58`
  - `MACX_FS20_SE50_P0p2_A1_C0p58`
  - `MACX_FS20_SE50_P0p1_A1_C0p58`
- Exit:
  - `MVX_N10_R3p6_T1p7_D18_B20p0`
  - `MVX_N9_R3p6_T1p7_D18_B20p0`
  - `MVX_N9_R3p5_T1p7_D18_B20p0`
  - `MVX_N9_R3p6_T1p6_D18_B20p0`
  - `MDX_C3_R3p2_T1p5_D18_O75p0`
  - `MDX_C3_R3p2_T1p6_D18_O75p0`
  - `MDX_C2_R3p2_T1p5_D18_O75p0`
  - `MDX_C2_R3p2_T1p6_D18_O75p0`

这个自动选择有两个问题：

- 它会把 entry 侧几乎完全压缩到 `FS20`，这在主线判断上没错，但会丢掉 `MVX` 支线最有价值的 `FE20_A0` 锚点。
- 它对 exit 做了 `MVX 4 + MDX 4` 的硬对称分配，但本次结果显示更合理的是 `MDX` 主线更多、`MVX` 支线更少，而不是完全对称。

## 7. 修订后的Phase2建议文案（供校阅）

下面这段是建议替换原 redesign 中 Phase2 小节的内容草案。

---

### Phase2（Focused Two-Lane Refinement）

Goal:

- 不再把 entry 和 exit 视为同等不确定。
- Entry 侧在 Phase1 后已明显收敛，Phase2 应该缩窄 entry 搜索范围。
- Exit 侧继续保留双通道：`MDX` 作为主线精修，`MVX` 作为次主线保留。
- 为避免误杀 `MVX` 兼容分支，保留少量 `FE20_A0` 作为锚点，但不再大范围扩展 `FE20`。

Recommended scope:

- Entry: `20` variants
  - `FS20` 主网格 `12`
    - Spread in `{0.00, 0.10, 0.20}`
    - `A in {0,1}`
    - `C in {0.58, 0.62}`
  - `FS20` 中点验证 `4`
    - Spread in `{0.05, 0.15}`
    - `A = 0`
    - `C in {0.58, 0.62}`
  - `FE20` 的 `MVX` 锚点 `4`
    - Spread in `{0.00, 0.05}`
    - `A = 0`
    - `C in {0.58, 0.62}`

- Exit: `14` variants
  - `MDX` 主线 `8`
    - `C in {2,3}`
    - `R in {3.1, 3.2}`
    - `T in {1.5, 1.6}`
    - `D = 18`, `O = 75.0`
  - `MVX` 支线 `6`
    - 以 `N10_R3p6_T1p7` 为中心
    - 保留 `N in {9,10}`
    - 保留 `R in {3.5, 3.6}`
    - 保留 `T in {1.6, 1.7}`
    - `D = 18`, `B = 20.0`
    - 实际脚本阶段再从该邻域中选最近的 `6` 个

Volume:

- Combos: `20 x 14 = 280`
- Tasks: `280 x 5 = 1,400`
- Estimated runtime: about `5.8 hours`

Interpretation:

- 与原来的 `24 x 12` 相比，这个版本减少了对 entry 的重复采样。
- 额外节省下来的预算没有浪费，而是用于把 exit 侧保留成“MDX 主线 + MVX 支线”的更合理结构。
- 这个版本更符合当前结果，而不是沿用 Phase1 之前的旧中心假设。

Selection rule after Phase2:

- 如果 `MDX` 仍同时占据冠军和高均值区，则 Phase3 以 `MDX` 为主、`MVX` 为辅。
- 如果 `MVX` 在保留的 `FE20_A0` 锚点下继续给出更强的最差年和回撤质量，则 Phase3 继续保留一条 `MVX` 比较支线。
- 若 `FE20_A0 + MVX` 在 Phase2 仍明显落后，则 Phase3 可以正式删除 `FE20` 支线。

---

## 8. 当前建议

- 不要直接沿用旧的 Phase2 文案和默认脚本生成逻辑。
- 先以本文这版 Phase2 文案做校阅。
- 校阅通过后，再据此生成新的 entry/exit 列表和 Phase2 启动脚本。