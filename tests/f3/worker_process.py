from __future__ import annotations

import argparse
import time
from pathlib import Path

import django


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--lease-seconds", type=int, required=True)
    parser.add_argument("--test-mode")
    parser.add_argument("--barrier-after-marker")
    parser.add_argument("--barrier-after-transport")
    args = parser.parse_args()
    django.setup()
    from medicafe_v1.claims.delivery_worker import run_delivery_worker_once

    def stop_at(path):
        def callback(*_args):
            Path(path).write_text("reached", encoding="utf-8")
            while True:
                time.sleep(1)
        return callback

    result = run_delivery_worker_once(
        worker_id=args.worker_id, lease_seconds=args.lease_seconds,
        test_mode=args.test_mode,
        after_marker=(stop_at(args.barrier_after_marker)
                      if args.barrier_after_marker else None),
        after_transport=(stop_at(args.barrier_after_transport)
                         if args.barrier_after_transport else None),
    )
    print(result.reason_code)


if __name__ == "__main__":
    main()
