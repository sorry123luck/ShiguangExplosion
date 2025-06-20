# ✅ TouchAgent Python 端主控逻辑优化版（最终整理版）
import tkinter as tk
import tech_timer_manager
import subprocess
import os
import threading
import time
import global_state as gs
import rift_core
import collect_core
import expedition_core
import tech_research_core
from tkinter import ttk
from expedition_core import set_expedition_flags, set_expedition_enabled
from utils.adb_tools import TouchServerSocket, ScreenshotSocket, get_rift_stream_listener, ControlSocket,enable_rift_listener
from position_config import COLLECT_POINTS
from utils.toast_notify import show_toast, register_log_callback

pause_event = threading.Event()
TOUCH_SERVER_HOST = "127.0.0.1"
TOUCH_SERVER_PORT = 6100
server_socket = TouchServerSocket(host=TOUCH_SERVER_HOST, port=TOUCH_SERVER_PORT)
_last_research_callback_ts = 0

# 全局主控状态
def pause_all_tasks():
    pause_event.set()
    collect_core.stop_collect()
    rift_core.stop_rift_module(server_socket)
    gs.current_task_flag = None

def resume_all_tasks():
    #print(f"[DEBUG] resume_all_tasks 当前 gs.current_collect_enabled: {gs.current_collect_enabled}")
    #print(f"[DEBUG] resume_all_tasks 当前 resource_vars 状态: {[f'{label}={var.get()}' for label, var in resource_vars.items()]}")
    if gs.current_task_flag is None:
        gs.research_pause_event.clear()
        if gs.current_collect_enabled:
            gs.current_collect_points = (
                ["食物"] if global_resource_mode.get()
                else [label for label, var in resource_vars.items() if var.get()]
            )
            gs.current_task_flag = "collect"
            safe_after(0, lambda: current_task_status_var.set("采集中 🏃‍♂️"))
            collect_core.start_collect(server_socket, gs.current_collect_points.copy())
            print(f"▶️ 已恢复采集任务（资源: {', '.join(gs.current_collect_points)}）")
        else:
            gs.current_task_flag = None
            safe_after(0, lambda: current_task_status_var.set("空闲"))
            print("▶️ 无采集勾选，恢复为空闲")

# ADB转发
def setup_adb_forward():
    try:
        adb_path = os.path.join(os.path.dirname(__file__), "adb.exe")
        result = subprocess.run([adb_path, "devices"], stdout=subprocess.PIPE)
        lines = result.stdout.decode().splitlines()
        device_id = next((line.split()[0] for line in lines if "\tdevice" in line), None)
        if not device_id:
            print("❌ 没有可用的ADB设备")
            return
        subprocess.run([adb_path, "-s", device_id, "forward", "tcp:6100", "tcp:6100"])
        subprocess.run([adb_path, "-s", device_id, "forward", "tcp:6101", "tcp:6101"])
        subprocess.run([adb_path, "-s", device_id, "forward", "tcp:6102", "tcp:6102"])
        print(f"✅ 使用设备：{device_id}，ADB端口转发完成")
    except Exception as e:
        print(f"❌ ADB 执行失败: {e}")

# 异步启动 adb forward
threading.Thread(target=setup_adb_forward, daemon=True).start()

# ✅ 6102 端口指令发送工具（短连 → 收ACK → 断开）
def send_control_command(cmd_str):
    import socket
    try:
        with socket.socket() as s:
            s.settimeout(2.0)  # ✅ 设定超时 2 秒，避免卡死
            print(f"[ControlSocket] 准备 connect")
            s.connect(("127.0.0.1", 6102))
            print(f"[ControlSocket] 已 connect，准备发送: {cmd_str.strip()}")
            s.sendall(cmd_str.encode())
            print(f"[ControlSocket] 已发送，准备 recv")
            resp = s.recv(128).decode().strip()
            print(f"[ControlSocket] 收到响应: {resp}")
            return resp
    except Exception as e:
        print(f"[ControlSocket] 发送指令失败: {e}")
        return None
    
