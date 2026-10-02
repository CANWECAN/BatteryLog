from collections.abc import Iterator
from typing import Protocol

import pandas as pd

from batterylog.config import SignalMapping


class MeasurementLoader(Protocol):
    """Yield source-named scalar measurements in source row order.

    The engine owns canonical mapping and required-value validation. Adapters
    must preserve missing/invalid values, stable signal identities and aligned
    rows, without interpolating or silently dropping defects. Physical units
    and source preparation follow docs/MEASUREMENT_CONTRACT.md.
    """

    @property
    def source_format(self) -> str: ...

    def iter_chunks(
        self,
        *,
        signal_mapping: SignalMapping | None,
    ) -> Iterator[pd.DataFrame]: ...
