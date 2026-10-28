"""Appliances only change releases through the signed, journaled path unless told otherwise."""
import json

import pytest

from test_appliance import appliance_machine, modules  # noqa: F401  (fixtures)
from test_system_release import bundle, release_installer, release_tree  # noqa: F401  (fixtures)
from test_update_bundle import machine, make_bundle, updater  # noqa: F401  (fixtures)


def test_unsigned_bundle_is_refused_on_an_appliance_without_explicit_recovery(appliance_machine, updater, tmp_path):
    module, _ = updater
    archive, digest = make_bundle(tmp_path, module)
    with pytest.raises(ValueError, match="--unsigned-recovery"):
        module.run(archive, digest, root=appliance_machine)
    assert module.latest(appliance_machine / module.STATE) is None
    module.run(archive, digest, root=appliance_machine, unsigned_recovery=True)
    assert module.latest(appliance_machine / module.STATE)[1]["status"] == "pending"


@pytest.fixture
def appliance_state(tmp_path):
    state = tmp_path / "system-state"
    (state / "updates").mkdir(parents=True)
    (state / "appliance-v1").touch()
    return state


def test_direct_release_install_requires_recovery_flag_on_an_appliance(release_installer, release_tree,
                                                                       tmp_path, appliance_state):
    installer, _ = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    with pytest.raises(ValueError, match="--unsigned-recovery"):
        installer.install(archive, digest, root=root, mode_file=mode, state=appliance_state)
    assert installer.install(archive, digest, root=root, mode_file=mode, state=appliance_state,
                             unsigned_recovery=True) == release_id


@pytest.mark.parametrize("busy", ["marker", "pending", "applying"])
def test_direct_release_install_never_runs_beside_an_update(release_installer, release_tree,
                                                            tmp_path, appliance_state, busy):
    installer, _ = release_installer
    root, mode = release_tree
    archive, digest, _ = bundle(tmp_path)
    if busy == "marker":
        (appliance_state / "maintenance").write_text("installation\n")
    else:
        (appliance_state / "updates/job").mkdir()
        (appliance_state / "updates/job/state.json").write_text(json.dumps({"status": busy}))
    with pytest.raises(ValueError, match="in progress"):
        installer.install(archive, digest, root=root, mode_file=mode, state=appliance_state,
                          unsigned_recovery=True)
    assert (root / "current").resolve() == root / "releases/old"


def test_the_journaled_updater_call_is_not_blocked_by_its_own_marker(release_installer, release_tree,
                                                                     tmp_path, appliance_state):
    installer, _ = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    (appliance_state / "maintenance").write_text("installation\n")
    assert installer.install(archive, digest, root=root, mode_file=mode, state=appliance_state,
                             journaled=True) == release_id


def test_torn_unreferenced_release_is_kept_aside_and_reinstalled(release_installer, release_tree, tmp_path):
    installer, controller = release_installer
    root, mode = release_tree
    archive, digest, release_id = bundle(tmp_path)
    torn = root / "releases" / release_id
    (torn / "src/toddlerbox").mkdir(parents=True)
    (torn / "src/toddlerbox/launcher.py").write_bytes(b"")  # Delayed allocation after a power cut.
    assert installer.install(archive, digest, root=root, mode_file=mode) == release_id
    assert (torn / "src/toddlerbox/launcher.py").read_bytes() == b"# launcher\n"
    (kept,) = (root / "releases").glob(f".conflict-{release_id}-*")
    assert (kept / "src/toddlerbox/launcher.py").read_bytes() == b""


def test_direct_install_waits_for_no_update_by_holding_the_update_lock(release_installer, release_tree,
                                                                      tmp_path, appliance_state):
    import fcntl
    installer, _ = release_installer
    root, mode = release_tree
    archive, digest, _ = bundle(tmp_path)
    with (appliance_state / "updates/lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)  # A signed update is running.
        with pytest.raises(ValueError, match="running"):
            installer.install(archive, digest, root=root, mode_file=mode, state=appliance_state,
                              unsigned_recovery=True)
    assert (root / "current").resolve() == root / "releases/old"
