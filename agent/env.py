"""Environment emulator (Opsi A): reset(seed) / step(actions). Satu actor per port bottleneck.

Prasyarat: ryu-manager sudah jalan. Butuh root (Mininet, OVSDB lokal).
Aksi per agen: indeks profil (int) atau dict shares {urllc, embb, be} (dipakai baseline statis).
Observasi actor  : backlog 3 kelas /1000 + throughput 3 kelas /kapasitas + one-hot aksi sebelumnya.
Observasi critic : info['global'] = gabungan observasi semua actor + utilisasi link core1-core2.
"""
import csv
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import requests

from monitor.tc_reader import read_classes, tx_bytes
from topology.qos_setup import ROOT, load_cfg, load_profiles
from topology.topo import start_net
from traffic.scheduler import RateSchedule

BACKLOG_NORM = 1000.0  # = txqueuelen default, batas antrian leaf HTB
COLUMNS = ['t', 'method', 'seed', 'step', 'agent', 'action', 'infer_ms', 'reward',
           'embb_thr_bps', 'embb_demand_bps', 'urllc_p99_ms', 'urllc_n', 'drop_rate',
           'backlog_q0', 'backlog_q1', 'backlog_q2', 'thr_q0_bps', 'thr_q1_bps', 'thr_q2_bps', 'core_util']


