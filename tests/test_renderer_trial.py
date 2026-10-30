from pathlib import Path
import subprocess
import pytest


SOURCE = (Path(__file__).resolve().parents[1] / 'system/bin/toddlerbox-session').read_text()
FUNCTION = SOURCE[SOURCE.index('paint_trial_renderer() {'):SOURCE.index('\ntrial_flag=')]


@pytest.mark.parametrize('now,renderer,expires,extra,expected', [
    ('100', 'gles2', '200', '', 'gles2'),
    ('100', 'gles2', '400', '', 'gles2'),
    ('100', 'gles2', '401', '', 'pixman'),
    ('100', 'gles2', '100', '', 'pixman'),
    ('100', 'gles2', '99', '', 'pixman'),
    ('00100', 'gles2', '00200', '', 'gles2'),
    ('100', 'other', '200', '', 'pixman'),
    ('100', 'gles2', '200', 'extra', 'pixman'),
    ('100', 'gles2', '9999999999999999999999999', '', 'pixman'),
    ('100', 'gles2', '$(false)', '', 'pixman'),
    ('100', 'gles2', '', '', 'pixman'),
])
def test_only_explicit_unexpired_bounded_gles_trial_is_admitted(now, renderer, expires, extra, expected):
    result = subprocess.run(['bash', '-s', '--', now, renderer, expires, extra],
                            input=FUNCTION + '\npaint_trial_renderer "$@"\n',
                            text=True, capture_output=True, check=True)
    assert result.stdout == expected


@pytest.mark.linux_only
@pytest.mark.parametrize('metadata,symlink,expected', [
    ('0:644', False, 'gles2'), ('1000:644', False, 'pixman'),
    ('0:666', False, 'pixman'), ('0:644', True, 'pixman'),
])
def test_root_ownership_mode_and_no_symlink_are_required(tmp_path, metadata, symlink, expected):
    import time
    flag = tmp_path / 'flag'
    target = tmp_path / 'target'
    target.write_text(f'gles2 {int(time.clock_gettime(time.CLOCK_BOOTTIME)) + 30}\n')
    if symlink:
        flag.symlink_to(target)
    else:
        flag.write_bytes(target.read_bytes())
    selection = SOURCE[SOURCE.index('paint_trial_renderer() {'):SOURCE.index('export PYGAME_HIDE_SUPPORT_PROMPT')]
    selection = selection.replace('trial_flag=/run/toddlerbox-system/cage-renderer-trial', 'trial_flag=$1')
    # Mock only stat's metadata response; execute the production file/symlink
    # checks, deadline parser and shell selection with a real isolated file.
    script = 'WLR_RENDERER=pixman\nstat() { printf "%s" "' + metadata + '"; }\n'
    result = subprocess.run(['bash', '-s', '--', str(flag)],
                            input=script + selection + '\nprintf "%s" "$WLR_RENDERER"\n',
                            text=True, capture_output=True, check=True)
    assert result.stdout == expected
