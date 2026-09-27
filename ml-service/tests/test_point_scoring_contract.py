from __future__ import annotations

import numpy as np

from point_scoring import score_with_model, scores_with_model


class _Estimator:
    def decision_function(self, values):
        return np.asarray([0.2 - 0.2 * row[0] for row in values], dtype=float)


def test_batch_and_scalar_use_the_same_production_transform():
    model = _Estimator()
    vectors = [[float(i)] + [0.0] * 22 for i in range(3)]
    batch = scores_with_model(model, vectors)
    assert batch == [score_with_model(model, row) for row in vectors]
    assert batch[0] < 0.5
    assert batch[1] == 0.5
    assert batch[2] > 0.5


def test_scores_are_bounded_for_extreme_estimator_output():
    class Extreme:
        def decision_function(self, values):
            return np.asarray([1e9, -1e9], dtype=float)

    low, high = scores_with_model(Extreme(), [[0.0], [0.0]])
    assert 0.0 <= low < 1e-300
    assert high == 1.0
