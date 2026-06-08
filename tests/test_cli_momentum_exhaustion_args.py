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
            ]
        )
        assert args.momentum_exhaustion_mode == "enforce"
        assert args.momentum_exhaustion_max_score == 4.0
        assert args.momentum_exhaustion_threshold_method == "absolute"
