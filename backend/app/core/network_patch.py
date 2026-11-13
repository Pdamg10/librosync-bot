"""
Network DNS resolver patch (opcional).

Redirige api.telegram.org a una IP concreta para evitar bloqueos de routing del
ISP. Es un workaround frágil: solo se aplica si ENABLE_NETWORK_PATCH=true.
"""
import logging

logger = logging.getLogger("librosync.network")
TELEGRAM_DIRECT_IP = "149.154.167.99"

_originals = {}
_applied = False


def _is_telegram_host(host) -> bool:
    if isinstance(host, (bytes, bytearray)):
        host_str = host.decode("utf-8", errors="ignore")
    else:
        host_str = str(host or "")
    return host_str.strip().rstrip(".").lower() == "api.telegram.org"


def apply_network_patches() -> None:
    global _applied
    if _applied:
        return

    import socket

    _originals["socket_getaddrinfo"] = socket.getaddrinfo

    def _patched_socket_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if _is_telegram_host(host):
            if family == socket.AF_INET6:
                raise socket.gaierror(
                    socket.EAI_ADDRFAMILY,
                    "Address family for hostname not supported",
                )
            return _originals["socket_getaddrinfo"](
                TELEGRAM_DIRECT_IP, port, socket.AF_INET, type, proto, flags
            )
        return _originals["socket_getaddrinfo"](host, port, family, type, proto, flags)

    socket.getaddrinfo = _patched_socket_getaddrinfo

    try:
        import uvloop

        _originals["uvloop_getaddrinfo"] = uvloop.Loop.getaddrinfo

        async def _patched_uvloop_getaddrinfo(self, host, port, **kwargs):
            if _is_telegram_host(host):
                kwargs["family"] = socket.AF_INET
                return await _originals["uvloop_getaddrinfo"](
                    self, TELEGRAM_DIRECT_IP, port, **kwargs
                )
            return await _originals["uvloop_getaddrinfo"](self, host, port, **kwargs)

        uvloop.Loop.getaddrinfo = _patched_uvloop_getaddrinfo
    except (ImportError, AttributeError):
        pass

    _applied = True
    logger.warning(
        "Network patch habilitado: api.telegram.org -> %s. "
        "Desactívalo si tu red resuelve correctamente.",
        TELEGRAM_DIRECT_IP,
    )
