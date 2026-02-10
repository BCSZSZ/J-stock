#!/usr/bin/env python3
"""Test monitor list loading"""
import json
from pathlib import Path

# Test JSON loading
json_file = Path("data/monitor_list.json")
if json_file.exists():
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        print(f"✅ JSON exists: {len(data['tickers'])} stocks")
        print("First 3:", [s['code'] for s in data['tickers'][:3]])
else:
    print("❌ JSON file not found")

# Test main.py function
from main import load_monitor_list
config = {'data': {'monitor_list_file': 'data/monitor_list.txt'}}
tickers = load_monitor_list(config)
print(f"main.py load_monitor_list() returned: {len(tickers)} stocks")
print("First 3:", tickers[:3])

# Test data_fetch_manager function  
from src.data_fetch_manager import load_monitor_list as fetch_load
tickers2 = fetch_load()
print(f"data_fetch_manager.load_monitor_list() returned: {len(tickers2)} stocks")
print("First 3:", tickers2[:3])
