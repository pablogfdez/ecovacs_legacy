"""XMPP/XML protocol of legacy Ecovacs robots (Deebot OZMO 930 and similar).

Pure Python module (no Home Assistant imports) so it can be unit tested and
used by the probe script. The message formats were ported from
``ecovacs-deebot.js`` (``library/non950type``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

CLEAN_MODE_TO_ECOVACS = {
    "auto": "auto",
    "edge": "border",
    "spot": "spot",
    "spot_area": "SpotArea",
    "single_room": "singleroom",
    "stop": "stop",
}
CLEAN_MODE_FROM_ECOVACS = {
    "auto": "auto",
    "border": "edge",
    "spot": "spot",
    "SpotArea": "spot_area",
    "singleroom": "single_room",
    "stop": "stop",
    "going": "returning",
}
CLEAN_ACTION_TO_ECOVACS = {"start": "s", "pause": "p", "resume": "r", "stop": "h"}
CLEAN_ACTION_FROM_ECOVACS = {"s": "start", "p": "pause", "r": "resume", "h": "stop"}

FAN_SPEED_NORMAL = "standard"
FAN_SPEED_HIGH = "strong"
FAN_SPEEDS = (FAN_SPEED_NORMAL, FAN_SPEED_HIGH)

CHARGE_MODE_FROM_ECOVACS = {
    "Going": "returning",
    "going": "returning",
    "SlotCharging": "charging",
    "slot_charging": "charging",
    "WireCharging": "charging",
    "Idle": "idle",
    "idle": "idle",
}

COMPONENT_TO_ECOVACS = {
    "main_brush": "Brush",
    "side_brush": "SideBrush",
    "filter": "DustCaseHeap",
}
COMPONENT_FROM_ECOVACS = {
    "brush": "main_brush",
    "Brush": "main_brush",
    "side_brush": "side_brush",
    "SideBrush": "side_brush",
    "sideBrush": "side_brush",
    "dust_case_heap": "filter",
    "DustCaseHeap": "filter",
    "heap": "filter",
}
COMPONENTS = tuple(COMPONENT_TO_ECOVACS)

ERROR_CODES = {
    "0": "NoError: Robot is operational",
    "100": "NoError: Robot is operational",
    "101": "BatteryLow: Low battery",
    "102": "HostHang: Robot is off the floor",
    "103": "WheelAbnormal: Driving Wheel malfunction",
    "104": "DownSensorAbnormal: Excess dust on the Anti-Drop Sensors",
    "105": "Stuck: Robot is stuck",
    "106": "SideBrushExhausted: Side Brushes have expired",
    "107": "DustCaseHeapExhausted: Dust case filter expired",
    "108": "SideAbnormal: Side Brushes are tangled",
    "109": "RollAbnormal: Main Brush is tangled",
    "110": "NoDustBox: Dust Bin Not installed",
    "111": "BumpAbnormal: Bump sensor stuck",
    "112": 'LDS: LDS "Laser Distance Sensor" malfunction',
    "113": "MainBrushExhausted: Main brush has expired",
    "114": "DustCaseFilled: Dust bin full",
    "115": "BatteryError",
    "116": "ForwardLookingError",
    "117": "GyroscopeError",
    "118": "StrainerBlock",
    "119": "FanError",
    "120": "WaterBoxError",
    "121": "PlateJammed",
    "125": "Reservoir malfunction",
    "126": "Reservoir is not installed",
    "128": "Mopping Pad Plates are not both installed",
    "129": "Mopping Pad Plate is tangled",
    "404": "Recipient unavailable",
    "500": "Request Timeout",
}

# Maintenance reminders and transport errors must not put the vacuum in error
ERROR_NON_BLOCKING = {"106", "107", "113", "404", "500"}


def new_request_id() -> str:
    """Return a random request id (same style as ecovacs-deebot.js)."""
    return str(random.randint(1_000_000, 99_999_999))


def _attrs_xml(attrs: dict[str, Any]) -> str:
    return "".join(f" {k}={quoteattr(str(v))}" for k, v in attrs.items())


@dataclass
class Command:
    """A ``<ctl td="..."/>`` command sent to the robot."""

    name: str
    attrs: dict[str, Any] = field(default_factory=dict)
    children: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    id: str = field(default_factory=new_request_id)

    def to_xml(self) -> str:
        """Serialize to the XML payload placed inside the ``com:ctl`` query."""
        head = "<ctl" + _attrs_xml({"td": self.name, "id": self.id, **self.attrs})
        if not self.children:
            return head + "/>"
        body = "".join(f"<{tag}{_attrs_xml(a)}/>" for tag, a in self.children)
        return f"{head}>{body}</ctl>"


def clean(
    mode: str = "auto",
    action: str = "start",
    speed: str = FAN_SPEED_NORMAL,
    **extra: Any,
) -> Command:
    """Create a ``Clean`` command."""
    attrs = {
        "type": CLEAN_MODE_TO_ECOVACS[mode],
        "speed": speed,
        "act": CLEAN_ACTION_TO_ECOVACS[action],
        **extra,
    }
    return Command("Clean", children=[("clean", attrs)])


def pause(mode: str = "auto") -> Command:
    """Pause cleaning."""
    return clean(mode, "pause")


def resume() -> Command:
    """Resume cleaning."""
    return clean("auto", "resume")


def stop() -> Command:
    """Stop cleaning."""
    return clean("stop", "stop")


def spot_area(areas: str, action: str = "start") -> Command:
    """Clean the given spot area ids (comma separated)."""
    return clean("spot_area", action, mid=areas)


def custom_area(coordinates: str, passes: int = 1, action: str = "start") -> Command:
    """Clean the given custom area ``x1,y1,x2,y2``."""
    return clean("spot_area", action, p=coordinates, deep=passes)


def charge() -> Command:
    """Return to the charging station."""
    return Command("Charge", children=[("charge", {"type": "go"})])


def play_sound(sid: int = 0) -> Command:
    """Play a sound (locate the robot)."""
    return Command("PlaySound", {"sid": sid})


def set_clean_speed(speed: str) -> Command:
    """Set the suction power."""
    return Command("SetCleanSpeed", {"speed": speed})


def set_water_level(level: int) -> Command:
    """Set the water permeability level."""
    return Command("SetWaterPermeability", {"v": level})


def get_lifespan(component: str) -> Command:
    """Request the lifespan of a component."""
    return Command("GetLifeSpan", {"type": COMPONENT_TO_ECOVACS[component]})


def raw(name: str, params: dict[str, Any] | None = None) -> Command:
    """Create an arbitrary command; ``params`` become attributes."""
    return Command(name, dict(params or {}))


INITIAL_QUERIES = (
    "GetCleanState",
    "GetChargeState",
    "GetBatteryInfo",
    "GetCleanSpeed",
    "GetWaterPermeability",
    "GetWaterBoxInfo",
    "GetCleanSum",
    "GetNetInfo",
    "GetPos",
    "GetChargerPos",
)


def initial_commands() -> list[Command]:
    """Commands to request the full robot state."""
    commands = [Command(name) for name in INITIAL_QUERIES]
    commands.extend(get_lifespan(component) for component in COMPONENTS)
    return commands


def local_name(tag: str) -> str:
    """Strip the XML namespace of a tag."""
    return tag.rsplit("}", 1)[-1]


def normalize_command(command: str) -> str:
    """Normalize the ``td`` name like ecovacs-deebot.js does."""
    name = command.strip("_").replace("Get", "").replace("Server", "")
    if name.startswith("On") and name != "OnOff":
        name = name[2:]
    return name


def find_ctl(stanza: ET.Element) -> ET.Element | None:
    """Return the ``ctl`` element of an ``iq`` stanza, if any."""
    for query in stanza:
        if local_name(query.tag) == "query":
            for child in query:
                if local_name(child.tag) == "ctl":
                    return child
    return None


def get_error(attrs: dict[str, str]) -> tuple[str, str] | None:
    """Return ``(code, description)`` from error attributes."""
    for key in ("new", "code", "errno", "error", "errs"):
        value = attrs.get(key)
        if value:
            code = "0" if value == "100" else str(value)
            return code, ERROR_CODES.get(code, f"unknown errorCode: {code}")
    return None


def _to_int(value: Any, default: int | None) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


@dataclass
class RobotState:
    """State of a legacy robot."""

    battery: int | None = None
    charge: str | None = None
    clean_report: str | None = None
    fan_speed: str | None = None
    water_level: int | None = None
    water_box: bool | None = None
    lifespan: dict[str, int] = field(default_factory=dict)
    cleaned_area: int | None = None
    cleaned_seconds: int | None = None
    total_area: int | None = None
    total_seconds: int | None = None
    total_count: int | None = None
    error_code: str = "0"
    error_text: str = ""
    wifi_ssid: str | None = None
    ip: str | None = None
    position: str | None = None
    charger_position: str | None = None

    def _stats(self, area: Any, seconds: Any, stopped: bool) -> None:
        # The 930 keeps the stats until the next start; reset them when stopped
        if stopped and self.charge != "returning":
            self.cleaned_area, self.cleaned_seconds = 0, 0
        else:
            self.cleaned_area = _to_int(area, self.cleaned_area)
            self.cleaned_seconds = _to_int(seconds, self.cleaned_seconds)

    def apply(self, command: str, ctl: ET.Element) -> bool:
        """Update the state from a message; return True if it was understood."""
        name = normalize_command(command)
        attrs = dict(ctl.attrib)
        child = next(iter(ctl), None)
        cattrs = dict(child.attrib) if child is not None else {}

        if name == "CleanSt":
            self._stats(attrs.get("a"), attrs.get("l"), False)
        elif name == "ChargeState":
            value = CHARGE_MODE_FROM_ECOVACS.get(cattrs.get("type", ""))
            if value:
                self.charge = value
        elif name == "BatteryInfo":
            power = cattrs.get("power", attrs.get("power"))
            if power is not None:
                self.battery = _to_int(power, self.battery)
        elif name in ("CleanState", "CleanReport"):
            self._clean_report(cattrs or attrs)
        elif name == "CleanSpeed":
            speed = (cattrs or attrs).get("speed")
            if speed in FAN_SPEEDS:
                self.fan_speed = speed
        elif name == "LifeSpan":
            self._lifespan(attrs)
        elif name == "Pos":
            if "p" in attrs:
                self.position = f"{attrs['p']},{attrs.get('a', '')}"
        elif name == "ChargerPos":
            if "p" in attrs:
                self.charger_position = f"{attrs['p']},{attrs.get('a', '')}"
        elif name == "WaterPermeability":
            self.water_level = _to_int(attrs.get("v"), self.water_level)
        elif name == "WaterBoxInfo":
            if "on" in attrs:
                self.water_box = attrs["on"] == "1"
        elif name == "NetInfo":
            self.ip = attrs.get("wi", self.ip)
            self.wifi_ssid = attrs.get("s", self.wifi_ssid)
        elif name == "CleanSum":
            self.total_area = _to_int(attrs.get("a"), self.total_area)
            self.total_seconds = _to_int(attrs.get("l"), self.total_seconds)
            self.total_count = _to_int(attrs.get("c"), self.total_count)
        elif name == "Error":
            if error := get_error(attrs):
                self.error_code, self.error_text = error
        else:
            return False
        return True

    def _clean_report(self, attrs: dict[str, str]) -> None:
        kind = attrs.get("type", "")
        kind = CLEAN_MODE_FROM_ECOVACS.get(kind, kind)
        action = None
        if "st" in attrs:
            action = CLEAN_ACTION_FROM_ECOVACS.get(attrs["st"])
        elif "act" in attrs:
            action = CLEAN_ACTION_FROM_ECOVACS.get(attrs["act"])
        if action in ("stop", "pause"):
            kind = action
        self.clean_report = kind
        if kind in ("auto", "edge", "spot", "spot_area", "single_room"):
            self.error_code, self.error_text = "0", ""
        if "a" in attrs and "t" in attrs:
            self._stats(attrs["a"], attrs["t"], kind == "stop")
        if attrs.get("speed") in FAN_SPEEDS:
            self.fan_speed = attrs["speed"]

    def _lifespan(self, attrs: dict[str, str]) -> None:
        component = COMPONENT_FROM_ECOVACS.get(attrs.get("type", ""))
        if not component:
            return
        try:
            total = int(attrs["total"])
            value = int(attrs["val"])
        except (KeyError, ValueError):
            return
        if total > 0:
            self.lifespan[component] = max(0, min(100, round(value / total * 100)))

    @property
    def vacuum_state(self) -> str:
        """Return one of cleaning/paused/returning/docked/idle/error."""
        if (
            self.error_code not in ("0", "")
            and self.error_code.isdigit()
            and self.error_code not in ERROR_NON_BLOCKING
        ):
            return "error"
        if self.charge == "charging":
            return "docked"
        if self.charge == "returning" or self.clean_report == "returning":
            return "returning"
        if self.clean_report == "pause":
            return "paused"
        if self.clean_report in ("auto", "edge", "spot", "spot_area", "single_room"):
            return "cleaning"
        return "idle"
