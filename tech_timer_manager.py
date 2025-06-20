import threading
import time
from datetime import timedelta
import global_state as gs

# === 状态变量 ===
research_time_remaining = None
accelerate_cd_remaining = None

# === 回调函数（供 tech_research_core / main_controller 使用）===
research_expired_callback = None
accelerate_ready_callback = None

# === Event 用于主控 / 其他模块监听 ===
research_ready_event = threading.Event()
accelerate_ready_event = threading.Event()

# === 线程运行控制 ===
running = False
stop_accelerate_notification = False

# === 设置计时器 ===
def set_research_timer(seconds, callback=None):
    global research_time_remaining, research_expired_callback
    research_time_remaining = seconds
    research_expired_callback = callback
    print(f"🕑 设置研究计时器: {seconds} 秒，callback: {bool(callback)}")

def set_accelerate_timer(seconds, callback=None):
    global accelerate_cd_remaining, accelerate_ready_callback
    accelerate_cd_remaining = seconds
    accelerate_ready_callback = callback
    print(f"🕑 设置加速CD计时器: {seconds} 秒，callback: {bool(callback)}")

# === 主动清除 ===
def clear_research_timer():
    global research_time_remaining, research_expired_callback
    research_time_remaining = None
    research_expired_callback = None
    print("🗑️ 清除研究计时器")

def clear_accelerate_timer():
    global accelerate_cd_remaining, accelerate_ready_callback
    accelerate_cd_remaining = None
    accelerate_ready_callback = None
    print("🗑️ 清除加速CD计时器")

def stop_all():
    global running
    running = False
    print("🛑 停止计时器线程")

# === 启动倒计时线程 ===
def start_timer_thread():
    global running
    if running:
        return
    running = True
    threading.Thread(target=timer_loop, daemon=True).start()
    print("▶️ 启动计时器线程")

# === 倒计时核心循环 ===
def timer_loop():
    global research_time_remaining, accelerate_cd_remaining
    while running:
        time.sleep(1)

        # 研究计时逻辑
        if research_time_remaining is not None:
            research_time_remaining = max(0, research_time_remaining - 1)
            if research_time_remaining == 0:
                print("🔔 研究倒计时归 0，已通知主控")
                research_ready_event.set()

                # 优先用 callback 通知
                if research_expired_callback:
                    try:
                        research_expired_callback()
                    except Exception as e:
                        print(f"⚠️ 研究回调异常: {e}")

                # 兼容主控 tech_timer_post_message_callback
                if gs.tech_timer_post_message_callback:
                    try:
                        gs.tech_timer_post_message_callback('research_ready', None)
                    except Exception as e:
                        print(f"⚠️ 研究 ready 消息投递失败: {e}")

        # 加速计时逻辑
        if accelerate_cd_remaining is not None:
            accelerate_cd_remaining = max(0, accelerate_cd_remaining - 1)

            if accelerate_cd_remaining == 0 and not stop_accelerate_notification:
                print("🔔 加速CD倒计时归 0，直接调用主控处理")
                accelerate_ready_event.set()
                accelerate_cd_remaining = None

# === 查询当前状态 ===
def get_timer_status():
    return {
        "研究剩余": str(timedelta(seconds=research_time_remaining)) if research_time_remaining else "无",
        "加速CD": str(timedelta(seconds=accelerate_cd_remaining)) if accelerate_cd_remaining else "无"
    }
