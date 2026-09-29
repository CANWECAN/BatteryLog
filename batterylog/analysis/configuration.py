import warnings

from batterylog.config import (
    DataQualityConfig,
    EventDetectionConfig,
    SignalMapping,
    ValidationLimits,
    override_validation_limits,
)


def warn_legacy_threshold_arguments(
    imbalance_limit_v: float | None,
    temp_warning_c: float | None,
) -> None:
    if imbalance_limit_v is None and temp_warning_c is None:
        return

    warnings.warn(
        "imbalance_limit_v and temp_warning_c are deprecated; "
        "pass a ValidationLimits instance via limits=. "
        "Legacy values currently override the corresponding limits fields.",
        DeprecationWarning,
        stacklevel=3,
    )


def resolve_limits(
    limits: ValidationLimits | None,
    imbalance_limit_v: float | None,
    temp_warning_c: float | None,
) -> ValidationLimits:
    if limits is not None and not isinstance(limits, ValidationLimits):
        raise TypeError("limits must be a ValidationLimits instance or null")

    resolved = limits if limits is not None else ValidationLimits()
    return override_validation_limits(
        resolved,
        imbalance_max_v=imbalance_limit_v,
        temperature_max_c=temp_warning_c,
    )


def resolve_event_detection(
    event_detection: EventDetectionConfig | None,
) -> EventDetectionConfig:
    if event_detection is not None and not isinstance(
        event_detection,
        EventDetectionConfig,
    ):
        raise TypeError("event_detection must be an EventDetectionConfig instance or null")
    return event_detection if event_detection is not None else EventDetectionConfig()


def resolve_data_quality(data_quality: DataQualityConfig | None) -> DataQualityConfig:
    if data_quality is not None and not isinstance(data_quality, DataQualityConfig):
        raise TypeError("data_quality must be a DataQualityConfig instance or null")
    return data_quality if data_quality is not None else DataQualityConfig()


def validate_signal_mapping(signal_mapping: SignalMapping | None) -> None:
    if signal_mapping is not None and not isinstance(signal_mapping, SignalMapping):
        raise TypeError("signal_mapping must be a SignalMapping instance or null")
