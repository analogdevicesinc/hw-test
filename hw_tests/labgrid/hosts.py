import socket
from functools import wraps

_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_INSTALLED = False


def _aliases_for(host):
    aliases = [host]
    if "." not in host:
        aliases.append(f"{host}.local")
    elif host.endswith(".local"):
        aliases.append(host.removesuffix(".local"))
    return aliases


def parse_host_map(value):
    hosts = {}

    for raw_line in (value or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if "=" in line:
            host, address = line.split("=", 1)
        else:
            parts = line.split()
            if len(parts) < 2:
                continue
            host, address = parts[0], parts[1]

        host = host.strip()
        address = address.strip()
        if not host or not address:
            continue

        for alias in _aliases_for(host):
            hosts[alias] = address

    return hosts


def install_host_aliases(value=None):
    global _INSTALLED

    host_map = parse_host_map(value)
    if not host_map or _INSTALLED:
        return

    @wraps(_ORIGINAL_GETADDRINFO)
    def getaddrinfo(host, port, *args, **kwargs):
        return _ORIGINAL_GETADDRINFO(host_map.get(host, host), port, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo
    _INSTALLED = True
