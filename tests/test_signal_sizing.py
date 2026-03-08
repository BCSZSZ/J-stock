from src.utils.signal_sizing import extract_buy_size_multiplier


def test_default_multiplier_without_metadata():
    assert extract_buy_size_multiplier(None) == 1.0
    assert extract_buy_size_multiplier({}) == 1.0


def test_alias_keys_supported():
    assert extract_buy_size_multiplier({"buy_size_multiplier": 0.8}) == 0.8
    assert extract_buy_size_multiplier({"position_size_multiplier": 0.7}) == 0.7
    assert extract_buy_size_multiplier({"entry_size_multiplier": 0.6}) == 0.6


def test_invalid_or_out_of_range_values_safe():
    assert extract_buy_size_multiplier({"buy_size_multiplier": "x"}) == 1.0
    assert extract_buy_size_multiplier({"buy_size_multiplier": -1}) == 0.0
    assert extract_buy_size_multiplier({"buy_size_multiplier": 1.5}) == 1.0