class SlicingEnv:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_cfg()
        self.prof = load_profiles()
        self.agents = sorted(self.cfg['agents'])
        self.n_actions = len(self.prof['profiles'])
        self.obs_dim = 2 * len(self.cfg['queues']) + self.n_actions
        self.global_dim = len(self.agents) * self.obs_dim + 1
        self.procs, self.log_file, self.readers = [], None, {}
        self.net = start_net(self.cfg)
        self.ip = {h.name: h.IP() for h in self.net.hosts}

    # ---------- siklus episode ----------
    def reset(self, seed, method='rl'):
        self._close_run()
        self.seed, self.method, self.n = seed, method, 0
        self.run_dir = os.path.join(ROOT, 'results', 'raw', '%s_s%d_%s' % (method, seed, time.strftime('%Y%m%d-%H%M%S')))
        os.makedirs(self.run_dir)
        for name in ('experiment.yaml', 'profiles.yaml'):  # versi konfigurasi ikut tersimpan per run
            shutil.copy(os.path.join(ROOT, 'config', name), self.run_dir)
        self.log_file = open(os.path.join(self.run_dir, 'steps.csv'), 'w', newline='')
        self.log = csv.writer(self.log_file)
        self.log.writerow(COLUMNS)
        self.last = {}
        for a in self.agents:
            self._apply(a, self.prof['static_split'])
        self._start_traffic(seed)
        time.sleep(1)  # biarkan antrian terisi dulu
        self._snapshot()
        time.sleep(self.cfg['step_s'])
        obs, _, info = self._measure()
        return obs, info

    def step(self, actions, infer_ms=0.0):
        for a, act in actions.items():
            self._apply(a, act)
        time.sleep(self.cfg['step_s'])
        self.n += 1
        return self._measure(infer_ms)

    def close(self):
        self._close_run()
        self.net.stop()
        subprocess.run(['bash', os.path.join(ROOT, 'scripts', 'cleanup.sh')])

    # ---------- aksi ----------
    def _apply(self, agent, act):
        if self.last.get(agent) == act:
            return
        body = {'shares': act} if isinstance(act, dict) else {'profile': int(act)}
        r = requests.post('%s/slice/%d/profile' % (self.cfg['rest_url'], self.cfg['switches'][agent]),
                          json=body, timeout=5)
        r.raise_for_status()
        self.last[agent] = act

    # ---------- trafik ----------
    def _popen(self, host, args, logname):
        f = open(os.path.join(self.run_dir, logname), 'w')
        self.procs.append((self.net.get(host).popen(args, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT), f))

    def _start_traffic(self, seed):
        c, P, py = self.cfg, self.cfg['ports'], sys.executable
        self.servers = sorted(set(c['flows'].values()))
        for s in self.servers:
            self._popen(s, [py, '-m', 'traffic.urllc_probe', 'recv',
                            '--out', os.path.join(self.run_dir, 'urllc_%s.csv' % s)], '%s_probe.log' % s)
            self._popen(s, [py, '-m', 'traffic.embb_sender', 'sink', '--kind', 'embb'], '%s_sink.log' % s)
        for i, (h, s) in enumerate(c['be_flows']):
            self._popen(s, ['iperf3', '-s', '-p', str(P['be'] + i)], '%s_iperf%d.log' % (s, i))
        time.sleep(1)  # server siap sebelum klien mulai
        self.sched = {}
        for i, (h, s) in enumerate(sorted(c['flows'].items())):
            hs = seed * 100 + i  # seed berbeda per host, tetap reproducible
            self.sched[h] = RateSchedule(seed=hs, **c['traffic']['embb'])
            self._popen(h, [py, '-m', 'traffic.urllc_probe', 'send', '--dst', self.ip[s]], '%s_probe.log' % h)
            self._popen(h, [py, '-m', 'traffic.embb_sender', 'send', '--dst', self.ip[s],
                            '--kind', 'embb', '--seed', str(hs)], '%s_embb.log' % h)
            self._popen(h, [py, '-m', 'traffic.embb_sender', 'send', '--dst', self.ip[s],
                            '--kind', 'urllc_load', '--seed', str(hs + 50)], '%s_urllc_load.log' % h)
        for i, (h, s) in enumerate(c['be_flows']):
            self._popen(h, ['iperf3', '-c', self.ip[s], '-p', str(P['be'] + i), '-t', '86400', '-C', 'bbr'],
                        '%s_be%d.log' % (h, i))
        self.t0 = time.time()

    def _close_run(self):
        for p, _ in self.procs:
            p.terminate()
        for p, f in self.procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
            f.close()
        for f in self.readers.values():
            f.close()
        if self.log_file:
            self.log_file.close()
        self.procs, self.readers, self.buf, self.log_file = [], {}, {}, None

    # ---------- pengukuran ----------
    def _snapshot(self):
        self.prev_tc = {a: read_classes(self.cfg['agents'][a]['port']) for a in self.agents}
        self.prev_core = sum(tx_bytes(p) for p in self.cfg['core_ports'])
        self.prev_t = time.time()

    def _read_urllc(self):
        """Delay probe baru sejak langkah sebelumnya: {ip_sumber: [delay_ms]}."""
        out = {}
        for s in self.servers:
            if s not in self.readers:
                path = os.path.join(self.run_dir, 'urllc_%s.csv' % s)
                if not os.path.exists(path):
                    continue
                self.readers[s], self.buf[s] = open(path), ''
            lines = (self.buf[s] + self.readers[s].read()).split('\n')
            self.buf[s] = lines.pop()  # baris terakhir mungkin belum lengkap
            for ln in lines:
                if ln and not ln.startswith('t,'):
                    _, src, _, d = ln.split(',')
                    out.setdefault(src, []).append(float(d))
        return out

    def _measure(self, infer_ms=0.0):
        now = time.time()
        dt = now - self.prev_t
        tc = {a: read_classes(self.cfg['agents'][a]['port']) for a in self.agents}
        core = sum(tx_bytes(p) for p in self.cfg['core_ports'])
        core_util = (core - self.prev_core) * 8 / dt / self.cfg['core_link_bps']
        delays = self._read_urllc()
        R, Q, nq = self.cfg['reward'], self.cfg['queues'], len(self.cfg['queues'])
        obs, rew, info = {}, {}, {'core_util': core_util}
        for a in self.agents:
            spec, cur, prev = self.cfg['agents'][a], tc[a], self.prev_tc[a]
            thr = [(cur[q]['bytes'] - prev[q]['bytes']) * 8 / dt for q in range(nq)]
            sent = sum(cur[q]['pkts'] - prev[q]['pkts'] for q in range(nq))
            drops = sum(cur[q]['drops'] - prev[q]['drops'] for q in range(nq))
            drop_rate = drops / max(1, sent + drops)
            backlog = [cur[q]['backlog_pkts'] for q in range(nq)]
            d = [x for h in spec['hosts'] for x in delays.get(self.ip[h], [])]
            p99 = float(np.percentile(d, 99)) if d else float('inf')  # tak ada probe tiba = delay > 1 langkah
            demand = sum(self.sched[h].mbps(now - self.t0) for h in spec['hosts']) * 1e6
            embb = thr[Q['embb']]
            rew[a] = (R['w1'] * min(1.0, embb / demand)
                      - R['w2'] * float(p99 > R['urllc_p99_ms'])
                      - R['w3'] * drop_rate)
            onehot = np.zeros(self.n_actions)
            last = self.last.get(a)
            if not isinstance(last, dict) and last is not None:
                onehot[int(last)] = 1
            obs[a] = np.concatenate([np.array(backlog) / BACKLOG_NORM,
                                     np.array(thr) / self.cfg['capacity_bps'], onehot]).astype(np.float32)
            info[a] = dict(backlog=backlog, thr=thr, drop_rate=drop_rate, urllc_p99_ms=p99,
                           urllc_n=len(d), embb_thr=embb, embb_demand=demand)
            self.log.writerow(['%.3f' % now, self.method, self.seed, self.n, a,
                               'shares' if isinstance(last, dict) else last, '%.3f' % infer_ms, '%.4f' % rew[a],
                               int(embb), int(demand), '%.3f' % p99, len(d), '%.4f' % drop_rate,
                               *backlog, *(int(x) for x in thr), '%.4f' % core_util])
        self.log_file.flush()
        info['global'] = np.concatenate([obs[a] for a in self.agents] + [[core_util]]).astype(np.float32)
        self.prev_tc, self.prev_core, self.prev_t = tc, core, now
        return obs, rew, info
