#!/usr/bin/env bash
# Bersihkan sisa Mininet, record QoS/queue OVSDB, dan proses trafik. Jalankan dengan sudo.
mn -c >/dev/null 2>&1 || true
ovs-vsctl --all destroy qos -- --all destroy queue 2>/dev/null || true
pkill -f 'traffic\.(urllc_probe|embb_sender)' || true
pkill -x iperf3 || true
