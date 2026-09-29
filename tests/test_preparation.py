import numpy as np
import pandas as pd
import pytest

from batterylog.analysis.preparation import prepare_measurements


def test_prepare_measurements_masks_excluded_rows_from_rule_inputs() -> None:
    numeric = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0],
            "pack_voltage_v": [7.9, 99.0],
            "cell_1_v": [4.0, 99.0],
            "cell_2_v": [3.9, 99.0],
            "temp_1_c": [25.0, 99.0],
        }
    )
    invalid_rows = pd.Series([False, True])

    prepared = prepare_measurements(
        numeric,
        invalid_rows,
        pack_cols=["pack_voltage_v"],
        cell_cols=["cell_1_v", "cell_2_v"],
        temp_cols=["temp_1_c"],
        pack_current_col=None,
        pack_voltage_col="pack_voltage_v",
    )

    assert prepared.valid_rows.tolist() == [True, False]
    assert len(prepared.valid_numeric) == 1
    rule_numeric = prepared.rule_inputs.numeric
    assert rule_numeric.loc[1, "timestamp_s"] == 1.0
    for column in ["pack_voltage_v", "cell_1_v", "cell_2_v", "temp_1_c"]:
        assert np.isnan(rule_numeric.loc[1, column])

    assert prepared.rule_inputs.cell_sum is not None
    assert prepared.rule_inputs.cell_sum.iloc[0] == pytest.approx(7.9)
    assert np.isnan(prepared.rule_inputs.cell_sum.iloc[1])


@pytest.mark.parametrize(
    "numeric",
    [
        pd.DataFrame(
            {
                "timestamp_s": [0.0],
                "cell_1_v": [1e308],
                "cell_2_v": [-1e308],
                "temp_1_c": [25.0],
            }
        ),
        pd.DataFrame(
            {
                "timestamp_s": [0.0],
                "cell_1_v": [3.8],
                "temp_1_c": [1e308],
                "temp_2_c": [-1e308],
            }
        ),
    ],
)
def test_prepare_measurements_preserves_source_row_offset_on_derived_overflow(
    numeric: pd.DataFrame,
) -> None:
    cell_cols = [column for column in numeric if column.startswith("cell_")]
    temp_cols = [column for column in numeric if column.startswith("temp_")]

    with pytest.raises(ValueError, match=r"data row 50001"):
        prepare_measurements(
            numeric,
            pd.Series([False]),
            pack_cols=[],
            cell_cols=cell_cols,
            temp_cols=temp_cols,
            pack_current_col=None,
            pack_voltage_col=None,
            row_offset=50_000,
        )