collect_core.register_main_callbacks(pause_event, pause_all_tasks)  # 注册采集模块回调
gs.rift_send_control_command_callback = send_control_command # 注册发送控制命令回调              

# Tkinter 界面
root = tk.Tk()
root.title("自动游戏助手 | 主控面板")
root.geometry("500x700")
root.resizable(False, False)
connection_status_var = tk.StringVar(value="⏳ 正在连接 TouchServer...")
listen_mode_var = tk.StringVar(value="监听模式：未知")
rift_level_var = tk.StringVar(value="裂隙层数：无")

# 裂隙模块反馈层数
def update_rift_level(level_text, failure_count):
    text = f"裂隙层数：{level_text} / {failure_count}"
    rift_level_var.set(text)
    print(f"📌 当前识别层数为：{text}")

# 注册为全局回调
gs.rift_level_callback = update_rift_level

def safe_after(ms, func):
    try:
        if threading.current_thread() == threading.main_thread():
            if root.winfo_exists() and root.tk.call('tk', 'windowingsystem') != '':
                root.after(ms, func)
        else:
            # 非主线程，改用 thread-safe 的 queue + after_idle 触发
            import queue
            if not hasattr(safe_after, "_q"):
                safe_after._q = queue.Queue()

                def _process_queue():
                    try:
                        while not safe_after._q.empty():
                            f = safe_after._q.get_nowait()
                            f()
                    except Exception:
                        pass
                    finally:
                        root.after(50, _process_queue)

                root.after(50, _process_queue)

            safe_after._q.put(lambda: func())

    except RuntimeError as e:
        try:
            print(f"⚠️ safe_after 调用失败（可能主线程卡住/退出）: {e}")
        except:
            pass

# 连接状态监控
def monitor_touch_connection():
    while True:
        try:
            if server_socket.is_connected:
                safe_after(0, lambda: connection_status_var.set("✅ 已连接 "))
            else:
                safe_after(0, lambda: connection_status_var.set("⏳ 尝试重连中..."))
                server_socket.connect()
                if server_socket.is_connected:
                    safe_after(0, lambda: connection_status_var.set("✅ 已重新连接 "))
        except Exception as e:
            safe_after(0, lambda: connection_status_var.set(f"❌ 连接失败: {e}"))
        time.sleep(3)

threading.Thread(target=monitor_touch_connection, daemon=True).start()

def monitor_listen_mode():
    def query_and_update():
        try:
            resp = send_control_command("query_status\n")
            print(f"[ListenMode] 当前模式反馈: {resp}")
            if resp == "STATUS:VIDEO_STREAM_MODE":
                safe_after(0, lambda: (
                    listen_mode_var.set("🎬 视频流"),
                    listen_mode_label.config(foreground="blue")
                ))
            elif resp == "STATUS:SCREENSHOT_MODE":
                safe_after(0, lambda: (
                    listen_mode_var.set("📸 截图"),
                    listen_mode_label.config(foreground="green")
                ))
            else:
                safe_after(0, lambda: (
                    listen_mode_var.set(f"❌ 未知 ({resp})"),
                    listen_mode_label.config(foreground="red")
                ))
        except Exception as e:
            print(f"[ListenMode] 查询监听模式失败: {e}")
            safe_after(0, lambda: (
                listen_mode_var.set("❌ 断开/异常"),
                listen_mode_label.config(foreground="red")
            ))

    # 先主动请求一次
    query_and_update()

    while True:
        time.sleep(30)  # 等 30 秒再更新
        query_and_update()


# 启动监听模式轮询线程
threading.Thread(target=monitor_listen_mode, daemon=True).start()

# 日志区
def log(msg):
    try:
        if gs.global_log_callback:
            gs.global_log_callback(msg)
        print(msg)
    except Exception as e:
        print(f"[log异常] {e}")

register_log_callback(log)

