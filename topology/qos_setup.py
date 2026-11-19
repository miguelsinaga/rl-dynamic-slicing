"""QoS linux-htb di port bottleneck lewat OVSDB (ovs-vsctl).

Modul ini juga diimpor Ryu (Python 3.9): tetap kompatibel 3.9, dependensi hanya pyyaml.
"""
import os
import subprocess

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_cfg(name='experiment.yaml'):
    with open(os.path.join(ROOT, 'config', name)) as f:
        return yaml.safe_load(f)


def load_profiles():
    return load_cfg('profiles.yaml')


def vsctl(args, db=None):
    cmd = ['ovs-vsctl'] + (['--db=' + db] if db else []) + list(args)
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def queue_rates(shares, cfg, mode):
    """shares {urllc, embb, be} dalam persen -> [(min_bps, max_bps)] urut queue id."""
    cap = cfg['capacity_bps']
    rates = [None] * len(cfg['queues'])
    for cls, q in cfg['queues'].items():
        r = int(cap * shares[cls] / 100)
        rates[q] = (r, r if mode == 'strict' else cap)
    return rates


def setup_qos(cfg, shares, mode):
    """Buat QoS + 3 queue di setiap port bottleneck. Butuh root (socket OVSDB lokal)."""
    vsctl(['set-manager', 'ptcp:6640:127.0.0.1'])  # supaya Ryu bisa ubah queue tanpa sudo
    for agent in cfg['agents'].values():
        rates = queue_rates(shares, cfg, mode)
        args = ['--', 'set', 'port', agent['port'], 'qos=@qos',
                '--', '--id=@qos', 'create', 'qos', 'type=linux-htb',
                'other-config:max-rate=%d' % cfg['capacity_bps']]
        args += ['queues:%d=@q%d' % (q, q) for q in range(len(rates))]
        for q, (lo, hi) in enumerate(rates):
            args += ['--', '--id=@q%d' % q, 'create', 'queue',
                     'other-config:min-rate=%d' % lo, 'other-config:max-rate=%d' % hi]
        vsctl(args)


def set_rates(port, shares, cfg, mode, db=None):
    """Ubah rate queue yang sudah ada (flow rule tidak disentuh, flow tidak putus)."""
    qos = vsctl(['get', 'port', port, 'qos'], db)
    raw = vsctl(['get', 'qos', qos, 'queues'], db)  # "{0=uuid, 1=uuid, 2=uuid}"
    uuids = dict(kv.split('=') for kv in raw.strip('{}').split(', '))
    args = []
    for q, (lo, hi) in enumerate(queue_rates(shares, cfg, mode)):
        args += ['--', 'set', 'queue', uuids[str(q)],
                 'other-config:min-rate=%d' % lo, 'other-config:max-rate=%d' % hi]
    vsctl(args, db)
