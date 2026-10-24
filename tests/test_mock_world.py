from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from endorsement_agent.mock_world.insurer import InsurerStep, MockInsurer
from endorsement_agent.mock_world.policies import Policy, PolicyStore
from endorsement_agent.mock_world.rules import RulesMaster

PERSONAS = Path(__file__).parents[1] / "fixtures" / "documents" / "personas.yaml"
INSURERS = ["Northwind General", "Cedar Mutual", "Halcyon Assurance"]


@pytest.fixture(scope="module")
def store() -> PolicyStore:
    return PolicyStore.load()


@pytest.fixture(scope="module")
def rules() -> RulesMaster:
    return RulesMaster.load()


# --- policies -------------------------------------------------------------------------------


def test_policies_unique(store: PolicyStore) -> None:
    assert len(store.policies) == 15
    assert len({p.policy_no for p in store.policies}) == 15
    assert len({p.reg_no for p in store.policies}) == 15
    assert {p.insurer for p in store.policies} == set(INSURERS)


def _one(store: PolicyStore, persona: dict[str, Any]) -> Policy:
    [policy] = store.lookup(policy_no=persona["policy_no"])
    assert (policy.insurer, policy.reg_no) == (persona["insurer"], persona["reg_no"])
    return policy


def test_policies_match_personas(store: PolicyStore) -> None:
    personas = yaml.safe_load(PERSONAS.read_text())
    for case in ("case_01_owner_transfer_clean", "case_02_owner_transfer_degraded"):
        p, policy = personas[case], _one(store, personas[case])
        assert policy.holder.name == p["old_owner"]["name"]
        assert (policy.chassis_no, policy.engine_no) == (p["chassis_no"], p["engine_no"])
        assert policy.vehicle.model_dump() == p["vehicle"]
        assert policy.period.model_dump() == p["policy_period"]
    p = personas["case_03_nominee_update"]
    policy = _one(store, p)
    assert policy.holder.name == p["policyholder"]["name"]
    assert policy.nominee is not None and policy.nominee.model_dump() == p["current_nominee"]
    p = personas["case_04_name_correction_marriage"]
    assert _one(store, p).holder.name == p["old_name"]
    p = personas["case_05_name_typo"]
    assert _one(store, p).holder.name == p["name_on_policy"]


def test_lookup_normalises_keys(store: PolicyStore) -> None:
    assert [p.reg_no for p in store.lookup(policy_no="nwg mot 240117")] == ["KA05MZ4182"]
    assert [p.policy_no for p in store.lookup(reg_no="ka 05 mz 4182")] == ["NWG-MOT-240117"]
    assert [p.policy_no for p in store.lookup(policy_no="HLA-MC-88104577")] == ["HLA/MC/88104577"]


def test_lookup_by_phone_can_match_several(store: PolicyStore) -> None:
    assert len(store.lookup(phone="+91 96110 48820")) == 2
    assert store.lookup(phone="12345") == []


def test_lookup_not_found_and_no_key(store: PolicyStore) -> None:
    assert store.lookup(policy_no="NWG-MOT-000000") == []
    with pytest.raises(ValueError):
        store.lookup()


def test_snapshot_carries_twists(store: PolicyStore) -> None:
    [lapsed] = store.lookup(reg_no="TN22AZ4410")
    [hyp, _] = store.lookup(phone="9611048820")
    assert lapsed.snapshot().extra["status"] == "lapsed"
    assert hyp.snapshot().extra["hypothecated_to"] == "Lakeside Finance Ltd"


# --- rules ----------------------------------------------------------------------------------


def test_rules_cover_every_type_and_insurer(rules: RulesMaster) -> None:
    assert rules.types == ["change-of-owner", "name-correction", "nominee-update"]
    for t in rules.types:
        for insurer in INSURERS:
            r = rules.get(t, insurer)
            assert r.rows and r.requirements().slots
    assert 40 <= len(rules.rows) <= 50


def test_every_insurer_has_conditional_twists(rules: RulesMaster) -> None:
    for insurer in INSURERS:
        assert sum(1 for r in rules.rows if r.insurer == insurer and r.condition) >= 2


def test_rules_reject_non_canonical_type(rules: RulesMaster) -> None:
    with pytest.raises(KeyError):
        rules.get("owner-change", "Northwind General")


def test_requirements_split_by_mode(rules: RulesMaster) -> None:
    req = rules.get("change-of-owner", "Northwind General").requirements()
    assert [d.name for d in req.docs] == [
        "rc",
        "transfer_form",
        "aadhaar",
        "noc",
        "inspection_report",
    ]
    assert [s.name for s in req.slots] == ["new_owner_name", "new_owner_phone", "transfer_date"]
    assert next(d for d in req.docs if d.name == "noc").condition


def test_rules_master_validates_doc_types(rules: RulesMaster) -> None:
    raw = rules.model_dump()
    raw["rows"][0]["item"] = "selfie"
    with pytest.raises(ValueError):
        RulesMaster.model_validate(raw)


# --- insurer --------------------------------------------------------------------------------


def test_default_script_runs_to_issued() -> None:
    insurer = MockInsurer()
    ref = insurer.submit("case-1", "Northwind General")
    assert ref == "NWG-END-0001"
    assert [insurer.status(ref).stage for _ in range(4)] == [
        "received",
        "approved",
        "issued",
        "issued",
    ]


def test_submit_is_idempotent_per_case() -> None:
    insurer = MockInsurer()
    assert insurer.submit("c", "Cedar Mutual") == insurer.submit("c", "Cedar Mutual")
    assert insurer.submit("d", "Halcyon Assurance") == "HLA-END-0002"


def test_query_holds_until_answered() -> None:
    insurer = MockInsurer()
    script = [
        InsurerStep(stage="received"),
        InsurerStep(stage="query_raised", message="seller NOC unclear"),
        InsurerStep(stage="approved"),
    ]
    ref = insurer.submit("c", "Cedar Mutual", script)
    with pytest.raises(ValueError):
        insurer.respond(ref, "too early")
    assert insurer.status(ref).stage == "received"
    assert insurer.status(ref).message == "seller NOC unclear"
    assert insurer.status(ref).stage == "query_raised"
    insurer.respond(ref, "NOC re-uploaded as doc_7")
    assert insurer.status(ref).stage == "approved"
    assert insurer.submission(ref).responses == ["NOC re-uploaded as doc_7"]


def test_empty_script_rejected() -> None:
    with pytest.raises(ValueError):
        MockInsurer().submit("c", "Cedar Mutual", [])
