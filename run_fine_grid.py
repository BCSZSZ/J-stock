#!/usr/bin/env python3
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
        "MVX_N8_R3p4_T1p5_D18_B19p5", "MVX_N8_R3p4_T1p6_D18_B19p5", "MVX_N8_R3p4_T1p7_D18_B19p5", "MVX_N8_R3p5_T1p5_D18_B19p5", "MVX_N8_R3p5_T1p6_D18_B19p5", "MVX_N8_R3p5_T1p7_D18_B19p5", "MVX_N8_R3p6_T1p5_D18_B19p5", "MVX_N8_R3p6_T1p6_D18_B19p5", "MVX_N8_R3p6_T1p7_D18_B19p5", "MVX_N9_R3p4_T1p5_D18_B19p5", "MVX_N9_R3p4_T1p6_D18_B19p5", "MVX_N9_R3p4_T1p7_D18_B19p5", "MVX_N9_R3p5_T1p5_D18_B19p5", "MVX_N9_R3p5_T1p6_D18_B19p5", "MVX_N9_R3p5_T1p7_D18_B19p5", "MVX_N9_R3p6_T1p5_D18_B19p5", "MVX_N9_R3p6_T1p6_D18_B19p5", "MVX_N9_R3p6_T1p7_D18_B19p5", "MVX_N10_R3p4_T1p5_D18_B19p5", "MVX_N10_R3p4_T1p6_D18_B19p5", "MVX_N10_R3p4_T1p7_D18_B19p5", "MVX_N10_R3p5_T1p5_D18_B19p5", "MVX_N10_R3p5_T1p6_D18_B19p5", "MVX_N10_R3p5_T1p7_D18_B19p5", "MVX_N10_R3p6_T1p5_D18_B19p5", "MVX_N10_R3p6_T1p6_D18_B19p5", "MVX_N10_R3p6_T1p7_D18_B19p5", "MVX_N8_R3p4_T1p5_D18_B20p0", "MVX_N8_R3p4_T1p6_D18_B20p0", "MVX_N8_R3p4_T1p7_D18_B20p0", "MVX_N8_R3p5_T1p5_D18_B20p0", "MVX_N8_R3p5_T1p6_D18_B20p0", "MVX_N8_R3p5_T1p7_D18_B20p0", "MVX_N8_R3p6_T1p5_D18_B20p0", "MVX_N8_R3p6_T1p6_D18_B20p0", "MVX_N8_R3p6_T1p7_D18_B20p0", "MVX_N9_R3p4_T1p5_D18_B20p0", "MVX_N9_R3p4_T1p6_D18_B20p0", "MVX_N9_R3p4_T1p7_D18_B20p0", "MVX_N9_R3p5_T1p5_D18_B20p0", "MVX_N9_R3p5_T1p6_D18_B20p0", "MVX_N9_R3p5_T1p7_D18_B20p0", "MVX_N9_R3p6_T1p5_D18_B20p0", "MVX_N9_R3p6_T1p6_D18_B20p0", "MVX_N9_R3p6_T1p7_D18_B20p0", "MVX_N10_R3p4_T1p5_D18_B20p0", "MVX_N10_R3p4_T1p6_D18_B20p0", "MVX_N10_R3p4_T1p7_D18_B20p0", "MVX_N10_R3p5_T1p5_D18_B20p0", "MVX_N10_R3p5_T1p6_D18_B20p0", "MVX_N10_R3p5_T1p7_D18_B20p0", "MVX_N10_R3p6_T1p5_D18_B20p0", "MVX_N10_R3p6_T1p6_D18_B20p0", "MVX_N10_R3p6_T1p7_D18_B20p0", "MVX_N8_R3p4_T1p5_D18_B20p5", "MVX_N8_R3p4_T1p6_D18_B20p5", "MVX_N8_R3p4_T1p7_D18_B20p5", "MVX_N8_R3p5_T1p5_D18_B20p5", "MVX_N8_R3p5_T1p6_D18_B20p5", "MVX_N8_R3p5_T1p7_D18_B20p5", "MVX_N8_R3p6_T1p5_D18_B20p5", "MVX_N8_R3p6_T1p6_D18_B20p5", "MVX_N8_R3p6_T1p7_D18_B20p5", "MVX_N9_R3p4_T1p5_D18_B20p5", "MVX_N9_R3p4_T1p6_D18_B20p5", "MVX_N9_R3p4_T1p7_D18_B20p5", "MVX_N9_R3p5_T1p5_D18_B20p5", "MVX_N9_R3p5_T1p6_D18_B20p5", "MVX_N9_R3p5_T1p7_D18_B20p5", "MVX_N9_R3p6_T1p5_D18_B20p5", "MVX_N9_R3p6_T1p6_D18_B20p5", "MVX_N9_R3p6_T1p7_D18_B20p5", "MVX_N10_R3p4_T1p5_D18_B20p5", "MVX_N10_R3p4_T1p6_D18_B20p5", "MVX_N10_R3p4_T1p7_D18_B20p5", "MVX_N10_R3p5_T1p5_D18_B20p5", "MVX_N10_R3p5_T1p6_D18_B20p5", "MVX_N10_R3p5_T1p7_D18_B20p5", "MVX_N10_R3p6_T1p5_D18_B20p5", "MVX_N10_R3p6_T1p6_D18_B20p5", "MVX_N10_R3p6_T1p7_D18_B20p5"
    ]
    
    print("=" * 80)
    print("🔬 细化参数网格回测执行器")
    print("=" * 80)
    print(f"总策略数: {len(strategies)}")
    print(f"总回测数: {len(strategies)} × 5年 = {len(strategies) * 5}")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
    os.chdir("e:\\Code\\AI-stock\\J-stock")
    
    # 执行
    try:
        result = subprocess.run(cmd, capture_output=False)
        sys.exit(result.returncode)
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
