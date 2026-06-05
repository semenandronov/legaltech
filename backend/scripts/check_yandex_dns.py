import socket
import sys
import multiprocessing as mp


def _resolve(host: str, port: int, out: mp.Queue) -> None:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        addrs = sorted({info[4][0] for info in infos if info and info[4]})
        out.put(("ok", addrs))
    except Exception as e:
        out.put(("err", str(e)))


def main() -> int:
    host = "api.cloud.yandex.net"
    port = 443
    q: mp.Queue = mp.Queue()
    p = mp.Process(target=_resolve, args=(host, port, q), daemon=True)
    p.start()
    p.join(timeout=3.0)
    if p.is_alive():
        p.kill()
        p.join(timeout=1.0)
        print(f"FAIL: DNS resolve {host}:{port}: timeout (>3s)")
        return 2

    if q.empty():
        print(f"FAIL: DNS resolve {host}:{port}: no result")
        return 2

    status, payload = q.get()
    if status != "ok":
        print(f"FAIL: DNS resolve {host}:{port}: {payload}")
        return 2

    print(f"OK: {host}:{port} resolved to: {payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

