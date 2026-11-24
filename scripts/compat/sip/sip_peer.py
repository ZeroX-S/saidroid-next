#!/usr/bin/env python3
"""Local Digest registrar and deterministic SIP peer for service contracts."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import threading
import time
import uuid
from rtp_peer import RtpPeer


def parse(data):
    head, _, body = data.partition(b'\r\n\r\n')
    lines = head.decode('utf-8').split('\r\n')
    headers = {}
    for line in lines[1:]:
        name, value = line.split(':', 1)
        headers.setdefault(name.lower(), []).append(value.strip())
    return dict(line=lines[0], headers=headers, body=body.decode('utf-8'))


def header(message, name):
    return message['headers'].get(name.lower(), [''])[0]


def user(uri):
    match = re.search(r'sip:([^@;>]+)@', uri)
    return match.group(1) if match else ''


class SipPeer:
    def __init__(self, address):
        self.address = address
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind((address, 0))
        self.port = self.udp.getsockname()[1]
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind((address, self.port))
        self.tcp.listen()
        self.rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtp.bind((address, 0))
        self.rtp_port = self.rtp.getsockname()[1]
        self.lock = threading.RLock()
        self.registered = {}
        self.invites = {}
        self.incoming = {}
        self.responses = {}
        self.metrics = {}
        self.stopped = threading.Event()
        self.connections = set()
        self.nonce = uuid.uuid4().hex
        self.registration_expiry = 4
        self.fail_next_registration = False
        self.media = RtpPeer(self.rtp, self.stopped)

    def count(self, name):
        self.metrics[name] = self.metrics.get(name, 0) + 1

    def sdp(self, codec=0, hold=False):
        name = 'PCMU' if codec == 0 else 'PCMA'
        return (f'v=0\r\no=peer 1 1 IN IP4 {self.address}\r\ns=SIP contracts\r\n'
                f'c=IN IP4 {self.address}\r\nt=0 0\r\nm=audio {self.rtp_port} RTP/AVP {codec} 101\r\n'
                f'a=rtpmap:{codec} {name}/8000\r\na=rtpmap:101 telephone-event/8000\r\n'
                f'a=fmtp:101 0-15\r\n' + ('a=recvonly\r\n' if hold else ''))

    def response(self, request, status, reason, extra=None, body='', tag='peer'):
        rows = [f'SIP/2.0 {status} {reason}']
        for index, value in enumerate(request['headers'].get('via', [])):
            if index == 0 and 'source' in request and re.search(r';rport(?:;|$)', value):
                value = re.sub(r';rport(?=;|$)', ';rport=' + str(request['source'][1]), value)
                value += ';received=' + request['source'][0]
            rows.append('Via: ' + value)
        to = header(request, 'to')
        if status > 100 and ';tag=' not in to: to += ';tag=' + tag
        rows += ['From: ' + header(request, 'from'), 'To: ' + to,
                 'Call-ID: ' + header(request, 'call-id'), 'CSeq: ' + header(request, 'cseq')]
        rows += [name + ': ' + value for name, value in (extra or {}).items()]
        if body: rows.append('Content-Type: application/sdp')
        rows.append('Content-Length: ' + str(len(body.encode())))
        return ('\r\n'.join(rows) + '\r\n\r\n' + body).encode()

    def authenticated(self, message, proxy=False):
        authorization = header(message, 'proxy-authorization' if proxy else 'authorization')
        fields = dict((key.lower(), quoted or bare) for key, quoted, bare in
                      re.findall(r'(\w+)\s*=\s*(?:"([^"]*)"|([^,\s]+))', authorization))
        if not fields: return False
        method, uri, _ = message['line'].split(' ', 2)
        username = fields.get('username')
        if username != 'fixture-auth': return False
        def md5(value): return hashlib.md5(value.encode()).hexdigest()
        first = md5(username + ':' + self.address + ':fixture-password')
        second = md5(method + ':' + fields.get('uri', ''))
        if fields.get('uri') != uri: return False
        if fields.get('qop') == 'auth':
            expected = md5(':'.join([first, self.nonce, fields.get('nc', ''), fields.get('cnonce', ''), 'auth', second]))
        else:
            expected = md5(first + ':' + self.nonce + ':' + second)
        return fields.get('nonce') == self.nonce and fields.get('response') == expected

    def challenge(self, request, send, proxy=False):
        name = 'Proxy-Authenticate' if proxy else 'WWW-Authenticate'
        value = f'Digest realm="{self.address}", nonce="{self.nonce}", algorithm=MD5, qop="auth"'
        send(self.response(request, 407 if proxy else 401, 'Authentication Required', {name:value}))
        self.count('proxy_challenges' if proxy else 'register_challenges')

    def process(self, message, send, transport, address):
        with self.lock:
            if message['line'].startswith('SIP/2.0'):
                self.incoming_response(message, send)
                return
            method, uri, _ = message['line'].split(' ', 2)
            message['source'] = address
            call_id = header(message, 'call-id')
            cseq = header(message, 'cseq')
            key = (call_id, cseq, header(message, 'via'))
            self.count(method.lower())
            self.count(transport.lower() + '_requests')
            if key in self.responses and method != 'ACK':
                send(self.responses[key])
                return
            if method == 'REGISTER':
                if not self.authenticated(message):
                    self.challenge(message, send)
                    return
                username = user(header(message, 'to'))
                expiry = int(header(message, 'expires') or '0')
                if self.fail_next_registration and expiry > 0:
                    self.fail_next_registration = False
                    send(self.response(message, 503, 'Service Unavailable'))
                    self.count('transient_registration_errors')
                    return
                expiry = min(expiry, self.registration_expiry)
                contact = header(message, 'contact')
                if expiry:
                    self.registered[username] = dict(contact=contact, send=send, address=address, transport=transport)
                    self.count('registration_successes')
                else:
                    self.registered.pop(username, None)
                    self.count('deregistrations')
                    if contact == '*': self.count('wildcard_deregistrations')
                response = self.response(message, 200, 'OK', {'Contact':contact.split(';expires=')[0] + ';expires=' + str(expiry),
                                                           'Expires':str(expiry)})
                self.responses[key] = response
                send(response)
            elif method == 'INVITE':
                peer = user(uri)
                if peer == 'authenticated' and not self.authenticated(message, proxy=True):
                    self.challenge(message, send, proxy=True)
                    return
                if ';tag=' in header(message, 'to'):
                    if 'a=x-reject' in message['body']:
                        send(self.response(message, 488, 'Not Acceptable Here'))
                        self.count('reinvite_rejections')
                        return
                    response = self.response(message, 200, 'OK', {'Contact':f'<sip:peer@{self.address}:{self.port}>'},
                                             self.sdp(hold='a=sendonly' in message['body']))
                    self.responses[key] = response
                    send(response)
                    self.count('reinvites')
                    return
                self.invites[call_id] = dict(request=message, send=send, peer=peer, key=key, canceled=False)
                if peer == 'busy': send(self.response(message, 486, 'Busy Here')); return
                if peer == 'decline': send(self.response(message, 603, 'Decline')); return
                send(self.response(message, 100, 'Trying'))
                if peer != 'timeout': send(self.response(message, 180, 'Ringing'))
                if peer in ('cancel', 'timeout', 'ring-timeout', 'late-answer'): return
                def answer():
                    with self.lock:
                        current = self.invites.get(call_id)
                        if not current or current['canceled'] or self.stopped.is_set(): return
                        response = self.response(message, 200, 'OK', {'Contact':f'<sip:peer@{self.address}:{self.port}>'}, self.sdp(8 if peer == 'pcma' else 0))
                        self.responses[key] = response
                        send(response)
                timer = threading.Timer(0.1, answer)
                timer.daemon = True
                timer.start()
            elif method == 'CANCEL':
                send(self.response(message, 200, 'OK'))
                original = self.invites.get(call_id)
                if original:
                    original['canceled'] = True
                    if original['peer'] == 'late-answer':
                        original['send'](self.response(original['request'], 200, 'OK',
                            {'Contact':f'<sip:peer@{self.address}:{self.port}>'}, self.sdp()))
                        self.count('late_answers')
                    else:
                        original['send'](self.response(original['request'], 487, 'Request Terminated'))
            elif method == 'BYE':
                send(self.response(message, 200, 'OK'))
                self.invites.pop(call_id, None)
            elif method == 'OPTIONS': send(self.response(message, 200, 'OK'))
            elif method == 'ACK': pass
            else: send(self.response(message, 501, 'Not Implemented'))

    def incoming_response(self, message, send):
        call_id = header(message, 'call-id')
        incoming = self.incoming.get(call_id)
        if not incoming: return
        status = int(message['line'].split()[1])
        if 'INVITE' not in header(message, 'cseq'): return
        incoming['status'] = status
        if status < 200: return
        rows = [f'ACK {incoming["target"]} SIP/2.0', 'Via: ' + incoming['via'],
                'From: ' + header(message, 'from'), 'To: ' + header(message, 'to'),
                'Call-ID: ' + call_id, 'CSeq: 1 ACK', 'Max-Forwards: 70', 'Content-Length: 0']
        incoming['send'](('\r\n'.join(rows) + '\r\n\r\n').encode())
        self.count('incoming_answers' if status == 200 else 'incoming_rejections')
        if status == 200:
            incoming['to'] = header(message, 'to')

    def start_incoming(self, username):
        with self.lock:
            registration = self.registered[username]
            contact = re.search(r'<([^>]+)>', registration['contact']).group(1)
            contact = contact.split(';expires=')[0]
            call_id = uuid.uuid4().hex + '@' + self.address
            via = f'SIP/2.0/{registration["transport"]} {self.address}:{self.port};branch=z9hG4bK{uuid.uuid4().hex};rport'
            body = self.sdp()
            rows = [f'INVITE {contact} SIP/2.0', 'Via: ' + via,
                    f'From: <sip:incoming@{self.address}:{self.port}>;tag=caller', f'To: <sip:{username}@{self.address}>',
                    'Call-ID: ' + call_id, 'CSeq: 1 INVITE', 'Max-Forwards: 70',
                    f'Contact: <sip:incoming@{self.address}:{self.port}>', 'Content-Type: application/sdp',
                    'Content-Length: ' + str(len(body.encode()))]
            self.incoming[call_id] = dict(target=contact, via=via, send=registration['send'], status=0)
            registration['send'](('\r\n'.join(rows) + '\r\n\r\n' + body).encode())
            return call_id

    def end_incoming(self, call_id):
        with self.lock:
            incoming = self.incoming[call_id]
            rows = [f'BYE {incoming["target"]} SIP/2.0',
                    f'Via: SIP/2.0/UDP {self.address}:{self.port};branch=z9hG4bK{uuid.uuid4().hex}',
                    f'From: <sip:incoming@{self.address}:{self.port}>;tag=caller', 'To: ' + incoming['to'],
                    'Call-ID: ' + call_id, 'CSeq: 2 BYE', 'Max-Forwards: 70', 'Content-Length: 0']
            incoming['send'](('\r\n'.join(rows) + '\r\n\r\n').encode())

    def udp_loop(self):
        self.udp.settimeout(0.2)
        while not self.stopped.is_set():
            try: data, address = self.udp.recvfrom(65535)
            except socket.timeout: continue
            except OSError: return
            try:
                self.process(parse(data), lambda response, target=address: self.udp.sendto(response, target), 'UDP', address)
            except Exception as failure:
                with self.lock:
                    self.count('peer_errors')
                    print('SIP_PEER_ERROR=' + type(failure).__name__ + ':' + str(failure), flush=True)

    def tcp_loop(self):
        self.tcp.settimeout(0.2)
        while not self.stopped.is_set():
            try: connection, address = self.tcp.accept()
            except socket.timeout: continue
            except OSError: return
            self.connections.add(connection)
            def receive(client=connection, target=address):
                buffer = b''
                try:
                    while not self.stopped.is_set():
                        data = client.recv(65535)
                        if not data: break
                        buffer += data
                        while b'\r\n\r\n' in buffer:
                            end = buffer.index(b'\r\n\r\n') + 4
                            match = re.search(rb'(?im)^Content-Length:\s*(\d+)', buffer[:end])
                            length = int(match.group(1)) if match else 0
                            if len(buffer) < end + length: break
                            message = buffer[:end + length]
                            buffer = buffer[end + length:]
                            if message.strip(): self.process(parse(message), client.sendall, 'TCP', target)
                except OSError: pass
                finally:
                    self.connections.discard(client)
                    client.close()
            threading.Thread(target=receive, daemon=True).start()

    def close(self):
        self.stopped.set()
        for connection in list(self.connections): connection.close()
        self.udp.close()
        self.tcp.close()
        self.rtp.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', default='127.0.0.1')
    parser.add_argument('--ready', type=Path, required=True)
    args = parser.parse_args()
    peer = SipPeer(args.address)
    class Control(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            with peer.lock:
                if self.path == '/metrics': result = dict(peer.metrics)
                elif self.path == '/rtp': result = peer.media.evidence()
                else: result = {name:value['status'] for name,value in peer.incoming.items()}
            self.respond(result)
        def respond(self, result):
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            configuration = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or b'{}')
            if self.path == '/incoming': result = dict(call_id=peer.start_incoming(configuration['user']))
            elif self.path == '/bye': peer.end_incoming(configuration['call_id']); result = dict(ended=True)
            elif self.path == '/fail-registration': peer.fail_next_registration = True; result = dict(armed=True)
            elif self.path == '/rtp/reset': peer.media.reset(); result = dict(reset=True)
            elif self.path == '/rtp/malformed': peer.media.malformed(); result = dict(sent=True)
            else: peer.stopped.set(); result = dict(stopped=True)
            self.respond(result)
    control = ThreadingHTTPServer((args.address, 0), Control)
    threading.Thread(target=peer.udp_loop, daemon=True).start()
    threading.Thread(target=peer.tcp_loop, daemon=True).start()
    threading.Thread(target=control.serve_forever, daemon=True).start()
    peer.media.start()
    args.ready.write_text(json.dumps(dict(address=args.address, sip_port=peer.port, rtp_port=peer.rtp_port,
                                         control_port=control.server_port)) + '\n')
    try: peer.stopped.wait()
    finally: control.shutdown(); control.server_close(); peer.close()


if __name__ == '__main__': main()
