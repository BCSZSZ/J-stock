from pathlib import Path

from src.utils.industry_filter import (
    IndustryFilterConfig,
    evaluate_industry_filter_for_ranked_tickers,
    get_industry_name,
    normalize_ticker_code,
)


def _reference_file() -> Path:
    directory = Path("tmp/test_industry_filter")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "jpx_final_list.csv"
    path.write_text(
        "\n".join(
            [
                "Yahoo_Ticker,Code,銘柄名,Type,市場・商品区分,33業種区分,規模区分",
                "8306.T,8306,三菱ＵＦＪ,Stock,Prime,銀行業,TOPIX Core30",
                "8308.T,8308,りそな,Stock,Prime,銀行業,TOPIX Large70",
                "8411.T,8411,みずほ,Stock,Prime,銀行業,TOPIX Core30",
                "7203.T,7203,トヨタ,Stock,Prime,輸送用機器,TOPIX Core30",
                "1306.T,1306,TOPIX ETF,ETF,ETF,-,-",
            ]
        ),
        encoding="utf-8-sig",
    )
    return path


def test_normalize_ticker_code_supports_common_jpx_forms() -> None:
    assert normalize_ticker_code("8306") == "8306"
    assert normalize_ticker_code("8306.T") == "8306"
    assert normalize_ticker_code("8306.0") == "8306"
    assert normalize_ticker_code(8306) == "8306"


def test_get_industry_name_loads_jpx_reference_file() -> None:
    reference_file = _reference_file()

    assert get_industry_name("8306.T", str(reference_file)) == "銀行業"
    assert get_industry_name("1306", str(reference_file)) == "Unknown"
    assert get_industry_name("9999", str(reference_file)) == "Unknown"


def test_industry_filter_keeps_first_ranked_buy_per_day() -> None:
    reference_file = _reference_file()
    config = IndustryFilterConfig(
        mode="enforce",
        max_buy_per_industry_per_day=1,
        max_total_positions_per_industry=3,
        reference_file=str(reference_file),
    )

    decisions = evaluate_industry_filter_for_ranked_tickers(
        ["8411", "8306", "7203"],
        config,
        existing_position_tickers=["8308"],
    )

    assert decisions["8411"].filtered is False
    assert decisions["8411"].industry_existing_positions == 1
    assert decisions["8411"].industry_total_positions_after_buy == 2
    assert decisions["8306"].filtered is True
    assert decisions["8306"].industry_filter_daily_cap_blocked is True
    assert decisions["7203"].filtered is False


def test_industry_filter_blocks_when_total_position_cap_is_reached() -> None:
    reference_file = _reference_file()
    config = IndustryFilterConfig(
        mode="enforce",
        max_buy_per_industry_per_day=1,
        max_total_positions_per_industry=3,
        reference_file=str(reference_file),
    )

    decisions = evaluate_industry_filter_for_ranked_tickers(
        ["8411"],
        config,
        existing_position_tickers=["8306", "8308", "8411.T"],
    )

    assert decisions["8411"].filtered is True
    assert decisions["8411"].industry_filter_total_position_blocked is True
    assert "3/3 reached" in str(decisions["8411"].reason)


def test_industry_filter_add_on_buy_does_not_count_as_new_total_position() -> None:
    reference_file = _reference_file()
    config = IndustryFilterConfig(
        mode="enforce",
        max_buy_per_industry_per_day=1,
        max_total_positions_per_industry=1,
        reference_file=str(reference_file),
    )

    decisions = evaluate_industry_filter_for_ranked_tickers(
        ["8306"],
        config,
        existing_position_tickers=["8306"],
        add_on_tickers=["8306"],
    )

    assert decisions["8306"].filtered is False
    assert decisions["8306"].industry_filter_total_position_blocked is False
    assert decisions["8306"].industry_total_positions_after_buy == 1


def test_industry_filter_add_on_buy_still_counts_toward_daily_buy_cap() -> None:
    reference_file = _reference_file()
    config = IndustryFilterConfig(
        mode="enforce",
        max_buy_per_industry_per_day=1,
        max_total_positions_per_industry=3,
        reference_file=str(reference_file),
    )

    decisions = evaluate_industry_filter_for_ranked_tickers(
        ["8306", "8411"],
        config,
        existing_position_tickers=["8306"],
        add_on_tickers=["8306"],
    )

    assert decisions["8306"].filtered is False
    assert decisions["8411"].filtered is True
    assert decisions["8411"].industry_filter_daily_cap_blocked is True


def test_industry_filter_shadow_mode_marks_without_filtering() -> None:
    reference_file = _reference_file()
    config = IndustryFilterConfig(
        mode="shadow",
        max_buy_per_industry_per_day=1,
        max_total_positions_per_industry=3,
        reference_file=str(reference_file),
    )

    decisions = evaluate_industry_filter_for_ranked_tickers(
        ["8411", "8306"],
        config,
    )

    assert decisions["8306"].blocked is True
    assert decisions["8306"].filtered is False
    assert decisions["8306"].shadowed is True
