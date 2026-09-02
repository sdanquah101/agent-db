"""anchor/ingest_muscatine.py: unit-explicit parsing of the daily file and its statistics."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from anchor.ingest_muscatine import (
    DAILY_FILE,
    GAL_TO_M3,
    DailyRecord,
    assay_statistics,
    delivery_statistics,
    load_daily,
    seasonal_amplitude_from_monthly_means,
)

pytestmark = pytest.mark.skipif(not DAILY_FILE.exists(), reason="Muscatine daily file not present")


@pytest.fixture(scope="module")
def records() -> list[DailyRecord]:
    return load_daily()


def test_units_are_converted_and_flagged(records):
    first = records[0]
    assert first.date == dt.date(2020, 1, 1)
    assert first.twas_m3 == pytest.approx(4583 * GAL_TO_M3)
    assert first.ps_m3 == pytest.approx(15412 * GAL_TO_M3)
    assert first.hsw_m3 == 0.0 and first.fog_m3 == 0.0
    assert first.dig1_T_K == pytest.approx((95.5 - 32) * 5 / 9 + 273.15)
    assert first.dig1_alk_kg_caco3_m3 == pytest.approx(4.399)
    assert first.dig1_vfa_kg_m3 is None  # blank in the file
    assert first.ps_vs_kg_kg == pytest.approx(0.019)
    assert first.biogas_m3_d == pytest.approx(43.3 * 0.0283168 * 1440)
    assert first.biogas_reference_conditions_known is False
    assert len(records) == 1103
    for name, field in DailyRecord.model_fields.items():
        if name not in ("date", "biogas_reference_conditions_known"):
            assert any(u in (field.description or "") for u in ("m3", "K", "pH", "d", "kg"))


def test_delivery_statistics_reproduce_the_plant_config_numbers(records):
    hsw = delivery_statistics(records, "hsw_m3", per_unit=2)
    assert hsw.n_days == 1103
    assert hsw.zero_fraction == pytest.approx(111 / 1103, abs=1e-3)
    assert hsw.mean_zero_run_d == pytest.approx(6.94, abs=0.05)
    assert hsw.indicator_lag1 == pytest.approx(0.84, abs=0.01)
    assert hsw.nonzero_median == pytest.approx(23.6, abs=0.1)
    assert hsw.log_sigma == pytest.approx(0.78, abs=0.01)
    fog = delivery_statistics(records, "fog_m3", per_unit=2)
    assert fog.zero_fraction == pytest.approx(339 / 1103, abs=1e-3)
    assert min(fog.zero_fraction_by_weekday[5:]) > 0.9
    ps = delivery_statistics(records, "ps_m3", per_unit=2)
    assert ps.zero_fraction == 0.0 and ps.indicator_lag1 == 0.0 and ps.mean_zero_run_d == 0.0
    assert ps.nonzero_median == pytest.approx(30.3, abs=0.1)
    assert 0.0 < ps.seasonal_amplitude < 0.2


def test_assay_statistics(records):
    twas = assay_statistics(records, "twas_vs_kg_kg")
    assert twas.n == 1046 and twas.median == pytest.approx(0.0312, abs=1e-4)
    assert twas.log_sigma == pytest.approx(0.20, abs=0.01)
    assert min(twas.measured_fraction_by_weekday) > 0.85
    hsw = assay_statistics(records, "hsw_vs_kg_kg")
    assert hsw.n == 670 and max(hsw.measured_fraction_by_weekday[5:]) < 0.05
    cod = assay_statistics(records, "hsw_cod_kg_m3")
    assert cod.median == pytest.approx(136.8, abs=0.1)


def test_seasonal_amplitude_helper():
    dates = [dt.date(2021, 1, 1) + dt.timedelta(days=i) for i in range(365)]
    doy = np.arange(1, 366)
    values = np.exp(0.3 * np.cos(2 * np.pi * (doy - 200) / 365.25))
    amp, peak = seasonal_amplitude_from_monthly_means(values, dates)
    assert amp == pytest.approx(0.3, abs=0.02)
    assert peak == pytest.approx(200, abs=16)
