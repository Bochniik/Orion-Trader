"""Central, conservative configuration for continuous research scanning."""
import os
from dataclasses import asdict, dataclass

from app.services.staged_market_scanner import ScannerConfig


@dataclass(frozen=True)
class ScannerSettings:
    enabled: bool = True
    broad_interval_seconds: int = 600
    active_interval_seconds: int = 120
    page_size: int = 250
    activity_limit: int = 100
    fast_limit: int = 30
    full_analysis_limit: int = 15
    result_limit: int = 10
    active_limit: int = 50
    active_ttl_seconds: int = 1800
    inactive_cycles: int = 3
    ideal_feature_age_seconds: int = 120
    maximum_feature_age_seconds: int = 1200
    snapshot_ttl_seconds: int = 300
    delayed_penalty_points: int = 10
    minimum_cycle_gap_seconds: int = 60
    universe_cache_seconds: int = 3600
    daily_cache_seconds: int = 3600
    minute_cache_seconds: int = 60
    cache_symbols: int = 2000
    provider_chunk_size: int = 10
    provider_spacing_seconds: int = 1

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == "enabled":
                if not isinstance(value, bool):
                    raise ValueError("enabled must be boolean")
            elif isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.active_interval_seconds < 60 or self.broad_interval_seconds < 300:
            raise ValueError("Minimum scanner intervals: active 60s, broad 300s")
        if self.broad_interval_seconds <= self.active_interval_seconds:
            raise ValueError("Broad interval must exceed active interval")
        if not 60 <= self.minimum_cycle_gap_seconds <= self.active_interval_seconds:
            raise ValueError("Cycle spacing must be at least 60s and cannot exceed active interval")
        if not self.ideal_feature_age_seconds < self.maximum_feature_age_seconds <= 1200:
            raise ValueError("Ideal feature age must be below technical ceiling (at most 1200s)")
        if self.active_limit > 200 or self.provider_chunk_size > 10 or self.delayed_penalty_points > 100:
            raise ValueError("Active/provider/penalty safety bound exceeded")
        if self.active_limit > self.page_size:
            raise ValueError("Active set must fit in one scanner page")
        self.stage_config()

    def stage_config(self):
        return ScannerConfig(universe_limit=self.page_size, activity_limit=self.activity_limit,
                             fast_limit=self.fast_limit, analysis_limit=self.full_analysis_limit,
                             return_limit=self.result_limit,
                             maximum_feature_age_seconds=self.maximum_feature_age_seconds)

    @classmethod
    def from_env(cls, environ=None):
        environ = os.environ if environ is None else environ
        defaults = asdict(cls())
        values = {}
        for name, default in defaults.items():
            key = "ORION_SCANNER_" + name.upper()
            raw = environ.get(key)
            if raw is None:
                values[name] = default
            elif name == "enabled":
                if raw.lower() not in {"true", "false"}:
                    raise ValueError(f"{key} must be true or false")
                values[name] = raw.lower() == "true"
            else:
                try:
                    values[name] = int(raw)
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be an integer") from None
        return cls(**values)