# 注册 tech_timer_direct_callback
# 工具函数，保证在主线程里安全获取 collect_enabled.get()
def is_collect_enabled():
    result = [False]
    event = threading.Event()
    def check():
        result[0] = collect_enabled.get()
        event.set()
    safe_after(0, check)
    event.wait(timeout=0.2)  # 最多等 200ms
    return result[0]

# 注册 tech_timer_direct_callback
def tech_timer_direct_callback(task_type):
    global _last_research_callback_ts, selected_collect_points
    now = time.time()
    if now - _last_research_callback_ts < 2:
        print(f"⏳ 科技回调触发过快，延迟 {(2 - (now - _last_research_callback_ts)):.1f} 秒，再尝试执行...")
        threading.Timer(2 - (now - _last_research_callback_ts), lambda: gs.tech_timer_direct_callback(task_type)).start()
        return

    _last_research_callback_ts = now

    if gs.current_task_flag in [None, "collect"]:
        print(f"⚙️ 收到 timer_direct_callback → {task_type}，直接触发科技流程")
        gs.research_pause_event.set()
        pause_all_tasks()
        time.sleep(0.3)
        gs.current_task_flag = "research"
        safe_after(0, lambda: current_task_status_var.set("研究中 💡"))

        # ✅ 正常科技流程
        tech_research_core.research_ready_event.clear()
        tech_research_core.initialize_research_state(server_socket)
        tech_research_core.research_ready_event.wait()

        # ✅ 科技流程完成 → 判断是否启用采集（使用 current_collect_enabled）
        if gs.current_collect_enabled:
            #print(f"[DEBUG] tech_timer_direct_callback 恢复采集 current_collect_points = {gs.current_collect_points}")
            #print(f"✅ 科技流程完成，恢复采集（资源: {', '.join(gs.current_collect_points)}）")
            pause_event.clear()
            gs.research_pause_event.clear()
            gs.current_task_flag = "collect"
            safe_after(0, lambda: current_task_status_var.set("采集中 🏃‍♂️"))
            collect_core.start_collect(server_socket, gs.current_collect_points.copy())
        else:
            print("✅ 科技流程完成（未启用采集模块，不恢复采集）")
            gs.research_pause_event.clear()
            gs.current_task_flag = None
            safe_after(0, lambda: current_task_status_var.set("空闲"))

    elif gs.current_task_flag == "expedition":
        print(f"⚠️ 当前远征中，延迟 10 秒等待状态确认后触发科技流程")

        def delayed_check_and_run():
            if gs.current_task_flag in [None, "collect"]:
                print(f"⚙️ 延迟后确认状态 {gs.current_task_flag}，开始科技流程")
                pause_event.set()
                time.sleep(0.3)

                gs.current_task_flag = "research"
                safe_after(0, lambda: current_task_status_var.set("研究中 💡"))

                tech_research_core.research_ready_event.clear()
                tech_research_core.initialize_research_state(server_socket)
                tech_research_core.research_ready_event.wait()

                if gs.current_collect_enabled:

                    print(f"✅ 科技流程完成，恢复采集（资源: {', '.join(gs.current_collect_points)}）")
                    pause_event.clear()
                    gs.current_task_flag = "collect"
                    safe_after(0, lambda: current_task_status_var.set("采集中 🏃‍♂️"))
                    collect_core.start_collect(server_socket, gs.current_collect_points.copy())
                else:
                    print("✅ 科技流程完成（未启用采集模块，不恢复采集）")
                    pause_event.clear()
                    gs.current_task_flag = None
                    safe_after(0, lambda: current_task_status_var.set("空闲"))
            else:
                print(f"⚠️ 延迟后仍在 {gs.current_task_flag}，暂不处理科技流程")

        threading.Timer(10, delayed_check_and_run).start()

    else:
        print(f"⚠️ 当前状态 {gs.current_task_flag}，忽略科技流程插入")

gs.tech_timer_direct_callback = tech_timer_direct_callback

