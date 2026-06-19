from __future__ import annotations

from main import build_parser


def test_momentum_exhaustion_cli_flags_are_available_on_runtime_commands() -> None:
    parser = build_parser()
    commands = [
        ["evaluate"],
        ["pos-evaluation"],
        ["walk-forward-evaluate", "--years", "2024", "2025"],
        ["replay-evaluation", "--report-file", "report.md"],
        ["entry-signal-analysis"],
        ["entry-exit-validation"],
        ["production", "--daily"],
    ]

    for command in commands:
        args = parser.parse_args(
            [
                *command,
                "--momentum-exhaustion-mode",
                "enforce",
                "--momentum-exhaustion-max-score",
                "4.0",
                "--momentum-exhaustion-threshold-method",
                "absolute",
                "--industry-filter-mode",
                "enforce",
                "--max-buy-per-industry-per-day",
                "1",
                "--max-total-positions-per-industry",
                "3",
                "--industry-reference-file",
                "data/jpx_final_list.csv",
            ]
        )
        assert args.momentum_exhaustion_mode == "enforce"
        assert args.momentum_exhaustion_max_score == 4.0
        assert args.momentum_exhaustion_threshold_method == "absolute"
        assert args.industry_filter_mode == "enforce"
        assert args.max_buy_per_industry_per_day == 1
        assert args.max_total_positions_per_industry == 3
        assert args.industry_reference_file == "data/jpx_final_list.csv"


def test_allow_held_position_buys_cli_flag_is_available_on_supported_commands() -> None:
    parser = build_parser()
    supported_commands = [
        ["evaluate"],
        ["pos-evaluation"],
        ["walk-forward-evaluate", "--years", "2024", "2025"],
        ["production", "--daily"],
    ]

    for command in supported_commands:
        default_args = parser.parse_args(command)
        enabled_args = parser.parse_args([*command, "--allow-held-position-buys"])

        assert default_args.allow_held_position_buys is False
        assert enabled_args.allow_held_position_buys is True
