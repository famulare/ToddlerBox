"""After acceptance, missing rollback material is advisory; tampering still fails closed."""
import pytest

from test_appliance import appliance_machine, modules, pending  # noqa: F401  (fixtures)
from test_update_bundle import machine, make_bundle, updater  # noqa: F401  (fixtures)


def accepted(root, updater, modules, tmp_path):
    recovery, core, _, _ = modules
    pending(root, updater, tmp_path)
    core._candidate_entry(root)
    core.observed(root)
    core.accept(root)
    return recovery.latest(root)


@pytest.mark.parametrize("loss", ["backup", "previous-release"])
def test_lost_rollback_material_never_blocks_child_mode_after_acceptance(appliance_machine, updater, modules,
                                                                          tmp_path, loss):
    recovery, core, _, _ = modules
    job, value = accepted(appliance_machine, updater, modules, tmp_path)
    if loss == "backup":
        (job / "controller.py").unlink()
    else:
        release = value["old_links"]["current"]
        if release is None:
            pytest.skip("fixture has no previous release")
        import shutil
        shutil.rmtree(appliance_machine / "opt/toddlerbox/releases" / release)
    assert recovery.gate(appliance_machine)
    assert (appliance_machine / recovery.STATE / "rollback-unavailable").exists()
    assert not (appliance_machine / recovery.STATE / "recovery-error").exists()
    core._candidate_entry(appliance_machine)  # Child mode is allowed.
    with pytest.raises(ValueError):
        updater[0].run(rollback=True, root=appliance_machine)
    assert not (appliance_machine / recovery.STATE / "maintenance").exists()


def test_tampered_backup_after_acceptance_still_fails_closed(appliance_machine, updater, modules, tmp_path):
    recovery = modules[0]
    job, _ = accepted(appliance_machine, updater, modules, tmp_path)
    (job / "controller.py").write_bytes(b"tampered")
    assert not recovery.gate(appliance_machine)
    assert (appliance_machine / recovery.STATE / "recovery-error").exists()


def test_missing_backup_for_an_unaccepted_candidate_still_fails_closed(appliance_machine, updater, modules, tmp_path):
    recovery = modules[0]
    pending(appliance_machine, updater, tmp_path)
    job, _ = recovery.latest(appliance_machine)
    (job / "controller.py").unlink()
    assert not recovery.gate(appliance_machine)
    assert not (appliance_machine / recovery.STATE / "rollback-unavailable").exists()
