"""Tests for the XML protocol of legacy robots."""

from xml.etree import ElementTree as ET

from ecovacs_legacy import protocol
from ecovacs_legacy.protocol import RobotState, find_ctl


def ctl(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def test_clean_command_xml():
    cmd = protocol.clean("auto", "start")
    root = ET.fromstring(cmd.to_xml())
    assert root.tag == "ctl"
    assert root.get("td") == "Clean"
    assert root.get("id") == cmd.id
    child = root[0]
    assert child.tag == "clean"
    assert child.attrib == {"type": "auto", "speed": "standard", "act": "s"}


def test_stop_pause_resume_charge():
    assert ET.fromstring(protocol.stop().to_xml())[0].attrib["act"] == "h"
    assert ET.fromstring(protocol.pause().to_xml())[0].attrib["act"] == "p"
    assert ET.fromstring(protocol.resume().to_xml())[0].attrib["act"] == "r"
    assert ET.fromstring(protocol.charge().to_xml())[0].attrib == {"type": "go"}


def test_attribute_escaping():
    xml = protocol.raw("Test", {"v": 'a"<b'}).to_xml()
    assert ET.fromstring(xml).get("v") == 'a"<b'


def test_lifespan_command():
    assert ET.fromstring(protocol.get_lifespan("filter").to_xml()).get("type") == "DustCaseHeap"


def test_find_ctl_with_namespaces():
    iq = ET.fromstring(
        "<iq xmlns='jabber:client' type='set'><query xmlns='com:ctl'>"
        "<ctl td='BatteryInfo'><battery power='87'/></ctl></query></iq>"
    )
    found = find_ctl(iq)
    assert found is not None and found.get("td") == "BatteryInfo"


def test_state_updates():
    state = RobotState()
    assert state.apply("BatteryInfo", ctl("<ctl><battery power='87'/></ctl>"))
    assert state.battery == 87
    assert state.apply("OnBatteryInfo", ctl("<ctl><battery power='50'/></ctl>"))
    assert state.battery == 50
    state.apply("ChargeState", ctl("<ctl><charge type='SlotCharging'/></ctl>"))
    assert state.vacuum_state == "docked"
    state.apply("ChargeState", ctl("<ctl><charge type='Going'/></ctl>"))
    assert state.vacuum_state == "returning"
    state.apply("ChargeState", ctl("<ctl><charge type='Idle'/></ctl>"))
    state.apply("CleanReport", ctl("<ctl><clean type='auto' st='s' a='3' t='60'/></ctl>"))
    assert state.vacuum_state == "cleaning"
    assert (state.cleaned_area, state.cleaned_seconds) == (3, 60)
    state.apply("CleanReport", ctl("<ctl><clean type='auto' st='p'/></ctl>"))
    assert state.vacuum_state == "paused"
    state.apply("CleanReport", ctl("<ctl><clean type='auto' st='h' a='3' t='60'/></ctl>"))
    assert state.vacuum_state == "idle"
    assert (state.cleaned_area, state.cleaned_seconds) == (0, 0)


def test_speed_water_lifespan_sum_error():
    state = RobotState()
    state.apply("CleanSpeed", ctl("<ctl><clean speed='strong'/></ctl>"))
    assert state.fan_speed == "strong"
    state.apply("WaterPermeability", ctl("<ctl v='2'/>"))
    assert state.water_level == 2
    state.apply("WaterBoxInfo", ctl("<ctl on='1'/>"))
    assert state.water_box is True
    state.apply("LifeSpan", ctl("<ctl type='SideBrush' val='90' total='200'/>"))
    assert state.lifespan == {"side_brush": 45}
    state.apply("CleanSum", ctl("<ctl a='1000' l='36000' c='25'/>"))
    assert (state.total_area, state.total_seconds, state.total_count) == (1000, 36000, 25)
    state.apply("NetInfo", ctl("<ctl wi='10.0.0.5' s='home'/>"))
    assert (state.ip, state.wifi_ssid) == ("10.0.0.5", "home")
    state.apply("Error", ctl("<ctl errno='105'/>"))
    assert state.vacuum_state == "error" and "Stuck" in state.error_text
    state.apply("Error", ctl("<ctl errno='100'/>"))
    assert state.vacuum_state == "idle"


def test_unknown_command_not_handled():
    assert not RobotState().apply("Whatever", ctl("<ctl/>"))
