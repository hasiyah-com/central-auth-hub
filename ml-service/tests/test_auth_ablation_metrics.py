import numpy as np

from scripts.ablate_auth_context import rates, roc_recall, GROUPS
from scripts.compare_auth_context import CONTEXT_NAMES


def test_rates_do_not_confuse_false_positives_with_attack_recall():
    y = np.asarray([0, 0, 0, 1, 1])
    result = rates(y, np.asarray([True, False, False, True, False]))
    assert result == {"normal": 3, "attack": 2, "fpr": 1/3, "recall": .5}
    assert rates(np.asarray([1]), np.asarray([True]))["fpr"] is None


def test_low_fpr_recall_respects_tied_scores():
    y = np.asarray([0, 0, 1, 1])
    assert roc_recall(y, np.asarray([.8, .1, .8, .9]), 0) == .5


def test_groups_cover_every_context_parameter_exactly_once():
    assert [feature for group in GROUPS.values() for feature in group] == CONTEXT_NAMES
