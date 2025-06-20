# RiftCore V3.1 状态优先级版【完整版】
import time
import threading
import cv2
import datetime
import numpy as np
import pytesseract
import global_state as gs
from utils.toast_notify import show_toast
from utils.adb_tools import TouchServerSocket, get_rift_stream_listener
from position_config import RIFT_POINTS

rift_running = False
failure_count = 0
_resume_callback = None
_pause_callback = None
last_level_text = None
_frame_listener = None
current_phase = "state_wait_sweep"
failure_retry_limit = 30
rift_paused = False

# 注册主控回调
def register_main_callbacks(resume_func, pause_func):
    global _resume_callback, _pause_callback
    _resume_callback = resume_func
    _pause_callback = pause_func

# 获取视频帧
def capture_screen():
    if rift_paused:
        rift_log("⏸️ 当前处于暂停状态，跳过帧获取")
        time.sleep(0.1)
        return None
    frame = _frame_listener.get_latest_frame()
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    if frame is None or frame.shape[0] < 100 or frame.shape[1] < 100:
        print(f"[{ts}] ⚠️ 获取帧失败/尺寸异常")
        return None
    return frame.copy()

# 裂隙日志
def rift_log(msg):
    try:
        if gs.global_log_callback:
            gs.global_log_callback("[裂隙] " + msg)
    except Exception as e:
        print(f"[裂隙] 日志回调异常: {e}")
    print(msg)

# 主界面判断
def is_main_page(screen):
    from position_config import EXPEDITION_POINTS
    region = EXPEDITION_POINTS["主页识别区"]
    cropped = screen[region[1]:region[3], region[0]:region[2]]
    tpl = cv2.imread("icons/ZY-FY.png", 0)
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
    return cv2.minMaxLoc(res)[1] >= 0.95

# 启动裂隙模块
def start_rift_module(dummy_frame_listener, touch_socket, force=False):
    global rift_running, failure_count, current_phase, _frame_listener   # ✅ 这一行放开头就 OK，下面就别再 global 了！

    if rift_running and not force:
        print("⚠️ 裂隙模块已在运行")
        return
    if _frame_listener is not None:
        _frame_listener.stop()
        print("✅ 已关闭之前 FrameListener")

    if gs.rift_send_control_command_callback:
        gs.rift_send_control_command_callback("SWITCH_TO_VIDEO\n")
        rift_log("✅ 已发送切换到视频流指令，等待视频帧准备...")
    else:
        rift_log("⚠️ 未设置切换视频流指令回调，无法切换")
        return

    time.sleep(0.5)
    _frame_listener = get_rift_stream_listener()
    _frame_listener.start()
    print("✅ FrameListener 重新启动，连接 6101 等待帧")

    for i in range(10):
        if _frame_listener.is_ready():
            rift_log(f"🎬 FrameListener 首帧已准备就绪 (第 {i+1} 次轮询)")
            break
        rift_log(f"⏳ 等待 FrameListener 首帧准备中... ({i+1}/10)")
        time.sleep(0.2)
    else:
        rift_log("⚠️ FrameListener 首帧未就绪，继续后续流程")

    current_phase = "state_wait_sweep"   
    gs.rift_state = "opening"
    failure_count = 0
    rift_running = True
    threading.Thread(target=unified_state_loop, args=(touch_socket,), daemon=True).start()
    rift_log("✅ 裂隙模块已启动，开始监听视频流")

# === 停止裂隙模块 ===
def stop_rift_module(touch_socket=None):
    global rift_running, _frame_listener
    rift_running = False
    gs.rift_state = "idle"
    if _frame_listener is not None:
        try:
            _frame_listener.stop()
            print("✅ FrameListener 已停止")
        except Exception as e:
            print(f"⚠️ FrameListener 停止异常: {e}")
        _frame_listener = None

# === 恢复裂隙模块（继续挑战）===
def resume_rift(touch_socket):
    global rift_paused, current_phase
    if not rift_running:
        rift_log("⚠️ 裂隙模块未在运行，resume 无效")
        return
    rift_log("▶️ 收到继续挑战指令，恢复裂隙流程")
    rift_paused = False
    gs.rift_state = "running"
    

