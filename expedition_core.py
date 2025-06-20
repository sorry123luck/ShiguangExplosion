import time
import cv2
import re
import numpy as np
import pytesseract
import threading
from utils.toast_notify import show_toast
from utils.adb_tools import TouchServerSocket, ScreenshotSocket
from position_config import EXPEDITION_POINTS, SCOUT_POINTS
import global_state as gs
from global_state import expedition_pause_event

_resume_collect_callback = None
_pause_all_callback = None

def register_main_callbacks(resume_collect_func, pause_all_func):
    global _resume_collect_callback, _pause_all_callback
    _resume_collect_callback = resume_collect_func
    _pause_all_callback = pause_all_func
    
def has_idle_troop(screen):
    region = EXPEDITION_POINTS["空闲部队识别区域"]
    tpl = cv2.imread("icons/YZ-LXZY-KXBD.png", 0)
    gray = cv2.cvtColor(screen[region[1]:region[3], region[0]:region[2]], cv2.COLOR_BGR2GRAY)
    return cv2.minMaxLoc(cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED))[1] >= 0.85


def set_expedition_enabled(value: bool):
    gs.expedition_enabled_flag = value

def check_expedition_paused():
    if gs.expedition_pause_event.is_set():
        print("⏸️ 检测到暂停信号，终止远征流程")
        return True
    return False
    
def is_expedition_enabled():
    return gs.expedition_enabled_flag

def is_expedition_running():
    return gs.running_expedition

def set_expedition_running(value: bool):
    gs.running_expedition = value

def set_expedition_flags(scout_enabled, reward_enabled):
    gs.scout_enabled_global = scout_enabled
    gs.reward_enabled_global = reward_enabled

def capture_screen():
    try:
        screenshot_socket = ScreenshotSocket("127.0.0.1", 6101)
        data = screenshot_socket.request_screenshot()
        if data:
            image = np.frombuffer(data, dtype=np.uint8)
            return cv2.imdecode(image, cv2.IMREAD_COLOR)
        return None
    except:
        return None

