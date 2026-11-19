from check_reliability import problems

BASE = {"production": {"sealed_rows": 12}}
GOOD = {"seeds": {"PRIVATE_SEED": True}, "private": {"ready": True, "sealed_rows": 12}, "record": {"verified": True}}


def test_baseline_is_quiet():
    assert problems("production", GOOD, BASE) == []


def test_a_replaced_key_is_loud():
    bad = dict(GOOD, private={"ready": True, "sealed_rows": 40})
    assert any("rose to 40" in p for p in problems("production", bad, BASE))


def test_missing_seed_and_broken_chain():
    bad = dict(GOOD, seeds={"PRIVATE_SEED": False}, record={"verified": False})
    assert len(problems("production", bad, BASE)) == 2


def test_escrow_seed_is_optional():
    ok = dict(GOOD, seeds={"PRIVATE_SEED": True, "PRIVATE_SEED_NEXT": False})
    assert problems("production", ok, BASE) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
