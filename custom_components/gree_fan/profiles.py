"""Known Gree standalone fan protocol profiles."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FanProfile:
    """Capabilities and protocol columns for one fan family."""

    mid: str
    models: tuple[str, ...]
    columns: tuple[str, ...]
    speed_count: int
    preset_modes: tuple[tuple[str, int], ...] = ()
    horizontal_angles: tuple[tuple[str, int], ...] = ()
    vertical_swing_angle: int | None = None

    def supports(self, prop: str) -> bool:
        """Return whether the model reports the protocol property."""
        return prop in self.columns


COMMON_PRESET_MODES = (
    ("普通风", 0),
    ("睡眠风", 2),
    ("快循环", 6),
)

PROFILES: dict[str, FanProfile] = {
    "828200": FanProfile(
        "828200",
        ("legacy fan",),
        ("Pow", "WdSpd", "Mod", "estate", "estate2"),
        3,
    ),
    "828202": FanProfile(
        "828202",
        ("FLZ-0903Bag", "FL-09T65Bh"),
        ("Pow", "WdSpd", "Mod", "MidType", "Wet", "estate", "estate1", "estate2", "estate3"),
        3,
    ),
    "828203": FanProfile(
        "828203",
        ("KS-0705D",),
        ("Pow", "WdSpd", "Mod", "HotWind", "estate", "estate2", "estate3"),
        3,
    ),
    "828204": FanProfile(
        "828204",
        ("legacy circulation fan",),
        (
            "Pow", "WdSpd", "Mod", "Cycle", "Rotate", "TmrHour",
            "TmrMin", "TmrOn", "TmrAction", "estate3",
        ),
        8,
    ),
    "828205": FanProfile(
        "828205",
        ("KS-1501RD",),
        ("Pow", "WdSpd", "Mod", "HotWind", "estate", "estate2", "estate3"),
        3,
    ),
    "828208": FanProfile(
        "828208",
        ("FWZ-1201Bg",),
        (
            "Pow", "WdSpd", "Mod", "Rotate", "PM25", "LRAngle",
            "SwUpDn", "TmrOn", "TmrAction", "TmrHour", "TmrMin",
            "estate1", "estate3", "JFerr", "rssi", "MidType",
        ),
        12,
    ),
    "828209": FanProfile(
        "828209",
        ("FSZ-20X60Bg3", "FSZ-2001Bg3", "FSZ-20X60Bag3"),
        (
            "Pow", "WdSpd", "Mod", "Cycle", "Rotate", "SwUpDn",
            "UpDnAngle", "LRAngle", "TmrHour", "TmrMin", "TmrOn",
            "TmrAction", "estate", "estate1", "estate2", "JFerr",
        ),
        8,
        COMMON_PRESET_MODES,
        (("60°", 12), ("80°", 16), ("100°", 20)),
        18,
    ),
    "828210": FanProfile(
        "828210",
        ("FLZ-1001RBga",),
        (
            "Pow", "WdSpd", "Mod", "Rotate", "HotWind",
            "HotwindOnOff", "LRAngle", "TmrHour", "TmrMin", "TmrOn",
            "TmrAction", "estate1", "estate3", "JFerr", "rssi",
        ),
        8,
    ),
    "828211": FanProfile(
        "828211",
        ("FLZ-09X67Bg",),
        (
            "Pow", "WdSpd", "Mod", "Rotate", "LRAngle", "TmrHour",
            "TmrMin", "TmrOn", "TmrAction", "estate", "JFerr",
        ),
        12,
    ),
    "828212": FanProfile(
        "828212",
        ("FDZ-40X69Bg9Z",),
        (
            "Pow", "WdSpd", "Rotate", "Mod", "TmrOn", "TmrAction",
            "TmrHour", "TmrMin", "estate2", "JFerr",
        ),
        12,
    ),
    "828214": FanProfile(
        "828214",
        ("new-generation fan",),
        (
            "Pow", "WdSpd", "Mod", "Rotate", "LRAngle", "WdAuto",
            "TmrHour", "TmrMin", "TmrOn", "TmrAction", "JFerr",
            "LRHeadAngle", "Quiet", "OSD", "estate", "rssi",
            "StepWdSpd",
        ),
        12,
    ),
}

MODEL_PROFILES = {
    model.casefold(): profile
    for profile in PROFILES.values()
    for model in profile.models
    if not model.startswith(("legacy", "new-generation"))
}


def normalize_mid(value: object) -> str:
    """Normalize a discovery MID value."""
    return str(value or "").strip()


def get_profile(mid: object) -> FanProfile | None:
    """Return a known profile or a conservative future 8282xx profile."""
    normalized = normalize_mid(mid)
    if normalized in PROFILES:
        return PROFILES[normalized]
    if normalized.startswith("8282"):
        return _generic_profile(normalized)
    return None


def _generic_profile(mid: str = "unknown-fan") -> FanProfile:
    """Return a basic profile that does not expose unverified capabilities."""
    return FanProfile(mid, (), ("Pow", "WdSpd", "Mod"), 8)


def profile_for_device(device_info) -> FanProfile | None:
    """Classify a discovery result without relying on its display name."""
    profile = get_profile(getattr(device_info, "mid", None))
    if profile is not None:
        return profile

    for candidate in (device_info.model, device_info.name):
        normalized = str(candidate or "").strip().casefold()
        if normalized in MODEL_PROFILES:
            return MODEL_PROFILES[normalized]

    fan_markers = {"fan", "fan_x", "风扇"}
    for candidate in (
        getattr(device_info, "catalog", None),
        getattr(device_info, "series", None),
    ):
        if str(candidate or "").strip().casefold() in fan_markers:
            return _generic_profile()
    return None
