#!/usr/bin/env python3
"""
参数细化网格生成脚本 (Fine-grain Parameter Grid Generator)
功能: 生成围绕最优参数D18_B20的微调网格 (3^4 = 81个组合)
调用主程序: main.py evaluate
"""

from itertools import product


def generate_parameter_grid():
    """
    生成微调参数网格

    固定参数:
    - D (持仓天数) = 18

    微调参数:
    - B (偏离度百分比): [19.5, 20.0, 20.5]        (步长0.5)
    - N (MACD直方图收缩周期): [8, 9, 10]       (步长1)
    - R (回报倍数): [3.4, 3.5, 3.6]            (步长0.1)
    - T (尾随倍数): [1.5, 1.6, 1.7]            (步长0.1)

    总数: 3 × 3 × 3 × 3 = 81个策略组合
    年份: 5年 (2021-2025)
    总回测数: 81 × 5 = 405个
    """

    # 参数域
    D_value = 18  # 固定
    B_values = [19.5, 20.0, 20.5]
    N_values = [8, 9, 10]
    R_values = [3.4, 3.5, 3.6]
    T_values = [1.5, 1.6, 1.7]

    # 生成所有组合
    combinations = list(product(B_values, N_values, R_values, T_values))

    print("✅ 参数网格生成信息")
    print(f"   固定参数: D = {D_value} 天")
    print(f"   B空间: {B_values} (3个值)")
    print(f"   N空间: {N_values} (3个值)")
    print(f"   R空间: {R_values} (3个值)")
    print(f"   T空间: {T_values} (3个值)")
    print(f"   总组合数: {len(combinations)}")
    print(f"   总回测数: {len(combinations)} × 5年 = {len(combinations) * 5}")
    print()

    # 生成策略名称列表
    strategies = []
    for b, n, r, t in combinations:
        # 策略名格式: MVX_N{n}_R{r}_T{t}_D{d}_B{b}
        # 由于B可能是浮点数，需要特殊处理
        b_str = str(b).replace(".", "p")  # 20.5 -> 20p5
        n_int = int(n)
        r_str = str(r).replace(".", "p")
        t_str = str(t).replace(".", "p")

        strategy_name = f"MVX_N{n_int}_R{r_str}_T{t_str}_D{D_value}_B{b_str}"
        strategies.append(strategy_name)

    return strategies


def generate_cli_command(strategies):
    """
    生成主程序的CLI命令行
    """
    cmd = [
        "e:.venv\\Scripts\\python.exe main.py evaluate",
        "--mode annual",
        "--years 2021 2022 2023 2024 2025",
        "--entry-strategies MACDCrossoverStrategy",
        "--exit-strategies",
    ]

    # 添加所有策略
    cmd.extend(strategies)

    # 换行符处理 (PowerShell需要 `)
    return " `\n  ".join(cmd)


def generate_powershell_script(strategies, output_path="execute_fine_grid.ps1"):
    """
    生成PowerShell脚本执行命令
    """
    script = f"""# 细化参数网格回测脚本 (Fine-grain Parameter Grid)
# 生成时间: 2026-02-22
# 总回测数: {len(strategies) * 5}个 (81策略 × 5年)
# 预期耗时: ~25-30分钟 (4 workers)

cd e:\\Code\\AI-stock\\J-stock

Write-Host "=== 开始执行细化参数网格回测 ===" -ForegroundColor Cyan
Write-Host "总策略数: {len(strategies)}" -ForegroundColor Green
Write-Host "总回测数: {len(strategies) * 5}" -ForegroundColor Green
Write-Host "预期耗时: 25-30分钟" -ForegroundColor Yellow
Write-Host ""

$startTime = Get-Date

e:.venv\\Scripts\\python.exe main.py evaluate `
  --mode annual `
  --years 2021 2022 2023 2024 2025 `
  --entry-strategies MACDCrossoverStrategy `
  --exit-strategies `
    {" ".join([f"{s}" for s in strategies])}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host ""
Write-Host "=== 回测完成 ===" -ForegroundColor Green
Write-Host "耗时: $($duration.TotalMinutes) 分钟" -ForegroundColor Cyan
Write-Host "结果已保存到 Google Drive" -ForegroundColor Green
"""

    # 写入文件
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(script)

    return output_path


