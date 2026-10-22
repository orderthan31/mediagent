"""Explicit model egress: exact approved origins, literal address pins, no DNS/proxy/retry.

Controlled HTTP is loopback-only and additionally requires a disposable-test flag.
Normal policy is HTTPS with certificate/SNI verification and public address pins.
"""
import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def origin_key(value):
    url = httpx.URL(value)
    return url.scheme, url.raw_host.decode('ascii'), url.port or (443 if url.scheme == 'https' else 80)


@dataclass(frozen=True)
class RegisteredPolicy:
    mode: str
    approved_origins: frozenset
    targets: tuple
    sha256: str
    context: ssl.SSLContext

    @classmethod
    def from_file(cls, path, *, allow_controlled=False):
        try:
            raw = Path(path).read_bytes()
            if not 0 < len(raw) <= 8192:
                raise ValueError()
            value = json.loads(raw)
            if (not isinstance(value, dict) or not {'version', 'mode', 'origins'} <= set(value)
                    or set(value) - {'version', 'mode', 'origins', 'ca_file'}
                    or type(value['version']) is not int or value['version'] != 1
                    or value['mode'] not in {'external', 'controlled_http'}
                    or not isinstance(value['origins'], list) or not 1 <= len(value['origins']) <= 16):
                raise ValueError()
            controlled = value['mode'] == 'controlled_http'
            if controlled and (not allow_controlled or os.environ.get('MIDEAGENT_TEST_DISPOSABLE') != '1'):
                raise ValueError()
            if not controlled and allow_controlled:
                raise ValueError()
            targets, approved = [], []
            for row in value['origins']:
                if not isinstance(row, dict) or set(row) != {'origin', 'addresses'}:
                    raise ValueError()
                origin = row['origin']
                url = urlsplit(origin)
                if (not isinstance(origin, str) or url.scheme not in {'http', 'https'}
                        or not url.hostname or url.username or url.password or '*' in origin
                        or url.path or url.query or url.fragment or url.port == 0
                        or origin != f'{url.scheme}://{url.netloc}'
                        or not isinstance(row['addresses'], list) or not 1 <= len(row['addresses']) <= 4
                        or any(not isinstance(address, str) for address in row['addresses'])):
                    raise ValueError()
                addresses = tuple(str(ipaddress.ip_address(address)) for address in row['addresses'])
                if controlled:
                    if url.scheme != 'http' or url.hostname != '127.0.0.1' or addresses != ('127.0.0.1',):
                        raise ValueError()
                elif url.scheme != 'https' or any(not ipaddress.ip_address(address).is_global
                        or ipaddress.ip_address(address).is_multicast or ipaddress.ip_address(address).is_reserved
                        for address in addresses):
                    raise ValueError()
                key = origin_key(origin)
                if key in [entry[0] for entry in targets]:
                    raise ValueError()
                approved.append(origin)
                targets.append((key, addresses))
            ca = value.get('ca_file')
            if ca is not None and (not isinstance(ca, str) or not Path(ca).is_absolute()):
                raise ValueError()
            context = ssl.create_default_context(cafile=ca)
            digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            return cls(value['mode'], frozenset(approved), tuple(targets), digest, context)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            raise ValueError('invalid_registered_address_policy') from None

    def transport(self):
        return PinnedModelTransport(self)


class PinnedModelTransport(httpx.BaseTransport):
    def __init__(self, policy):
        self.policy = policy

    def handle_request(self, request):
        key = origin_key(request.url)
        addresses = dict(self.policy.targets).get(key)
        if (not addresses or request.method != 'POST' or request.url.username or request.url.password
                or request.url.query or request.url.fragment
                or request.headers.get('host') != request.url.netloc.decode('ascii')):
            raise httpx.TransportError('registered_request_denied')
        body = bytearray()
        body_stream = request.stream
        if not isinstance(body_stream, httpx.SyncByteStream):
            raise httpx.TransportError('registered_request_denied')
        for chunk in body_stream:
            body.extend(chunk)
            if len(body) > 3 * 1024 * 1024:
                raise httpx.TransportError('registered_request_denied')
        connection = http.client.HTTPConnection(key[1], key[2], timeout=15)
        stream = None
        try:
            # No getaddrinfo(hostname), proxy, alternative-address retry, or redirect.
            stream = socket.create_connection((addresses[0], key[2]), timeout=15)
            if key[0] == 'https':
                stream = self.policy.context.wrap_socket(stream, server_hostname=key[1])
            connection.sock = stream
            headers = {name: value for name, value in request.headers.items()
                       if name.lower() not in {'accept-encoding', 'transfer-encoding', 'content-length', 'connection'}}
            headers.update({'Accept-Encoding': 'identity', 'Connection': 'close'})
            connection.request('POST', request.url.raw_path.decode('ascii'), bytes(body), headers)
            response = connection.getresponse()
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError()
            content = response.read(262145)
            if len(content) > 262144:
                raise ValueError()
            return httpx.Response(response.status, headers=response.getheaders(), content=content, request=request)
        except (OSError, ValueError, http.client.HTTPException):
            raise httpx.TransportError('registered_transport_failure') from None
        finally:
            connection.close()
            if stream is not None:
                stream.close()
