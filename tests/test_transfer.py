"""Lossless transport, fixed snapshots, and system argument-size limits."""
import os
import time
import unittest
from support import FISH, Fixture, FishPTY, age_history, quote


@unittest.skipUnless(FISH, 'fish is required')
class TransferTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def shell(self, init=''):
        shell = FishPTY(self.fixture, init)
        self.addCleanup(shell.close)
        return shell

    def test_literal_multiline_order_and_no_execution(self):
        entries = ['echo OLDEST', 'begin\n    echo "two lines"\nend',
                   '  leading and trailing whitespace \t\n', '--looks-like-an-option',
                   'echo 雪 🦑',
                   'echo "$HOME" \'quotes\' \\ * ? [x] {a,b}; (touch EXPLOITED) | cat > OTHER',
                   '`touch BACKTICKS` $(touch DOLLAR) && echo newest']
        shell = self.shell('builtin history append -- ' + ' '.join(map(quote, entries)))
        self.assertEqual(shell.history(), list(reversed(entries)))
        shell.enter()
        self.assertEqual([entry for entry in shell.history() if entry in entries], list(reversed(entries)))
        for name in ('EXPLOITED', 'OTHER', 'BACKTICKS', 'DOLLAR'):
            self.assertFalse((self.fixture.root / name).exists())
        shell.leave()

    def test_snapshot_does_not_merge_or_follow_other_shells(self):
        self.fixture.fish('builtin history append ORIGINAL_DISK; builtin history save')
        age_history()
        shell = self.shell('builtin history append PARENT_MEMORY')
        self.assertIn('ORIGINAL_DISK', shell.history())
        self.fixture.fish('builtin history append OTHER_BEFORE; builtin history save')
        age_history()
        shell.enter()
        self.assertNotIn('OTHER_BEFORE', shell.history())
        self.fixture.fish('builtin history append OTHER_AFTER; builtin history save')
        age_history()
        self.assertNotIn('OTHER_AFTER', shell.history())
        shell.leave()
        self.assertNotIn('OTHER_BEFORE', shell.history())
        self.assertNotIn('OTHER_AFTER', shell.history())

    def test_history_larger_than_arg_max(self):
        huge_length = os.sysconf('SC_ARG_MAX') + 4096
        history = self.fixture.root / 'data/fish/fish_history'
        history.parent.mkdir(parents=True)
        timestamp = int(time.time()) - 10
        with history.open('w') as stream:
            for index in range(6000):
                stream.write(f'- cmd: LARGE_{index} ' + 'x' * 512 + f'\n  when: {timestamp}\n')
            stream.write('- cmd: HUGE_' + 'z' * huge_length + f'\n  when: {timestamp}\n')
        baseline = self.fixture.history_files()
        shell = self.shell()
        shell.enter()
        output, result = shell.run('set -l entries (builtin history search --null --prefix LARGE_ | string split0); printf "LARGE_COUNT=%s\\n" (count $entries)')
        self.assertEqual(result, 0)
        self.assertIn(b'LARGE_COUNT=6000\r\n', output)
        output, result = shell.run('set -l entry (builtin history search --null --prefix HUGE_ | string split0); printf "HUGE_LENGTH=%s\\n" (string length -- "$entry")')
        self.assertEqual(result, 0)
        self.assertIn(f'HUGE_LENGTH={huge_length + 5}\r\n'.encode(), output)
        current = self.fixture.history_files()

        def commands(files):
            return {line[7:] for content in files.values() for line in content.splitlines()
                    if line.startswith(b'- cmd: ')}
        original_commands = commands(baseline)
        saved_commands = commands(current)
        self.assertTrue(original_commands <= saved_commands)
        self.assertTrue(saved_commands - original_commands <= {b'cuttle'})
        shell.leave()
        # A consumer that exits before reading a large pipe must not strand or
        # terminate the normal parent (which owns the snapshot producer).
        config = self.fixture.config.read_text()
        self.fixture.config.write_text(config + '\nif test -n "$fish_private_mode"; set -gx fish_history unsafe_large; end\n')
        self.assertEqual(shell.run('cuttle')[1], 1)
        self.assertEqual(shell.run('echo PARENT_AFTER_LARGE_FAILURE')[1], 0)
