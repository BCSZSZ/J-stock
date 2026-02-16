import json
import sys
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
    """Load monitor list from config-specified JSON file (single source of truth)."""
    list_file = Path(config["data"]["monitor_list_file"])

    if not list_file.exists():
        print(f"❌ 错误: 监视列表文件不存在 {list_file}")
        sys.exit(1)

    # JSON format with tickers array
    if list_file.suffix == ".json":
        with open(list_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [stock["code"] for stock in data["tickers"]]

    # TXT format (legacy support)
    tickers = []
    with open(list_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                tickers.append(line)

    return tickers
