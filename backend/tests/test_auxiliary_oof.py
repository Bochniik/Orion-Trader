from app.services.auxiliary_oof import expanding_oof_auxiliary_predictions

def test_oof_is_strictly_causal():
    x = [[float(i)] for i in range(8)]
    y = [float(2*i+1) for i in range(8)]
    rows = expanding_oof_auxiliary_predictions(x, y, y, min_observations=3)
    assert rows[2].status == "NO_TRADE"
    assert rows[3].status == "OK"
    assert rows[3].training_end_index == 2
    assert rows[-1].training_end_index == len(x)-2

def test_missing_target_is_not_imputed():
    x = [[float(i)] for i in range(6)]
    rows = expanding_oof_auxiliary_predictions(x, [1.0,None,3.0,4.0,5.0,6.0], [1.,2.,3.,4.,5.,6.], min_observations=3)
    assert rows[3].status == "NO_TRADE"
    assert rows[3].reason == "insufficient_training_data"
    assert rows[4].status == "OK"

def test_length_mismatch_fails_closed():
    rows = expanding_oof_auxiliary_predictions([[1.0],[2.0]], [1.0], [1.0,2.0], min_observations=2)
    assert len(rows) == 2
    assert all(r.status == "NO_TRADE" and r.reason == "length_mismatch" for r in rows)
