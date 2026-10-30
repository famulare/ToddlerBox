import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'timing_export', Path(__file__).resolve().parents[1] / 'scripts/collect-paint-timing.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_export_drops_unrecognized_content_and_nonfinite_metrics():
    report = module.sanitize({'private': 'not-exported', 'metrics': {
        'display_flip': {'count': 1, 'sum_ms': 2., 'max_ms': 2., 'buckets': [1] + [0] * 14},
        'unknown': {'private': 'not-exported'},
        'clock_tick': {'count': 1, 'sum_ms': float('nan'), 'max_ms': 1., 'buckets': [0] * 15}},
        'context': {'video_driver': 'not-exported', 'screen_size': [1366, 768]},
        'counts': {'pointer_accepted': 10, 'unknown': 'not-exported'}})
    assert set(report['metrics']) == {'display_flip'}
    assert report['context'] == {'screen_size': [1366, 768], 'compositor_hint': None, 'sdl_renderer_hint': None}
    assert report['counts'] == {'pointer_accepted': 10}
    assert 'not-exported' not in str(report)


def test_report_reader_refuses_symlink(tmp_path):
    private = tmp_path / 'private'
    private.write_text('{"private":"not-exported"}')
    (tmp_path / 'paint-timing-1.json').symlink_to(private)
    assert module.read_reports(tmp_path) == []
