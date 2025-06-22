# ✅ TouchAgent Python 端主控逻辑优化版（最终整理版）
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
import queue
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton,QVBoxLayout, QHBoxLayout, QGridLayout, QCheckBox, QTextEdit,QGroupBox, QLineEdit, QFrame)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, QMetaObject, Qt
from PyQt5.QtGui import QIntValidator
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
    if gs.current_task_flag is None:
        gs.research_pause_event.clear()
        if window.checkbox_collect.isChecked():
            gs.current_collect_points = (
                ["食物"] if window.checkbox_food_only.isChecked()
                else list(COLLECT_POINTS.keys())
            )
            gs.current_task_flag = "collect"
            safe_after(0, lambda: window.update_task_status("采集中 🏃‍♂️"))
            collect_core.start_collect(server_socket, gs.current_collect_points.copy())
            print(f"▶️ 已恢复采集任务（资源: {', '.join(gs.current_collect_points)}）")
        else:
            gs.current_task_flag = None
            safe_after(0, lambda: window.update_task_status("空闲"))
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

class MainWindow(QMainWindow):
    connection_status_signal = pyqtSignal(str, str)
    listen_mode_signal = pyqtSignal(str, str)
    task_status_signal = pyqtSignal(str, str)
    log_signal = pyqtSignal(str)
    def __init__(self):
        super().__init__()

        self.setWindowTitle("自动游戏助手 | 主控面板")
        self._ui_queue = queue.Queue()
        def _process_ui_queue():
            try:
                while not self._ui_queue.empty():
                    func = self._ui_queue.get_nowait()
                    func()
            except Exception:
                pass
            finally:
                QTimer.singleShot(50, _process_ui_queue)
        QTimer.singleShot(50, _process_ui_queue)
        
        self.setGeometry(100, 100, 430, 700)
        self.setFixedSize(430, 700)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.main_layout = QVBoxLayout()
        self.central_widget.setLayout(self.main_layout)

        # 功能启用设置
        function_group = QGroupBox("功能启用设置")
        function_layout = QGridLayout()
        function_group.setLayout(function_layout)

        self.checkbox_collect = QCheckBox("启用采集模块")
        self.checkbox_expedition = QCheckBox("启用远征模块")
        self.checkbox_mine_reward = QCheckBox("启用领地矿区一键领取（需配合远征）")
        self.checkbox_scout = QCheckBox("启用侦察功能（需配合远征）")
        self.checkbox_rift = QCheckBox("启用时空裂隙自动挑战")

        function_layout.addWidget(self.checkbox_collect, 0, 0)
        function_layout.addWidget(self.checkbox_expedition, 0, 1)
        function_layout.addWidget(self.checkbox_mine_reward, 1, 0)
        function_layout.addWidget(self.checkbox_scout, 1, 1)
        function_layout.addWidget(self.checkbox_rift, 2, 0)

        self.main_layout.addWidget(function_group)

        # 手动控制功能
        manual_group = QGroupBox("手动控制功能")
        manual_layout = QHBoxLayout()
        manual_group.setLayout(manual_layout)

        self.btn_manual_research = QPushButton("🔬 手动科技研究")
        self.btn_manual_expedition = QPushButton("📦 手动远征任务")
        self.btn_manual_rift = QPushButton("⚔️ 手动裂隙挑战")
        self.btn_continue_rift = QPushButton("▶️ 继续挑战")

        for btn in [self.btn_manual_research, self.btn_manual_expedition, self.btn_manual_rift, self.btn_continue_rift]:
            manual_layout.addWidget(btn)

        self.main_layout.addWidget(manual_group)

        # 采集资源选择
        resource_group = QGroupBox("采集资源选择")
        resource_layout = QVBoxLayout()
        resource_group.setLayout(resource_layout)

        row1 = QHBoxLayout()
        self.checkbox_wood = QCheckBox("木材")
        self.checkbox_food = QCheckBox("食物")
        self.checkbox_stone = QCheckBox("石头")
        self.checkbox_copper = QCheckBox("铜矿")
        self.checkbox_iron = QCheckBox("铁矿")
        for cb in [self.checkbox_wood, self.checkbox_food, self.checkbox_stone, self.checkbox_copper, self.checkbox_iron]:
            row1.addWidget(cb)

        resource_layout.addLayout(row1)
        resource_layout.addSpacing(5)
        self.main_layout.addWidget(resource_group)

        # 科技 + 裂隙状态
        status_frame = QFrame()
        status_layout = QHBoxLayout()
        status_frame.setLayout(status_layout)

        # 研究状态（左）
        left_box = QGroupBox("研究状态")
        left_layout = QVBoxLayout()
        self.research_status_label = QLabel("研究剩余：无")
        self.accel_status_label = QLabel("加速CD：无")
        left_layout.addWidget(self.research_status_label)
        left_layout.addWidget(self.accel_status_label)
        left_box.setLayout(left_layout)

        # 裂隙状态（右）
        right_box = QGroupBox("裂隙状态")
        right_layout = QVBoxLayout()

        self.rift_level_label = QLabel("裂隙层数：无 / 0")

        retry_row = QHBoxLayout()
        retry_label = QLabel("失败重试次数：")
        retry_label.setFixedWidth(90)  # ✅ 控制标签宽度，统一与左侧保持视觉对齐

        self.rift_retry_input = QLineEdit()
        self.rift_retry_input.setFixedWidth(40)
        self.rift_retry_input.setMaximumWidth(40)
        self.rift_retry_input.setAlignment(Qt.AlignCenter)  # 让数字居中看起来更舒服
        self.rift_retry_input.setText("30")  # 默认值设为30
        self.rift_retry_input.setValidator(QIntValidator(1, 99, self))

        retry_row = QHBoxLayout()
        retry_label = QLabel("失败重试次数：")
        retry_label.setFixedWidth(85)  # 稍微紧凑一点
        retry_row.setSpacing(5)        # 控制组件之间间距
        retry_row.addWidget(retry_label)
        retry_row.addWidget(self.rift_retry_input)
        retry_row.addStretch()

        right_layout.addWidget(self.rift_level_label)
        right_layout.addLayout(retry_row)
        right_box.setLayout(right_layout)

        # 合并到主布局中
        status_layout.addWidget(left_box, 1)
        status_layout.addWidget(right_box, 1)
        self.main_layout.addWidget(status_frame)

        # 软件状态
        status_group2 = QGroupBox("软件状态")
        status_layout2 = QHBoxLayout()
        status_group2.setLayout(status_layout2)

        self.connection_status_label = QLabel("未连接")
        self.listen_mode_label = QLabel("--")
        self.task_status_label = QLabel("--")

        status_layout2.addWidget(QLabel("TouchServer:"))
        status_layout2.addWidget(self.connection_status_label)
        self.connection_status_label.setStyleSheet("color: green; font-weight: bold;")
        status_layout2.addWidget(QLabel("监听模式:"))
        status_layout2.addWidget(self.listen_mode_label)
        self.listen_mode_label.setStyleSheet("color: blue; font-weight: bold;")
        status_layout2.addWidget(QLabel("运行状态:"))
        status_layout2.addWidget(self.task_status_label)
        self.task_status_label.setStyleSheet("color: orange; font-weight: bold;")

        self.main_layout.addWidget(status_group2)

        # 控制按钮
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ 启动")
        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_exit = QPushButton("❎ 退出")
        self.btn_screenshot = QPushButton("📸 测试截图")

        for btn in [self.btn_start, self.btn_pause, self.btn_exit, self.btn_screenshot]:
            btn.setFixedWidth(90)
            btn_layout.addWidget(btn)

        btn_layout.setSpacing(15)
        btn_layout.setAlignment(Qt.AlignCenter)
        self.main_layout.addLayout(btn_layout)

        # 日志输出框
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: #111; color: #0f0; font-family: Consolas;")
        self.log_output.setFixedHeight(200)
        self.main_layout.addWidget(self.log_output)
        register_log_callback(self.thread_safe_log)

        # 绑定按钮事件（外部定义）
        self.btn_start.clicked.connect(start_tasks)
        self.btn_pause.clicked.connect(stop_tasks)
        self.btn_exit.clicked.connect(exit_app)
        self.btn_screenshot.clicked.connect(test_screenshot)
        # ✅ 主控界面按钮事件绑定
        self.btn_manual_research.clicked.connect(manual_research)
        self.btn_manual_expedition.clicked.connect(manual_expedition)
        self.btn_manual_rift.clicked.connect(start_rift_manual)
        self.btn_continue_rift.clicked.connect(continue_rift)
        self.connection_status_signal.connect(self.update_connection_status)
        self.listen_mode_signal.connect(self.update_listen_mode)
        self.task_status_signal.connect(self.update_task_status)
        self.log_signal.connect(self.append_log)  # 绑定信号槽
        register_log_callback(self.log_signal.emit)  # ✅ 用 signal.emit 注册回调

        # ✅ 设置分组标题样式（加粗 + 字号）
        for group in [function_group, manual_group, resource_group, status_group2, left_box, right_box]:
            group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 12px; }")   

    def update_connection_status(self, text, color="green"):
        self.connection_status_label.setText(text)
        self.connection_status_label.setStyleSheet(f"color: {color};")

    def update_listen_mode(self, text, color="blue"):
        print(f"✅ UI正在更新监听模式：{text}")
        self.listen_mode_label.setText(text)
        self.listen_mode_label.setStyleSheet(f"color: {color};")

    def update_task_status(self, text, color="orange"):
        self.task_status_label.setText(text)
        self.task_status_label.setStyleSheet(f"color: {color};")

    def update_rift_level(self, text):
        self.rift_level_label.setText(text)

    def update_research_status(self, text):
        self.research_status_label.setText(f"研究剩余：{text}")

    def update_accel_status(self, text):
        self.accel_status_label.setText(f"加速CD：{text}")

    def append_log(self, message):
        self.log_output.append(message)
        self.log_output.ensureCursorVisible()

    def thread_safe_log(self, msg):
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.append_log(msg))
    
        


