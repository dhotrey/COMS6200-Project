"""Deterministic OpenFlow 1.3 baseline controller for the main project topology.

Active core is s1. Access switches s3-s6 use their s1 uplink for ordinary
host forwarding. s2 remains physically connected and controller-attached but
is excluded from baseline unicast and ARP flood so the initial datapath is a
loop-free tree.

This is not a learning switch and does not use OFPP_NORMAL or OFPP_FLOOD
across the redundant physical fabric.
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import ethernet, ether_types, packet
from ryu.ofproto import ofproto_v1_3

OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

BASELINE_PRIORITY = 100
BASELINE_COOKIE = 0x1000
TABLE_MISS_PRIORITY = 0

EXPECTED_DPIDS = frozenset({1, 2, 3, 4, 5, 6})
SWITCH_NAMES = {1: "s1", 2: "s2", 3: "s3", 4: "s4", 5: "s5", 6: "s6"}

MAC_H1 = "00:00:00:00:00:01"
MAC_H2 = "00:00:00:00:00:02"
MAC_H3 = "00:00:00:00:00:03"
MAC_H4 = "00:00:00:00:00:04"
MAC_H5 = "00:00:00:00:00:05"
MAC_H6 = "00:00:00:00:00:06"
MAC_H7 = "00:00:00:00:00:07"
MAC_H8 = "00:00:00:00:00:08"
# Destination-MAC -> output port on each datapath used for baseline unicast.
# s2 has no host-destination flows.
UNICAST_PORTS = {
    1: {
        MAC_H1: 2,
        MAC_H2: 2,
        MAC_H3: 3,
        MAC_H4: 3,
        MAC_H5: 4,
        MAC_H6: 4,
        MAC_H7: 5,
        MAC_H8: 5,
    },
    3: {
        MAC_H1: 3,
        MAC_H2: 4,
        MAC_H3: 1,
        MAC_H4: 1,
        MAC_H5: 1,
        MAC_H6: 1,
        MAC_H7: 1,
        MAC_H8: 1,
    },
    4: {
        MAC_H1: 1,
        MAC_H2: 1,
        MAC_H3: 3,
        MAC_H4: 4,
        MAC_H5: 1,
        MAC_H6: 1,
        MAC_H7: 1,
        MAC_H8: 1,
    },
    5: {
        MAC_H1: 1,
        MAC_H2: 1,
        MAC_H3: 1,
        MAC_H4: 1,
        MAC_H5: 3,
        MAC_H6: 4,
        MAC_H7: 1,
        MAC_H8: 1,
    },
    6: {
        MAC_H1: 1,
        MAC_H2: 1,
        MAC_H3: 1,
        MAC_H4: 1,
        MAC_H5: 1,
        MAC_H6: 1,
        MAC_H7: 3,
        MAC_H8: 4,
    },
}

# Loop-free ARP/broadcast flood ports (active tree only). s2 has none.
FLOOD_PORTS = {
    1: (2, 3, 4, 5),
    2: (),
    3: (1, 3, 4),
    4: (1, 3, 4),
    5: (1, 3, 4),
    6: (1, 3, 4),
}


class MainController(app_manager.RyuApp):
    OFP_VERSIONS = OFP_VERSIONS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connected_dpids: set[int] = set()
        self.logger.info("MainController starting (OpenFlow 1.3, active core s1)")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        name = SWITCH_NAMES.get(dpid, f"dpid={dpid}")
        version = datapath.ofproto.OFP_VERSION
        self.logger.info("Switch connected: %s / dpid=%s", name, dpid)
        self.logger.info("OpenFlow 1.3 datapath connected (version=0x%02x)", version)

        self._install_table_miss(datapath)
        installed = self._install_baseline_unicast(datapath)
        if installed:
            self.logger.info("Installed baseline forwarding for dpid=%s", dpid)
        else:
            self.logger.info(
                "Installed table-miss only for dpid=%s (redundant core; no baseline host forwarding)",
                dpid,
            )

        self.connected_dpids.add(dpid)
        connected = len(self.connected_dpids & EXPECTED_DPIDS)
        if connected == len(EXPECTED_DPIDS):
            self.logger.info("All expected switches connected: %s/%s", connected, len(EXPECTED_DPIDS))

    def _install_table_miss(self, datapath) -> None:
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=TABLE_MISS_PRIORITY,
            match=match,
            instructions=inst,
        )
        datapath.send_msg(mod)

    def _install_baseline_unicast(self, datapath) -> bool:
        ports = UNICAST_PORTS.get(datapath.id)
        if not ports:
            return False
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        for mac, out_port in ports.items():
            match = parser.OFPMatch(eth_dst=mac)
            actions = [parser.OFPActionOutput(out_port)]
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            mod = parser.OFPFlowMod(
                datapath=datapath,
                cookie=BASELINE_COOKIE,
                priority=BASELINE_PRIORITY,
                match=match,
                instructions=inst,
            )
            datapath.send_msg(mod)
        return True

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        is_arp = eth.ethertype == ether_types.ETH_TYPE_ARP
        is_broadcast = eth.dst == "ff:ff:ff:ff:ff:ff"
        if is_arp or is_broadcast:
            self.logger.debug(
                "ARP/broadcast PacketIn dpid=%s in_port=%s src=%s dst=%s",
                datapath.id,
                in_port,
                eth.src,
                eth.dst,
            )
            self._packet_out_active_tree(datapath, in_port, msg.data)
            return

        self.logger.debug(
            "Dropping unexpected packet dpid=%s in_port=%s src=%s dst=%s ethertype=0x%04x",
            datapath.id,
            in_port,
            eth.src,
            eth.dst,
            eth.ethertype,
        )

    def _packet_out_active_tree(self, datapath, in_port, data) -> None:
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        flood_ports = FLOOD_PORTS.get(datapath.id, ())
        actions = [parser.OFPActionOutput(port) for port in flood_ports if port != in_port]
        if not actions:
            return
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)
