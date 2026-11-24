"""G.711 reference media peer and controlled PulseAudio evidence."""
import math
from pathlib import Path
import socket
import struct
import subprocess
import threading
import time


def ulaw(value):
    value = (~value) & 255
    sample = (((value & 15) << 3) + 132) << ((value >> 4) & 7)
    return 132 - sample if value & 128 else sample - 132


def alaw(value):
    value ^= 85
    segment = (value >> 4) & 7
    sample = (value & 15) << 4
    sample += 8 if segment == 0 else 264
    if segment > 1:
        sample <<= segment - 1
    return sample if value & 128 else -sample


class RtpPeer:
    def __init__(self, stream, stopped):
        self.stream = stream
        self.stopped = stopped
        self.lock = threading.RLock()
        self.tables = {0: [ulaw(value) for value in range(256)],
                       8: [alaw(value) for value in range(256)]}
        samples = [round(7000 * math.sin(2 * math.pi * 400 * index / 8000)) for index in range(160)]
        self.tones = {codec: bytes(min(range(256), key=lambda value: abs(table[value] - sample))
                                  for sample in samples) for codec, table in self.tables.items()}
        self.remote = None
        self.codec = 0
        self.metrics = {}
        self.sequence = 0
        self.timestamp = 0
        self.receiver = threading.Thread(target=self.receive, daemon=True)
        self.sender = threading.Thread(target=self.send, daemon=True)

    def start(self):
        self.receiver.start()
        self.sender.start()

    def reset(self):
        with self.lock:
            self.remote = None
            self.metrics = {}

    def count(self, name):
        self.metrics[name] = self.metrics.get(name, 0) + 1

    def receive(self):
        self.stream.settimeout(0.2)
        while not self.stopped.is_set():
            try:
                packet, remote = self.stream.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            if len(packet) < 12 or packet[0] != 128:
                continue
            payload = packet[1] & 127
            with self.lock:
                if payload == 101 and len(packet) >= 16:
                    self.count('dtmf_' + str(packet[12]))
                    if packet[13] & 128:
                        self.count('dtmf_' + str(packet[12]) + '_end')
                    continue
                if payload not in self.tables or len(packet) < 13:
                    continue
                self.remote = remote
                self.codec = payload
                self.count('received_' + str(payload))
                samples = [self.tables[payload][value] for value in packet[12:]]
                if sum(value * value for value in samples) / len(samples) > 250000:
                    self.count('microphone_non_silent')

    def send(self):
        deadline = time.monotonic()
        while not self.stopped.is_set():
            with self.lock:
                if self.remote:
                    self.sequence = (self.sequence + 1) & 65535
                    self.timestamp = (self.timestamp + 160) & 0xffffffff
                    packet = struct.pack('!BBHII', 128, self.codec, self.sequence, self.timestamp, 0x11223344)
                    try:
                        self.stream.sendto(packet + self.tones[self.codec], self.remote)
                        self.count('sent')
                    except OSError:
                        return
            deadline += 0.02
            self.stopped.wait(max(0, deadline - time.monotonic()))

    def malformed(self):
        with self.lock:
            if not self.remote:
                raise RuntimeError('RTP endpoint was not established')
            header = struct.pack('!BBHII', 128, self.codec, 1, 0, 0x11223344)
            packets = [b'\x80', bytes([143]) + header[1:],
                       bytes([144]) + header[1:] + b'\x00\x00\xff\xff',
                       bytes([160]) + header[1:] + b'\xff',
                       bytes([160]) + header[1:] + b'\x00',
                       header + bytes(3000)]
            for packet in packets:
                self.stream.sendto(packet, self.remote)
            self.count('malformed_batches')

    def evidence(self):
        with self.lock:
            result = dict(self.metrics)
        result['rtp_port'] = self.stream.getsockname()[1]
        monitor = Path('/home/nobody/playback.pcm')
        if monitor.exists():
            with monitor.open('rb') as recording:
                recording.seek(max(0, monitor.stat().st_size - 16000))
                data = recording.read()
            samples = struct.unpack('<' + 'h' * (len(data) // 2), data[:len(data) & ~1])
            if samples:
                result['playback_rms'] = round(math.sqrt(sum(value * value for value in samples) / len(samples)))
                sine = sum(value * math.sin(2 * math.pi * 400 * index / 8000) for index, value in enumerate(samples))
                cosine = sum(value * math.cos(2 * math.pi * 400 * index / 8000) for index, value in enumerate(samples))
                result['playback_400hz_amplitude'] = round(2 * math.hypot(sine, cosine) / len(samples))
        server = 'unix:/home/nobody/pulse-native'
        if Path('/home/nobody/pulse-native').exists():
            for direction, label in (('source-outputs', 'capture_streams'), ('sink-inputs', 'playback_streams')):
                query = subprocess.run(['pactl', '-s', server, 'list', 'short', direction],
                                       capture_output=True, text=True, timeout=3)
                result[label] = len(query.stdout.splitlines()) if query.returncode == 0 else -1
        return result
