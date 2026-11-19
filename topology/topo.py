"""Topologi tree 8 switch + 6 host (bebas loop), controller Ryu remote, QoS HTB di bottleneck.

Jalankan dari root repo (Ryu harus sudah jalan):
    sudo .venv-agent/bin/python -m topology.topo
"""
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.topo import Topo

from topology.qos_setup import load_cfg, load_profiles, setup_qos


class SliceTopo(Topo):
    def build(self, switches):
        for name, dpid in switches.items():
            self.addSwitch(name, dpid='%016x' % dpid, protocols='OpenFlow13')
        for h in ('h1', 'h2', 'h3', 'h4', 'srv1', 'srv2'):
            self.addHost(h)
        # Nomor port eksplisit -> nama interface pasti:
        # eth1 di agg/acc = uplink (port bottleneck agg1-eth1, agg2-eth1); core eth2 = link core1-core2.
        self.addLink('agg1', 'core1', port1=1, port2=1)
        self.addLink('agg2', 'core2', port1=1, port2=1)
        self.addLink('core1', 'core2', port1=2, port2=2)
        self.addLink('core1', 'srv1', port1=3)
        self.addLink('core2', 'srv2', port1=3)
        for i, agg in ((1, 'agg1'), (2, 'agg1'), (3, 'agg2'), (4, 'agg2')):
            self.addLink('acc%d' % i, agg, port1=1, port2=2 if i % 2 else 3)
            self.addLink('acc%d' % i, 'h%d' % i, port1=2)
        # Tanpa TCLink(bw=...): shaping hanya lewat QoS OVS agar tc tidak saling menimpa.


def start_net(cfg):
    net = Mininet(topo=SliceTopo(cfg['switches']), switch=OVSSwitch, controller=None, autoSetMacs=True)
    net.addController('ryu', controller=RemoteController, ip='127.0.0.1', port=cfg['of_port'])
    net.start()
    prof = load_profiles()
    setup_qos(cfg, prof['static_split'], prof['mode'])
    for _ in range(5):
        if net.pingAll(timeout='1') == 0:
            return net
    net.stop()
    raise RuntimeError('pingall gagal. Apakah ryu-manager sudah jalan?')


if __name__ == '__main__':
    setLogLevel('info')
    net = start_net(load_cfg())
    CLI(net)
    net.stop()
