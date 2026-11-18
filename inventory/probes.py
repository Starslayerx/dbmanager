import socket
import time


def tcp_probe(host: str, port: int, timeout: float) -> tuple[bool, float, str | None]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = (time.perf_counter() - started) * 1000
            return True, latency_ms, None
    except OSError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return False, latency_ms, str(exc)
