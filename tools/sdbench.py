#!/usr/bin/env python3
"""Small SD card benchmark and stall detector for a Raspberry Pi. No dependencies.

Usage:
    sudo python3 tools/sdbench.py                 # quick benchmark (~1 min)
    sudo python3 tools/sdbench.py --soak 30       # additionally watch for stalls for 30 minutes
    sudo python3 tools/sdbench.py --dir /var/tmp --size 256

Run it as root (it drops the page cache so reads really hit the card).
It writes one test file into --dir (default /var/tmp, i.e. the SD card) and removes it.
Typical numbers for a healthy A1 card: seq write 10-40 MB/s, random 4k write with
fsync 2-15 ms per operation. Single operations of 500 ms or more are stalls.
"""
import argparse
import mmap
import os
import random
import re
import statistics
import subprocess
import sys
import time

BLOCK = 4096
STALL = 0.5  # seconds


def sysinfo():
    base = "/sys/block/mmcblk0/device/"
    out = {}
    for key in ("name", "manfid", "date", "oemid"):
        try:
            out[key] = open(base + key).read().strip()
        except OSError:
            out[key] = "?"
    print("Card: name=%(name)s manfid=%(manfid)s oemid=%(oemid)s date=%(date)s" % out)
    try:
        dm = subprocess.run(["dmesg", "-T"], capture_output=True, text=True).stdout
        n = len(re.findall(r"blocked for more than", dm))
        print(f"Kernel messages 'blocked for more than ...': {n}")
    except OSError:
        pass


def drop_caches():
    os.sync()
    try:
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write("3\n")
    except OSError:
        print("  (cannot drop caches, run as root for honest read numbers)")


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


def report(name, lat, extra=""):
    ms = [v * 1000 for v in lat]
    stalls = sum(1 for v in lat if v >= STALL)
    print(f"  {name:<22} n={len(ms):<5} median {statistics.median(ms):7.1f} ms  "
          f"p95 {pct(ms, 0.95):7.1f} ms  max {max(ms):8.1f} ms  stalls {stalls} {extra}")


def seq_write(path, size_mb):
    chunk = os.urandom(1 << 20)
    lat = []
    t0 = time.monotonic()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    for _ in range(size_mb):
        t = time.monotonic()
        os.write(fd, chunk)
        os.fsync(fd)
        lat.append(time.monotonic() - t)
    os.close(fd)
    dt = time.monotonic() - t0
    print(f"  sequential write       {size_mb / dt:6.1f} MB/s")
    report("  1 MB write+fsync", lat)


def seq_read(path, size_mb):
    drop_caches()
    t0 = time.monotonic()
    lat = []
    with open(path, "rb", buffering=0) as f:
        while True:
            t = time.monotonic()
            data = f.read(1 << 20)
            if not data:
                break
            lat.append(time.monotonic() - t)
    dt = time.monotonic() - t0
    print(f"  sequential read        {size_mb / dt:6.1f} MB/s")


def rand_read(path, size_mb, count=500):
    drop_caches()
    fd = os.open(path, os.O_RDONLY | os.O_DIRECT)
    buf = mmap.mmap(-1, BLOCK)  # page aligned, needed for O_DIRECT
    blocks = size_mb * 1024 * 1024 // BLOCK
    lat = []
    for _ in range(count):
        off = random.randrange(blocks) * BLOCK
        t = time.monotonic()
        os.preadv(fd, [buf], off)
        lat.append(time.monotonic() - t)
    os.close(fd)
    report("random 4k read", lat, f"({1 / statistics.mean(lat):.0f} IOPS)")


def rand_write(path, size_mb, count=300):
    fd = os.open(path, os.O_WRONLY | os.O_SYNC)
    blocks = size_mb * 1024 * 1024 // BLOCK
    data = os.urandom(BLOCK)
    lat = []
    for _ in range(count):
        off = random.randrange(blocks) * BLOCK
        t = time.monotonic()
        os.pwrite(fd, data, off)
        lat.append(time.monotonic() - t)
    os.close(fd)
    report("random 4k write+sync", lat, f"({1 / statistics.mean(lat):.0f} IOPS)")


def soak(path, minutes):
    """Write 4k + fsync once per second and log every slow operation with a timestamp."""
    print(f"\nSoak test for {minutes} min (Ctrl-C ends it early). Slow operations are logged:")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT)
    data = os.urandom(BLOCK)
    end = time.monotonic() + minutes * 60
    n = slow = 0
    worst = 0.0
    try:
        while time.monotonic() < end:
            t = time.monotonic()
            os.pwrite(fd, data, random.randrange(1024) * BLOCK)
            os.fsync(fd)
            d = time.monotonic() - t
            n += 1
            worst = max(worst, d)
            if d >= STALL:
                slow += 1
                print(f"  {time.strftime('%H:%M:%S')}  write+fsync took {d * 1000:8.0f} ms")
            time.sleep(max(0.0, 1.0 - d))
    except KeyboardInterrupt:
        pass
    os.close(fd)
    print(f"Soak done: {n} writes, {slow} slow (>= {STALL * 1000:.0f} ms), worst {worst * 1000:.0f} ms")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="/var/tmp", help="directory on the card to test (default /var/tmp)")
    ap.add_argument("--size", type=int, default=128, help="test file size in MB (default 128)")
    ap.add_argument("--soak", type=float, default=0, help="minutes of stall watching after the benchmark")
    args = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("Please run as root: sudo python3 tools/sdbench.py")
    path = os.path.join(args.dir, "sdbench.tmp")
    sysinfo()
    try:
        print("\nBenchmark:")
        seq_write(path, args.size)
        seq_read(path, args.size)
        rand_read(path, args.size)
        rand_write(path, args.size)
        if args.soak:
            soak(path, args.soak)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    sysinfo()


if __name__ == "__main__":
    main()