def update_runtime_flags_from_ui():
    gs.current_collect_enabled = window.checkbox_collect.isChecked()

    selected_resources = []
    if window.checkbox_wood.isChecked(): selected_resources.append("木材")
    if window.checkbox_food.isChecked(): selected_resources.append("食物")
    if window.checkbox_stone.isChecked(): selected_resources.append("石头")
    if window.checkbox_copper.isChecked(): selected_resources.append("铜矿")
    if window.checkbox_iron.isChecked(): selected_resources.append("铁矿")
    gs.current_collect_points = selected_resources.copy()

    gs.rift_max_retry = int(window.rift_retry_input.text())

def start_background_threads():
    if 'window' not in globals():
        print("❌ window 尚未定义，跳过启动监控线程")
        return
    threading.Thread(target=monitor_touch_connection, daemon=True).start()
    threading.Thread(target=monitor_listen_mode, daemon=True).start()

# 裂隙模块反馈层数
def update_rift_level(level_text, failure_count):
    text = f"裂隙层数：{level_text} / {failure_count}"
    window.update_rift_level(text)
    print(f"📌 当前识别层数为：{text}")
    show_toast("📌 裂隙层数更新", f"当前识别层数为：{level_text} / 失败次数：{failure_count}")

# 注册为全局回调
gs.rift_level_callback = update_rift_level

