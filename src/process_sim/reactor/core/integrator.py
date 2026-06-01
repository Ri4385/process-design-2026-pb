"""数値積分器。"""

from __future__ import annotations

from collections.abc import Callable

def rk4_step(
    state_vector: list[float],
    dz: float,
    derivative: Callable[[list[float]], list[float]],
) -> list[float]:
    """4次 Runge-Kutta 法で1ステップ進める。"""
    return _rk4_step_python(state_vector=state_vector, step=dz, derivative=derivative)


def rk4_step_with_position(
    state_vector: list[float],
    position: float,
    step: float,
    derivative: Callable[[list[float], float], list[float]],
) -> list[float]:
    """位置に依存する微分関数を4次 Runge-Kutta 法で1ステップ進める。"""
    return _rk4_step_with_position_python(
        state_vector=state_vector,
        position=position,
        step=step,
        derivative=derivative,
    )


def _rk4_step_python(
    state_vector: list[float],
    step: float,
    derivative: Callable[[list[float]], list[float]],
) -> list[float]:
    k1 = derivative(state_vector)
    k2 = derivative(_vector_add(state_vector, _vector_scale(k1, step / 2.0)))
    k3 = derivative(_vector_add(state_vector, _vector_scale(k2, step / 2.0)))
    k4 = derivative(_vector_add(state_vector, _vector_scale(k3, step)))
    next_state = state_vector[:]
    for index in range(len(state_vector)):
        next_state[index] = (
            state_vector[index]
            + step * (k1[index] + 2.0 * k2[index] + 2.0 * k3[index] + k4[index]) / 6.0
        )
    return next_state


def _rk4_step_with_position_python(
    state_vector: list[float],
    position: float,
    step: float,
    derivative: Callable[[list[float], float], list[float]],
) -> list[float]:
    k1 = derivative(state_vector, position)
    k2 = derivative(_vector_add(state_vector, _vector_scale(k1, step / 2.0)), position + step / 2.0)
    k3 = derivative(_vector_add(state_vector, _vector_scale(k2, step / 2.0)), position + step / 2.0)
    k4 = derivative(_vector_add(state_vector, _vector_scale(k3, step)), position + step)
    next_state = state_vector[:]
    for index in range(len(state_vector)):
        next_state[index] = (
            state_vector[index]
            + step * (k1[index] + 2.0 * k2[index] + 2.0 * k3[index] + k4[index]) / 6.0
        )
    return next_state


def _vector_add(left: list[float], right: list[float]) -> list[float]:
    return [left_value + right_value for left_value, right_value in zip(left, right, strict=True)]


def _vector_scale(values: list[float], scale: float) -> list[float]:
    return [value * scale for value in values]
