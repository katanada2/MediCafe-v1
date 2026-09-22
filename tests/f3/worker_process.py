from __future__ import annotations

import argparse

import django


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--lease-seconds", type=int, required=True)
    parser.add_argument("--test-mode", required=True)
    args = parser.parse_args()
    django.setup()
    from medicafe_v1.claims.delivery_worker import run_delivery_worker_once

    result = run_delivery_worker_once(
        worker_id=args.worker_id, lease_seconds=args.lease_seconds,
        test_mode=args.test_mode,
    )
    print(result.reason_code)


if __name__ == "__main__":
    main()
