"""Read Celsius readings from an Arduino on the same Wi-Fi network.

A board running the temperature sketch publishes ``_microbial._tcp`` and
serves one temperature per line on TCP port 8080. This module browses for
that service, and a typed address is accepted when a board does not appear.
"""

import socket
import threading
import time

import numpy as np

from arduino_serial import _parse_celsius

WIFI_NAME = 'arduino-temp.local'
WIFI_PORT = 8080
SERVICE_TYPE = '_microbial._tcp.local.'

_discovery_lock = threading.Lock()
_boards_lock = threading.Lock()
_boards = {}
_browser = None
_zeroconf = None
_discovery_error = None
_scan_lock = threading.Lock()
_scan_boards = {}
_scan_next_at = 0.0
_SCAN_INTERVAL_SEC = 5.0
_SCAN_TIMEOUT_SEC = 0.25


class _BoardListener:
    """Collect ``_microbial._tcp`` records as boards join and leave."""

    def add_service(self, zc, type_, name):
        self._remember(zc, type_, name)

    def update_service(self, zc, type_, name):
        self._remember(zc, type_, name)

    def remove_service(self, zc, type_, name):
        with _boards_lock:
            _boards.pop(name, None)

    def _remember(self, zc, type_, name):
        info = zc.get_service_info(type_, name, timeout=2000)
        record = _record_from_info(info)
        if record is None:
            return
        with _boards_lock:
            _boards[name] = record


def _record_from_info(info):
    """Return a board dict from a zeroconf record, or None when it has no IPv4 address."""
    if info is None:
        return None
    try:
        addresses = info.parsed_addresses()
    except Exception:
        addresses = []
    ip = next((item for item in addresses if ':' not in item), None)
    if not ip:
        return None
    server = (getattr(info, 'server', None) or '').rstrip('.')
    return {
        'name': info.name,
        'host': server or ip,
        'ip': ip,
        'port': info.port or WIFI_PORT,
    }


def start_discovery():
    """Open one mDNS browser for temperature boards. Later calls do nothing."""
    global _browser, _zeroconf, _discovery_error
    with _discovery_lock:
        if _browser is not None or _discovery_error:
            return
        try:
            from zeroconf import ServiceBrowser, Zeroconf

            _zeroconf = Zeroconf()
            _browser = ServiceBrowser(_zeroconf, SERVICE_TYPE, _BoardListener())
        except Exception as exc:
            _discovery_error = str(exc)


def _local_ipv4_networks():
    """Return (ip, prefix_len) pairs for non-loopback IPv4 interfaces."""
    networks = []
    try:
        import psutil  # optional; fall through if missing
        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if getattr(addr, 'family', None) != socket.AF_INET:
                    continue
                ip = addr.address
                if not ip or ip.startswith('127.'):
                    continue
                mask = addr.netmask or '255.255.255.0'
                prefix = sum(bin(int(part)).count('1') for part in mask.split('.'))
                networks.append((ip, prefix))
        if networks:
            return networks
    except Exception:
        pass

    # Fallback without psutil: parse ``ip -4 -o addr``.
    try:
        import subprocess
        out = subprocess.check_output(
            ['ip', '-4', '-o', 'addr', 'show', 'scope', 'global'],
            text=True,
            timeout=2,
        )
        for line in out.splitlines():
            parts = line.split()
            if 'inet' not in parts:
                continue
            cidr = parts[parts.index('inet') + 1]
            if '/' not in cidr:
                continue
            ip, prefix_text = cidr.split('/', 1)
            if ip.startswith('127.'):
                continue
            networks.append((ip, int(prefix_text)))
    except Exception:
        pass
    return networks


def _iter_subnet_hosts(ip, prefix):
    """Yield other host IPs in a small local subnet (skips huge ranges)."""
    prefix = max(24, min(int(prefix), 30))  # scan at most a /24
    parts = [int(p) for p in ip.split('.')]
    host = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]
    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    network = host & mask
    broadcast = network | (~mask & 0xFFFFFFFF)
    for value in range(network + 1, broadcast):
        if value == host:
            continue
        yield socket.inet_ntoa(value.to_bytes(4, 'big'))


def _probe_host(ip, port, timeout, sink):
    if _probe(ip, port, timeout):
        sink[ip] = {
            'name': f'{ip}:{port}',
            'host': ip,
            'ip': ip,
            'port': port,
        }


def _scan_local_boards(port=WIFI_PORT):
    """Find boards by probing TCP port 8080 on the local hotspot/LAN subnet.

    mDNS often fails on phone hotspots; a short subnet probe still finds the Uno.
    """
    global _scan_next_at
    now = time.time()
    with _scan_lock:
        if now < _scan_next_at:
            return list(_scan_boards.values())
        _scan_next_at = now + _SCAN_INTERVAL_SEC

        found = {}
        threads = []
        for ip, prefix in _local_ipv4_networks():
            for host in _iter_subnet_hosts(ip, prefix):
                thread = threading.Thread(
                    target=_probe_host,
                    args=(host, port, _SCAN_TIMEOUT_SEC, found),
                    daemon=True,
                )
                threads.append(thread)
                thread.start()
        for thread in threads:
            thread.join(timeout=_SCAN_TIMEOUT_SEC + 0.5)

        # Also try the well-known local hostname from older sketches.
        for name in (WIFI_NAME, 'temp.local'):
            try:
                infos = socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)
            except socket.gaierror:
                continue
            resolved = infos[0][4][0]
            if _probe(resolved, port, _SCAN_TIMEOUT_SEC):
                found[resolved] = {
                    'name': name,
                    'host': name.rstrip('.'),
                    'ip': resolved,
                    'port': port,
                }

        _scan_boards.clear()
        _scan_boards.update(found)
        return list(_scan_boards.values())


