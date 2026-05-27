import json
from pathlib import Path
from types import SimpleNamespace

from web.api.routers import production as production_router


SBI_SAMPLE_CSV = """約定履歴照会

商品指定,約定開始年月日,約定終了年月日,明細数,明細指定開始,明細指定終了
\"すべての商品\",\"2026年05月26日\",\"2026年05月27日\",\"5\",\"1\",\"5\"

（注）明細数はご指定された期間の合計です。

約定日,銘柄,銘柄コード,市場,取引,期限,預り,課税,約定数量,約定単価,手数料/諸経費等,税額,受渡日,受渡金額/決済損益
\"2026/05/26\",\"シップヘルスケアホールディングス\",\"3360\",\"東証\",株式現物買,\"--\",\" 特定 \",\"--\",100,2108,--,--,\"2026/05/28\",210800
\"2026/05/26\",\"日本製鉄\",\"5401\",\"東証\",株式現物買,\"--\",\" 特定 \",\"--\",100,555.3,--,--,\"2026/05/28\",55530
\"2026/05/26\",\"日本製鉄\",\"5401\",\"東証\",株式現物買,\"--\",\" 特定 \",\"--\",2000,555.4,--,--,\"2026/05/28\",1110800
\"2026/05/26\",\"日本製鉄\",\"5401\",\"PTS（X）\",株式現物買,\"--\",\" 特定 \",\"--\",100,555.3,--,--,\"2026/05/28\",55530
\"2026/05/26\",\"パナソニック　ホールディングス\",\"6752\",\"東証\",株式現物売,\"--\",\" 特定 \",\"申告\",200,3590,--,--,\"2026/05/28\",718000
"""


def _write_signal_file(path: Path, payload: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_sbi_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="cp932")


def test_input_trade_import_preview_prefers_csv_and_warns_on_mismatches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    signal_path = tmp_path / "signals" / "2026-05-25.json"
    history_dir = tmp_path / "historySBI"
    csv_path = history_dir / "SaveFile_latest.csv"

    _write_signal_file(
        signal_path,
        [
            {"ticker": "3360", "signal_type": "BUY", "suggested_qty": 100},
            {"ticker": "5401", "signal_type": "BUY", "suggested_qty": 2000},
            {"ticker": "6752", "signal_type": "BUY", "suggested_qty": 200},
            {"ticker": "9302", "signal_type": "BUY", "suggested_qty": 200},
        ],
    )
    _write_sbi_file(csv_path, SBI_SAMPLE_CSV)

    monkeypatch.setattr(
        production_router,
        "get_production_config",
        lambda: SimpleNamespace(
            signal_file_pattern=str(tmp_path / "signals" / "{date}.json"),
            sbi_history_dir=str(history_dir),
        ),
    )

    result = production_router.input_trade_import_preview("2026-05-25")

    assert result.mode == "csv_authoritative"
    assert result.trade_date == "2026-05-26"
    assert [(row.ticker, row.action) for row in result.rows] == [
        ("3360", "BUY"),
        ("5401", "BUY"),
        ("6752", "SELL"),
    ]
    assert result.matched_count == 2
    assert result.csv_only_count == 0
    assert result.signal_only_count == 1
    assert any("5401: signal qty 2000 differs" in warning for warning in result.warnings)
    assert any("6752: signal action BUY differs" in warning for warning in result.warnings)
    assert any("9302: signal row was not found" in warning for warning in result.warnings)
    steel_row = next(row for row in result.rows if row.ticker == "5401")
    assert steel_row.quantity == 2200
    assert steel_row.price == 555.390909


def test_input_trade_import_preview_falls_back_to_signals_when_latest_csv_has_no_trade_date(
    tmp_path: Path,
    monkeypatch,
) -> None:
    signal_path = tmp_path / "signals" / "2026-05-26.json"
    history_dir = tmp_path / "historySBI"
    csv_path = history_dir / "SaveFile_latest.csv"

    _write_signal_file(
        signal_path,
        [
            {"ticker": "3360", "signal_type": "BUY", "suggested_qty": 100},
        ],
    )
    _write_sbi_file(csv_path, SBI_SAMPLE_CSV)

    monkeypatch.setattr(
        production_router,
        "get_production_config",
        lambda: SimpleNamespace(
            signal_file_pattern=str(tmp_path / "signals" / "{date}.json"),
            sbi_history_dir=str(history_dir),
        ),
    )

    result = production_router.input_trade_import_preview("2026-05-26")

    assert result.mode == "signal_fallback"
    assert result.trade_date == "2026-05-27"
    assert [(row.ticker, row.price) for row in result.rows] == [("3360", None)]
    assert any("No rows for trade date 2026-05-27" in warning for warning in result.warnings)