"""The diagnostic must classify only known processes and parse Linux CPU fields."""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    'paint_collector', Path(__file__).resolve().parents[1] / 'scripts/collect-paint-session.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def test_only_known_paint_processes_are_labelled():
    assert collector.process_label('gnome-shell') == 'gnome'
    assert collector.process_label('toddlerbox-cage') == 'cage'
    assert collector.process_label('python', [b'python', b'-m', b'toddlerbox.paint']) == 'paint-direct'
    assert collector.process_label('python', [b'python', b'-m', b'toddlerbox.launcher']) == 'launcher'
    assert collector.process_label('python', [b'python', b'other.py', b'-m', b'toddlerbox.paint']) is None
    assert collector.process_label('python', [b'python', b'private.py']) is None
    assert collector.process_label('unrelated') is None


def test_proc_cpu_fields_handle_spaces_and_parentheses_in_comm():
    # Fields 3..22: state, ppid..cmajflt, utime, stime, cutime..itrealvalue, starttime.
    fields = ['S'] + ['0'] * 10 + ['25', '17'] + ['0'] * 6 + ['98765']
    assert collector.process_ticks('42 (strange (name)) ' + ' '.join(fields)) == (42, 98765)