def safe_after(ms, func):
    try:
        if threading.current_thread() == threading.main_thread():
            QTimer.singleShot(ms, func)
        else:
            if hasattr(window, "_ui_queue"):
                window._ui_queue.put(func)
            else:
                print("⚠️ window._ui_queue 不存在，无法排队执行 UI 更新")
    except RuntimeError as e:
        print(f"⚠️ safe_after 调用失败: {e}")

# 连接状态监控
def monitor_touch_connection():
    while True:
        try:
            if server_socket.is_connected:
                window.connection_status_signal.emit("✅ 已连接 ", "green")
            else:
                window.connection_status_signal.emit("⏳ 尝试重连中...", "orange")
                server_socket.connect()
                if server_socket.is_connected:
                    window.connection_status_signal.emit("✅ 已重新连接 ", "green")
        except Exception as e:
            window.connection_status_signal.emit(f"❌ 连接失败: {e}", "red")
        time.sleep(3)

def monitor_listen_mode():
    def query_and_update():
        try:
            resp = send_control_command("query_status\n")
            print(f"[ListenMode] 当前模式反馈: {resp}")
            if resp == "STATUS:VIDEO_STREAM_MODE":
                safe_after(0, lambda: window.listen_mode_signal.emit("🎬 视频流", "blue"))
            elif resp == "STATUS:SCREENSHOT_MODE":
                safe_after(0, lambda: window.listen_mode_signal.emit("📸 截图", "green"))
            else:
                safe_after(0, lambda: window.listen_mode_signal.emit(f"❌ 未知 ({resp})", "red"))
        except Exception as e:
            print(f"[ListenMode] 查询监听模式失败: {e}")
            safe_after(0, lambda: (
                window.listen_mode_signal.emit("❌ 断开/异常"),
                window.listen_mode_label.setStyleSheet("color: red;")
            ))

    # 先主动请求一次
    query_and_update()

    while True:
        time.sleep(30)  # 等 30 秒再更新
        query_and_update()



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
# 工具函数，保证在主线程里安全获取 window.checkbox_collect.isChecked()
def is_collect_enabled():
    result = [False]
    event = threading.Event()
    def check():
        result[0] = window.checkbox_collect.isChecked()
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
        show_toast("⚙️ 科技流程触发", "正在执行科技流程")
        gs.research_pause_event.set()
        pause_all_tasks()
        time.sleep(0.3)
        gs.current_task_flag = "research"
        safe_after(0, lambda: window.update_task_status("研究中 💡"))

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
            safe_after(0, lambda: window.update_task_status("采集中 🏃‍♂️"))
            collect_core.start_collect(server_socket, gs.current_collect_points.copy())
        else:
            print("✅ 科技流程完成（未启用采集模块，不恢复采集）")
            gs.research_pause_event.clear()
            gs.current_task_flag = None
            safe_after(0, lambda: window.update_task_status("空闲"))

    elif gs.current_task_flag == "expedition":
        print(f"⚠️ 当前远征中，延迟 10 秒等待状态确认后触发科技流程")

        def delayed_check_and_run():
            if gs.current_task_flag in [None, "collect"]:
                print(f"⚙️ 延迟后确认状态 {gs.current_task_flag}，开始科技流程")
                pause_event.set()
                time.sleep(0.3)

                gs.current_task_flag = "research"
                safe_after(0, lambda: window.update_task_status("研究中 💡"))

                tech_research_core.research_ready_event.clear()
                tech_research_core.initialize_research_state(server_socket)
                tech_research_core.research_ready_event.wait()

                if gs.current_collect_enabled:

                    print(f"✅ 科技流程完成，恢复采集（资源: {', '.join(gs.current_collect_points)}）")
                    pause_event.clear()
                    gs.current_task_flag = "collect"
                    safe_after(0, lambda: window.update_task_status("采集中 🏃‍♂️"))
                    collect_core.start_collect(server_socket, gs.current_collect_points.copy())
                else:
                    print("✅ 科技流程完成（未启用采集模块，不恢复采集）")
                    pause_event.clear()
                    gs.current_task_flag = None
                    safe_after(0, lambda: window.update_task_status("空闲"))
            else:
                print(f"⚠️ 延迟后仍在 {gs.current_task_flag}，暂不处理科技流程")

        threading.Timer(10, delayed_check_and_run).start()

    else:
        print(f"⚠️ 当前状态 {gs.current_task_flag}，忽略科技流程插入")

