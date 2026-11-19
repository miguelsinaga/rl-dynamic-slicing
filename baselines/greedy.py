"""Baseline: heuristik greedy terpusat.

Satu pengambil keputusan melihat metrik mentah semua port (info dari env):
URLLC tertekan (backlog tinggi / P99 lewat ambang) -> profil URLLC besar;
eMBB menumpuk -> profil eMBB besar; selain itu kembali ke profil default.
"""


class Greedy:
    def __init__(self, agents, cfg):
        self.agents, self.q, self.g = agents, cfg['queues'], cfg['greedy']
        self.p99_ms = cfg['reward']['urllc_p99_ms']

    def act(self, obs, info):
        out = {}
        for a in self.agents:
            m = info[a]
            if m['backlog'][self.q['urllc']] > self.g['urllc_backlog_high'] or m['urllc_p99_ms'] > self.p99_ms:
                out[a] = self.g['urllc_profile']
            elif m['backlog'][self.q['embb']] > self.g['embb_backlog_high']:
                out[a] = self.g['embb_profile']
            else:
                out[a] = self.g['default_profile']
        return out
