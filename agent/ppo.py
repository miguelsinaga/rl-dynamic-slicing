"""PPO multi-agen: satu actor per port bottleneck (input observasi lokal saja).

asymmetric=True  : satu critic melihat state global (info['global']) dan memberi value tiap agen.
asymmetric=False : baseline PPO simetris, critic per agen hanya melihat observasi lokal.
Selain input critic, arsitektur dan hyperparameter sama persis.
Setelah training, hanya actor yang dipakai saat eksekusi (lightweight inference).
"""
import numpy as np
import torch
import torch.nn as nn
from torch.distributions import Categorical

torch.set_num_threads(1)  # MLP kecil: multithread justru lebih lambat dan berebut CPU dengan emulator


def mlp(n_in, n_out, hidden):
    return nn.Sequential(nn.Linear(n_in, hidden), nn.Tanh(),
                         nn.Linear(hidden, hidden), nn.Tanh(),
                         nn.Linear(hidden, n_out))


class PPO:
    def __init__(self, agents, obs_dim, n_actions, global_dim, asymmetric, hp):
        self.agents, self.asym, self.hp = list(agents), asymmetric, hp
        self.dims = dict(obs_dim=obs_dim, n_actions=n_actions, global_dim=global_dim)
        h = hp['hidden']
        self.actors = nn.ModuleDict({a: mlp(obs_dim, n_actions, h) for a in self.agents})
        if asymmetric:
            self.critic = mlp(global_dim, len(self.agents), h)
        else:
            self.critic = nn.ModuleDict({a: mlp(obs_dim, 1, h) for a in self.agents})
        self.params = list(self.actors.parameters()) + list(self.critic.parameters())
        self.opt = torch.optim.Adam(self.params, lr=hp['lr'])

    @torch.no_grad()
    def act(self, obs, greedy=False):
        """obs {agen: array} -> ({agen: aksi}, {agen: log_prob})."""
        acts, logps = {}, {}
        for a in self.agents:
            logits = self.actors[a](torch.as_tensor(obs[a], dtype=torch.float32))
            d = Categorical(logits=logits)
            x = logits.argmax() if greedy else d.sample()
            acts[a], logps[a] = int(x), float(d.log_prob(x))
        return acts, logps

    def values(self, obs, glob):
        """obs {agen: [N, obs_dim]}, glob [N, global_dim] -> [N, n_agen]."""
        if self.asym:
            return self.critic(glob)
        return torch.cat([self.critic[a](obs[a]) for a in self.agents], dim=1)

    def update(self, episodes):
        """episodes: list dict {obs: {a: [T+1, d]}, glob: [T+1, g], act/logp: {a: [T]}, rew: [T, n_agen]}."""
        hp = self.hp
        obs, glob, act, logp, adv, ret = {a: [] for a in self.agents}, [], {a: [] for a in self.agents}, \
            {a: [] for a in self.agents}, [], []
        for ep in episodes:
            o = {a: torch.as_tensor(np.array(ep['obs'][a]), dtype=torch.float32) for a in self.agents}
            g = torch.as_tensor(np.array(ep['glob']), dtype=torch.float32)
            r = torch.as_tensor(np.array(ep['rew']), dtype=torch.float32)
            with torch.no_grad():
                v = self.values(o, g)  # [T+1, n]; baris terakhir = bootstrap (episode dipotong waktu, bukan terminal)
            T, gae = len(r), torch.zeros(len(self.agents))
            a_t = torch.zeros_like(r)
            for t in reversed(range(T)):
                gae = r[t] + hp['gamma'] * v[t + 1] - v[t] + hp['gamma'] * hp['lam'] * gae
                a_t[t] = gae
            adv.append(a_t)
            ret.append(a_t + v[:T])
            glob.append(g[:T])
            for a in self.agents:
                obs[a].append(o[a][:T])
                act[a].append(torch.as_tensor(ep['act'][a]))
                logp[a].append(torch.as_tensor(ep['logp'][a], dtype=torch.float32))
        obs = {a: torch.cat(obs[a]) for a in self.agents}
        act = {a: torch.cat(act[a]) for a in self.agents}
        logp = {a: torch.cat(logp[a]) for a in self.agents}
        glob, adv, ret = torch.cat(glob), torch.cat(adv), torch.cat(ret)
        adv = (adv - adv.mean(0)) / (adv.std(0) + 1e-8)

        stats = []
        for _ in range(hp['epochs']):
            for idx in torch.randperm(len(adv)).split(hp['minibatch']):
                pg_loss, ent = 0.0, 0.0
                for i, a in enumerate(self.agents):
                    d = Categorical(logits=self.actors[a](obs[a][idx]))
                    ratio = torch.exp(d.log_prob(act[a][idx]) - logp[a][idx])
                    A = adv[idx, i]
                    pg_loss = pg_loss - torch.min(ratio * A, ratio.clamp(1 - hp['clip'], 1 + hp['clip']) * A).mean()
                    ent = ent + d.entropy().mean()
                v_loss = ((self.values({a: obs[a][idx] for a in self.agents}, glob[idx]) - ret[idx]) ** 2).mean()
                loss = pg_loss - hp['ent_coef'] * ent + hp['vf_coef'] * v_loss
                self.opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.params, 0.5)
                self.opt.step()
                stats.append((pg_loss.item(), v_loss.item(), ent.item() / len(self.agents)))
        return dict(zip(('pg_loss', 'v_loss', 'entropy'), np.mean(stats, axis=0)))

    def save(self, path):
        torch.save({'agents': self.agents, 'asym': self.asym, 'hp': self.hp, 'dims': self.dims,
                    'actors': self.actors.state_dict(), 'critic': self.critic.state_dict()}, path)

    @classmethod
    def load(cls, path):
        ck = torch.load(path, weights_only=False)
        p = cls(ck['agents'], asymmetric=ck['asym'], hp=ck['hp'], **ck['dims'])
        p.actors.load_state_dict(ck['actors'])
        p.critic.load_state_dict(ck['critic'])
        return p


