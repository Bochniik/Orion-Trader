from app.services.auxiliary_oof import OOFRow
from app.services.multitask_stacking import expanding_oof_stacked_directional_predictions


def _aux(n: int):
    return [
        OOFRow(i, float(i + 1), float(i + 2), "OK", None, i - 1 if i else None)
        for i in range(n)
    ]


def test_stacker_never_trains_on_current_or_future_row():
    x = [[float(i)] for i in range(8)]
    y = [float(i % 2) for i in range(8)]
    rows = expanding_oof_stacked_directional_predictions(x, y, _aux(8), min_observations=3)
    assert rows[3].status == "OK"
    assert rows[3].training_end_index == 2
    assert rows[-1].training_end_index == 6


def test_unavailable_auxiliary_row_fails_closed():
    aux = _aux(5)
    aux[4] = OOFRow(4, None, None, "NO_TRADE", "insufficient_training_data", 3)
    rows = expanding_oof_stacked_directional_predictions(
        [[float(i)] for i in range(5)], [0., 1., 0., 1., 0.], aux, min_observations=2
    )
    assert rows[4].status == "NO_TRADE"
    assert rows[4].reason == "auxiliary_oof_unavailable"


def test_length_mismatch_fails_closed():
    rows = expanding_oof_stacked_directional_predictions([[1.0], [2.0]], [0.0], _aux(2), min_observations=2)
    assert len(rows) == 2
    assert all(row.status == "NO_TRADE" and row.reason == "length_mismatch" for row in rows)
