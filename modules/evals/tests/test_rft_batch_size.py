import pytest

from caliber.rft_preflight import _hyperparameter_errors


@pytest.mark.parametrize("value", [-1, 0, 257, True, "auto"])
def test_rejects_batch_sizes_the_foundry_trainer_cannot_accept(value):
    assert any("batch_size" in error for error in _hyperparameter_errors({"batch_size": value}))


@pytest.mark.parametrize("values", [{}, {"batch_size": 1}, {"batch_size": 256}])
def test_automatic_omission_and_explicit_boundaries_are_supported(values):
    assert _hyperparameter_errors(values) == []
