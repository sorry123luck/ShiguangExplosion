import threading
import time
import cv2
import numpy as np
from utils.toast_notify import show_toast
from utils.adb_tools import ScreenshotSocket, TouchServerSocket
from position_config import COLLECT_POINTS, ASSIST_POINTS, EXPEDITION_POINTS
import global_state as gs
from expedition_core import run_expedition_once, is_expedition_enabled, is_expedition_running

collect_running = threading.Event()
assist_running = threading.Event()
selected_points = []
pause_event = threading.Event()
pause_callback = None

def register_main_callbacks(pause_evt, pause_func):
    global pause_event, pause_callback
    pause_event = pause_evt
    pause_callback = pause_func

def set_collect_points(points):
    global selected_points
    selected_points = points.copy()
    gs.current_collect_points = points.copy()

def capture_screen_safe():
    try:
        screenshot_socket = ScreenshotSocket(host="127.0.0.1", port=6101)
        data = screenshot_socket.request_screenshot()
        if data:
            print("[助力] 已获取截图数据")
            image = np.frombuffer(data, dtype=np.uint8)
            return cv2.imdecode(image, cv2.IMREAD_COLOR)
        else:
            print("❌ 助力无法获取截图")
            return None
    except Exception as e:
        print(f"❌ 助力截图异常: {e}")
        return None

def match_template(screen, template, region, threshold=0.8):
    left, top, right, bottom = region
    region_img = screen[top:bottom, left:right]
    result = cv2.matchTemplate(region_img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return max_val >= threshold

def has_moyu_icon(screen_img):
    region = EXPEDITION_POINTS["摸鱼队伍区域"]
    #print(f"[DEBUG] 摸鱼区域: {region}")
    template = cv2.imread("icons/CJ-YZ.png", 0)
    gray = cv2.cvtColor(screen_img[region[1]:region[3], region[0]:region[2]], cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    print(f"[主页摸鱼识别] 匹配度: {max_val:.3f}")
    return max_val >= 0.85

def assist_loop(server_socket):
    global pause_callback 
    zhuli_template = cv2.imread("icons/zhuli.png")
    close_template = cv2.imread("icons/ZY-LT.png")
    print("[助力] 助力线程启动 ✅")

    while assist_running.is_set():
        if pause_event.is_set() or gs.expedition_pause_event.is_set():
            time.sleep(0.5)  # ✅ 挂起
            continue
        screen = capture_screen_safe()
        if screen is None:
            print("[助力] 截图失败，跳过本轮")
            time.sleep(1)
            continue

        if match_template(screen, close_template, ASSIST_POINTS["聊天关闭识别区域"]):
            print("[助力] 识别到聊天关闭图标，执行点击")
            server_socket.tap(*ASSIST_POINTS["关闭聊天窗口"])
            show_toast("聊天已关闭", "✅ 自动点击 /")
            time.sleep(1)
            continue

        if match_template(screen, zhuli_template, ASSIST_POINTS["助力图标识别区域"]):
            print("[助力] 识别到助力图标，点击执行")
            server_socket.tap(*ASSIST_POINTS["点击助力按钮"])
            show_toast("助力已识别", "✅ 已点击助力按钮")
            time.sleep(1)
            continue
        #print(f"[DEBUG] is_expedition_enabled: {is_expedition_enabled()}, is_expedition_running: {is_expedition_running()}")

        if is_expedition_enabled() and has_moyu_icon(screen) and not is_expedition_running():
            print("[助力] 检测到摸鱼队伍图标，准备请求主控切换远征流程")
            show_toast("⚔️ 摸鱼部队检测", "即将进入远征流程")
            gs.current_task_status_callback("远征中 🚀")
            if pause_callback:
                pause_callback()
            stop_collect()
            assist_running.clear()
            time.sleep(2.0)
            gs.expedition_pending_flag = True  # ✅ 只设置 pending_flag → 交给主控 main_loop 处理切换
            gs.running_expedition = True
            return

        for _ in range(8):
            if not assist_running.is_set():
                break
            time.sleep(1)

def collect_loop(server_socket):
    print("🟢 采集线程启动")
    while collect_running.is_set():
        if pause_event.is_set() or gs.expedition_pause_event.is_set():
            time.sleep(0.5)
            continue
        for label in selected_points:
            if (not collect_running.is_set() or 
                pause_event.is_set() or 
                gs.expedition_pause_event.is_set()):
                break
            if label in COLLECT_POINTS:
                coordinate = COLLECT_POINTS[label]
                server_socket.tap(*coordinate, delay=0.01)
                time.sleep(0.175)
        time.sleep(0.01)

def start_parallel_collect(server_socket, point_list):
    collect_running.set()
    for label in point_list:
        if label not in COLLECT_POINTS:
            continue
        individual_socket = TouchServerSocket(host="127.0.0.1", port=6100)
        individual_socket.connect()
        def click_loop(lbl=label, sock=individual_socket):
            while collect_running.is_set():
                sock.tap(*COLLECT_POINTS[lbl], delay=0.01)
                time.sleep(0.15)
        threading.Thread(target=click_loop, daemon=True).start()

def start_global_collect(server_socket):
    collect_running.set()
    def loop():
        coord = COLLECT_POINTS["食物"]
        while collect_running.is_set():
            server_socket.tap(*coord, delay=0.01)
            time.sleep(0.15)
    threading.Thread(target=loop, daemon=True).start()

def start_collect(server_socket, points):
    set_collect_points(points)
    collect_running.clear()  # ✅ 确保先 clear 一次（冗余清理，保证状态对）
    assist_running.clear()
    time.sleep(0.1)  # ✅ 等 100ms，确保老线程能退出
    collect_running.set()
    assist_running.set()
    threading.Thread(target=collect_loop, args=(server_socket,), daemon=True).start()
    threading.Thread(target=assist_loop, args=(server_socket,), daemon=True).start()
    print("✅ 采集与助力线程已启动")

def stop_collect():
    collect_running.clear()
    assist_running.clear()
