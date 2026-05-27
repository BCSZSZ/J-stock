import os
from datetime import datetime
from pathlib import Path

import pytest

from src.production.input_trade_import_preview import (
    aggregate_sbi_trades_for_date,
    find_latest_sbi_history_csv,
    format_sbi_history_mtime,
    parse_sbi_trade_history_csv,
)


SBI_SAMPLE_CSV = """約定履歴照会

商品指定,約定開始年月日,約定終了年月日,明細数,明細指定開始,明細指定終了
\"すべての商品\",\"2026年05月26日\",\"2026年05月27日\",\"6\",\"1\",\"6\"

（注）明細数はご指定された期間の合計です。

約定日,銘柄,銘柄コード,市場,取引,期限,預り,課税,約定数量,約定単価,手数料/諸経費等,税額,受渡日,受渡金額/決済損益
\"2026/05/26\",\"シップヘルスケアホールディングス\",\"3360\",\"東証\",株式現物買,\"--\",\" 特定 \",\"--\",100,2108,--,--,\"2026/05/28\",210800
\"2026/05/26\",\"日本製鉄\",\"5401\",\"東証\",株式現物買,\"--\",\" 特定 \",\"--\",100,555.3,--,--,\"2026/05/28\",55530
\"2026/05/26\",\"日本製鉄\",\"5401\",\"東証\",株式現物買,\"--\",\" 特定 \",\"--\",2000,555.4,--,--,\"2026/05/28\",1110800
\"2026/05/26\",\"日本製鉄\",\"5401\",\"東証（外）\",株式現物買,\"--\",\" 特定 \",\"--\",300,555.3,--,--,\"2026/05/28\",166590
\"2026/05/26\",\"日本製鉄\",\"5401\",\"PTS（X）\",株式現物買,\"--\",\" 特定 \",\"--\",100,555.3,--,--,\"2026/05/28\",55530
\"2026/05/26\",\"パナソニック　ホールディングス\",\"6752\",\"東証\",株式現物売,\"--\",\" 特定 \",\"申告\",200,3590,--,--,\"2026/05/28\",718000
"""


def _write_cp932_csv(path: Path, content: str) -> None:
    path.write_text(content, encoding="cp932")


def test_parse_sbi_trade_history_csv_decodes_cp932_and_maps_actions(tmp_path: Path) -> None:
    csv_path = tmp_path / "SaveFile_latest.csv"
    _write_cp932_csv(csv_path, SBI_SAMPLE_CSV)

    records = parse_sbi_trade_history_csv(csv_path)

    assert len(records) == 6
    assert records[0].trade_date == "2026-05-26"
    assert records[0].ticker == "3360"
    assert records[0].action == "BUY"
    assert records[-1].ticker == "6752"
    assert records[-1].action == "SELL"


def test_find_latest_sbi_history_csv_uses_mtime(tmp_path: Path) -> None:
    older = tmp_path / "SaveFile_older.csv"
    latest = tmp_path / "SaveFile_latest.csv"
    _write_cp932_csv(older, SBI_SAMPLE_CSV)
    _write_cp932_csv(latest, SBI_SAMPLE_CSV)

    os.utime(older, (100, 100))
    os.utime(latest, (200, 200))

    found = find_latest_sbi_history_csv(str(tmp_path))

    assert found == latest
    assert format_sbi_history_mtime(found) == datetime.fromtimestamp(200).isoformat(timespec="seconds")


def test_aggregate_sbi_trades_for_date_merges_partial_fills(tmp_path: Path) -> None:
    csv_path = tmp_path / "SaveFile_latest.csv"
    _write_cp932_csv(csv_path, SBI_SAMPLE_CSV)

    records = parse_sbi_trade_history_csv(csv_path)
    aggregated = aggregate_sbi_trades_for_date(records, "2026-05-26")

    assert [trade.ticker for trade in aggregated] == ["6752", "3360", "5401"]
    steel = next(trade for trade in aggregated if trade.ticker == "5401")
    assert steel.action == "BUY"
    assert steel.quantity == 2500
    assert steel.fill_count == 4
    assert steel.price == pytest.approx(555.38)
    assert steel.markets == ("PTS（X）", "東証", "東証（外）")