# 测试截图
def test_screenshot():
    # 更新当前状态
    current_task_status_var.set("截图中 📸")
    print("📸 请求切换到截图模式...")

    # 切换截图模式
    resp = send_control_command("SWITCH_TO_SCREENSHOT\n")
    if resp != "ACK_SWITCH_TO_SCREENSHOT":
        print(f"❌ 切换截图模式失败，返回: {resp}")
        current_task_status_var.set("空闲")
        return

    # 确认切换成功
    for i in range(5):
        status = send_control_command("query_status\n")
        print(f"📡 当前模式状态: {status}")
        if status == "STATUS:SCREENSHOT_MODE":
            break
        time.sleep(0.5)
    else:
        print("❌ 等待切换截图模式超时")
        current_task_status_var.set("空闲")
        return

    # 执行截图
    print("📸 开始请求截图")
    screenshot_socket = ScreenshotSocket(host="127.0.0.1", port=6101)
    img = screenshot_socket.request_screenshot()
    if img:
        with open("screenshot_from_socket.png", "wb") as f:
            f.write(img)
        print("✅ 截图保存完成 screenshot_from_socket.png")
    else:
        print("❌ 无法获取截图")

    # 恢复状态
    current_task_status_var.set("空闲")


# 裂隙模块启动 
def start_rift_manual():
    rift_socket = get_rift_stream_listener()
    current_task_status_var.set("裂隙中 ⚔️")
    pause_event.clear()
    print("⚙️ 启动裂隙模块（由裂隙模块内部处理切换）")
    threading.Thread(target=rift_core.start_rift_module, args=(rift_socket, server_socket), daemon=True).start()

# 裂隙模块退出后的回调
def resume_after_rift_callback():
    print("✅ 收到裂隙模块恢复通知，检查当前模式...")

    # 等待切回截图模式，最多等 5 秒
    for i in range(5):
        resp = send_control_command("query_status\n")
        print(f"📡 当前模式状态: {resp}")
        if resp == "STATUS:SCREENSHOT_MODE":
            print("✅ 当前是截图模式，恢复采集")
            pause_event.clear()
            safe_after(0, lambda: current_task_status_var.set("采集中 🏃‍♂️"))
            gs.current_task_flag = "collect"
            collect_core.start_collect(server_socket, gs.current_collect_points.copy())
            return
        else:
            print("⏳ 等待切回截图模式...")
            time.sleep(1)

    print("⚠️ 超时未切回截图模式，不恢复采集")

# 自动脚本启动
def start_tasks():
    pause_event.clear()
    gs.expedition_pause_event.clear()
    gs.current_task_flag = "running"
    threading.Thread(target=run_tasks_thread, daemon=True).start()

# 手动科技研究
def manual_research():
    print("🧪 手动触发科技研究")
    safe_after(0, lambda: current_task_status_var.set("研究中 💡"))
    pause_event.clear()
    tech_research_core.research_ready_event.clear()
    tech_research_core.initialize_research_state(server_socket)
    tech_research_core.research_ready_event.wait()
    print("✅ 手动科技流程完成")

def monitor_accelerate_ready_event():
    while True:
        tech_timer_manager.accelerate_ready_event.wait()
        tech_timer_manager.accelerate_ready_event.clear()

        print("🔔 主控检测到 accelerate_ready_event，调用 tech_timer_direct_callback")
        try:
            gs.tech_timer_direct_callback("accelerate")
        except Exception as e:
            print(f"⚠️ tech_timer_direct_callback 调用异常（主控监控线程）: {e}")
# 启动监控线程
threading.Thread(target=monitor_accelerate_ready_event, daemon=True).start()            

# 手动远征任务
def manual_expedition():
    print("🛰️ 手动触发远征流程")
    current_task_status_var.set("远征中 🚀")
    pause_event.clear()
    set_expedition_flags(scout_enabled.get(), camp_reward_enabled.get())
    gs.expedition_pause_event.clear()
    expedition_core.manual_trigger_expedition(server_socket, pause_event, pause_all_tasks)