# 统一状态循环
def unified_state_loop(server_socket):
    global rift_running, failure_count, current_phase, rift_paused
    gs.rift_state = "opening"
    failure_count = 0

    while rift_running:
        if rift_paused:
            time.sleep(0.5)   # 挂起状态循环，等待手动继续
            continue
        screen = capture_screen()
        if screen is None:
            time.sleep(0.1)
            continue

        # 主页
        if is_main_page(screen):
            if current_phase == "state_returning_home":
                rift_log("💬 少年郎，战斗力不够哦！还需要继续努力啊。")
                show_toast("裂隙挑战提示", "少年郎，战斗力不够哦！还需要继续努力啊。")  # 可选，弹出 toast 提示

            rift_log("✅ 回到主页，退出裂隙模块")
            if gs.rift_send_control_command_callback:
                gs.rift_send_control_command_callback("SWITCH_TO_SCREENSHOT\n")
                rift_log("✅ 已发送切回截图模式指令")
            if _resume_callback:
                _resume_callback()
            gs.rift_state = "idle"
            rift_running = False
            return

        # 广告
        if match_template(screen, "icons/GG-LB.png", RIFT_POINTS["广告识别区域"]):
            rift_log("📢 检测到广告弹窗，关闭")
            server_socket.tap(*RIFT_POINTS["关闭广告"])
            time.sleep(1.2)
            continue

        # 恭喜获得
        if match_template(screen, "icons/SGLX-GXHD.png", RIFT_POINTS["恭喜获得识别区域"]):
            rift_log("🎉 识别到恭喜获得弹窗，点击关闭")
            server_socket.tap(*RIFT_POINTS["恭喜获得关闭坐标"])
            time.sleep(1.5)
            continue

        # 失败
        if match_template(screen, "icons/SGLX-ZDSB.png", RIFT_POINTS["失败识别区域"]):
            handle_failed_battle(server_socket)
            if failure_count >= failure_retry_limit:
                rift_log(f"❌ 同一关失败{failure_retry_limit}次，准备退出到主页，连续点击返回按钮确保生效")
                for i in range(2):
                    server_socket.tap(*RIFT_POINTS["返回主界面"])
                    rift_log(f"🔁 第 {i+1} 次点击返回主界面按钮")
                    time.sleep(1.2)
                current_phase = "state_returning_home"
            continue

        # 开始挑战
        if match_template(screen, "icons/SGLX-KSTZ.png", RIFT_POINTS["开始挑战识别区域"]):
            rift_log("🎯 识别到开始挑战按钮")
            server_socket.tap(*RIFT_POINTS["开始挑战"])
            current_phase = "state_in_battle_anim"
            time.sleep(1.5)
            continue

        # 扫荡
        if not rift_paused and match_template(screen, "icons/LXTZ-SD.png", RIFT_POINTS["扫荡识别区"]):
            rift_log("🔄 检测到扫荡，请手动操作后点击继续挑战")
            gs.rift_state = "wait_continue"
            rift_paused = True
            if _pause_callback:
                _pause_callback()
            time.sleep(0.5)
            continue

        # 战斗动画
        if current_phase == "state_in_battle_anim" and match_template(screen, "icons/SJLX-GKZDZ.png", RIFT_POINTS["关卡战斗中识别区"]):
            rift_log("🎬 进入战斗中动画阶段")
            current_phase = "state_skip_available"
            time.sleep(0.5)
            continue

        # 跳过
        if current_phase == "state_skip_available" and match_template(screen, "icons/SGLX-TG.png", RIFT_POINTS["跳过识别区域"]):
            rift_log("🎬 跳过按钮已出现，点击跳过")
            server_socket.tap(*RIFT_POINTS["跳过按钮"])
            time.sleep(1.2)
            continue
        # 继续战斗（判定通关成功）
        if match_template(screen, "icons/SJLX-ZDSL-JXZD.png", RIFT_POINTS["继续战斗识别区域"]):
            rift_log("✅ 识别到 '继续战斗' 按钮，判定为通关成功")

            # 层数 +1
            if last_level_text:
                import re
                match = re.search(r"第\s*(\d+)\s*层", last_level_text)
                if match:
                    current_level = int(match.group(1)) + 1
                    last_level_text = f"第{current_level}层"
                    failure_count = 0
                    rift_log(f"📈 判定已通关，更新层数为：{last_level_text}")
                    if gs.rift_level_callback:
                        gs.rift_level_callback(last_level_text, failure_count)

            server_socket.tap(*RIFT_POINTS["继续战斗按钮"])
            time.sleep(1.5)
            continue

# 失败处理
def handle_failed_battle(server_socket):
    global failure_count, last_level_text

    rift_log("❌ 检测到战斗失败弹窗")
    server_socket.tap(*RIFT_POINTS["失败后关闭"])
    time.sleep(1.5)

    # 广告判断
    for _ in range(10):
        screen = capture_screen()
        if screen is not None and match_template(screen, "icons/GG-LB.png", RIFT_POINTS["广告识别区域"]):
            rift_log("📢 检测到广告弹窗，准备关闭")
            server_socket.tap(*RIFT_POINTS["关闭广告"])
            time.sleep(1.5)
            break
        else:
            rift_log("✅ 未检测到广告弹窗，继续流程")
            break

    # 层数识别
    screen = capture_screen()
    if screen is not None:
        level_num = extract_rift_level(screen)
        if level_num:
            last_level_text = f"第{level_num}层"
            rift_log(f"📌 当前关卡层数识别结果：{last_level_text}")
        else:
            rift_log("⚠️ 未能识别当前关卡层数")

    # 更新失败次数
    failure_count += 1
    rift_log(f"⚠️ 当前关卡失败次数累计：{failure_count}/{failure_retry_limit}")

    # 上报主控层数 + 失败次数
    if gs.rift_level_callback and last_level_text:
        gs.rift_level_callback(last_level_text, failure_count)

# 层数OCR
def extract_rift_level(screen):
    region = RIFT_POINTS["关卡识别区域"]
    x1, y1, x2, y2 = region
    area = screen[y1:y2, x1:x2]
    gray = cv2.cvtColor(area, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)[1]
    text = pytesseract.image_to_string(gray, lang='chi_sim')
    rift_log(f"[OCR] 识别结果: {text}")

    import re
    match = re.search(r"第\s*(\d+)\s*层", text)
    if match:
        return int(match.group(1))
    return None

# 通用模板匹配
def match_template(screen, icon_path, region, threshold=0.85):
    x1, y1, x2, y2 = region
    area = screen[y1:y2, x1:x2]
    gray = cv2.cvtColor(area, cv2.COLOR_BGR2GRAY)
    tpl = cv2.imread(icon_path, 0)

    # 加保护 ✅
    if gray.shape[0] < tpl.shape[0] or gray.shape[1] < tpl.shape[1]:
        rift_log(f"⚠️ 区域尺寸 {gray.shape} 小于模板 {tpl.shape}，跳过匹配：{icon_path}")
        return False

    res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
    return cv2.minMaxLoc(res)[1] >= threshold

