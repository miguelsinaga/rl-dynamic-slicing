"""Probe URLLC: paket UDP kecil bertimestamp tiap 10 ms; penerima mencatat one-way delay per paket.

Host Mininet berbagi jam kernel yang sama, jadi (t_terima - t_kirim) adalah one-way delay yang valid.
    python -m traffic.urllc_probe send --dst 10.0.0.5
    python -m traffic.urllc_probe recv --out results/raw/urllc_srv1.csv
"""
import argparse
import csv
import socket
import struct
import time

from topology.qos_setup import load_cfg

MAGIC = b'URLC'
HDR = struct.Struct('!4sId')  # magic, seq, timestamp kirim


def send(dst, port, interval, size, duration):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pad = bytes(max(0, size - HDR.size))
    t0, seq = time.time(), 0
    while time.time() - t0 < duration:
        s.sendto(HDR.pack(MAGIC, seq, time.time()) + pad, (dst, port))
        seq += 1
        time.sleep(max(0.0, t0 + seq * interval - time.time()))


def recv(port, out):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('', port))
    with open(out, 'w', newline='', buffering=1) as f:  # line-buffered: env membaca file ini saat berjalan
        w = csv.writer(f)
        w.writerow(['t', 'src', 'seq', 'delay_ms'])
        while True:
            data, (src, _) = s.recvfrom(65535)
            now = time.time()
            if len(data) < HDR.size or data[:4] != MAGIC:
                continue  # beban URLLC biasa ikut masuk port ini, bukan probe
            _, seq, ts = HDR.unpack_from(data)
            w.writerow(['%.6f' % now, src, seq, '%.3f' % ((now - ts) * 1000)])


def main():
    cfg = load_cfg()
    p = cfg['traffic']['probe']
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['send', 'recv'])
    ap.add_argument('--dst')
    ap.add_argument('--port', type=int, default=cfg['ports']['urllc'])
    ap.add_argument('--out')
    ap.add_argument('--duration', type=float, default=float('inf'))
    a = ap.parse_args()
    if a.mode == 'send':
        send(a.dst, a.port, p['interval_ms'] / 1000, p['size'], a.duration)
    else:
        recv(a.port, a.out)


if __name__ == '__main__':
    main()
