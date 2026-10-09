"""A normal tmux pane on a disposable server; never touches the user's server."""
import shlex
import shutil
import subprocess
import time
import unittest
from support import FISH, Fixture

TMUX = shutil.which('tmux')


@unittest.skipUnless(FISH and TMUX, 'fish and tmux are required')
class TmuxTests(unittest.TestCase):
    def test_normal_pane_invocation(self):
        fixture = Fixture()
        self.addCleanup(fixture.close)
        prefix = [TMUX, '-S', str(fixture.root / 't'), '-f', '/dev/null']

        def tmux(*args, check=True):
            return subprocess.run(prefix + list(args), env=fixture.env, cwd=fixture.root,
                                  capture_output=True, check=check, timeout=10).stdout

        def send(command):
            tmux('send-keys', '-t', 'cuttle:0.0', '-l', command)
            tmux('send-keys', '-t', 'cuttle:0.0', 'Enter')

        def wait_for(marker):
            deadline = time.monotonic() + 15
            output = b''
            while time.monotonic() < deadline:
                output = tmux('capture-pane', '-p', '-t', 'cuttle:0.0', '-S', '-')
                if marker in output:
                    return output
                time.sleep(.05)
            self.fail(f'tmux timeout waiting for {marker!r}: {output[-4000:]!r}')

        tmux('new-session', '-d', '-s', 'cuttle', '-x', '120', '-y', '40',
             shlex.join([FISH, '-i', '-C', 'builtin history append TMUX_PARENT']))
        self.addCleanup(lambda: tmux('kill-server', check=False))
        wait_for(b'CFPROMPT:normal:')
        send('cuttle')
        wait_for(b'CFPROMPT:private:')
        send('printf "%s%s=%s\\n" TMUX_ MODE "$fish_private_mode"')
        wait_for(b'TMUX_MODE=1')
        send('if builtin history search --exact TMUX_PARENT >/dev/null; printf "%s%s\\n" TMUX_ INHERITED_OK; end')
        wait_for(b'TMUX_INHERITED_OK')
        send('echo TMUX_TYPED_PRIVATE')
        send('builtin history append TMUX_APPENDED_PRIVATE; builtin history save; printf "%s%s\\n" TMUX_ PRIVATE_SAVED')
        wait_for(b'TMUX_PRIVATE_SAVED')
        send('exit')
        send('builtin history save; printf "%s%s\\n" TMUX_ PARENT_RETURNED')
        wait_for(b'TMUX_PARENT_RETURNED')
        histories = fixture.history_files()
        self.assertTrue(histories)
        for content in histories.values():
            self.assertNotIn(b'TMUX_TYPED_PRIVATE', content)
            self.assertNotIn(b'TMUX_APPENDED_PRIVATE', content)
            self.assertNotIn(b'TMUX_PRIVATE_SAVED', content)
