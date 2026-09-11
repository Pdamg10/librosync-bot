"""
Network DNS resolver patch.
Directs api.telegram.org requests to 149.154.167.99 to bypass ISP routing drops
on 149.154.166.110 while maintaining valid TLS/SSL verification.
Patches both standard socket.getaddrinfo and uvloop.Loop.getaddrinfo.
"""
import socket
import logging

logger = logging.getLogger("librosync.network")
TELEGRAM_DIRECT_IP = "149.154.167.99"

_orig_socket_getaddrinfo = socket.getaddrinfo

def _is_telegram_host(host) -> bool:
    if isinstance(host, (bytes, bytearray)):
        host_str = host.decode("utf-8", errors="ignore")
    else:
        host_str = str(host or "")
    return host_str.strip().rstrip(".").lower() == "api.telegram.org"

def _patched_socket_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if _is_telegram_host(host):
        if family == socket.AF_INET6:
            raise socket.gaierror(socket.EAI_ADDRFAMILY, "Address family for hostname not supported")
        return _orig_socket_getaddrinfo(TELEGRAM_DIRECT_IP, port, socket.AF_INET, type, proto, flags)
    return _orig_socket_getaddrinfo(host, port, family, type, proto, flags)

def apply_network_patches():
    # 1. Patch standard socket.getaddrinfo
    socket.getaddrinfo = _patched_socket_getaddrinfo

    # 2. Patch uvloop if present
    try:
        import uvloop
        _orig_uvloop_getaddrinfo = uvloop.Loop.getaddrinfo

        async def _patched_uvloop_getaddrinfo(self, host, port, **kwargs):
            if _is_telegram_host(host):
                kwargs["family"] = socket.AF_INET
                return await _orig_uvloop_getaddrinfo(self, TELEGRAM_DIRECT_IP, port, **kwargs)
            return await _orig_uvloop_getaddrinfo(self, host, port, **kwargs)

        uvloop.Loop.getaddrinfo = _patched_uvloop_getaddrinfo
    except (ImportError, AttributeError):
        pass

apply_network_patches()
