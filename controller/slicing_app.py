"""Ryu app (OpenFlow 1.3): klasifikasi slice + L2 learning + REST ganti profil split.

Table 0: UDP 5001 -> set_queue 1 (URLLC), UDP 5002 -> set_queue 2 (eMBB), sisanya queue default 0 (BE).
Table 1: L2 learning (match eth_dst). Topologi tree, jadi flooding aman tanpa STP.
OpenFlow hanya MEMILIH queue; rate queue diubah lewat OVSDB (management plane).

Jalankan dari root repo:
    .venv-ryu/bin/ryu-manager --wsapi-host 127.0.0.1 controller/slicing_app.py
REST:
    POST /slice/<dpid>/profile  {"profile": 2}  atau  {"shares": {"urllc": 30, "embb": 50, "be": 20}}
                                opsional "mode": "strict" | "borrowing"
    GET  /slice
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ryu.app.wsgi import ControllerBase, WSGIApplication, route  # noqa: E402
from ryu.base import app_manager  # noqa: E402
from ryu.controller import ofp_event  # noqa: E402
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls  # noqa: E402
from ryu.lib.packet import ether_types, ethernet, packet  # noqa: E402
from ryu.ofproto import ofproto_v1_3  # noqa: E402
from webob import Response  # noqa: E402

from topology.qos_setup import load_cfg, load_profiles, set_rates  # noqa: E402

CLASSIFY, FORWARD = 0, 1


class SlicingApp(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = load_cfg()
        self.prof = load_profiles()
        self.mac_to_port = {}
        self.current = {}
        kwargs['wsgi'].register(SliceRest, {'app': self})

    def add_flow(self, dp, table, prio, match, actions=None, goto=None):
        ofp, p = dp.ofproto, dp.ofproto_parser
        inst = []
        if actions:
            inst.append(p.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions))
        if goto is not None:
            inst.append(p.OFPInstructionGotoTable(goto))
        dp.send_msg(p.OFPFlowMod(datapath=dp, table_id=table, priority=prio, match=match, instructions=inst))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features(self, ev):
        dp = ev.msg.datapath
        ofp, p = dp.ofproto, dp.ofproto_parser
        for cls in ('urllc', 'embb'):
            match = p.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ip_proto=17, udp_dst=self.cfg['ports'][cls])
            self.add_flow(dp, CLASSIFY, 10, match, [p.OFPActionSetQueue(self.cfg['queues'][cls])], FORWARD)
        self.add_flow(dp, CLASSIFY, 0, p.OFPMatch(), goto=FORWARD)
        self.add_flow(dp, FORWARD, 0, p.OFPMatch(), [p.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])
        self.logger.info('switch %d terhubung, flow klasifikasi terpasang', dp.id)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, p = dp.ofproto, dp.ofproto_parser
        in_port = msg.match['in_port']
        eth = packet.Packet(msg.data).get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        table = self.mac_to_port.setdefault(dp.id, {})
        table[eth.src] = in_port
        out = table.get(eth.dst, ofp.OFPP_FLOOD)
        actions = [p.OFPActionOutput(out)]
        if out != ofp.OFPP_FLOOD:
            self.add_flow(dp, FORWARD, 1, p.OFPMatch(eth_dst=eth.dst), actions)
        dp.send_msg(p.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER, in_port=in_port,
                                   actions=actions, data=msg.data))


def _json(obj, status=200):
    return Response(status=status, content_type='application/json', charset='utf-8', text=json.dumps(obj))


class SliceRest(ControllerBase):
    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.app = data['app']

    @route('slice', '/slice', methods=['GET'])
    def get_all(self, req, **_):
        return _json(self.app.current)

    @route('slice', '/slice/{dpid}/profile', methods=['POST'])
    def set_profile(self, req, dpid, **_):
        cfg, prof = self.app.cfg, self.app.prof
        names = {v: k for k, v in cfg['switches'].items()}
        try:
            name = names.get(int(dpid))
            if name not in cfg['agents']:
                return _json({'error': 'dpid %s tidak punya port bottleneck' % dpid}, 404)
            body = req.json_body
            if 'profile' in body:
                idx = int(body['profile'])
                if not 0 <= idx < len(prof['profiles']):
                    raise ValueError('profile di luar rentang')
                shares = prof['profiles'][idx]
            else:
                shares = {k: float(body['shares'][k]) for k in cfg['queues']}
            mode = body.get('mode', prof['mode'])
            if mode not in ('strict', 'borrowing'):
                raise ValueError('mode harus strict/borrowing')
            if min(shares.values()) <= 0 or sum(shares.values()) > 100:
                raise ValueError('share harus > 0 dan total <= 100')
        except (ValueError, KeyError, TypeError) as e:
            return _json({'error': str(e)}, 400)
        try:
            set_rates(cfg['agents'][name]['port'], shares, cfg, mode, db=cfg['ovsdb'])
        except subprocess.CalledProcessError as e:
            return _json({'error': e.stderr.strip()}, 500)
        self.app.current[name] = {'shares': shares, 'mode': mode, 'profile': body.get('profile')}
        return _json(self.app.current[name])
