# RL-Based Dynamic Slicing (SDN)

Asymmetric actor-critic untuk slicing dinamis (URLLC / eMBB / BE) di Mininet + Open vSwitch + Ryu.

## 1. Siapkan VM (laptop Windows)

Butuh VirtualBox 7. Skrip membuat VM Ubuntu 22.04 Server (4 vCPU, 6 GB RAM, disk dinamis 25 GB),
mengunduh ISO + cek SHA256, dan meneruskan SSH ke `127.0.0.1:2222`.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_vm.ps1
```

Di installer Ubuntu: pilih bahasa/keyboard, buat user, **centang "Install OpenSSH server"**, reboot.
Lalu dari VS Code: Remote-SSH, tambahkan ke `~/.ssh/config`:

```
Host sdn-vm
    HostName 127.0.0.1
    Port 2222
    User <user-vm>
```

Jangan pakai WSL2 (kernelnya tanpa modul OVS, QoS `linux-htb` tidak bekerja).

## 2. Setup di dalam VM

```bash
git clone <url-repo> rl-dynamic-slicing && cd rl-dynamic-slicing
bash scripts/setup_vm.sh      # apt, sysctl (bbr, backlog), .venv-ryu (3.9), .venv-agent (3.10 + torch CPU)
```

## 3. Menjalankan

Semua perintah dari root repo. Terminal 1 (controller, tanpa sudo):

```bash
.venv-ryu/bin/ryu-manager --wsapi-host 127.0.0.1 controller/slicing_app.py
```

Terminal 2:

```bash
sudo .venv-agent/bin/python -m experiments.smoke_test       # checklist 7.9 otomatis, PASS/FAIL per poin
sudo .venv-agent/bin/python -m topology.topo                # topologi + Mininet CLI untuk eksplorasi manual
sudo .venv-agent/bin/python -m experiments.run_all --methods static greedy --seeds 1 2 3 4 5
sudo .venv-agent/bin/python -m agent.train --variant asym --seed 1   # lalu --variant sym (±50 menit/varian)
sudo bash scripts/cleanup.sh                                # bila ada run yang terhenti paksa
```

Hasil run ada di `results/raw/<metode>_s<seed>_<timestamp>/`: `steps.csv` (metrik per detik per agen),
`urllc_<server>.csv` (delay tiap probe, untuk CDF), salinan config, log tiap proses trafik.
File dibuat oleh root: `sudo chown -R $USER results` bila perlu.

Ganti profil manual (contoh agg1, dpid 3):

```bash
curl -X POST localhost:8080/slice/3/profile -d '{"profile": 4}'
curl -X POST localhost:8080/slice/3/profile -d '{"shares": {"urllc": 30, "embb": 50, "be": 20}, "mode": "borrowing"}'
curl localhost:8080/slice
sudo tc -s class show dev agg1-eth1
```

## 4. Alur data

```
experiments/run_all.py ── policy.act(obs, info) ──> agent/env.py ── REST ──> controller/slicing_app.py
        ^                                              |                         |  OpenFlow 1.3: set_queue
        |                                              |                         |  OVSDB: rate queue
        └── obs, reward, info <── tc -s class (monitor/tc_reader.py) + delay probe (traffic/urllc_probe.py)
```

- Bottleneck: `agg1-eth1` dan `agg2-eth1`, 20 Mbps, HTB queue 0 (BE) / 1 (URLLC, UDP 5001) / 2 (eMBB, UDP 5002).
- Trafik: probe URLLC 100 B tiap 10 ms + beban URLLC + eMBB (sinusoidal + lonjakan Poisson) dari h1–h4,
  TCP iperf3 sebagai BE. Semua nilai di `config/`.

## 5. Status modul

| Modul | Status |
|---|---|
| `topology/`, `controller/`, `traffic/`, `monitor/` | siap, belum diuji di VM |
| `agent/env.py`, `baselines/`, `experiments/` | siap, belum diuji di VM |
| `agent/ppo.py` | siap, lulus self-test env mainan (`python -m agent.ppo`) |
| `agent/train.py` | siap, belum diuji di VM |
| `agent/run_policy.py`, `sim_env.py` | belum (tahap 5 / opsional) |
| `analysis/plots.py` | belum (tahap 7) |
