"""Disposable fish fixtures and a PTY driver; no third-party dependencies."""
import errno
import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import subprocess
import tempfile
import time

FISH = shutil.which('fish')
ROOT = Path(__file__).resolve().parents[1]
PROMPT = rb'\x1eCFPROMPT:(normal|private):(\d+)\x1f'
DONE = rb'\x1eCFDONE:(\d+):(\d+)\x1f'


def quote(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def age_history():
    # fish excludes entries timestamped at/after startup (second resolution).
    time.sleep(1.1)


class Fixture:
    def __init__(self, extra=''):
        self.temp = tempfile.TemporaryDirectory(prefix='cuttle-test-')
        self.root = Path(self.temp.name)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('fish_', 'FISH_', 'XDG_'))}
        self.env.update(HOME=str(self.root), XDG_CONFIG_HOME=str(self.root / 'config'),
                        XDG_DATA_HOME=str(self.root / 'data'),
                        XDG_CACHE_HOME=str(self.root / 'cache'), TERM='xterm-256color')
        config = self.root / 'config/fish'
        config.mkdir(parents=True)
        self.config = config / 'config.fish'
        self.config.write_text('''
set -g fish_greeting
function fish_prompt
    set -l mode normal
    if test -n "$fish_private_mode"
        set mode private
    end
    printf '\\036CFPROMPT:%s:%s\\037' $mode $fish_pid
end
function fish_right_prompt
end
function __test_postexec --on-event fish_postexec
    set -l result $status
    printf '\\036CFDONE:%s:%s\\037' $fish_pid $result
end
function __test_preexec --on-event fish_preexec
    printf '\\036CFEXEC:%s\\037' $fish_pid
end
function __test_dump
    printf '\\036HSTART\\037'
    builtin history search --null --color=never
    printf '\\036HEND\\037'
end
source ''' + quote(ROOT / 'functions/cuttle.fish') + '\n' + extra)

    def fish(self, code):
        code = 'set -g fish_history fish; builtin history merge; ' + code
        return subprocess.run([FISH, '-N', '-c', code], env=self.env,
                              cwd=self.root, capture_output=True, check=True).stdout

    def history_files(self):
        return {p.relative_to(self.root): p.read_bytes()
                for p in self.root.rglob('*_history')}

    def close(self):
        self.temp.cleanup()


class FishPTY:
    def __init__(self, fixture, init=''):
        self.buffer = b''
        self.closed = False
        self.pids = set()
        self.stack = []
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(fixture.root)
            os.execvpe(FISH, [FISH, '-i', '-C', init], fixture.env)
        self.pids.add(self.pid)
        try:
            self.prompt()
        except BaseException:
            self.close()
            raise

    def until(self, pattern, timeout=40):
        deadline = time.monotonic() + timeout
        tail = b''
        while True:
            match = re.search(pattern, self.buffer)
            if match:
                output = self.buffer[:match.end()]
                self.buffer = self.buffer[match.end():]
                return output, match
            if time.monotonic() >= deadline:
                raise AssertionError(f'PTY timeout waiting for {pattern!r}: {self.buffer[-4000:]!r}')
            if select.select([self.fd], [], [], .1)[0]:
                try:
                    data = os.read(self.fd, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    data = b''
                if not data:
                    raise AssertionError(f'PTY closed waiting for {pattern!r}: {self.buffer[-4000:]!r}')
                self.buffer += data
                # The final DA query ends fish's terminal capability probing.
                if b'\x1b[0c' in tail + data:
                    os.write(self.fd, b'\x1b[?1;2c')
                tail = data[-3:]

    def prompt(self):
        output, match = self.until(PROMPT)
        self.current = int(match.group(2))
        self.mode = match.group(1).decode()
        self.pids.add(self.current)
        return output

    def send(self, command):
        os.write(self.fd, b'\x1b[200~' + command.encode() + b'\x1b[201~\r')

    def run(self, command):
        self.send(command)
        output, match = self.until(DONE)
        assert int(match.group(1)) == self.current, output[-4000:]
        return output + self.prompt(), int(match.group(2))

    def enter(self):
        previous = self.current
        self.send('cuttle')
        output = self.prompt()
        assert self.mode == 'private' and self.current != previous, output[-4000:]
        self.stack.append(previous)
        return output

    def recover(self):
        previous = self.stack.pop()
        output, match = self.until(rb'\x1eCFDONE:' + str(previous).encode() + rb':(\d+)\x1f')
        output += self.prompt()
        assert self.current == previous, output[-4000:]
        return output, int(match.group(1))

    def leave(self, code=0):
        self.send(f'exit {code}')
        return self.recover()

    def history(self):
        output, result = self.run('__test_dump')
        assert result == 0, output[-4000:]
        data = output.split(b'\x1eHSTART\x1f', 1)[1].split(b'\x1eHEND\x1f', 1)[0]
        return [item.decode() for item in data.replace(b'\r\n', b'\n').split(b'\0') if item]

    def close(self):
        if self.closed:
            return
        self.closed = True
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        os.close(self.fd)
        os.waitpid(self.pid, 0)
