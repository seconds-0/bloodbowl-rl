#!/usr/bin/env python3
"""Measure a verified Windows backing volume through its WSL drvfs mount.

The caller must first pin the distro's Windows BasePath/source drive with
check_wsl_backing_storage.py. This local, bounded check can then run in a
systemd supervisor without network or Windows interop dependencies. Guest
root-filesystem capacity is never a substitute for this physical measurement.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess


def validate_mount(record, mount, drive, device):
    if not re.fullmatch('[A-Z]', drive):
        raise ValueError('expected one uppercase Windows drive letter')
    if record.get('target') != mount or record.get('source') != drive + ':\\':
        raise ValueError('physical mount target/source differs from frozen backing drive')
    options = record.get('options', '')
    if (record.get('fstype') != '9p' or
            not re.search(r'(?:^|,)aname=drvfs(?:;|,|$)', options) or
            f';path={drive}:\\;' not in options):
        raise ValueError('expected exact Windows drvfs volume root')
    if record.get('maj:min') != device:
        raise ValueError('mount device changed during physical storage query')


def collect(mount, drive, expected_volume_bytes):
    if type(expected_volume_bytes) is not int or expected_volume_bytes <= 0:
        raise ValueError('expected physical volume size must be a positive integer')
    path = Path(mount)
    if not path.is_absolute() or str(path.resolve(strict=True)) != mount:
        raise ValueError('physical mount must be an absolute canonical directory')
    fd = os.open(mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        stat = os.fstat(fd)
        device = f'{os.major(stat.st_dev)}:{os.minor(stat.st_dev)}'
        result = subprocess.run(['findmnt', '--json', '--target', mount,
                                 '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS,MAJ:MIN'],
                                capture_output=True, text=True, timeout=5, check=True)
        records = json.loads(result.stdout).get('filesystems')
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError('expected exactly one mounted backing volume')
        validate_mount(records[0], mount, drive, device)
        # Measure the opened device, not a path that could resolve elsewhere.
        usage = os.fstatvfs(fd)
        if os.stat(mount).st_dev != stat.st_dev:
            raise ValueError('physical mount was replaced during query')
        size = usage.f_blocks * usage.f_frsize
        free = usage.f_bavail * usage.f_frsize
        if size != expected_volume_bytes or not 0 <= free <= size:
            raise ValueError('physical volume size differs from Windows preflight')
        return {'schema_version': 1, 'observed_utc': datetime.datetime.now(
            datetime.timezone.utc).isoformat(), 'mount': mount, 'source_drive': drive,
            'device': device, 'volume_bytes': size, 'free_bytes': free,
            'measurement': 'verified Windows drvfs physical backing volume'}
    finally:
        os.close(fd)


def assess(record, minimum_free_bytes, additional_bytes=0):
    for name, value in [('minimum reserve', minimum_free_bytes),
                        ('planned allocation', additional_bytes),
                        ('physical free space', record.get('free_bytes'))]:
        if type(value) is not int or value < 0:
            raise ValueError(f'invalid {name}')
    required = minimum_free_bytes + additional_bytes
    return {**record, 'minimum_reserve_bytes': minimum_free_bytes,
            'planned_additional_bytes': additional_bytes,
            'required_free_bytes': required, 'accepted': record['free_bytes'] >= required}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mount', required=True)
    parser.add_argument('--drive', required=True)
    parser.add_argument('--volume-bytes', required=True, type=int)
    parser.add_argument('--minimum-free-bytes', type=int, default=100 * (1 << 30))
    parser.add_argument('--additional-bytes', type=int, default=0)
    args = parser.parse_args()
    result = assess(collect(args.mount, args.drive, args.volume_bytes),
                    args.minimum_free_bytes, args.additional_bytes)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['accepted'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
