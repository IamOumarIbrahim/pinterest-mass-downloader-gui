import time

from pinmass import update


def test_newer_compares_versions_as_numbers():
    assert update.newer("4.10.0", "4.9.3") and update.newer("v5", "4.9.9")
    assert not update.newer("4.0.0", "4.0.0") and not update.newer("3.9", "4.0.0")
    assert update.newer("4.0.1-beta", "4.0") and not update.newer("nonsense", "1.0")


def test_check_asks_at_most_once_a_day_and_remembers_what_it_saw():
    calls = []

    def fetch():
        calls.append(1)
        return "9.0.0", "https://example.invalid/release"

    cfg = {}
    assert update.check(cfg, "4.0.0", fetch) == ("9.0.0", "https://example.invalid/release")
    assert update.check(cfg, "4.0.0", fetch) == ("9.0.0", "https://example.invalid/release")
    assert len(calls) == 1                                   # second answer came from memory
    assert update.check(cfg, "9.0.0", fetch) is None         # once you have it, the button goes
    cfg["update_checked"] = time.time() - 2 * update.EVERY
    update.check(cfg, "4.0.0", fetch)
    assert len(calls) == 2


def test_check_can_be_switched_off_and_survives_being_offline():
    assert update.check({"check_updates": False}, "1.0", lambda: 1 / 0) is None
    assert update.check({}, "1.0", lambda: None) is None