# 裂隙模块继续挑战
def continue_rift():
    print("▶️ 继续裂隙挑战执行")
    current_task_status_var.set("裂隙中 ⚔️")
    rift_core.resume_rift(server_socket)

# 自动脚本线程
def run_tasks_thread():
    global selected_collect_points

    print("▶️ 脚本已启动...")
    show_toast("▶️ 启动脚本", "所有系统已启动")

    set_expedition_enabled(expedition_enabled.get())
    set_expedition_flags(scout_enabled.get(), camp_reward_enabled.get())

    # 记录当前采集勾选状态
    gs.current_collect_enabled = collect_enabled.get()
    print(f"📢 当前启动时采集启用状态: {gs.current_collect_enabled}")

    # 科技模块
    if gs.current_collect_enabled:
        print("🧬 开始科技研究任务")
        if pause_event.is_set():
            print("⏸️ 检测到暂停信号，中止自动流程")
            current_task_status_var.set("空闲")
            return
        safe_after(0, lambda: current_task_status_var.set("研究中 💡"))
        tech_research_core.research_ready_event.clear()
        tech_research_core.initialize_research_state(server_socket)
        print("⏳ 等待科技处理...")
        tech_research_core.research_ready_event.wait()
        print("✅ 科技处理完成")
        gs.research_pause_event.clear()   # ✅ 先 clear
        gs.current_task_flag = "collect"
        safe_after(0, lambda: current_task_status_var.set("采集中 🏃‍♂️"))
        if pause_event.is_set():
            print("⏸️ 检测到暂停信号，中止自动流程")
            current_task_status_var.set("空闲")
            return

    # 采集模块
    if gs.current_collect_enabled:
        if pause_event.is_set():
            print("⏸️ 检测到暂停信号，中止自动流程")
            current_task_status_var.set("空闲")
            return
        pause_event.clear()
        gs.current_collect_enabled = collect_enabled.get()
        gs.current_collect_points = (
            ["食物"] if global_resource_mode.get()
            else [label for label, var in resource_vars.items() if var.get()]
        )
        def resume_after_expedition():
            print("📢 收到远征完成通知，恢复采集")
            pause_event.clear()
            gs.current_task_flag = "collect"
            collect_core.start_collect(server_socket, gs.current_collect_points.copy())

        expedition_core.register_main_callbacks(resume_after_expedition, pause_all_tasks)
        safe_after(0, lambda: current_task_status_var.set("采集中 🏃‍♂️"))

        print(f"📦 启用采集: {', '.join(gs.current_collect_points)}") 
        gs.research_pause_event.clear()
        gs.current_task_flag = "collect"
        threading.Thread(target=collect_core.start_collect, args=(server_socket, gs.current_collect_points.copy()), daemon=True).start()

    # 远征模块
    if expedition_enabled.get():
        print("✅ 远征模块已启用")

    # 裂隙模块
    if rift_enabled.get():
        enable_rift_listener()
        rift_socket = get_rift_stream_listener()
        print("⚔️ 启用裂隙闯关")
        pause_all_tasks()
        time.sleep(2)  # 等待其他模块彻底停下

        # ✅ 注册裂隙退出后恢复采集的回调
        def resume_after_rift_callback():
            print("✅ 收到裂隙模块恢复通知，检查当前模式...")
            control_socket = ControlSocket()

            # 等待切回截图模式，最多等 5 秒
            for i in range(5):
                resp = control_socket.query_status()
                print(f"📡 当前模式状态: {resp}")
                if resp == "STATUS:SCREENSHOT_MODE":
                    print("✅ 当前是截图模式，恢复采集")
                    pause_event.clear()
                    collect_core.start_collect(server_socket, gs.current_collect_points)
                    return
                else:
                    print("⏳ 等待切回截图模式...")
                    time.sleep(1)

            print("⚠️ 超时未切回截图模式，不恢复采集")

        # ✅ 主动注册回调到 rift_core
        rift_core.register_main_callbacks(resume_after_rift_callback, pause_all_tasks)

        threading.Thread(target=rift_core.start_rift_module, args=(rift_socket, server_socket), daemon=True).start()

