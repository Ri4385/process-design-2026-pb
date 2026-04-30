"""成分物性値。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeatCapacityCoefficients:
    """Cp = a + bT + cT^2 + dT^3 の係数。"""

    a: float
    b: float
    c: float
    d: float


@dataclass(frozen=True)
class SpeciesPhysicalProperty:
    """成分物性値。"""

    component_id: str
    display_name: str
    molecular_weight: float
    melting_point_k: float
    boiling_point_k: float
    latent_heat_kj_per_mol: float
    heat_of_formation_kj_per_kmol: float
    heat_capacity: HeatCapacityCoefficients


SPECIES_PHYSICAL_PROPERTIES: dict[str, SpeciesPhysicalProperty] = {
    "eb": SpeciesPhysicalProperty(
        component_id="eb",
        display_name="EB",
        molecular_weight=106.168,
        melting_point_k=178.2,
        boiling_point_k=409.3,
        latent_heat_kj_per_mol=35.59,
        heat_of_formation_kj_per_kmol=29_800.0,
        heat_capacity=HeatCapacityCoefficients(-43.101, 7.072e-1, -4.811e-4, 1.301e-7),
    ),
    "steam": SpeciesPhysicalProperty(
        component_id="steam",
        display_name="H2O",
        molecular_weight=18.015,
        melting_point_k=273.2,
        boiling_point_k=373.2,
        latent_heat_kj_per_mol=40.69,
        heat_of_formation_kj_per_kmol=-242_000.0,
        heat_capacity=HeatCapacityCoefficients(32.244, 1.924e-3, 1.056e-5, -3.597e-9),
    ),
    "styrene": SpeciesPhysicalProperty(
        component_id="styrene",
        display_name="SM",
        molecular_weight=104.152,
        melting_point_k=242.5,
        boiling_point_k=418.3,
        latent_heat_kj_per_mol=36.85,
        heat_of_formation_kj_per_kmol=147_500.0,
        heat_capacity=HeatCapacityCoefficients(-28.250, 6.159e-1, -4.023e-4, 9.936e-8),
    ),
    "benzene": SpeciesPhysicalProperty(
        component_id="benzene",
        display_name="BZ",
        molecular_weight=78.114,
        melting_point_k=278.7,
        boiling_point_k=353.3,
        latent_heat_kj_per_mol=30.78,
        heat_of_formation_kj_per_kmol=83_000.0,
        heat_capacity=HeatCapacityCoefficients(-33.919, 4.744e-1, -2.942e-4, 7.130e-8),
    ),
    "toluene": SpeciesPhysicalProperty(
        component_id="toluene",
        display_name="TL",
        molecular_weight=92.141,
        melting_point_k=178.0,
        boiling_point_k=383.8,
        latent_heat_kj_per_mol=33.20,
        heat_of_formation_kj_per_kmol=50_000.0,
        heat_capacity=HeatCapacityCoefficients(-24.356, 5.125e-1, -2.766e-4, 4.911e-8),
    ),
    "hydrogen": SpeciesPhysicalProperty(
        component_id="hydrogen",
        display_name="H2",
        molecular_weight=2.016,
        melting_point_k=14.0,
        boiling_point_k=20.4,
        latent_heat_kj_per_mol=0.90,
        heat_of_formation_kj_per_kmol=0.0,
        heat_capacity=HeatCapacityCoefficients(27.144, 9.274e-3, -1.381e-5, 7.645e-9),
    ),
    "co": SpeciesPhysicalProperty(
        component_id="co",
        display_name="CO",
        molecular_weight=28.010,
        melting_point_k=68.1,
        boiling_point_k=81.7,
        latent_heat_kj_per_mol=6.05,
        heat_of_formation_kj_per_kmol=-110_600.0,
        heat_capacity=HeatCapacityCoefficients(30.871, -1.285e-2, 2.789e-5, -1.272e-8),
    ),
    "co2": SpeciesPhysicalProperty(
        component_id="co2",
        display_name="CO2",
        molecular_weight=44.010,
        melting_point_k=216.6,
        boiling_point_k=194.7,
        latent_heat_kj_per_mol=17.17,
        heat_of_formation_kj_per_kmol=-393_800.0,
        heat_capacity=HeatCapacityCoefficients(19.796, 7.344e-2, -5.602e-5, 1.715e-8),
    ),
    "methane": SpeciesPhysicalProperty(
        component_id="methane",
        display_name="CH4",
        molecular_weight=16.043,
        melting_point_k=90.7,
        boiling_point_k=111.7,
        latent_heat_kj_per_mol=8.19,
        heat_of_formation_kj_per_kmol=-74_900.0,
        heat_capacity=HeatCapacityCoefficients(19.252, 5.213e-2, 1.197e-5, -1.132e-8),
    ),
    "ethylene": SpeciesPhysicalProperty(
        component_id="ethylene",
        display_name="C2H4",
        molecular_weight=28.054,
        melting_point_k=104.0,
        boiling_point_k=169.4,
        latent_heat_kj_per_mol=13.55,
        heat_of_formation_kj_per_kmol=52_300.0,
        heat_capacity=HeatCapacityCoefficients(3.806, 1.566e-1, -8.349e-5, 1.755e-8),
    ),
}
