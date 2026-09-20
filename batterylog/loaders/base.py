from collections.abc import Iterator
from typing import Protocol

import pandas as pd

from batterylog.config import SignalMapping


class MeasurementLoader(Protocol):
    """Source adapter that yields measurement frames for the validation engine."""

    source_format: str

    def iter_chunks(
        self,
        *,
        signal_mapping: SignalMapping | None,
    ) -> Iterator[pd.DataFrame]: ...
