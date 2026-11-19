"""Pola rate: sinusoidal (beban "harian" yang dipadatkan) + lonjakan Poisson. Deterministik per seed."""
import bisect
import math
import random


class RateSchedule:
    def __init__(self, min_mbps, max_mbps, period_s, spike_rate, spike_mbps, spike_s, seed,
                 horizon_s=7200, **_):
        rng = random.Random(seed)
        self.mid, self.amp = (min_mbps + max_mbps) / 2, (max_mbps - min_mbps) / 2
        self.w, self.phase = 2 * math.pi / period_s, rng.uniform(0, 2 * math.pi)
        self.spike_mbps, self.spike_s = spike_mbps, spike_s
        self.spikes, t = [], 0.0
        while spike_rate > 0:
            t += rng.expovariate(spike_rate)
            if t > horizon_s:
                break
            self.spikes.append(t)

    def mbps(self, t):
        active = bisect.bisect_right(self.spikes, t) - bisect.bisect_right(self.spikes, t - self.spike_s)
        return self.mid + self.amp * math.sin(self.w * t + self.phase) + active * self.spike_mbps


if __name__ == '__main__':
    s = RateSchedule(5, 25, 60, 0, 0, 0, seed=1)
    assert all(5 - 1e-9 <= s.mbps(t / 10) <= 25 + 1e-9 for t in range(6000))
    assert RateSchedule(5, 25, 60, 0.1, 10, 5, seed=3).mbps(17) == RateSchedule(5, 25, 60, 0.1, 10, 5, seed=3).mbps(17)
    sp = RateSchedule(5, 5, 60, 0.2, 10, 5, seed=2)
    t0 = sp.spikes[0]
    assert sp.mbps(t0 - 0.01) == 5 and sp.mbps(t0 + 0.01) >= 15
    print('scheduler OK')
