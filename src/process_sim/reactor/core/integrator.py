"""数値積分器。"""

from __future__ import annotations

from collections.abc import Callable


def rk4_step(
    state_vector: list[float],
    dz: float,
    derivative: Callable[[list[float]], list[float]],
) -> list[float]:
    """4次 Runge-Kutta 法で1ステップ進める。"""
    k1 = derivative(state_vector)
    k2 = derivative(_vector_add(state_vector, _vector_scale(k1, dz / 2.0)))
    k3 = derivative(_vector_add(state_vector, _vector_scale(k2, dz / 2.0)))
    k4 = derivative(_vector_add(state_vector, _vector_scale(k3, dz)))
    next_state = state_vector[:]
    for index in range(len(state_vector)):
        next_state[index] = state_vector[index] + dz * (k1[index] + 2.0 * k2[index] + 2.0 * k3[index] + k4[index]) / 6.0
    return next_state


def _vector_add(left: list[float], right: list[float]) -> list[float]:
    return [left_value + right_value for left_value, right_value in zip(left, right, strict=True)]


def _vector_scale(values: list[float], scale: float) -> list[float]:
    return [value * scale for value in values]
