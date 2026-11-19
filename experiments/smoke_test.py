"""Smoke test otomatis (checklist 7.9). Ryu harus sudah jalan.

    sudo .venv-agent/bin/python -m experiments.smoke_test
"""
import os
import subprocess
import sys
import time

import requests
from mininet.log import setLogLevel

from monitor.tc_reader import read_classes
from topology.qos_setup import ROOT, load_cfg, load_profiles
from topology.topo import start_net

PY = sys.executable
failed = []


def check(name, ok, detail=''):
    print('[%s] %s %s' % ('PASS' if ok else 'FAIL', name, detail))
    if not ok:
        failed.append(name)


def main():
    setLogLevel('warning')
    cfg, prof = load_cfg(), load_profiles()
    Q, cap = cfg['queues'], cfg['capacity_bps']
    out_dir = os.path.join(ROOT, 'results', 'raw', 'smoke')
    os.makedirs(out_dir, exist_ok=True)
    probe_csv = os.path.join(out_dir, 'urllc.csv')
    rest = '%s/slice/%d/profile' % (cfg['rest_url'], cfg['switches']['agg1'])

    net = start_net(cfg)  # gagal (exception) bila pingall tidak 0% loss
    check('pingall topologi 8 switch', True)
    procs = []
    try:
        flows = subprocess.run(['ovs-ofctl', '-O', 'OpenFlow13', 'dump-flows', 'agg1'],
                               capture_output=True, text=True).stdout
        check('flow set_queue terpasang di agg1', 'set_queue:1' in flows and 'set_queue:2' in flows)

        port, h1, srv = cfg['agents']['agg1']['port'], net.get('h1'), net.get('srv1')
        procs.append(srv.popen([PY, '-m', 'traffic.urllc_probe', 'recv', '--out', probe_csv], cwd=ROOT))
        procs.append(srv.popen([PY, '-m', 'traffic.embb_sender', 'sink', '--kind', 'embb'], cwd=ROOT))
        r = requests.post(rest, json={'shares': prof['static_split'], 'mode': 'strict'}, timeout=5)
        check('REST set shares statis', r.ok, r.text)
        time.sleep(1)

        before = read_classes(port)
        procs.append(h1.popen([PY, '-m', 'traffic.urllc_probe', 'send', '--dst', srv.IP(), '--duration', '20'], cwd=ROOT))
        embb = h1.popen([PY, '-m', 'traffic.embb_sender', 'send', '--dst', srv.IP(), '--kind', 'embb',
                         '--mbps', '25', '--duration', '20'], cwd=ROOT)
        procs.append(embb)
        h1.cmd('ping -c 20 -i 0.05 %s' % srv.IP())
        time.sleep(2)
        mid = read_classes(port)
        delta = {q: mid[q]['pkts'] - before[q]['pkts'] for q in mid}
        check('ping (BE) masuk queue 0', delta[Q['be']] >= 20, str(delta))
        check('UDP 5001 (URLLC) masuk queue 1', 100 <= delta[Q['urllc']] < 1000, str(delta))
        check('UDP 5002 (eMBB) masuk queue 2', delta[Q['embb']] > 1000, str(delta))

        def thr(secs=3):
            a = read_classes(port)[Q['embb']]['bytes']
            time.sleep(secs)
            return (read_classes(port)[Q['embb']]['bytes'] - a) * 8 / secs

        t1 = thr()
        r = requests.post(rest, json={'profile': 4, 'mode': 'strict'}, timeout=5)
        check('REST ganti ke profil 4', r.ok, r.text)
        time.sleep(1)
        t2 = thr()
        e1, e2 = cap * prof['static_split']['embb'] / 100, cap * prof['profiles'][4]['embb'] / 100
        check('throughput eMBB mengikuti rate queue', abs(t1 - e1) < 0.15 * e1 and abs(t2 - e2) < 0.15 * e2,
              '%.1f -> %.1f Mbps (target %.0f -> %.0f)' % (t1 / 1e6, t2 / 1e6, e1 / 1e6, e2 / 1e6))
        check('flow eMBB tidak putus saat rate diubah', embb.poll() is None)
        time.sleep(0.5)
        with open(probe_csv) as f:
            rows = sum(1 for _ in f) - 1
        check('probe URLLC menulis CSV', rows > 100, '%d baris' % rows)
    finally:
        for p in procs:
            p.terminate()
        net.stop()
        subprocess.run(['bash', os.path.join(ROOT, 'scripts', 'cleanup.sh')])
    print('\nSEMUA LULUS' if not failed else '\nGAGAL: %s' % ', '.join(failed))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