def _toy_check(asymmetric):
    """Env mainan: reward 1 bila aksi agen == indeks target di observasinya. Acak = 0.2."""
    rng = np.random.default_rng(0)
    torch.manual_seed(0)
    agents, n, T = ['agg1', 'agg2'], 5, 30
    hp = dict(hidden=32, lr=3e-3, gamma=0.95, lam=0.95, clip=0.2, epochs=8, minibatch=32, ent_coef=0.01, vf_coef=0.5)
    p = PPO(agents, n, n, 2 * n, asymmetric, hp)

    def obs_now():
        return {a: np.eye(n, dtype=np.float32)[rng.integers(n)] for a in agents}

    for it in range(40):
        eps, mean_r = [], []
        for _ in range(2):
            ep = dict(obs={a: [] for a in agents}, glob=[], act={a: [] for a in agents},
                      logp={a: [] for a in agents}, rew=[])
            o = obs_now()
            for _ in range(T):
                acts, lps = p.act(o)
                r = [float(acts[a] == int(o[a].argmax())) for a in agents]
                for a in agents:
                    ep['obs'][a].append(o[a]); ep['act'][a].append(acts[a]); ep['logp'][a].append(lps[a])
                ep['glob'].append(np.concatenate([o[a] for a in agents]))
                ep['rew'].append(r)
                mean_r.append(np.mean(r))
                o = obs_now()
            for a in agents:
                ep['obs'][a].append(o[a])
            ep['glob'].append(np.concatenate([o[a] for a in agents]))
            eps.append(ep)
        p.update(eps)
    final = np.mean(mean_r)
    assert final > 0.8, 'PPO %s tidak belajar: reward %.2f' % ('asym' if asymmetric else 'sym', final)
    return final


if __name__ == '__main__':
    for asym in (True, False):
        print('toy %s: reward akhir %.2f' % ('asym' if asym else 'sym', _toy_check(asym)))
    print('ppo OK')