def discovered_boards():
    """Boards currently announcing the temperature service, sorted by address."""
    start_discovery()
    with _boards_lock:
        boards = {board['ip']: board for board in _boards.values()}
    for board in _scan_local_boards():
        boards.setdefault(board['ip'], board)
    return sorted(boards.values(), key=lambda board: (board['ip'], board['host']))


def discovery_error():
    """Why browsing failed, or None when the browser is running."""
    start_discovery()
    return _discovery_error


def _same_host(left, right):
    """True when two host strings name the same machine, ignoring a trailing dot."""
    return (left or '').rstrip('.').lower() == (right or '').rstrip('.').lower()


def _match_discovered(host, port):
    """A discovered board whose name or address equals ``host``."""
    for board in discovered_boards():
        if board['port'] != port:
            continue
        if _same_host(board['ip'], host) or _same_host(board['host'], host):
            return board
    return None


def _split_host_port(value, default_port):
    """Return ``(host, port)`` from a hostname or ``host:port`` string."""
    text = (value or '').strip()
    if not text:
        return WIFI_NAME, default_port
    if text.count(':') == 1:
        host, port_text = text.rsplit(':', 1)
        if port_text.isdigit():
            port = int(port_text)
            if 1 <= port <= 65535 and host:
                return host, port
    return text, default_port


def _probe(ip, port, timeout):
    """True when a TCP connection to the board's temperature port succeeds."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def lookup_board(host=None, port=WIFI_PORT, timeout=3):
    """Resolve the board on the local network.

    Returns a dict with ``found``, ``host``, ``port``, and ``reachable``.
    ``ip`` is present when the name resolves.
    """
    name, board_port = _split_host_port(host or WIFI_NAME, port)
    try:
        infos = socket.getaddrinfo(name, board_port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        discovered = _match_discovered(name, board_port)
        if discovered is None and _same_host(name, WIFI_NAME):
            boards = [board for board in discovered_boards() if board['port'] == board_port]
            discovered = boards[0] if len(boards) == 1 else None
        if discovered is None:
            return {
                'found': False,
                'host': name,
                'port': board_port,
                'reachable': False,
            }
        return {
            'found': True,
            'host': discovered['host'],
            'ip': discovered['ip'],
            'port': discovered['port'],
            'reachable': _probe(discovered['ip'], discovered['port'], timeout),
        }
    ip = infos[0][4][0]
    return {
        'found': True,
        'host': name,
        'ip': ip,
        'port': board_port,
        'reachable': _probe(ip, board_port, timeout),
    }


def _readline(sock, pending):
    """Read one line already buffered or arriving on ``sock``."""
    while b'\n' not in pending[0]:
        chunk = sock.recv(256)
        if not chunk:
            return None
        pending[0] += chunk
    line, _, rest = pending[0].partition(b'\n')
    pending[0] = rest
    return line.decode('utf-8', errors='ignore')


def _read_latest(sock, pending):
    """Return the newest complete temperature already buffered, or the next line."""
    sock.settimeout(0.05)
    latest = None
    while True:
        try:
            raw = _readline(sock, pending)
        except (TimeoutError, socket.timeout):
            break
        if raw is None:
            break
        value = _parse_celsius(raw)
        if value is not None:
            latest = value
    if latest is not None:
        return latest

    sock.settimeout(2)
    try:
        raw = _readline(sock, pending)
    except (TimeoutError, socket.timeout):
        return None
    if raw is None:
        raise ConnectionError('The board closed the connection.')
    return _parse_celsius(raw)


def collect_wifi_temperature_data(host, duration_hours, interval_seconds=2, port=WIFI_PORT, log=None):
    """Collect a time series in the same shape as the USB collector.

    ``log`` is an optional callable that receives progress strings.
    Returns None when the board cannot be reached or no readings arrive.
    """
    def _log(message):
        if log is not None:
            log(message)

    interval_seconds = max(interval_seconds, 1)
    board = lookup_board(host, port)
    if not board['found']:
        _log(f"❌ Could not find {board['host']} on this network.")
        return None

    address = board['ip']
    board_port = board['port']
    label = board['host']
    if address != label:
        label = f"{label} ({address})"
    _log(f'📶 Connecting to {label} on port {board_port}...')

    time_data = []
    temps = []
    pending = [b'']
    try:
        with socket.create_connection((address, board_port), timeout=5) as sock:
            start = time.time()
            end = start + (duration_hours * 3600)
            while time.time() < end:
                celsius = _read_latest(sock, pending)
                if celsius is None:
                    continue
                elapsed_hours = (time.time() - start) / 3600
                time_data.append(elapsed_hours)
                temps.append(celsius)
                _log(f'🌡️ Reading #{len(temps)}: {celsius:.1f}°C')
                time.sleep(interval_seconds)
    except ConnectionError as exc:
        if time_data:
            _log(f'⚠️ {exc} Using the readings already received.')
        else:
            _log(f'❌ {exc}')
            return None
    except OSError as exc:
        _log(f'❌ Could not read {label}: {exc}')
        return None

    if not time_data:
        _log('❌ No temperature readings arrived. Check that the board is serving port 8080.')
        return None

    temperatures = np.array(temps)
    return {
        'time_hours': np.array(time_data),
        'ambient_temperature': temperatures,
        'internal_temperature': temperatures,
        'device_id': label,
        'readings_count': len(time_data),
    }
