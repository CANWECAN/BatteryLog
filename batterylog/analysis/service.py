"""Shared analysis entry point for CLI and application callers."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from batterylog.config import ValidationConfig
from batterylog.loaders import (
    MeasurementLoader,
    measurement_loader_for_file,
    measurement_loader_for_path,
)
from batterylog.models import AnalysisResult

from .report_series import ReportSeries, ReportSeriesCollector
from .streaming import _analyze_battery_chunks


@dataclass(frozen=True)
class AnalysisOutput:
    """Canonical result and optional display geometry from the same analysis."""

    result: AnalysisResult
    report_series: ReportSeries | None = None


@dataclass(frozen=True)
class AnalysisService:
    """Run measurements with one effective config and no per-run service state.

    Report collection is opt-in through a point budget. Source snapshots,
    provenance, output files and process exit codes belong to the caller.
    """

    config: ValidationConfig = field(default_factory=ValidationConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.config, ValidationConfig):
            raise TypeError("config must be a ValidationConfig instance")

    def analyze_loader(
        self,
        loader: MeasurementLoader,
        *,
        report_max_points: int | None = None,
    ) -> AnalysisOutput:
        collector = (
            ReportSeriesCollector(max_points=report_max_points)
            if report_max_points is not None
            else None
        )
        result = _analyze_battery_chunks(
            loader.iter_chunks(signal_mapping=self.config.signals),
            limits=self.config.limits,
            event_detection=self.config.event_detection,
            data_quality=self.config.data_quality,
            signal_mapping=self.config.signals,
            report_series_collector=collector,
        )
        return AnalysisOutput(result, collector.finish() if collector is not None else None)

    def analyze_path(
        self,
        path: str | Path,
        *,
        report_max_points: int | None = None,
    ) -> AnalysisOutput:
        return self.analyze_loader(
            measurement_loader_for_path(path),
            report_max_points=report_max_points,
        )

    def analyze_file(
        self,
        handle: BinaryIO,
        *,
        source_name: str | Path | None = None,
        report_max_points: int | None = None,
    ) -> AnalysisOutput:
        """Analyze a caller-owned seekable handle; source_name selects its format."""
        return self.analyze_loader(
            measurement_loader_for_file(handle, source_name=source_name),
            report_max_points=report_max_points,
        )
