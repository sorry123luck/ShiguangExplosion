# ✅ global_state.py

import threading

# 全局状态日志
global_log_callback = None

# 当前主任务状态（采集、远征、裂隙、研究）
current_task_flag = None

# === 主控界面当前任务状态更新回调 ===
current_task_status_callback = None
rift_pending_flag = False
tech_pending_flag = False
expedition_pending_flag = False
tech_timer_post_message_callback = None
current_collect_enabled = False
current_collect_points = []

# === 远征模块状态 ===
running_expedition = False
expedition_enabled_flag = False
scout_enabled_global = False
reward_enabled_global = False

# === 暂停控制事件（新增）===
pause_event = threading.Event()              # 用于主控暂停一切任务
expedition_pause_event = threading.Event()   # 单独控制远征模块暂停
research_pause_event = threading.Event()

# === 点击冻结标志（科研、裂隙保护用）===
click_frozen = threading.Event()

# === 裂隙模块层数 ===
rift_level_callback = None  # 主控注册的裂隙层数更新回调函数
rift_state = "idle"  # 可取值：idle / opening  / wait_continue / battling
rift_send_control_command_callback = None  # 主控注册的发送控制命令回调函数
rift_max_retry = 30 # 裂隙最大重试次数