def match_template(screen, template, region, threshold=0.85, debug_name=None):
    x1, y1, x2, y2 = region
    img = screen[y1:y2, x1:x2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    tpl = cv2.imread(template, 0)
    res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
    score = cv2.minMaxLoc(res)[1]
    matched = score >= threshold

    # ✅ 不管是否匹配成功，只要传了 debug_name 就画图保存
    if debug_name:
        debug_img = screen.copy()
        color = (0, 255, 0) if matched else (0, 0, 255)
        label = f"{debug_name} {'✓' if matched else '✗'} ({score:.2f})"
        cv2.rectangle(debug_img, (x1, y1), (x2, y2), color, 2)
        text_y = y2 + 20
        cv2.putText(debug_img, label, (x1, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        cv2.imwrite(f"debug_area_{debug_name}_{int(time.time())}.png", debug_img)

    return matched


#def save_debug_match_area(img, region, name, matched=False, score=None):
    x1, y1, x2, y2 = region
    debug_img = img.copy()
    color = (0, 255, 0) if matched else (0, 0, 255)
    cv2.rectangle(debug_img, (x1, y1), (x2, y2), color, 2)

    label = f"{name} {'✓' if matched else '✗'}"
    if score is not None:
        label += f" ({score:.2f})"

    # 让文本不会越界出图
    text_y = y1 - 10 if y1 > 20 else y2 + 20
    cv2.putText(debug_img, label, (x1, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    timestamp = int(time.time())
    cv2.imwrite(f"debug_area_{name}_{timestamp}.png", debug_img)


def check_popup_and_close(screen, server_socket):
    popup_templates = {
        "YZ-SJWC.png": EXPEDITION_POINTS["事件完成识别区域"],
        "YZ-TFCG.png": EXPEDITION_POINTS["讨伐成功识别区域"],
        "YZ-CJCG.png": EXPEDITION_POINTS["采集成功识别区域"],
    }

    for name, region in popup_templates.items():
        template_path = f"icons/{name}"
        x1, y1, x2, y2 = region
        crop = screen[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        tpl = cv2.imread(template_path, 0)

        if tpl is None:
            print(f"❌ 模板加载失败: {template_path}")
            continue

        if gray.shape[0] < tpl.shape[0] or gray.shape[1] < tpl.shape[1]:
            print(f"❗ 匹配区域比模板还小，跳过: {name} ({gray.shape} < {tpl.shape})")
            continue

        res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        score = cv2.minMaxLoc(res)[1]
        matched = score >= 0.7

        # save_debug_match_area(screen, region, name, matched, score) 截图识别

        if matched:
            print(f"📌 检测到弹窗：{name}，点击关闭")
            server_socket.tap(*EXPEDITION_POINTS["事件完成确认关闭"])
            time.sleep(0.5)
            return True

    return False


def wait_for_expedition_page_ready(server_socket, timeout=8):
    main_page_region = EXPEDITION_POINTS["联盟领地"]
    close_button = EXPEDITION_POINTS["事件完成确认关闭"]

    popup_templates = {
        "YZ-SJWC.png": EXPEDITION_POINTS["事件完成识别区域"],
        "YZ-TFCG.png": EXPEDITION_POINTS["讨伐成功识别区域"],
        "YZ-GXHD.png": EXPEDITION_POINTS["恭喜获得识别区域"],
        "YZ-CJCG.png": EXPEDITION_POINTS["采集成功识别区域"],
    }

    start = time.time()
    while time.time() - start < timeout:
        img = capture_screen()
        if img is None:
            continue

        popup_detected = False

        # 1️⃣ 弹窗识别与关闭
        for name, region in popup_templates.items():
            tpl = cv2.imread(f"icons/{name}", 0)
            if tpl is None:
                continue
            x1, y1, x2, y2 = region
            crop = img[y1:y2, x1:x2]
            if crop.shape[0] < tpl.shape[0] or crop.shape[1] < tpl.shape[1]:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
            score = cv2.minMaxLoc(res)[1]
            matched = score >= 0.7
            # save_debug_match_area(img, region, name, matched, score) 截图识别

            if matched:
                print(f"📌 检测到弹窗：{name}，点击关闭")
                server_socket.tap(*close_button)
                time.sleep(1.2)
                popup_detected = True
                break  # ❗ 只关闭一个弹窗后立即重新截图，防止图像变化导致误识别

        # 2️⃣ 如果刚刚关闭了弹窗 → 下一轮识别（不要识别 LMLD）
        if popup_detected:
            continue

        # 3️⃣ 没有弹窗，才开始识别 LMLD
        if match_template(img, "icons/YZ-LMLD.png", main_page_region, threshold=0.85): #, debug_name="YZ-LMLD"可补充做截图识别
            print("✅ 成功识别远征页面（联盟领地图标）")
            return True

        time.sleep(0.5)

    print("❌ 超时未能识别远征页面")
    return False


def wait_for_lingdi_page(server_socket, timeout=5):
    template = "icons/YZ-LMLD.png"
    region = EXPEDITION_POINTS["联盟领地"]
    start = time.time()
    while time.time() - start < timeout:
        screen = capture_screen()
        if screen is None:
            continue
        if check_popup_and_close(screen, server_socket):
            time.sleep(0.5)
            continue
        if match_template(screen, template, region):
            return True
        time.sleep(0.8)
    return False

def handle_fixed_resource_claim(server_socket):
    server_socket.tap(*EXPEDITION_POINTS["领地图标"])
    time.sleep(1)
    server_socket.tap(*EXPEDITION_POINTS["领地-一键领取按钮"])
    time.sleep(0.5)
    server_socket.tap(*EXPEDITION_POINTS["领地-一键领取按钮"])
    time.sleep(0.5)
    server_socket.tap(*EXPEDITION_POINTS["关闭领地资源"])
    if check_expedition_paused():
        print("⏸️ 检测到暂停信号")
        return

def wait_for_event_page(timeout=5):
    """确认是否成功进入事件页面"""
    template = "icons/YZ-SJ-LDSJ.png"
    region = EXPEDITION_POINTS["领地事件识别区域"]  
    start = time.time()
    while time.time() - start < timeout:
        img = capture_screen()
        if img is not None:
            if match_template(img, template, region, threshold=0.85):
                return True
        time.sleep(0.6)
    return False

def parse_scout_energy(screen):
    x1, y1, x2, y2 = SCOUT_POINTS["体力值区域"]
    cropped = screen[y1:y2, x1:x2]
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    
    # 二值化处理，增强数字识别
    _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)

    # OCR 设置为数字模式，增强识别
    config = "--psm 7 -c tessedit_char_whitelist=0123456789/"
    #cv2.imwrite("scout_energy_debug.png", gray)

    text = pytesseract.image_to_string(binary, lang='eng', config=config)
    print(f"[侦察体力识别] OCR原始结果: {text.strip()}")

    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if match:
        current = int(match.group(1))
        total = int(match.group(2))
        print(f"[侦察体力识别] 当前体力: {current} / 最大体力: {total}")
        return current
    else:
        print("[侦察体力识别] 未能识别到体力格式")
        return 0


def perform_scouting(server_socket):
    max_attempts = 10
    for i in range(max_attempts):
        if check_expedition_paused():
            print("⏸️ 侦察流程中检测到暂停，终止侦察")
            return

        screen = capture_screen()
        if screen is None:
            print(f"[侦察] 第{i+1}次截图失败，跳过")
            continue

        check_popup_and_close(screen, server_socket)

        energy = parse_scout_energy(screen)
        if energy <= 0:
            print("🧃 体力耗尽，结束侦察流程")
            return

        print(f"[侦察] 执行第 {i+1} 次侦察点击（当前体力: {energy}）")
        server_socket.tap(*SCOUT_POINTS["侦察按钮"])
        time.sleep(0.8)  # 可根据动画调整等待时间


def find_unoccupied_resource_click_points(screen, dx=365, dy=-33):
    """基于图像模板匹配无人前往标志，计算点击点"""
    from position_config import EXPEDITION_POINTS

    x1, y1, x2, y2 = EXPEDITION_POINTS["联盟资源识别区"]
    qx1, qy1, qx2, qy2 = EXPEDITION_POINTS["前往按钮识别区"]
    region_crop = screen[y1:y2, x1:x2]

    tpl = cv2.imread("icons/YZ-LXZY-WRQW.png", 0)
    gray = cv2.cvtColor(region_crop, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)

    click_points = []
    while True:
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < 0.95:
            break
        cx = max_loc[0] + tpl.shape[1] // 2
        cy = max_loc[1] + tpl.shape[0] // 2
        abs_center = (cx + x1, cy + y1)
        click_pos = (abs_center[0] + dx, abs_center[1] + dy)

        if qx1 <= click_pos[0] <= qx2 and qy1 <= click_pos[1] <= qy2:
            click_points.append(click_pos)

        # 避免重复匹配
        cv2.rectangle(res, max_loc,
                      (max_loc[0] + tpl.shape[1], max_loc[1] + tpl.shape[0]),
                      -1, thickness=cv2.FILLED)
    return click_points

def wait_for_troop_page(timeout=5):
    tpl = cv2.imread("icons/YZ-LXZY-KXBD.png", 0)
    region = EXPEDITION_POINTS["空闲部队识别区域"]
    start = time.time()
    while time.time() - start < timeout:
        screen = capture_screen()
        if screen is not None:
            gray = cv2.cvtColor(screen[region[1]:region[3], region[0]:region[2]], cv2.COLOR_BGR2GRAY)
            if cv2.minMaxLoc(cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED))[1] >= 0.85:
                return True
        time.sleep(0.5)
    return False

def is_main_page(screen):
    try:
        region = EXPEDITION_POINTS["主页识别区"]  # (503, 29, 577, 88)
        cropped = screen[region[1]:region[3], region[0]:region[2]]
        tpl = cv2.imread("icons/ZY-FY.png", 0)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
        max_val = cv2.minMaxLoc(res)[1]
        print(f"🎯 主页“繁荣”匹配度: {max_val:.3f}")
        return max_val >= 0.95
    except Exception as e:
        print(f"⚠️ 主界面匹配出错: {e}")
        return False

def exit_expedition_page(server_socket):
    print("🚪 开始退出远征页面...")

    for i in range(3):
        print(f"🔁 第 {i + 1} 次尝试退出远征页面...")
        server_socket.tap(*EXPEDITION_POINTS["退出远征页面"])
        time.sleep(2.0)

        img = capture_screen()
        if img is not None:
            if is_main_page(img):
                print("✅ 成功识别主页，远征流程结束")

                # ✅ 正确时通知主控恢复采集
                print("📢 通知主控恢复采集（延迟2秒执行）")
                if _resume_collect_callback:
                    threading.Timer(2, _resume_collect_callback).start()
                return True
            else:
                print("⏳ 未识别为主页，继续尝试...")
        else:
            print("⚠️ 截图失败，跳过本次识别")

    print("❌ 多次尝试退出失败，未能识别主页")

    # ⚠️ 匹配失败不应该通知主控恢复采集！
    return False
def manual_trigger_expedition(server_socket, pause_event, callback=None):
    if is_expedition_running():
        print("⚠️ 已在执行远征流程，跳过")
        return
    # 模拟 pause_all_callback 再调用 run_expedition_once
    if callback:
        callback()
    threading.Thread(target=run_expedition_once, args=(server_socket,), daemon=True).start()


def run_expedition_once(server_socket):
    if _pause_all_callback:
        _pause_all_callback()
    if is_expedition_running():
        print("⚠️ 已在执行远征流程，跳过")
        return
    set_expedition_running(True)
    try:
        if check_expedition_paused(): return
        server_socket.tap(*EXPEDITION_POINTS["远征按钮"])
        time.sleep(2)
        
        if check_expedition_paused(): return
        if not wait_for_expedition_page_ready(server_socket):
            print("❌ 跳转远征页面失败，终止流程")
            return

        if gs.reward_enabled_global:
            if check_expedition_paused(): return
            handle_fixed_resource_claim(server_socket)
            print("⏳ 关闭领地资源后等待页面稳定...")
            time.sleep(0.8)
            if not wait_for_lingdi_page(server_socket):
                return

        if gs.scout_enabled_global:
            if check_expedition_paused(): return
            perform_scouting(server_socket)

        print("▶️ 准备开始远征任务处理流程（联盟资源采集）")
        time.sleep(1.6)

        if check_expedition_paused(): return
        for attempt in range(3):
            if check_expedition_paused(): return
            print(f"🔘 第 {attempt + 1} 次点击事件按钮")
            server_socket.tap(*EXPEDITION_POINTS["事件按钮"])
            time.sleep(1)
            if wait_for_event_page():
                print("✅ 成功进入事件页面")
                break
            else:
                print("⏳ 未进入事件页面，准备重试")
        else:
            print("❌ 多次点击事件按钮失败，终止远征流程")
            return

        if check_expedition_paused(): return
        server_socket.tap(*EXPEDITION_POINTS["页签_联盟资源"])
        time.sleep(0.8)

        max_swipe = 15
        swipe_count = 0
        while swipe_count < max_swipe:
            if check_expedition_paused(): return

            screen = capture_screen()
            if screen is None:
                break

            click_points = find_unoccupied_resource_click_points(screen)

            if not click_points:
                print(f"🔄 执行第{swipe_count}次翻页")
                server_socket.swipe(*EXPEDITION_POINTS["向上滑动找资源"][0], *EXPEDITION_POINTS["向上滑动找资源"][1])
                time.sleep(1.0)
                swipe_count += 1
                continue

            for idx, point in enumerate(click_points):
                if check_expedition_paused(): return
                print(f"🚀 点击第 {idx+1} 个无人前往资源: {point}")
                server_socket.tap(*point)
                time.sleep(1)

                if check_expedition_paused(): return
                server_socket.tap(*EXPEDITION_POINTS["事件详情_中心点"])
                time.sleep(0.5)

                if check_expedition_paused(): return
                server_socket.tap(*EXPEDITION_POINTS["联盟资源-采集按钮"])
                time.sleep(0.8)

                troop_screen = capture_screen()
                if troop_screen is None:
                    continue

                idle_tpl = cv2.imread("icons/YZ-LXZY-KXBD.png", 0)
                idle_region = EXPEDITION_POINTS["空闲部队识别区域"]
                troop_gray = cv2.cvtColor(troop_screen[idle_region[1]:idle_region[3], idle_region[0]:idle_region[2]], cv2.COLOR_BGR2GRAY)

                if cv2.minMaxLoc(cv2.matchTemplate(troop_gray, idle_tpl, cv2.TM_CCOEFF_NORMED))[1] >= 0.85:
                    if check_expedition_paused(): return
                    server_socket.tap(*EXPEDITION_POINTS["联盟资源-采集-出兵按钮"])
                    print(f"✅ 成功出兵")
                    time.sleep(1.5)

                    if check_expedition_paused(): return
                    server_socket.tap(*EXPEDITION_POINTS["返回事件页"])
                    time.sleep(0.8)
                    time.sleep(0.2)
                else:
                    print(f"❌ 无空闲部队，跳过此资源点")
                    server_socket.tap(*EXPEDITION_POINTS["返回事件页"])
                    time.sleep(0.5)
                    server_socket.tap(*EXPEDITION_POINTS["返回事件页"])
                    time.sleep(0.5)
                    server_socket.tap(*EXPEDITION_POINTS["关闭事件页面"])
                    time.sleep(0.5)
                    exit_expedition_page(server_socket)
                    return

            swipe_count += 1
            if swipe_count >= max_swipe:
                print("❌ 超过最大翻页次数，退出远征任务")
                server_socket.tap(*EXPEDITION_POINTS["关闭事件页面"])
                time.sleep(0.5)
                exit_expedition_page(server_socket)
                return

    finally:
        set_expedition_running(False)
