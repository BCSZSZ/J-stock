from dataclasses import dataclass
from typing import Literal, Mapping, cast


EvaluationCapacityMode = Literal["off", "enforce"]
ProductionCapacityMode = Literal["off", "shadow", "enforce"]


class ConfigValidationError(ValueError):
    """Raised when the runtime config violates the canonical schema."""

    def __init__(self, message: str, state: dict[str, object]) -> None:
        super().__init__(message)
        self.state = state


@dataclass(frozen=True)
class CapacityTierConfig:
    name: str
    max_equity_jpy: float | None
    max_positions: int
    max_position_pct: float
    participation_cap_pct: float
    min_turnover_20_jpy: float

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "max_equity_jpy": self.max_equity_jpy,
            "max_positions": self.max_positions,
            "max_position_pct": self.max_position_pct,
            "participation_cap_pct": self.participation_cap_pct,
            "min_turnover_20_jpy": self.min_turnover_20_jpy,
        }


@dataclass(frozen=True)
class CapacityRegimeConfig:
    version: str
    equity_window_days: int
    turnover_field: str
    tiers: tuple[CapacityTierConfig, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "equity_window_days": self.equity_window_days,
            "turnover_field": self.turnover_field,
            "tiers": [tier.to_dict() for tier in self.tiers],
        }


def _as_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if isinstance(value, dict):
        return cast(Mapping[str, object], value)
    raise ConfigValidationError(
        f"Invalid config object at {path}",
        {"path": path, "value_type": type(value).__name__},
    )


def _read_required_str(data: Mapping[str, object], *, key: str, path: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ConfigValidationError(
        f"Missing or invalid string at {path}.{key}",
        {"path": f"{path}.{key}", "value": value},
    )


def _read_required_int(data: Mapping[str, object], *, key: str, path: str) -> int:
    value = data.get(key)
    if isinstance(value, bool):
        raise ConfigValidationError(
            f"Invalid integer at {path}.{key}",
            {"path": f"{path}.{key}", "value": value},
        )
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ConfigValidationError(
        f"Missing or invalid integer at {path}.{key}",
        {"path": f"{path}.{key}", "value": value},
    )


def _read_required_float(data: Mapping[str, object], *, key: str, path: str) -> float:
    value = data.get(key)
    if isinstance(value, bool):
        raise ConfigValidationError(
            f"Invalid float at {path}.{key}",
            {"path": f"{path}.{key}", "value": value},
        )
    if isinstance(value, (int, float)):
        return float(value)
    raise ConfigValidationError(
        f"Missing or invalid float at {path}.{key}",
        {"path": f"{path}.{key}", "value": value},
    )


def _read_optional_float(data: Mapping[str, object], *, key: str, path: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ConfigValidationError(
            f"Invalid float at {path}.{key}",
            {"path": f"{path}.{key}", "value": value},
        )
    if isinstance(value, (int, float)):
        return float(value)
    raise ConfigValidationError(
        f"Invalid optional float at {path}.{key}",
        {"path": f"{path}.{key}", "value": value},
    )


def parse_capacity_regime(section: object) -> CapacityRegimeConfig:
    data = _as_mapping(section, path="capacity_regime")
    version = _read_required_str(data, key="version", path="capacity_regime")
    equity_window_days = _read_required_int(
        data, key="equity_window_days", path="capacity_regime"
    )
    turnover_field = _read_required_str(
        data, key="turnover_field", path="capacity_regime"
    )

    raw_tiers = data.get("tiers")
    if not isinstance(raw_tiers, list) or not raw_tiers:
        raise ConfigValidationError(
            "capacity_regime.tiers must be a non-empty list",
            {"path": "capacity_regime.tiers", "value": raw_tiers},
        )

    tiers: list[CapacityTierConfig] = []
    seen_names: set[str] = set()
    for index, raw_tier in enumerate(raw_tiers):
        tier_path = f"capacity_regime.tiers[{index}]"
        tier_data = _as_mapping(raw_tier, path=tier_path)
        name = _read_required_str(tier_data, key="name", path=tier_path)
        if name in seen_names:
            raise ConfigValidationError(
                f"Duplicate capacity tier name: {name}",
                {"path": tier_path, "name": name},
            )
        seen_names.add(name)

        tiers.append(
            CapacityTierConfig(
                name=name,
                max_equity_jpy=_read_optional_float(
                    tier_data, key="max_equity_jpy", path=tier_path
                ),
                max_positions=_read_required_int(
                    tier_data, key="max_positions", path=tier_path
                ),
                max_position_pct=_read_required_float(
                    tier_data, key="max_position_pct", path=tier_path
                ),
                participation_cap_pct=_read_required_float(
                    tier_data, key="participation_cap_pct", path=tier_path
                ),
                min_turnover_20_jpy=_read_required_float(
                    tier_data, key="min_turnover_20_jpy", path=tier_path
                ),
            )
        )

    if tiers[-1].max_equity_jpy is not None:
        raise ConfigValidationError(
            "The final capacity tier must have max_equity_jpy = null",
            {
                "path": f"capacity_regime.tiers[{len(tiers) - 1}].max_equity_jpy",
                "value": tiers[-1].max_equity_jpy,
            },
        )

    return CapacityRegimeConfig(
        version=version,
        equity_window_days=equity_window_days,
        turnover_field=turnover_field,
        tiers=tuple(tiers),
    )


def parse_evaluation_capacity_mode(value: object) -> EvaluationCapacityMode:
    if value in {"off", "enforce"}:
        return cast(EvaluationCapacityMode, value)
    raise ConfigValidationError(
        "evaluation.capacity_regime_mode must be 'off' or 'enforce'",
        {"path": "evaluation.capacity_regime_mode", "value": value},
    )


def parse_production_capacity_mode(value: object) -> ProductionCapacityMode:
    if value in {"off", "shadow", "enforce"}:
        return cast(ProductionCapacityMode, value)
    raise ConfigValidationError(
        "production.capacity_regime_mode must be 'off', 'shadow', or 'enforce'",
        {"path": "production.capacity_regime_mode", "value": value},
    )