"""Jalankan metode x seed di emulator. Ryu harus sudah jalan.

    sudo .venv-agent/bin/python -m experiments.run_all --methods static greedy --seeds 1 2 3 4 5
Hasil per run: results/raw/<metode>_s<seed>_<timestamp>/ (steps.csv, urllc_*.csv, salinan config).
"""
import argparse
import time

from agent.env import SlicingEnv
from baselines.greedy import Greedy
from baselines.static_split import StaticSplit

POLICIES = {
    'static': lambda env: StaticSplit(env.agents),
    'greedy': lambda env: Greedy(env.agents, env.cfg),
    # 'ppo_asym' / 'ppo_sym': tambahkan setelah agent/run_policy.py siap (actor beku)
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--methods', nargs='+', choices=list(POLICIES), default=list(POLICIES))
    ap.add_argument('--seeds', nargs='+', type=int, default=[1, 2, 3, 4, 5])
    ap.add_argument('--run-s', type=float, help='durasi per run (default: run_s di config)')
    a = ap.parse_args()
    env = SlicingEnv()
    steps = int((a.run_s or env.cfg['run_s']) / env.cfg['step_s'])
    try:
        for method in a.methods:
            for seed in a.seeds:
                policy = POLICIES[method](env)
                obs, info = env.reset(seed, method)
                print('== %s seed %d -> %s' % (method, seed, env.run_dir))
                for _ in range(steps):
                    t = time.perf_counter()
                    act = policy.act(obs, info)
                    ms = (time.perf_counter() - t) * 1000
                    obs, rew, info = env.step(act, infer_ms=ms)
    finally:
        env.close()  # selalu bersihkan Mininet + QoS


if __name__ == '__main__':
    main()
