#!/usr/bin/env bash
# Setup lengkap di Ubuntu 22.04 (di dalam VM). Jalankan dari root repo:  bash scripts/setup_vm.sh
# Memakai sudo untuk: apt install, PPA deadsnakes (Python 3.9 untuk Ryu), sysctl, modul tcp_bbr.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. Paket sistem"
sudo apt-get update
sudo apt-get install -y git build-essential python3-venv python3-pip software-properties-common \
    openvswitch-switch iperf3 tcpdump net-tools iproute2 mininet
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get install -y python3.9 python3.9-venv python3.9-dev

echo "== 2. Tuning kernel (sesuai slide)"
sudo tee /etc/sysctl.d/99-sdn-slicing.conf >/dev/null <<'EOF'
net.core.netdev_max_backlog = 50000
net.ipv4.tcp_congestion_control = bbr
net.ipv4.ip_forward = 1
EOF
echo tcp_bbr | sudo tee /etc/modules-load.d/bbr.conf >/dev/null
sudo modprobe tcp_bbr
sudo sysctl --system >/dev/null

echo "== 3. venv Ryu (Python 3.9)"
[ -d .venv-ryu ] || python3.9 -m venv .venv-ryu
# ryu 4.34 gagal build dengan setuptools baru (get_script_args dihapus): pin + tanpa build isolation
.venv-ryu/bin/pip install -q --upgrade pip "setuptools==67.6.1" wheel pbr
.venv-ryu/bin/pip install -q --no-build-isolation -r requirements-ryu.txt

echo "== 4. venv agen (Python 3.10, akses modul mininet sistem)"
[ -d .venv-agent ] || python3 -m venv --system-site-packages .venv-agent
.venv-agent/bin/pip install -q --upgrade pip
.venv-agent/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cpu
.venv-agent/bin/pip install -q -r requirements-agent.txt

echo "== 5. Cek"
sysctl net.ipv4.tcp_congestion_control net.core.netdev_max_backlog
sudo ovs-vsctl --version | head -1
.venv-ryu/bin/ryu-manager --version
.venv-agent/bin/python -c "import torch, mininet.net, yaml, requests; print('torch', torch.__version__)"
.venv-agent/bin/python -m traffic.scheduler
.venv-agent/bin/python -m monitor.tc_reader
sudo mn --switch ovsbr --test pingall   # OVS kernel jalan (tanpa controller)
sudo mn -c >/dev/null 2>&1
echo "Setup selesai. Lanjut: smoke test (lihat README)."
