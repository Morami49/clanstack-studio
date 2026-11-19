import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_worker_names import main, problems  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL = (ROOT / "hub" / "wrangler.toml").read_text()


def cfg(text=REAL):
    return tomllib.loads(text)


def test_real_config_passes():
    assert problems(cfg()) == []
    assert main(str(ROOT / "hub" / "wrangler.toml")) == 0


def test_catches_production_rename():
    assert any("production" in p and "Worker name" in p for p in problems(cfg(REAL.replace('name = "clanstack-hub"\n', 'name = "nodach-hub"\n', 1))))


def test_catches_staging_rename():
    assert any("staging" in p for p in problems(cfg(REAL.replace('"clanstack-hub-staging"', '"nodach-hub-staging"'))))


def test_catches_class_change_and_one_way_migration():
    t = REAL.replace('class_name = "Record"', 'class_name = "Store"', 1)
    assert any("binding RECORD" in p for p in problems(cfg(t)))
    t = REAL + '\n[[migrations]]\ntag = "v2"\nrenamed_classes = [{from = "Record", to = "Store"}]\n'
    assert any("one-way" in p for p in problems(cfg(t)))


def test_catches_missing_staging_env():
    c = cfg(); c.pop("env")
    assert problems(c) == ["[staging] environment is missing"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
