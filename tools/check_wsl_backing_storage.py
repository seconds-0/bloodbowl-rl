#!/usr/bin/env python3
"""Read the Windows backing volume before copying/building/training inside WSL.

Guest df reports virtual VHD capacity, which is not the physical host capacity.
This read-only check must precede a WSL experiment and be repeated by its guard.
"""
import argparse
import base64
import datetime
import json
import math
import re
import subprocess
import sys


def assess(record, minimum_free_bytes, additional_bytes=0):
    if type(minimum_free_bytes) is not int or minimum_free_bytes < 0:
        raise ValueError('invalid minimum physical free space')
    if type(additional_bytes) is not int or additional_bytes < 0:
        raise ValueError('invalid planned additional allocation')
    for key in ('free_bytes', 'volume_bytes', 'vhd_file_bytes'):
        if type(record.get(key)) is not int or record[key] < 0:
            raise ValueError(f'missing or invalid Windows storage field: {key}')
    if record['free_bytes'] > record['volume_bytes']:
        raise ValueError('Windows free space exceeds volume size')
    required = minimum_free_bytes + additional_bytes
    return {**record, 'required_free_bytes': required,
            'minimum_reserve_bytes': minimum_free_bytes,
            'planned_additional_bytes': additional_bytes,
            'accepted': record['free_bytes'] >= required}


def collect(host, distribution, target_drive=None):
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+', host):
        raise ValueError('expected a configured SSH alias or user@IPv4/hostname')
    quoted = distribution.replace("'", "''")
    drive = '' if target_drive is None else target_drive.upper()
    if drive and not re.fullmatch('[A-Z]', drive):
        raise ValueError('target drive must be one letter')
    script = r"""
$ErrorActionPreference='Stop'
$entries=@(Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.DistributionName -eq '__DISTRO__' })
if ($entries.Count -ne 1) { throw 'Expected exactly one registered distribution' }
$base=$entries[0].BasePath
$root=[System.IO.Path]::GetPathRoot($base)
if ($root -notmatch '^[A-Za-z]:\\$') { throw 'Unsupported backing volume path' }
$sourceDrive=$root.Substring(0,1).ToUpper()
$drive='__DRIVE__'
if (-not $drive) { $drive=$sourceDrive }
$vhd=@(Get-ChildItem -LiteralPath $base -Filter '*.vhdx')
if ($vhd.Count -ne 1) { throw 'Expected exactly one distribution VHD' }
$volume=Get-Volume -DriveLetter $drive
@{ distribution=$entries[0].DistributionName; source_drive=$sourceDrive; checked_drive=$drive; backing_path=$vhd[0].FullName; vhd_file_bytes=[long]$vhd[0].Length; free_bytes=[long]$volume.SizeRemaining; volume_bytes=[long]$volume.Size } | ConvertTo-Json -Compress
""".replace('__DISTRO__', quoted).replace('__DRIVE__', drive)
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    command = ['ssh', '-n', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
               host, 'powershell.exe -NoProfile -EncodedCommand ' + encoded]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Windows storage query failed: ' + result.stderr[-2000:])
    record = json.loads(result.stdout)
    if record.get('distribution') != distribution:
        raise RuntimeError('queried distribution identity differs')
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--windows-host', required=True)
    p.add_argument('--distribution', required=True)
    p.add_argument('--target-drive')
    p.add_argument('--min-free-gib', type=float, default=100)
    p.add_argument('--additional-bytes', type=int, default=0)
    args = p.parse_args()
    if not math.isfinite(args.min_free_gib) or args.min_free_gib < 0:
        p.error('minimum free space must be finite and nonnegative')
    record = collect(args.windows_host, args.distribution, args.target_drive)
    result = assess(record, math.ceil(args.min_free_gib * (1 << 30)), args.additional_bytes)
    result.update(schema_version=1, host=args.windows_host,
                  observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  measurement='Windows physical volume; independent of guest virtual free space')
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['accepted'] else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f'backing storage preflight failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
