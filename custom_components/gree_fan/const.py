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

# 水平摆风角度映射（关 + 60°、80°、100°）
HORIZONTAL_SWING_OPTIONS = {
    "关":   0,  # 关闭摆风
    "60°":  2,  # 中角度
    "80°":  3,  # 大角度
    "100°": 4,  # 更大角度
}

HORIZONTAL_SWING_OPTIONS_REVERSE = {v: k for k, v in HORIZONTAL_SWING_OPTIONS.items()}

# 垂直摆风 (使用原厂协议 SwingUD)
VERTICAL_SWING_ON = 1
VERTICAL_SWING_OFF = 0

# 定时范围（小时）
TIMER_MIN = 0
TIMER_MAX = 8
TIMER_STEP = 1
