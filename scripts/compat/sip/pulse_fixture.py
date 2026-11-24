"""Private PulseAudio source/sink used only by the ARM64 media fixture."""
import math
import os
from pathlib import Path
import pwd
import struct
import subprocess
import threading
import time


class PulseFixture:
    def __init__(self):
        self.folder = Path('/home/nobody')
        self.stopped = threading.Event()
        self.children = []
        self.logs = []
        self.writer = None

    def start(self):
        fifo = self.folder / 'capture.fifo'
        account = pwd.getpwnam('nobody')
        script = self.folder / 'pulse.pa'
        script.write_text('\n'.join([
            'load-module module-native-protocol-unix socket=/home/nobody/pulse-native auth-anonymous=1',
            'load-module module-null-sink sink_name=saildroid_sip_output format=s16le rate=8000 channels=1',
            'load-module module-pipe-source source_name=saildroid_sip_capture file=/home/nobody/capture.fifo format=s16le rate=8000 channels=1',
            'set-default-sink saildroid_sip_output', 'set-default-source saildroid_sip_capture', '']))
        os.chown(script, account.pw_uid, account.pw_gid)
        log = (self.folder / 'pulse.log').open('w')
        self.logs.append(log)
        environment = ['env', '-i', 'PATH=/usr/bin:/bin', 'HOME=/home/nobody',
                       'XDG_RUNTIME_DIR=/home/nobody', 'PULSE_SERVER=unix:/home/nobody/pulse-native']
        server = subprocess.Popen(['runuser', '-u', 'nobody', '--', *environment, 'pulseaudio',
            '-n', '-F', str(script), '--daemonize=no', '--use-pid-file=no', '--exit-idle-time=-1',
            '--log-target=stderr'], stdout=log, stderr=subprocess.STDOUT)
        self.children.append(server)
        deadline = time.monotonic() + 15
        while not (self.folder / 'pulse-native').is_socket() or not fifo.exists():
            if server.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('Controlled PulseAudio server failed to start')
            time.sleep(0.05)
        self.writer = threading.Thread(target=self.feed, daemon=True)
        self.writer.start()
        recording = (self.folder / 'playback.pcm').open('wb')
        self.logs.append(recording)
        errors = (self.folder / 'parec.log').open('w')
        self.logs.append(errors)
        capture = subprocess.Popen(['runuser', '-u', 'nobody', '--', *environment,
            'parec', '--device=saildroid_sip_output.monitor', '--rate=8000', '--format=s16le',
            '--channels=1', '--raw', '--latency-msec=32'], stdout=recording, stderr=errors)
        self.children.append(capture)

    def feed(self):
        descriptor = None
        try:
            while not self.stopped.is_set() and descriptor is None:
                try:
                    descriptor = os.open(self.folder / 'capture.fifo', os.O_WRONLY | os.O_NONBLOCK)
                except OSError:
                    self.stopped.wait(0.05)
            offset = 0
            deadline = time.monotonic()
            while not self.stopped.is_set():
                samples = [round(6000 * math.sin(2 * math.pi * 700 * (offset + index) / 8000)) for index in range(256)]
                try:
                    os.write(descriptor, struct.pack('<256h', *samples))
                except BlockingIOError:
                    pass
                offset += 256
                deadline += 0.032
                self.stopped.wait(max(0, deadline - time.monotonic()))
        except OSError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def close(self):
        self.stopped.set()
        if self.writer:
            self.writer.join(timeout=3)
        for child in reversed(self.children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for log in self.logs:
            log.close()
