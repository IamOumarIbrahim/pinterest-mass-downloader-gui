"""Network tuning.

Pinterest's servers have several addresses. `requests` tries them one by one
and waits out a full timeout on each dead one, so a single unreachable IPv6
address (common on home routers with half-working IPv6) turns every new
connection into a 5-20 second stall. tune() notices that once and falls back
to IPv4 for the rest of the session.
"""

from __future__ import annotations

import socket
import threading

HOSTS = ("i.pinimg.com", "www.pinterest.com")
_lock = threading.Lock()
_done = False
ipv4_only = False


def _probe(family, addr, results: list, timeout: float):
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(addr)
        results.append((family, True))
    except OSError:
        results.append((family, False))
    finally:
        s.close()


def check(hosts=HOSTS, timeout: float = 2.0) -> bool:
    """True if some IPv6 address is unreachable while IPv4 works."""
    results: list = []
    threads = []
    for host in hosts:
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            continue
        for family, _t, _p, _c, addr in infos:
            t = threading.Thread(target=_probe, args=(family, addr, results, timeout), daemon=True)
            t.start()
            threads.append(t)
    for t in threads:
        t.join(timeout + 0.5)
    v6_bad = any(f == socket.AF_INET6 and not ok for f, ok in results)
    v4_ok = any(f == socket.AF_INET and ok for f, ok in results)
    return v6_bad and v4_ok


def tune() -> bool:
    """Run the check once per session. Returns True the one time IPv4 gets forced."""
    global _done, ipv4_only
    with _lock:
        if _done:
            return False
        _done = True
        try:
            if check():
                import urllib3.util.connection as conn
                conn.HAS_IPV6 = False
                ipv4_only = True
        except Exception:
            pass
        return ipv4_only
