#!/usr/bin/env bash
# Verifikasi kernel/mesin sebelum setup. Penting di VM cloud (mis. Huawei Cloud ECS):
# sebagian image memakai kernel ringan tanpa modul OVS/HTB. Tidak butuh sudo.
fail=0
echo "Kernel : $(uname -r)   Virtualisasi: $(systemd-detect-virt 2>/dev/null || echo ?)"
echo "OS     : $(. /etc/os-release && echo "$PRETTY_NAME")"
echo "vCPU   : $(nproc)   RAM: $(free -g | awk '/Mem:/{print $2}') GiB   Disk bebas /: $(df -h / | awk 'NR==2{print $4}')"

for m in openvswitch sch_htb tcp_bbr veth; do
    if modinfo "$m" >/dev/null 2>&1; then
        echo "[OK]   modul $m"
    else
        echo "[FAIL] modul $m tidak ada di kernel ini"
        fail=1
    fi
done
[ -e /proc/self/ns/net ] && echo "[OK]   network namespace" || { echo "[FAIL] network namespace"; fail=1; }
[ "$(nproc)" -ge 4 ] || echo "[WARN] vCPU < 4 (spesifikasi minimal 4)"

if [ "$fail" -ne 0 ]; then
    cat <<EOF

Kernel belum lengkap. Coba (butuh sudo, lalu reboot):
  sudo apt-get install -y linux-modules-extra-\$(uname -r)
atau pindah ke kernel generic:
  sudo apt-get install -y linux-generic && sudo reboot
EOF
    exit 1
fi
echo "Kernel siap."