# 停止所有模块
def stop_tasks():
    pause_all_tasks()
    gs.expedition_pause_event.set()
    gs.current_task_flag = None
    current_task_status_var.set("空闲")
    print("⏸️ 所有模块已暂停（裂隙模块已自动切回截图模式）")
    show_toast("⏸️ 暂停所有模块", "已停止所有任务")

# 退出程序
def exit_app():
    gs.current_task_flag = None
    print("❎ 脚本退出")
    show_toast("❎ 脚本退出", "感谢使用")
    server_socket.close()
    root.quit()

# 变量定义
collect_enabled = tk.BooleanVar()
expedition_enabled = tk.BooleanVar()
rift_enabled = tk.BooleanVar()
camp_reward_enabled = tk.BooleanVar()
scout_enabled = tk.BooleanVar()
global_resource_mode = tk.BooleanVar()
resource_vars = {label: tk.BooleanVar() for label in COLLECT_POINTS if label in ["木材", "食物", "石头", "铜矿", "铁矿"]}

# GUI 布局
frame = ttk.LabelFrame(root, text="功能启用设置")
frame.pack(fill="x", padx=10, pady=10)

features = [
    ("启用采集模块", collect_enabled),
    ("启用远征模块", expedition_enabled),
    ("启用领地矿区一键领取（需配合远征）", camp_reward_enabled),
    ("启用侦察功能（需配合远征）", scout_enabled),
    ("启用时空裂隙自动挑战", rift_enabled),
]

for i, (text, var) in enumerate(features):
    ttk.Checkbutton(frame, text=text, variable=var).grid(row=i // 2, column=i % 2, sticky="w", padx=10, pady=2)

# 手动控制功能
manual_frame = ttk.LabelFrame(root, text="手动控制功能")
manual_frame.pack(fill="x", padx=10, pady=(0, 10))

ttk.Button(manual_frame, text="🔬 手动科技研究", command=lambda: threading.Thread(target=manual_research, daemon=True).start()).grid(row=0, column=0, padx=10, pady=5)
ttk.Button(manual_frame, text="📦 手动远征任务", command=lambda: threading.Thread(target=manual_expedition, daemon=True).start()).grid(row=0, column=1, padx=10, pady=5)
ttk.Button(manual_frame, text="⚔️ 手动裂隙挑战", command=lambda: threading.Thread(target=start_rift_manual, daemon=True).start()).grid(row=0, column=2, padx=10, pady=5)
ttk.Button(manual_frame, text="▶️ 继续挑战", command=continue_rift).grid(row=0, column=3, padx=10, pady=5)

# 采集资源选择
resource_frame = ttk.LabelFrame(root, text="采集资源选择")
resource_frame.pack(fill="x", padx=10, pady=5)

resource_list = list(resource_vars.items())
for i, (label, var) in enumerate(resource_list):
    ttk.Checkbutton(resource_frame, text=label, variable=var).grid(row=0, column=i, padx=10, pady=2, sticky="w")

ttk.Checkbutton(resource_frame, text="全资源区域点击（批量采集）", variable=global_resource_mode).grid(row=2, column=0, columnspan=3, padx=10, pady=(5, 0), sticky="w")

# ▶️ 包装容器，放入两块模块
status_container = ttk.Frame(root)
status_container.pack(fill="x", padx=10, pady=5)

# ✅ 科技研究状态区块（左）
research_frame = ttk.LabelFrame(status_container, text="研究状态")
research_frame.grid(row=0, column=0, sticky="w", padx=(0, 10))

research_status_var = tk.StringVar(value="研究剩余：无")
accel_status_var = tk.StringVar(value="加速CD：无")

ttk.Label(research_frame, textvariable=research_status_var).grid(row=0, column=0, sticky="w", padx=10, pady=2)
ttk.Label(research_frame, textvariable=accel_status_var).grid(row=1, column=0, sticky="w", padx=10, pady=2)

# ✅ 裂隙状态区块（右）
rift_frame = ttk.LabelFrame(status_container, text="裂隙状态")
rift_frame.grid(row=0, column=1, sticky="e")

rift_level_var = tk.StringVar(value="裂隙层数：无 / 0")
ttk.Label(rift_frame, textvariable=rift_level_var, foreground="orange").grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=2)

