from __future__ import annotations

import argparse
import sys

from quickshare.mdns import default_device_name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quickshare", description="Minimal Quick Share receiver for Linux")
    sub = parser.add_subparsers(dest="command", required=True)

    receive = sub.add_parser("receive", help="Advertise this device and receive incoming file transfers")
    receive.add_argument("-o", "--output-dir", default=".", help="Directory to save received files into (default: current directory)")
    receive.add_argument("-n", "--name", default=None, help="Device name to advertise (default: hostname)")
    receive.add_argument("-i", "--iface", default=None, help="Network interface to advertise on, e.g. enp6s0 (default: auto-detect)")
    receive.add_argument("--yes", action="store_true", help="Auto-accept incoming transfers without prompting")
    receive.add_argument("--no-color", action="store_true", help="Disable colored terminal output")

    send = sub.add_parser("send", help="Discover a nearby device and send it one or more files")
    send.add_argument("paths", nargs="+", help="File path(s) to send")
    send.add_argument("-n", "--name", default=None, help="Device name to advertise as sender (default: hostname)")
    send.add_argument("-i", "--iface", default=None, help="Network interface to use for discovery, e.g. enp6s0 (default: auto-detect)")
    send.add_argument("-t", "--target", default=None, metavar="HOST:PORT", help="Connect directly instead of discovering (skips the device picker)")
    send.add_argument("--no-color", action="store_true", help="Disable colored terminal output")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "receive":
        if args.no_color:
            from quickshare import color

            color.disable()

        from quickshare.server import run_receiver

        return run_receiver(
            output_dir=args.output_dir,
            device_name=args.name or default_device_name(),
            iface=args.iface,
            auto_accept=args.yes,
        )

    if args.command == "send":
        if args.no_color:
            from quickshare import color

            color.disable()

        from quickshare.send import run_sender

        return run_sender(
            paths=args.paths,
            device_name=args.name or default_device_name(),
            iface=args.iface,
            target=args.target,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
