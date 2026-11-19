"""Baca statistik kelas HTB dari `tc -s class show` (backlog/drop tidak ada di OpenFlow).

OVS linux-htb memetakan queue n ke kelas 1:(n+1). Hasil: {queue_id: {bytes, pkts, drops, backlog_bytes, backlog_pkts}}.
"""
import re
import subprocess

UNIT = {'': 1, 'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3}
CLASS_RE = re.compile(
    r'htb 1:([0-9a-f]+) .*?Sent (\d+) bytes (\d+) pkt \(dropped (\d+),.*?backlog ([\d.]+)([KMG]?)b (\d+)p', re.S)


def parse(text):
    out = {}
    for block in re.split(r'(?m)^class ', text):
        m = CLASS_RE.match(block)
        if not m:
            continue
        minor = int(m.group(1), 16)
        if minor == 0xfffe:  # kelas root, bukan queue
            continue
        out[minor - 1] = {
            'bytes': int(m.group(2)), 'pkts': int(m.group(3)), 'drops': int(m.group(4)),
            'backlog_bytes': int(float(m.group(5)) * UNIT[m.group(6)]), 'backlog_pkts': int(m.group(7)),
        }
    return out


def read_classes(dev):
    return parse(subprocess.run(['tc', '-s', 'class', 'show', 'dev', dev],
                                check=True, capture_output=True, text=True).stdout)


def tx_bytes(dev):
    with open('/sys/class/net/%s/statistics/tx_bytes' % dev) as f:
        return int(f.read())


SAMPLE = """class htb 1:1 parent 1:fffe prio 0 rate 4Mbit ceil 4Mbit burst 1563b cburst 1563b
 Sent 1200 bytes 10 pkt (dropped 0, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
 lended: 10 borrowed: 0 giants: 0
class htb 1:fffe root rate 20Mbit ceil 20Mbit burst 1500b cburst 1500b
 Sent 99999 bytes 70 pkt (dropped 0, overlimits 0 requeues 0)
 backlog 0b 0p requeues 0
class htb 1:2 parent 1:fffe prio 0 rate 6Mbit ceil 6Mbit burst 1599b cburst 1599b
 Sent 5000 bytes 50 pkt (dropped 3, overlimits 9 requeues 0)
 backlog 2800b 2p requeues 0
class htb 1:3 parent 1:fffe prio 0 rate 10Mbit ceil 10Mbit burst 1600b cburst 1600b
 Sent 3000000 bytes 2100 pkt (dropped 120, overlimits 400 requeues 0)
 backlog 1352Kb 990p requeues 0
"""

if __name__ == '__main__':
    r = parse(SAMPLE)
    assert sorted(r) == [0, 1, 2], r
    assert r[1] == {'bytes': 5000, 'pkts': 50, 'drops': 3, 'backlog_bytes': 2800, 'backlog_pkts': 2}
    assert r[2]['backlog_bytes'] == 1352 * 1024 and r[2]['drops'] == 120
    print('tc_reader OK')
