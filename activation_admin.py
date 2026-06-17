#!/usr/bin/env python3
"""Create and inspect Oniflow activation codes."""

from __future__ import annotations

import argparse
import secrets
from datetime import datetime, timezone

from activation_server import connect


def create_code(days: int, devices: int, code: str | None) -> None:
    value = (code or f"ONIFLOW-{secrets.token_hex(4).upper()}").strip().upper()
    connection = connect()
    connection.execute(
        "INSERT INTO codes(code, days, max_devices, created_at) VALUES (?, ?, ?, ?)",
        (value, days, devices, datetime.now(timezone.utc).isoformat()),
    )
    connection.commit()
    print(value)


def list_codes() -> None:
    connection = connect()
    rows = connection.execute(
        """
        SELECT c.code, c.days, c.max_devices, c.enabled, COUNT(a.device_id) AS used_devices
        FROM codes c LEFT JOIN activations a ON a.code = c.code
        GROUP BY c.code ORDER BY c.created_at DESC
        """
    )
    for row in rows:
        print(
            f"{row['code']} | {row['days']} days | {row['used_devices']}/{row['max_devices']} devices | "
            f"{'enabled' if row['enabled'] else 'disabled'}"
        )


def set_enabled(code: str, enabled: bool) -> None:
    connection = connect()
    result = connection.execute(
        "UPDATE codes SET enabled = ? WHERE code = ?", (int(enabled), code.strip().upper())
    )
    connection.commit()
    if not result.rowcount:
        raise SystemExit("Code not found.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Oniflow activation codes.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--days", type=int, default=30)
    create.add_argument("--devices", type=int, default=1)
    create.add_argument("--code")
    subparsers.add_parser("list")
    for name in ("enable", "disable"):
        command = subparsers.add_parser(name)
        command.add_argument("code")
    args = parser.parse_args()
    if args.command == "create":
        create_code(args.days, args.devices, args.code)
    elif args.command == "list":
        list_codes()
    else:
        set_enabled(args.code, args.command == "enable")


if __name__ == "__main__":
    main()