def generate_python_wrapper(strategies, output_path="run_fine_grid.py"):
    """
    生成Python包装脚本 (如果想用Python执行)
    """
    strategies_str = ", ".join([f'"{s}"' for s in strategies])

    script = f'''#!/usr/bin/env python3
"""
细化参数网格回测执行脚本 (Python Wrapper)
调用主程序进行大规模并行回测
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime

def main():
    # 策略列表 (81个组合)
    strategies = [
        {strategies_str}
    ]
    
    print("=" * 80)
    print("🔬 细化参数网格回测执行器")
    print("=" * 80)
    print(f"总策略数: {{len(strategies)}}")
    print(f"总回测数: {{len(strategies)}} × 5年 = {{len(strategies) * 5}}")
    print(f"执行时间: {{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}")
    print(f"预期耗时: 25-30分钟 (4 workers)")
    print("=" * 80)
    print()
    
    # 构建命令参数
    cmd = [
        "e:.venv/Scripts/python.exe",
        "main.py",
        "evaluate",
        "--mode", "annual",
        "--years", "2021", "2022", "2023", "2024", "2025",
        "--entry-strategies", "MACDCrossoverStrategy",
        "--exit-strategies"
    ]
    
    # 添加所有策略
    cmd.extend(strategies)
    
    # 切换到项目目录
    import os
    os.chdir("e:\\\\Code\\\\AI-stock\\\\J-stock")
    
    # 执行
    try:
        result = subprocess.run(cmd, capture_output=False)
        sys.exit(result.returncode)
    except Exception as e:
        print(f"❌ 执行失败: {{e}}")
        sys.exit(1)

if __name__ == "__main__":
    main()
'''

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(script)

    return output_path


def main():
    """主函数"""

    # 1. 生成参数网格
    print("🔄 生成参数网格...")
    strategies = generate_parameter_grid()
    print(f"✅ 生成成功! 共 {len(strategies)} 个策略")
    print()

    # 2. 生成PowerShell脚本 (推荐)
    print("📝 生成PowerShell脚本...")
    ps_path = generate_powershell_script(strategies, "execute_fine_grid.ps1")
    print(f"✅ 已生成: {ps_path}")
    print()

    # 3. 生成Python脚本 (备选)
    print("📝 生成Python脚本...")
    py_path = generate_python_wrapper(strategies, "run_fine_grid.py")
    print(f"✅ 已生成: {py_path}")
    print()

    # 4. 生成CLI命令 (显示)
    print("=" * 80)
    print("📋 CLI命令参考 (如需手动执行)")
    print("=" * 80)
    cmd = generate_cli_command(strategies)
    print(cmd)
    print()

    # 5. 输出策略列表
    print("=" * 80)
    print("🎯 生成的81个策略 (B维度 × N维度 × R维度 × T维度)")
    print("=" * 80)
    for i, s in enumerate(strategies, 1):
        print(f"{i:2d}. {s}")
    print()

    print("=" * 80)
    print("✨ 执行建议:")
    print("=" * 80)
    print("方案A (推荐): PowerShell 执行")
    print("  > cd e:\\Code\\AI-stock\\J-stock")
    print("  > .\\execute_fine_grid.ps1")
    print()
    print("方案B: Python 执行")
    print("  > python tools/run_fine_grid.py")
    print()
    print("方案C: 手动命令")
    print("  复制上面的 CLI命令，直接在PowerShell执行")
    print("=" * 80)


if __name__ == "__main__":
    main()
