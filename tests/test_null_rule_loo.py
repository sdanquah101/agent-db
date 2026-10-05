"""The null rule proposed for P2 (``docs/p2_design.md`` §4), measured on the clean record.

1. The committed ``reports/background/null_rule_loo.json`` is what the script computes from
   the committed record, so the false-alarm rates the design quotes can be reproduced.
2. The rule means what the design says, on constructed placements: a rise in scatter alone
   is not a failure; a channel fails only biased on the same side at the defaults and
   after the fit with its after-fit scatter above every clean run; temperature is never a
   failure; the balance fails on the mean and the worst window on the same side, or on
   more inadmissible windows than any clean run.
3. The leave-one-out placement is the published envelope's rule: no margin.
"""

from __future__ import annotations

import json

from scripts import declared_background as bg
from scripts import null_rule_loo as loo


def test_the_committed_rates_are_what_the_record_gives():
    committed = json.loads(loo.OUT_FILE.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(loo.leave_one_out(bg.read_record())))
    rules = committed["rules"]
    assert committed["n_runs"] == 120
    # the union is the three components, and it is quieter than the rules it replaces
    assert rules["null_rejected"]["false_alarms"] <= sum(
        rules[k]["false_alarms"] for k in ("NB", "NM", "NS")
    )
    assert rules["null_rejected"]["rate"] < rules["any_channel_after_fit_mean_outside"]["rate"]
    assert rules["null_rejected"]["rate"] < rules["any_statistic_outside"]["rate"]


def _channel(mean_d: int, mean_f: int, rms_d: int, rms_f: int) -> dict[str, int]:
    return {"at_defaults.mean_z": mean_d, "after_fit.mean_z": mean_f,
            "at_defaults.rms_z": rms_d, "after_fit.rms_z": rms_f}  # fmt: skip


def _placement(**chs: dict[str, int]) -> loo.Placement:
    out: loo.Placement = {}
    for name, stats in chs.items():
        for k, v in stats.items():
            out[f"{name}.{k}"] = v
    return out


def test_the_null_rule_means_what_the_design_says():
    inside = _channel(0, 0, 0, 0)
    failed = _channel(1, 1, 0, 1)
    # scatter alone, on every channel, is not a failure (Level 1's truth is none)
    noisy = _placement(gas_flow=_channel(0, 0, 1, 1), ph=_channel(0, 0, 1, 1))
    assert not loo.RULES["null_rejected"](noisy)
    # a bias on opposite sides at the defaults and after the fit is not one either
    assert not loo.channel_fails(_placement(gas_flow=_channel(1, -1, 0, 1)), "gas_flow")
    # nor a bias without the after-fit scatter above every clean run
    assert not loo.channel_fails(_placement(gas_flow=_channel(1, 1, 1, 0)), "gas_flow")
    assert loo.channel_fails(_placement(gas_flow=failed), "gas_flow")
    # one channel failed, the others' after-fit means inside: NS, not NM
    single = _placement(gas_flow=failed, ph=inside, tan=_channel(0, 0, 1, 1))
    assert loo.n_single(single) and not loo.n_multi(single)
    # one channel failed but another's after-fit mean outside: neither NS nor NM
    assert not loo.n_single(_placement(gas_flow=failed, ph=_channel(0, 1, 0, 0)))
    # two channels failed: NM
    assert loo.n_multi(_placement(gas_flow=failed, ph=failed))
    # temperature is read, never a failure
    assert not loo.RULES["null_rejected"](_placement(temperature=failed, ph=inside))
    # the balance: mean and worst window on the same side, or the inadmissible count above
    assert loo.n_bal({"cod_closure": -1, "cod_closure_worst": -1})
    assert not loo.n_bal({"cod_closure": -1, "cod_closure_worst": 1})
    assert not loo.n_bal({"cod_closure": -1, "cod_closure_worst": 0})
    assert loo.n_bal({"n_cod_inadmissible": 1})
    assert not loo.n_bal({"n_cod_inadmissible": -1})  # fewer bad windows is not a fault


def test_the_placement_is_the_envelope_with_no_margin():
    assert loo.place(1.0, 1.0, 2.0) == 0 and loo.place(2.0, 1.0, 2.0) == 0
    assert loo.place(2.0000001, 1.0, 2.0) == 1 and loo.place(0.9999999, 1.0, 2.0) == -1
    records = bg.read_record()
    bb = sorted(
        (r for r in records if (r["plant"], r["tier"]) == ("B", "B")), key=lambda r: r["key"]
    )
    # a run judged against an envelope that includes itself is inside on every statistic
    assert all(v == 0 for v in loo.placement(bb[0], bb).values())
