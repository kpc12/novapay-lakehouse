"""Session fixture: generate day-0 master data and simulate the full test window once."""
import pytest
from helpers import SIM_END, SIM_START, small_cfg

from data_generator.daily import run_daily
from data_generator.master_data import generate_initial


@pytest.fixture(scope="session")
def sim(tmp_path_factory):
    root = tmp_path_factory.mktemp("sim")
    cfg = small_cfg(root)
    generate_initial(cfg)
    run_daily(cfg, SIM_START, SIM_END)
    return cfg, root
