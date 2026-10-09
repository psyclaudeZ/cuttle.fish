#!/usr/bin/env python3
"""Run all disposable tests, or select tests with standard unittest names."""
import os
import signal
import subprocess
import sys
import time
import unittest
from support import FISH, INCOGNITO, ROOT, Fixture, FishPTY, age_history, quote


@unittest.skipUnless(FISH, 'fish is required')
class CuttleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def shell(self, init=''):
        shell = FishPTY(self.fixture, init)
        self.addCleanup(shell.close)
        return shell

    def test_interactive_lifetime(self):
        self.fixture.fish('builtin history append DISK_BASE; builtin history save')
        age_history()
        shell = self.shell('builtin history append MEMORY_BASE')
        shell.enter()
        inherited = shell.history()
        self.assertIn('DISK_BASE', inherited)
        self.assertIn('MEMORY_BASE', inherited)
        self.assertLess(inherited.index('MEMORY_BASE'), inherited.index('DISK_BASE'))
        shell.run('echo TYPED_PRIVATE')
        multiline = 'begin\necho TYPED_MULTILINE_PRIVATE\nend'
        shell.run(multiline)
        shell.run('builtin history append APPENDED_PRIVATE; builtin history save')
        self.assertIn('echo TYPED_PRIVATE', shell.history())
        self.assertIn('APPENDED_PRIVATE', shell.history())
        self.assertIn(multiline, shell.history())
        self.assertEqual(shell.leave(7)[1], 7)
        self.assertEqual(shell.run('echo PARENT_USABLE')[1], 0)
        self.assertNotIn('echo TYPED_PRIVATE', shell.history())
        shell.run('builtin history save')
        age_history()
        persisted = self.fixture.fish('builtin history search --null')
        self.assertNotIn(b'PRIVATE', persisted)
        self.assertIn(b'DISK_BASE', persisted)
        self.assertIn(b'PARENT_USABLE', persisted)
        expected = {'DISK_BASE', 'MEMORY_BASE', 'cuttle', 'echo PARENT_USABLE',
                    '__test_dump', 'builtin history save'}
        self.assertEqual({entry.decode() for entry in persisted.split(b'\0') if entry}, expected)

    def test_exported_namespace_environment_and_directory(self):
        self.fixture.env.update(fish_history='parent_named', CUTTLE_TEST_EXPORT='exported-value')
        shell = self.shell('set -g parent_local secret; function parent_only; end')
        shell.enter()
        self.assertEqual(shell.history(), [])
        output, result = shell.run('printf "ENV=%s DIR=%s HIST=%s\\n" "$CUTTLE_TEST_EXPORT" "$PWD" "$fish_history"; set -q parent_local; or echo LOCAL_ABSENT; functions -q parent_only; or echo FUNCTION_ABSENT')
        self.assertEqual(result, 0)
        self.assertIn(b'ENV=exported-value', output)
        self.assertIn(str(self.fixture.root.resolve()).encode(), output)
        self.assertIn(b'HIST=\r\n', output)
        self.assertIn(b'LOCAL_ABSENT\r\n', output)
        self.assertIn(b'FUNCTION_ABSENT\r\n', output)
        shell.run('echo PRIVATE_EMPTY; cd /')
        shell.leave()
        output, _ = shell.run('printf "PARENT_DIR=%s\\n" "$PWD"')
        self.assertIn(str(self.fixture.root.resolve()).encode(), output)
        shell.run('builtin history save')
        for content in self.fixture.history_files().values():
            self.assertNotIn(b'PRIVATE_EMPTY', content)

    def test_nested_lifetimes(self):
        shell = self.shell('builtin history append BASE_NESTED')
        self.assertEqual(shell.enter().count(INCOGNITO), 1)
        shell.run('echo OUTER_PRIVATE')
        self.assertEqual(shell.enter().count(INCOGNITO), 1)
        self.assertIn('echo OUTER_PRIVATE', shell.history())
        shell.run('echo INNER_PRIVATE')
        shell.leave()
        self.assertNotIn('echo INNER_PRIVATE', shell.history())
        self.assertIn('echo OUTER_PRIVATE', shell.history())
        shell.leave()
        self.assertNotIn('echo OUTER_PRIVATE', shell.history())
        shell.run('builtin history save')
        for content in self.fixture.history_files().values():
            self.assertNotIn(b'PRIVATE', content)

    def test_prompt_preserves_theme_status_pipeline_and_parent(self):
        config = self.fixture.config.read_text()
        # Instrument the configured prompt, including a multiline theme and
        # transient rendering. Read status/pipestatus before any other commands.
        self.fixture.config.write_text(config + '''
set -g fish_transient_prompt 1
function fish_prompt
    set -l previous "$status" "$pipestatus"
    if contains -- --final-rendering $argv
        printf '\\036FINAL_RENDER\\037'
        return
    end
    printf '\\036THEME_INPUT:%s:%s\\037' $previous[1] $previous[2]
    printf 'CUSTOM_THEME\\n'
    set -l mode normal
    if test -n "$fish_private_mode"
        set mode private
    end
    printf '\\036CFPROMPT:%s:%s\\037' $mode $fish_pid
end
''')
        shell = self.shell()
        self.assertIn(b'CUSTOM_THEME', shell.enter())
        output, result = shell.run('false')
        self.assertEqual(result, 1)
        self.assertIn(INCOGNITO + b'\x1eTHEME_INPUT:1:1\x1f', output)
        self.assertIn(b'\x1eFINAL_RENDER\x1f', output)
        self.assertIn(INCOGNITO, output)
        self.assertNotIn(b'incognito', output)
        output, result = shell.run('/bin/sh -c "exit 7" | /bin/sh -c "exit 3"')
        self.assertEqual(result, 3)
        self.assertIn(b'\x1eTHEME_INPUT:3:7 3\x1f', output)
        shell.leave()
        output, result = shell.run('false')
        self.assertEqual(result, 1)
        self.assertIn(b'CUSTOM_THEME', output)
        self.assertIn(b'\x1eTHEME_INPUT:1:1\x1f', output)
        self.assertNotIn(INCOGNITO, output)

    def test_recall_and_autosuggestion(self):
        shell = self.shell('builtin history append "echo CF_AUTOSUGGEST_RESULT"')
        shell.enter()
        os.write(shell.fd, b'echo CF_AUTO')
        shell.until(b'SUGGEST_RESULT')
        os.write(shell.fd, b'\x1b[C\r')
        output, _ = shell.until(DONE_PATTERN)
        self.assertIn(b'\rCF_AUTOSUGGEST_RESULT\r\n', output)
        shell.prompt()
        shell.run('echo CF_TYPED_RECALL')
        os.write(shell.fd, b'\x1b[A\r')
        output, _ = shell.until(DONE_PATTERN)
        self.assertIn(b'\rCF_TYPED_RECALL\r\n', output)
        shell.prompt()
        shell.leave()

    def test_interrupt_and_termination_restore_parent(self):
        shell = self.shell()
        shell.enter()
        shell.send('sleep 30')
        shell.until(rb'\x1eCFEXEC:' + str(shell.current).encode() + rb'\x1f')
        time.sleep(.1)  # let the command acquire the foreground process group
        os.write(shell.fd, b'\x03')
        _, match = shell.until(DONE_PATTERN)
        self.assertEqual(int(match.group(2)), 130)
        shell.prompt()
        self.assertEqual(shell.run('echo CHILD_AFTER_INTERRUPT')[1], 0)
        os.kill(shell.current, signal.SIGTERM)
        self.assertEqual(shell.recover()[1], 143)
        self.assertEqual(shell.run('echo PARENT_AFTER_TERMINATION')[1], 0)

    def test_ctrl_d_restores_parent(self):
        shell = self.shell('builtin history append CTRL_D_BASE')
        shell.enter()
        shell.run('echo CTRL_D_PRIVATE')
        os.write(shell.fd, b'\x04')
        self.assertEqual(shell.recover()[1], 0)
        self.assertEqual(shell.run('echo PARENT_AFTER_CTRL_D')[1], 0)
        shell.run('builtin history save')
        for content in self.fixture.history_files().values():
            self.assertNotIn(b'CTRL_D_PRIVATE', content)

    def test_startup_failures_and_namespace_rejection(self):
        original = self.fixture.config.read_text()
        for startup, expected in [('set -gx fish_history unsafe_named', 1), ("exec /bin/sh -c 'exit 73'", 73)]:
            with self.subTest(startup=startup):
                self.fixture.config.write_text(original + '\nif test -n "$fish_private_mode"; ' + startup + '; end\n')
                shell = self.shell('builtin history append SECRET_INHERITED')
                output, result = shell.run('cuttle')
                self.assertEqual(result, expected, output[-4000:])
                if expected == 1:
                    self.assertIn(b'refusing to import history', output)
                self.assertEqual(shell.run('echo PARENT_AFTER_FAILURE')[1], 0)
                for name, content in self.fixture.history_files().items():
                    if 'unsafe_named' in str(name):
                        self.assertNotIn(b'SECRET_INHERITED', content)
                shell.close()
        self.fixture.config.write_text(original)

    def test_noninteractive_and_arguments_are_rejected(self):
        result = subprocess.run([FISH, '-N', '-c', 'source ' + quote(ROOT / 'functions/cuttle.fish') + '; cuttle'], env=self.fixture.env, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'interactive terminal is required', result.stderr)
        self.assertEqual(self.shell().run('cuttle --private')[1], 2)


DONE_PATTERN = rb'\x1eCFDONE:(\d+):(\d+)\x1f'
if __name__ == '__main__':
    if len(sys.argv) > 1:
        unittest.main(verbosity=2)
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