gs.tech_timer_direct_callback = tech_timer_direct_callback

# 测试截图
def test_screenshot():
    # 更新当前状态
    window.update_task_status("截图中 📸")
    print("📸 请求切换到截图模式...")

    # 切换截图模式
    resp = send_control_command("SWITCH_TO_SCREENSHOT\n")
    if resp != "ACK_SWITCH_TO_SCREENSHOT":
        print(f"❌ 切换截图模式失败，返回: {resp}")
        window.update_task_status("空闲")
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
        window.update_task_status("空闲")
        return

    # 执行截图
    print("📸 开始请求截图")
    screenshot_socket = ScreenshotSocket(host="127.0.0.1", port=6101)
    img = screenshot_socket.request_screenshot()
    if img:
        with open("screenshot_from_socket.png", "wb") as f:
            f.write(img)
        print("✅ 截图保存完成 screenshot_from_socket.png")
        show_toast("✅ 截图完成", "已保存为 screenshot_from_socket.png")
    else:
        print("❌ 无法获取截图")

    # 恢复状态
    window.update_task_status("空闲")


# 裂隙模块启动 
def start_rift_manual():
    rift_socket = get_rift_stream_listener()
    window.update_task_status("裂隙中 ⚔️")
    pause_event.clear()
    print("⚙️ 启动裂隙模块（由裂隙模块内部处理切换）")
    show_toast("⚙️ 启动裂隙模块", "裂隙模块已启动，等待挑战")
    try:
        retry_count = int(window.rift_retry_input.text())
    except:
        retry_count = 30
    threading.Thread(target=rift_core.start_rift_module, args=(rift_socket, server_socket, retry_count), daemon=True).start()

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
            safe_after(0, lambda: window.update_task_status("采集中 🏃‍♂️"))
            gs.current_task_flag = "collect"
            collect_core.start_collect(server_socket, gs.current_collect_points.copy())
            return
        else:
            print("⏳ 等待切回截图模式...")
            time.sleep(1)

    print("⚠️ 超时未切回截图模式，不恢复采集")

