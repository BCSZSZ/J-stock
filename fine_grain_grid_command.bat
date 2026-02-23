REM 细化参数网格回测命令
REM D = 16, 17, 18, 19 (4个值)
REM B = 17, 18, 19, 20, 21 (5个值)
REM 总计: 20个组合 × 5年 = 100个回测

cd e:\Code\AI-stock\J-stock

e:.venv\Scripts\python.exe main.py evaluate ^
  --mode annual ^
  --years 2021 2022 2023 2024 2025 ^
  --entry-strategies MACDCrossoverStrategy ^
  --exit-strategies ^
    MVX_N9_R3p5_T1p6_D16_B17 ^
    MVX_N9_R3p5_T1p6_D16_B18 ^
    MVX_N9_R3p5_T1p6_D16_B19 ^
    MVX_N9_R3p5_T1p6_D16_B20 ^
    MVX_N9_R3p5_T1p6_D16_B21 ^
    MVX_N9_R3p5_T1p6_D17_B17 ^
    MVX_N9_R3p5_T1p6_D17_B18 ^
    MVX_N9_R3p5_T1p6_D17_B19 ^
    MVX_N9_R3p5_T1p6_D17_B20 ^
    MVX_N9_R3p5_T1p6_D17_B21 ^
    MVX_N9_R3p5_T1p6_D18_B17 ^
    MVX_N9_R3p5_T1p6_D18_B18 ^
    MVX_N9_R3p5_T1p6_D18_B19 ^
    MVX_N9_R3p5_T1p6_D18_B20 ^
    MVX_N9_R3p5_T1p6_D18_B21 ^
    MVX_N9_R3p5_T1p6_D19_B17 ^
    MVX_N9_R3p5_T1p6_D19_B18 ^
    MVX_N9_R3p5_T1p6_D19_B19 ^
    MVX_N9_R3p5_T1p6_D19_B20 ^
    MVX_N9_R3p5_T1p6_D19_B21

timeout /t 10
