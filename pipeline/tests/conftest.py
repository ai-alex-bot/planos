from pathlib import Path

import pytest

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    return SAMPLES_DIR


@pytest.fixture(scope="session")
def clean_dxf() -> Path:
    return SAMPLES_DIR / "depto_2d_limpio.dxf"


@pytest.fixture(scope="session")
def messy_dxf() -> Path:
    return SAMPLES_DIR / "depto_2d_desordenado.dxf"


@pytest.fixture(scope="session")
def two_units_dxf() -> Path:
    return SAMPLES_DIR / "planta_2_unidades.dxf"
