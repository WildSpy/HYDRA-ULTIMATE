"""Точка входа веб-панели: python3 -m hydra.services.webpanel."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="hydra.services.webpanel",
                                     description="HYDRA Web Panel")
    parser.add_argument("--host", default=None, help="Адрес прослушивания (override)")
    parser.add_argument("--port", type=int, default=None, help="Порт (override)")
    tls = parser.add_mutually_exclusive_group()
    tls.add_argument("--tls", dest="tls", action="store_true", help="Включить HTTPS")
    tls.add_argument("--no-tls", dest="tls", action="store_false", help="Отключить HTTPS")
    parser.set_defaults(tls=None)
    args = parser.parse_args(argv)

    from hydra.services.webpanel.server import serve
    serve(host=args.host, port=args.port, tls=args.tls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
