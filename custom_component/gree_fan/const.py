"""Constants for the Gree Fan integration."""

COORDINATORS = "coordinators"

DATA_DISCOVERY_SERVICE = "discovery_service"
DATA_DISCOVERY_INTERVAL = "gree_discovery_interval"

DISCOVERY_SCAN_INTERVAL = 300
DISCOVERY_TIMEOUT = 8
DISPATCH_DEVICE_DISCOVERED = "gree_device_discovered"
DISPATCHERS = "dispatchers"

DOMAIN = "gree_fan"
COORDINATOR = "coordinator"

MAX_ERRORS = 2

# 格力风扇协议中的模式值
MODE_NORMAL = 0   # 仅送风 / 普通风
MODE_SLEEP = 2    # 除湿模式 → 睡眠风
MODE_AUTO = 6     # 自动模式 → 快循环

# 风扇协议扩展字段。它们不是空调使用的 SwingLfRig。
PROP_ROTATE = "Rotate"
PROP_LR_ANGLE = "LRAngle"
PROP_SW_UP_DOWN = "SwUpDn"
PROP_UP_DOWN_ANGLE = "UpDnAngle"
PROP_TIMER_ON = "TmrOn"
PROP_TIMER_ACTION = "TmrAction"
PROP_TIMER_HOUR = "TmrHour"
PROP_TIMER_MINUTE = "TmrMin"

# 上下摆风对外只支持开/关，对应原厂协议 SwUpDn=1/0。
VERTICAL_SWING_ON = 1
VERTICAL_SWING_OFF = 0

# 定时范围（小时）
TIMER_MIN = 0
TIMER_MAX = 8
TIMER_STEP = 1
TIMER_ACTION_TURN_OFF = 0