# 自动脚本启动
def start_tasks():
    show_toast("▶️ 启动脚本", "正在启动所有模块...")
    pause_event.clear()
    gs.expedition_pause_event.clear()
    gs.current_task_flag = "running"
    threading.Thread(target=run_tasks_thread, daemon=True).start()

# 手动科技研究
def manual_research():
    print("🧪 手动触发科技研究")
    show_toast("🧪 手动科技研究", "正在执行手动科技流程")
    safe_after(0, lambda: window.update_task_status("研究中 💡"))
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
    show_toast("🛰️ 手动远征流程", "正在执行手动远征任务")
    window.update_task_status("远征中 🚀")
    pause_event.clear()
    set_expedition_flags(window.checkbox_scout.isChecked(), window.checkbox_mine_reward.isChecked())
    gs.expedition_pause_event.clear()
    expedition_core.manual_trigger_expedition(server_socket, pause_event, pause_all_tasks)

# 裂隙模块继续挑战
def continue_rift():
    print("▶️ 继续裂隙挑战执行")
    show_toast("▶️ 继续裂隙挑战", "正在继续裂隙挑战")
    window.update_task_status("裂隙中 ⚔️")
    rift_core.resume_rift(server_socket)

# 自动脚本线程
def run_tasks_thread():

    print("▶️ 脚本已启动...")

    set_expedition_enabled(window.checkbox_expedition.isChecked())
    set_expedition_flags(window.checkbox_scout.isChecked(), window.checkbox_mine_reward.isChecked())

    # 记录当前采集勾选状态
    gs.current_collect_enabled = window.checkbox_collect.isChecked()
    print(f"📢 当前启动时采集启用状态: {gs.current_collect_enabled}")

    # 科技模块
    if gs.current_collect_enabled:
        print("🧬 开始科技研究任务")
        show_toast("🧬 科技研究任务", "正在执行科技研究流程")
        if pause_event.is_set():
            print("⏸️ 检测到暂停信号，中止自动流程")
            window.update_task_status("空闲")
            return
        safe_after(0, lambda: window.update_task_status("研究中 💡"))
        tech_research_core.research_ready_event.clear()
        tech_research_core.initialize_research_state(server_socket)
        print("⏳ 等待科技处理...")
        tech_research_core.research_ready_event.wait()
        print("✅ 科技处理完成")
        gs.research_pause_event.clear()   # ✅ 先 clear
        gs.current_task_flag = "collect"
        safe_after(0, lambda: window.update_task_status("采集中 🏃‍♂️"))
        show_toast("✅ 科技研究完成", "已恢复采集任务")
        if pause_event.is_set():
            print("⏸️ 检测到暂停信号，中止自动流程")
            window.update_task_status("空闲")
            return

    # 采集模块
    if gs.current_collect_enabled:
        if pause_event.is_set():
            print("⏸️ 检测到暂停信号，中止自动流程")
            window.update_task_status("空闲")
            return
        pause_event.clear()
        gs.current_collect_enabled = window.checkbox_collect.isChecked()
        selected_resources = []
        if window.checkbox_wood.isChecked(): selected_resources.append("木材")
        if window.checkbox_food.isChecked(): selected_resources.append("食物")
        if window.checkbox_stone.isChecked(): selected_resources.append("石头")
        if window.checkbox_copper.isChecked(): selected_resources.append("铜矿")
        if window.checkbox_iron.isChecked(): selected_resources.append("铁矿")
        gs.current_collect_points = selected_resources.copy()
        def resume_after_expedition():
            print("📢 收到远征完成通知，恢复采集")
            show_toast("📢 收到远征完成通知", "正在恢复采集任务")
            pause_event.clear()
            gs.current_task_flag = "collect"
            collect_core.start_collect(server_socket, gs.current_collect_points.copy())

        expedition_core.register_main_callbacks(resume_after_expedition, pause_all_tasks)
        safe_after(0, lambda: window.update_task_status("采集中 🏃‍♂️"))

        print(f"📦 启用采集: {', '.join(gs.current_collect_points)}") 
        show_toast("📦 启用采集", f"已启用采集任务（资源: {', '.join(gs.current_collect_points)}）")
        gs.research_pause_event.clear()
        gs.current_task_flag = "collect"
        threading.Thread(target=collect_core.start_collect, args=(server_socket, gs.current_collect_points.copy()), daemon=True).start()

    # 远征模块
    if window.checkbox_expedition.isChecked():
        print("✅ 远征模块已启用")

    # 裂隙模块
    if window.checkbox_rift.isChecked():
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
    window.update_task_status("空闲")
    print("⏸️ 所有模块已暂停（裂隙模块已自动切回截图模式）")
    show_toast("⏸️ 暂停所有模块", "已停止所有任务")

# 退出程序
def exit_app():
    gs.current_task_flag = None
    print("❎ 脚本退出")
    show_toast("❎ 脚本退出", "感谢使用")
    server_socket.close()
    QApplication.quit()

def update_status_labels():
    status = tech_timer_manager.get_timer_status()
    window.research_status_label.setText("研究剩余：" + status["研究剩余"])
    window.accel_status_label.setText("加速CD：" + status["加速CD"])
    QTimer.singleShot(1000, update_status_labels)

# 启动主循环
if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    window = MainWindow()
    update_status_labels()
    update_runtime_flags_from_ui()
    window.show()
    start_background_threads()
    sys.exit(app.exec_())

