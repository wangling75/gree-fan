"""Constants for the Gree Fan integration."""

COORDINATORS = "coordinators"

DATA_DISCOVERY_SERVICE = "gree_discovery"
DATA_DISCOVERY_INTERVAL = "gree_discovery_interval"

DISCOVERY_SCAN_INTERVAL = 300
DISCOVERY_TIMEOUT = 8
DISPATCH_DEVICE_DISCOVERED = "gree_device_discovered"
DISPATCHERS = "dispatchers"

DOMAIN = "gree_fan"
COORDINATOR = "coordinator"

# 风扇速度等级 1-8
SPEED_COUNT = 8
SPEED_RANGE = (1, SPEED_COUNT)

MAX_ERRORS = 2

# 格力风扇协议中的模式值
MODE_NORMAL = 0   # 仅送风 / 普通风
MODE_SLEEP = 2    # 除湿模式 → 睡眠风
MODE_AUTO = 6     # 自动模式 → 快循环

# 风扇协议扩展字段。它们不是空调使用的 SwingLfRig。
PROP_ROTATE = "Rotate"
PROP_LR_ANGLE = "LRAngle"

# 水平摆风角度映射（关 + 60°、80°、100°）。
# ⚠️ 单位注意：GREE 风扇的 LRAngle 协议值单位是「5°/单位」，
#    即  真实摆风角度 = 协议值 × 5
# 因此 60° → 协议值 12，80° → 16，100° → 20（绝不能是 60/80/100）。
# 旧代码把 60/80/100 直接当协议值下发，风扇实际摆幅被放大成
# 300/400/500°，在格力 App 里就显示成 300/400。
# 这里写的是「协议值」，HA 里给用户看的标签仍是 60°/80°/100°。
HORIZONTAL_SWING_OPTIONS = {
    "关": 0,
    "60°": 12,
    "80°": 16,
    "100°": 20,
}

HORIZONTAL_SWING_OPTIONS_REVERSE = {v: k for k, v in HORIZONTAL_SWING_OPTIONS.items()}

# 垂直摆风 (使用原厂协议 SwingUD)
VERTICAL_SWING_ON = 1
VERTICAL_SWING_OFF = 0

# 定时范围（小时）
TIMER_MIN = 0
TIMER_MAX = 8
TIMER_STEP = 1
