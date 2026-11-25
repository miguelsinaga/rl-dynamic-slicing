"""Training PPO asimetris / simetris langsung di emulator (Opsi A). Ryu harus sudah jalan.

    sudo .venv-agent/bin/python -m agent.train --variant asym --seed 1
    sudo .venv-agent/bin/python -m agent.train --variant sym  --seed 1

Output:
    results/train/<varian>_s<seed>.csv          kurva reward per episode
    checkpoints/<varian>_s<seed>/ep<N>.pt       checkpoint berkala (di-ignore git)
    checkpoints/final/ppo_<varian>_s<seed>.pt   actor final (kecil, boleh masuk repo)
"""
import argparse
import csv
import os
import time

import numpy as np
import torch

from agent.env import SlicingEnv
from agent.ppo import PPO
from topology.qos_setup import ROOT, load_cfg


def run_episode(env, policy, seed, method):
    obs, info = env.reset(seed, method)
    A = env.agents
    ep = dict(obs={a: [] for a in A}, glob=[], act={a: [] for a in A}, logp={a: [] for a in A}, rew=[])
    for _ in range(env.cfg['episode_steps']):
        t = time.perf_counter()
        acts, logps = policy.act(obs)
        ms = (time.perf_counter() - t) * 1000
        for a in A:
            ep['obs'][a].append(obs[a]); ep['act'][a].append(acts[a]); ep['logp'][a].append(logps[a])
        ep['glob'].append(info['global'])
        obs, rew, info = env.step(acts, infer_ms=ms)
        ep['rew'].append([rew[a] for a in A])
    for a in A:  # state terakhir untuk bootstrap value
        ep['obs'][a].append(obs[a])
    ep['glob'].append(info['global'])
    return ep


def main():
    hp = load_cfg('ppo.yaml')
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', choices=['asym', 'sym'], required=True)
    ap.add_argument('--seed', type=int, default=load_cfg()['seed'])
    ap.add_argument('--episodes', type=int, default=hp['episodes'])
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    np.random.seed(a.seed)

    name = '%s_s%d' % (a.variant, a.seed)
    ck_dir, final_dir, log_dir = (os.path.join(ROOT, *p) for p in
                                  (('checkpoints', name), ('checkpoints', 'final'), ('results', 'train')))
    for d in (ck_dir, final_dir, log_dir):
        os.makedirs(d, exist_ok=True)

    env = SlicingEnv()
    policy = PPO(env.agents, env.obs_dim, env.n_actions, env.global_dim, a.variant == 'asym', hp)
    log_f = open(os.path.join(log_dir, name + '.csv'), 'w', newline='')
    log = csv.writer(log_f)
    log.writerow(['episode', 'time', 'return_mean'] + ['return_' + ag for ag in env.agents] +
                 ['pg_loss', 'v_loss', 'entropy'])
    batch = []
    try:
        for ep_i in range(a.episodes):
            ep = run_episode(env, policy, a.seed * 1000 + ep_i, 'train_' + a.variant)
            batch.append(ep)
            ret = np.sum(ep['rew'], axis=0)
            stats = {}
            if len(batch) == hp['episodes_per_update']:
                stats = policy.update(batch)
                batch = []
            log.writerow([ep_i, '%.0f' % time.time(), '%.3f' % ret.mean()] + ['%.3f' % r for r in ret] +
                         ['%.4f' % stats[k] if stats else '' for k in ('pg_loss', 'v_loss', 'entropy')])
            log_f.flush()
            print('episode %d/%d  return %.2f' % (ep_i + 1, a.episodes, ret.mean()))
            if (ep_i + 1) % hp['save_every'] == 0:
                policy.save(os.path.join(ck_dir, 'ep%d.pt' % (ep_i + 1)))
        policy.save(os.path.join(final_dir, 'ppo_%s.pt' % name))
    finally:
        log_f.close()
        env.close()


if __name__ == '__main__':
    main()
