import os
from pathlib import Path
import subprocess
import pytest


SOURCE = (Path(__file__).resolve().parents[1] / 'system/bin/toddlerbox-session').read_text()
PREDICATE = SOURCE[SOURCE.index('startup_without_frame() {'):SOURCE.index('\nrun_cage_session()')]
RUNNER = SOURCE[SOURCE.index('run_cage_session() {'):SOURCE.index('\nexport PYGAME_HIDE_SUPPORT_PROMPT')]


@pytest.mark.parametrize('gpu,cpu,allow,renderer,expected,attempts', [
    (0, 0, True, 'gles2', 0, ['gles2']),
    (1, 0, True, 'gles2', 0, ['gles2', 'pixman']),
    (2, 3, True, 'gles2', 3, ['gles2', 'pixman']),
    (143, 0, True, 'gles2', 143, ['gles2']),
    (1, 0, False, 'gles2', 1, ['gles2']),
    (0, 4, True, 'pixman', 4, ['pixman']),
])
def test_renderer_success_failure_signal_and_retry_bounds(tmp_path, gpu, cpu, allow, renderer, expected, attempts):
    command = tmp_path / 'compositor'
    command.write_text('#!/bin/bash\nprintf "%s\\n" "$WLR_RENDERER" >> "$TRIAL_LOG"\n'
                       'if [[ $WLR_RENDERER == gles2 ]]; then exit "$GPU_STATUS"; else exit "$CPU_STATUS"; fi\n')
    command.chmod(0o755)
    log = tmp_path / 'attempts'
    env = {**os.environ, 'TRIAL_LOG': str(log), 'GPU_STATUS': str(gpu), 'CPU_STATUS': str(cpu)}
    script = 'set -euo pipefail\n' + RUNNER
    script += '\nstartup_without_frame() { return ' + ('0' if allow else '1') + '; }\n'
    script += 'run_cage_session "$@"\n'
    result = subprocess.run(['bash', '-s', '--', renderer, str(command)], input=script,
                            env=env, text=True, capture_output=True)
    assert result.returncode == expected
    assert log.read_text().splitlines() == attempts
    if len(attempts) == 2:
        assert 'once' in result.stderr


@pytest.mark.parametrize('content,expected', [
    ('{"mode":"child","seen_frame":false}', 0),
    ('{"mode":"child","seen_frame":true}', 1),
    ('{"mode":"parent","seen_frame":false}', 1),
    ('{"mode":"child","seen_frame":0}', 1),
    ('{"mode":"child"}', 1), ('not json', 1), ('[]', 1),
])
def test_fallback_requires_current_controller_child_no_frame_evidence(tmp_path, content, expected):
    status = tmp_path / 'status.json'
    status.write_text(content)
    # Replace only the data-source path; keep the production parsing/decision.
    predicate = PREDICATE.replace('Path("/run/toddlerbox-system/status.json")', f'Path({str(status)!r})')
    result = subprocess.run(['bash', '-s'], input=predicate + '\nstartup_without_frame\n', text=True)
    assert result.returncode == expected


def test_missing_controller_evidence_refuses_fallback(tmp_path):
    status = tmp_path / 'missing.json'
    predicate = PREDICATE.replace('Path("/run/toddlerbox-system/status.json")', f'Path({str(status)!r})')
    result = subprocess.run(['bash', '-s'], input=predicate + '\nstartup_without_frame\n', text=True)
    assert result.returncode == 1
