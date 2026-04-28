"""反応器モデルで使う既定定数。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UniversalConstants:
    """物理定数。"""

    gas_constant_j_per_mol_k: float = 8.31446
    reference_temperature_k: float = 298.15
    pa_per_kpa: float = 1000.0


@dataclass(frozen=True)
class SpeciesThermo:
    """気相物性と標準生成エンタルピー。"""

    heat_capacity_a: float
    heat_capacity_b: float
    heat_capacity_c: float
    heat_capacity_d: float
    heat_of_formation_kj_per_kmol: float


@dataclass(frozen=True)
class ThermoConstants:
    """成分物性。"""

    hydrogen: SpeciesThermo = SpeciesThermo(27.144, 9.274e-3, -1.381e-5, 7.645e-9, 0.0)
    co: SpeciesThermo = SpeciesThermo(30.871, -1.285e-2, 2.789e-5, -1.272e-8, -110_600.0)
    methane: SpeciesThermo = SpeciesThermo(19.252, 5.213e-2, 1.197e-5, -1.132e-8, -74_900.0)
    ethylene: SpeciesThermo = SpeciesThermo(3.806, 1.566e-1, -8.349e-5, 1.755e-8, 52_300.0)
    co2: SpeciesThermo = SpeciesThermo(19.796, 7.344e-2, -5.602e-5, 1.715e-8, -393_800.0)
    benzene: SpeciesThermo = SpeciesThermo(-33.919, 4.744e-1, -2.942e-4, 7.130e-8, 83_000.0)
    steam: SpeciesThermo = SpeciesThermo(32.244, 1.924e-3, 1.056e-5, -3.597e-9, -242_000.0)
    toluene: SpeciesThermo = SpeciesThermo(-24.356, 5.125e-1, -2.766e-4, 4.911e-8, 50_000.0)
    eb: SpeciesThermo = SpeciesThermo(-43.101, 7.072e-1, -4.811e-4, 1.301e-7, 29_800.0)
    styrene: SpeciesThermo = SpeciesThermo(-28.250, 6.159e-1, -4.023e-4, 9.936e-8, 147_500.0)

    def by_name(self, name: str) -> SpeciesThermo:
        """成分名から物性を返す。"""
        return getattr(self, name)


@dataclass(frozen=True)
class KineticsConstants:
    """3反応の速度定数。"""

    k11_pre_exponential: float = 1.090e6
    k11_activation_energy_j_per_mol: float = 74_170.0

    k12_pre_exponential: float = 0.1929
    k12_activation_energy_j_per_mol: float = -50_409.0

    k2_pre_exponential: float = 5.690e9
    k2_activation_energy_j_per_mol: float = 160_620.0

    k3_pre_exponential: float = 2.490e10
    k3_activation_energy_j_per_mol: float = 165_100.0


@dataclass(frozen=True)
class ReactorOperationDefaults:
    """反応器の参照条件。"""

    pressure_kpa: float = 101.325
    stage_inlet_temperatures_c: tuple[float, float, float] = (545.4, 571.0, 605.9)
    stage_lengths_m: tuple[float, float, float] = (3.09, 3.09, 3.09)
    inlet_superficial_velocity_m_per_s: float = 1.93
    segments_per_stage: int = 80
    profile_points_per_stage: int = 12


@dataclass(frozen=True)
class ReactorConfigDefaults:
    universal: UniversalConstants = UniversalConstants()
    thermo: ThermoConstants = ThermoConstants()
    kinetics: KineticsConstants = KineticsConstants()
    operation: ReactorOperationDefaults = ReactorOperationDefaults()


DEFAULT_REACTOR_CONFIG = ReactorConfigDefaults()
