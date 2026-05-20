"""Ergun 式によるラジアルフロー反応器の圧力損失計算。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErgunParameters:
    """Ergun 式に使う固定パラメータ。"""

    pellet_diameter_m: float
    bed_void_fraction: float
    catalyst_bulk_density_kg_m3: float
    ergun_a: float = 1.75
    ergun_b: float = 150.0
    gas_viscosity_pa_s: float = 4.0e-5

    def __post_init__(self) -> None:
        """圧損パラメータの範囲を確認する。"""
        if self.pellet_diameter_m <= 0.0:
            raise ValueError("pellet_diameter_m must be positive")
        if self.bed_void_fraction <= 0.0 or self.bed_void_fraction >= 1.0:
            raise ValueError("bed_void_fraction must be between 0 and 1")
        if self.catalyst_bulk_density_kg_m3 <= 0.0:
            raise ValueError("catalyst_bulk_density_kg_m3 must be positive")
        if self.ergun_a <= 0.0:
            raise ValueError("ergun_a must be positive")
        if self.ergun_b <= 0.0:
            raise ValueError("ergun_b must be positive")
        if self.gas_viscosity_pa_s <= 0.0:
            raise ValueError("gas_viscosity_pa_s must be positive")


def ergun_pressure_gradient_pa_per_m(
    superficial_mass_velocity_kg_m2_s: float,
    gas_density_kg_m3: float,
    parameters: ErgunParameters,
) -> float:
    """半径方向の Ergun 圧力勾配 dP/dr を Pa/m で返す。"""
    if superficial_mass_velocity_kg_m2_s < 0.0:
        raise ValueError("superficial_mass_velocity_kg_m2_s must be non-negative")
    if gas_density_kg_m3 <= 0.0:
        raise ValueError("gas_density_kg_m3 must be positive")

    eps = parameters.bed_void_fraction
    dp = parameters.pellet_diameter_m
    mu = parameters.gas_viscosity_pa_s
    g = superficial_mass_velocity_kg_m2_s
    viscous = parameters.ergun_b * (1.0 - eps) ** 2 * mu * g / (eps**3 * dp**2 * gas_density_kg_m3)
    inertial = parameters.ergun_a * (1.0 - eps) * g**2 / (eps**3 * dp * gas_density_kg_m3)
    return -(viscous + inertial)


def reynolds_over_one_minus_void(
    superficial_mass_velocity_kg_m2_s: float,
    parameters: ErgunParameters,
) -> float:
    """Leite et al. の Ergun 係数適用範囲に使う Re/(1-eps) を返す。"""
    reynolds = (
        superficial_mass_velocity_kg_m2_s
        * parameters.pellet_diameter_m
        / max(parameters.gas_viscosity_pa_s, 1e-18)
    )
    return reynolds / max(1.0 - parameters.bed_void_fraction, 1e-18)
