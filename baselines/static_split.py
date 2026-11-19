"""Baseline: split statis eMBB 50 / URLLC 30 / BE 20 untuk semua agen (tidak pernah berubah)."""
from topology.qos_setup import load_profiles


class StaticSplit:
    def __init__(self, agents):
        shares = load_profiles()['static_split']
        self.actions = {a: shares for a in agents}

    def act(self, obs, info):
        return self.actions
