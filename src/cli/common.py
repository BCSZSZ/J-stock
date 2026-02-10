import sys
import json
from pathlib import Path


def load_config() -> dict:
    """Load config.json or exit with error."""
    config_path = Path("config.json")
    if not config_path.exists():
        print("❌ 错误: config.json 不存在")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_monitor_list(config: dict) -> list:
    """Load monitor list from JSON (preferred) or TXT fallback."""
    json_file = Path("data/monitor_list.json")
    if json_file.exists():
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [stock["code"] for stock in data["tickers"]]

    list_file = Path(config["data"]["monitor_list_file"])
    if not list_file.exists():
        print(f"❌ 错误: 监视列表文件不存在 {list_file}")
        sys.exit(1)

    tickers = []
    with open(list_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                tickers.append(line)

    return tickers
