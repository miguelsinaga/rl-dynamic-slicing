"""Pengirim UDP dengan rate berubah (iperf3 tidak bisa ganti rate di tengah run) + sink penerima.

Dipakai untuk eMBB (port 5002) dan beban URLLC (port 5001).
    python -m traffic.embb_sender send --dst 10.0.0.5 --kind embb --seed 101
    python -m traffic.embb_sender send --dst 10.0.0.5 --kind embb --mbps 25 --duration 10   # rate tetap
    python -m traffic.embb_sender sink --port 5002
"""
import argparse
import socket
import time

from topology.qos_setup import load_cfg
from traffic.scheduler import RateSchedule

PORT_OF = {'embb': 'embb', 'urllc_load': 'urllc'}


def send(dst, port, rate_mbps, size, duration):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = bytes(size)
    t0 = last = time.time()
    credit = 0.0
    while True:
        now = time.time()
        if now - t0 >= duration:
            break
        # token bucket: kredit byte sesuai rate, burst dibatasi 64 paket
        credit = min(credit + max(0.0, rate_mbps(now - t0)) * 1e6 / 8 * (now - last), 64 * size)
        last = now
        while credit >= size:
            s.sendto(payload, (dst, port))
            credit -= size
        time.sleep(0.001)


def sink(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('', port))
    while True:
        s.recv(65535)


def main():
    cfg = load_cfg()
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['send', 'sink'])
    ap.add_argument('--dst')
    ap.add_argument('--kind', choices=list(PORT_OF), default='embb')
    ap.add_argument('--port', type=int)
    ap.add_argument('--seed', type=int, default=cfg['seed'])
    ap.add_argument('--mbps', type=float, help='rate tetap (abaikan pola)')
    ap.add_argument('--duration', type=float, default=float('inf'))
    a = ap.parse_args()
    port = a.port or cfg['ports'][PORT_OF[a.kind]]
    if a.mode == 'sink':
        return sink(port)
    tc = cfg['traffic'][a.kind]
    rate = (lambda t: a.mbps) if a.mbps is not None else RateSchedule(seed=a.seed, **tc).mbps
    send(a.dst, port, rate, tc['size'], a.duration)


if __name__ == '__main__':
    main()