# ✨ 裂隙失败次数输入框
ttk.Label(rift_frame, text="失败重试次数：").grid(row=1, column=0, sticky="e", padx=(10, 5), pady=2)
rift_retry_var = tk.StringVar(value="30")
rift_retry_entry = ttk.Entry(rift_frame, textvariable=rift_retry_var, width=5)
rift_retry_entry.grid(row=1, column=1, sticky="w", padx=(0, 10), pady=2)

# ✅ 绑定修改事件，实时更新给 rift_core
def update_rift_retry_limit(*args):
    try:
        val = int(rift_retry_var.get())
        if val < 1:
            val = 1
        elif val > 99:
            val = 99
        rift_core.failure_retry_limit = val
        print(f"[主控面板] 已更新裂隙失败重试次数为: {val}")
    except ValueError:
        pass  # 不处理非数字，保持原值不变

rift_retry_var.trace_add("write", update_rift_retry_limit)


def update_status_labels():
    status = tech_timer_manager.get_timer_status()
    research_status_var.set("研究剩余：" + status["研究剩余"])
    accel_status_var.set("加速CD：" + status["加速CD"])
    root.after(1000, update_status_labels)

update_status_labels()

# 主控界面更新任务状态
def set_current_task_status(status_text):
    current_task_status_var.set(status_text)

# 注册回调到 global_state
gs.current_task_status_callback = set_current_task_status

# 软件状态显示   
software_status_frame = ttk.LabelFrame(root, text="软件状态")
software_status_frame.pack(fill="x", padx=10, pady=10)

# 横向容器
status_inner_frame = ttk.Frame(software_status_frame)
status_inner_frame.pack(fill="x", padx=5, pady=5)

# TouchServer 状态
ttk.Label(status_inner_frame, text="TouchServer：").grid(row=0, column=0, sticky="w", padx=(5, 5))
connection_status_label = ttk.Label(status_inner_frame, textvariable=connection_status_var, foreground="blue")
connection_status_label.grid(row=0, column=1, sticky="w", padx=(0, 15))

# 监听模式
ttk.Label(status_inner_frame, text="监听模式：").grid(row=0, column=2, sticky="w", padx=(0, 5))
listen_mode_label = ttk.Label(status_inner_frame, textvariable=listen_mode_var, foreground="green")
listen_mode_label.grid(row=0, column=3, sticky="w", padx=(0, 15))

# 当前运行模块状态
ttk.Label(status_inner_frame, text="运行状态：").grid(row=0, column=4, sticky="w", padx=(0, 5))
current_task_status_var = tk.StringVar(value="空闲")
current_task_status_label = ttk.Label(status_inner_frame, textvariable=current_task_status_var, foreground="purple")
current_task_status_label.grid(row=0, column=5, sticky="w")

# 按钮框架
btn_frame = ttk.Frame(root)
btn_frame.pack(pady=10)
for i, (text, cmd) in enumerate([
    ("▶ 启动", start_tasks),
    ("⏸ 暂停", stop_tasks),
    ("❎ 退出", exit_app),
    ("📸 测试截图", test_screenshot)
]):
    ttk.Button(btn_frame, text=text, command=cmd).grid(row=0, column=i, padx=10)

log_text = tk.Text(root, height=15, state='disabled', bg="#111", fg="#0f0", insertbackground="#0f0")
log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

# 启动主循环
if __name__ == '__main__':
    root.mainloop()
