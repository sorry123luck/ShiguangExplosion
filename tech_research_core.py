import re
import cv2
import time
import numpy as np
import pytesseract
import threading
import easyocr
import torch 
import global_state as gs
from utils.toast_notify import show_toast
from utils.adb_tools import ScreenshotSocket
from position_config import RESEARCH_POINTS
from tech_timer_manager import (
    set_research_timer, set_accelerate_timer,
    start_timer_thread, research_time_remaining, accelerate_cd_remaining
)

_pause_callback = None


def register_main_callbacks(pause_func):
    global _pause_callback
    _pause_callback = pause_func

# 状态变量
research_running = False
server_socket = None
research_ready_event = threading.Event()
has_requested_help = False

# 模板路径
IMG_DONE_PATH = "icons/KJ-YJWC.png"
IMG_ACCEL_TRUE_PATH = "icons/KJ-JSSJ-T.png"
IMG_ACCEL_FALSE_PATH = "icons/YJ-JSSJ-F.png"

try:
    gpu_available = torch.cuda.is_available()
except Exception:
    gpu_available = False

# 如果 CPU 版，强制设置 False，防止版本号里出现 +cpu 误判
if "+cpu" in torch.__version__:
    gpu_available = False

print(f"🚀 EasyOCR 初始化，GPU 可用: {gpu_available}")
reader = easyocr.Reader(['ch_sim'], gpu=gpu_available)

# === 工具函数 ===
def get_screenshot():
    sock = ScreenshotSocket("127.0.0.1", 6101)
    data = sock.request_screenshot()
    if not data:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

def safe_get_screenshot(retries=3, delay=1.0):
    for i in range(retries):
        img = get_screenshot()
        if img is not None:
            if i == 0:
                # 只保存第一次成功的截图，防止多次覆盖
                #cv2.imwrite("tech_current_screen.png", img)
                #print("✅ 已保存科技界面截图 tech_current_screen.png")
                pass
            return img
        else:
            print(f"⚠️ 第 {i + 1} 次截图失败，等待 {delay}s 重试...")
            time.sleep(delay)
    print("❌ 连续截图失败，返回 None")
    return None

def crop(img, region):
    x1, y1, x2, y2 = region
    return img[y1:y2, x1:x2]

def extract_time(region_img):
    text = pytesseract.image_to_string(region_img, lang='chi_sim')
    match = re.search(r"(\d{1,2}):(\d{1,2}):(\d{1,2})", text)
    if match:
        h, m, s = map(int, match.groups())
        return h * 3600 + m * 60 + s
    return None

def match_template(region_img, template_path):
    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    gray = cv2.cvtColor(region_img, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)
    return max_val > 0.8

def is_research_done(img):
    region = crop(img, RESEARCH_POINTS["研究完成提示识别区域"])
    return match_template(region, IMG_DONE_PATH)

def is_currently_researching(img):
    x1, y1, x2, y2 = RESEARCH_POINTS["研究中判断区域"]
    roi = img[y1:y2, x1:x2]
    cv2.imwrite("debug_research_roi.png", roi)

    # 1️⃣ 原图
    print("🔍 尝试原图识别研究状态...")
    results = reader.readtext(roi)
    print("🧪 OCR原始结果（原图）:", results)
    for _, text, conf in results:
        text_clean = text.replace(" ", "")
        if any(k in text_clean for k in ["研究", "研", "究"]) and conf > 0.08:
            print(f"📘 【研究状态】识别成功 (原图): {text}")
            return True

    # 2️⃣ variant9 降亮度
    variant9 = cv2.convertScaleAbs(roi, alpha=0.5, beta=0)
    cv2.imwrite("research_current_variant9.png", variant9)
    results = reader.readtext(variant9)
    print("🧪 OCR原始结果（variant9）:", results)
    for _, text, conf in results:
        text_clean = text.replace(" ", "")
        if any(k in text_clean for k in ["研究", "研", "究"]) and conf > 0.08:
            print(f"📘 【研究状态】识别成功 (variant9): {text}")
            return True

    # 3️⃣ equalizeHist + adaptiveThreshold
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    eq = cv2.equalizeHist(gray)
    enhanced = cv2.adaptiveThreshold(eq, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                     cv2.THRESH_BINARY, 11, 2)
    cv2.imwrite("research_current_enhanced.png", enhanced)
    results = reader.readtext(enhanced)
    print("🧪 OCR原始结果（增强）:", results)
    for _, text, conf in results:
        text_clean = text.replace(" ", "")
        if any(k in text_clean for k in ["研究", "研", "究"]) and conf > 0.08:
            print(f"📘 【研究状态】识别成功 (增强): {text}")
            return True

    print("❌ 最终三阶段均未识别出研究状态")
    return False

def is_accel_available(img):
    region = crop(img, RESEARCH_POINTS["加速按钮识别区域"])  # 保留彩色，不转灰度
    tpl_on = cv2.imread(IMG_ACCEL_TRUE_PATH)  # 彩色读图
    tpl_off = cv2.imread(IMG_ACCEL_FALSE_PATH)  # 彩色读图

    res_on = cv2.matchTemplate(region, tpl_on, cv2.TM_CCOEFF_NORMED)
    res_off = cv2.matchTemplate(region, tpl_off, cv2.TM_CCOEFF_NORMED)

    max_on = cv2.minMaxLoc(res_on)[1]
    max_off = cv2.minMaxLoc(res_off)[1]
    diff = max_on - max_off

    print(f"匹配结果 → 亮:{max_on:.3f} / 灰:{max_off:.3f} → 差值:{diff:.3f}")

    # 推荐加差值判断，避免亮灰分数接近时误判
    return diff > 0.01 and max_on > 0.75


def detect_ke_yan_fa_with_easyocr(image):
    region = RESEARCH_POINTS["可研发识别区域"] 
    x1, y1, x2, y2 = region
    roi = image[y1:y2, x1:x2]

    # --- 通用增强方案：用 equalizeHist + adaptiveThreshold ---
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    equalized = cv2.equalizeHist(gray)
    enhanced = cv2.adaptiveThreshold(equalized, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                     cv2.THRESH_BINARY, 11, 2)
    #cv2.imwrite("ke_yan_fa_enhanced.png", enhanced)

    # --- 第一次识别 ---
    print("🔍 正在用【通用增强方案】尝试识别 可研发 ...")
    results = reader.readtext(enhanced)

    best_match = None
    best_conf = 0
    for bbox, text, conf in results:
        print(f"[通用方案] 识别: {text} (conf={conf:.2f})")
        if "可研发" in text and conf > best_conf:
            best_conf = conf
            (bx1, by1), (bx2, by2) = bbox[0], bbox[2]
            x = int((bx1 + bx2) / 2) + x1
            y = int((by1 + by2) / 2) + y1
            best_match = (x, y)

    # --- 如果通用方案识别不到 → fallback 用方案9 ---
    if best_match is None:
        print("⚠️ 通用增强未识别到 可研发，切换到【备用9】再试 ...")
        variant9 = cv2.convertScaleAbs(roi, alpha=0.5, beta=0)
        #cv2.imwrite("ke_yan_fa_variant9.png", variant9)
        results = reader.readtext(variant9)

        for bbox, text, conf in results:
            print(f"[备用9] 识别: {text} (conf={conf:.2f})")
            if "可研发" in text and conf > best_conf:
                best_conf = conf
                (bx1, by1), (bx2, by2) = bbox[0], bbox[2]
                x = int((bx1 + bx2) / 2) + x1
                y = int((by1 + by2) / 2) + y1
                best_match = (x, y)

    # --- 返回结果 ---
    if best_match:
        print(f"✅ 【可研发】识别成功: conf={best_conf:.2f}, 坐标={best_match}")
        return best_match
    else:
        print("⚠️ 未识别到 可研发，使用默认坐标点击")
        return (537, 1408)

def try_click_accelerate():
    if _pause_callback: _pause_callback()
    print("⏳ 正在检查加速按钮状态，准备进入科技页面")
    server_socket.tap(*RESEARCH_POINTS["主页_技术按钮"])
    time.sleep(1.2)
    img = safe_get_screenshot()
    if img is None:
        print("❌ 获取截图失败，跳过此次加速检查")
        return
    if is_accel_available(img):
        print("⚡ 加速按钮亮起，点击执行")
        server_socket.tap(*RESEARCH_POINTS["加速按钮"])
        time.sleep(0.8)
        server_socket.tap(*RESEARCH_POINTS["免费减少按钮"])
        set_accelerate_timer(7199, callback=try_click_accelerate)
        if research_time_remaining and research_time_remaining > 1800:
            set_research_timer(research_time_remaining - 1800, callback=lambda: initialize_research_state(server_socket))
        else:
            set_research_timer(0, callback=lambda: initialize_research_state(server_socket))
    else:
        cd = extract_time(crop(img, RESEARCH_POINTS["加速CD时间区域"]))
        if cd:
            set_accelerate_timer(cd, callback=try_click_accelerate)
        else:
            set_accelerate_timer(60, callback=try_click_accelerate)

def initialize_research_state(socket):
    if _pause_callback: _pause_callback()
    global research_running, server_socket, has_requested_help
    server_socket = socket
    research_ready_event.clear()
    has_requested_help = False
    start_timer_thread()

    server_socket.tap(*RESEARCH_POINTS["主页_技术按钮"])
    time.sleep(4)
    img = safe_get_screenshot()
    if img is None:
        print("❌ 无法截图，终止研究流程")
        research_ready_event.set()
        return

    if is_research_done(img):
        print("✅ 检测到研究完成图标，进入新研究流程")
        server_socket.tap(*RESEARCH_POINTS["关闭研究完成页面"])
        time.sleep(0.6)
        server_socket.tap(*detect_ke_yan_fa_with_easyocr(img))
        time.sleep(0.5)
        server_socket.tap(*RESEARCH_POINTS["科技研究按钮"])
        time.sleep(0.8)
        if not has_requested_help:
            server_socket.tap(*RESEARCH_POINTS["联盟求助按钮"])
            has_requested_help = True
            time.sleep(0.5)
    else:
        if is_currently_researching(img):
            print("📘 当前处于研究中状态")
            seconds = extract_time(crop(img, RESEARCH_POINTS["研究剩余时间区域"]))
            if seconds:
                print(f"⏳ 研究剩余时间：{seconds}秒")
                set_research_timer(seconds, callback=lambda: initialize_research_state(server_socket))
            if is_accel_available(img):
                print("⚡ 加速按钮亮起，点击加速")
                server_socket.tap(*RESEARCH_POINTS["加速按钮"])
                time.sleep(0.5)
                server_socket.tap(*RESEARCH_POINTS["免费减少按钮"])
                time.sleep(1.5)
                img = safe_get_screenshot()
                seconds = extract_time(crop(img, RESEARCH_POINTS["研究剩余时间区域"]))
                if seconds:
                    set_research_timer(seconds, callback=lambda: initialize_research_state(server_socket))
                set_accelerate_timer(7199, callback=try_click_accelerate)   
            cd = extract_time(crop(img, RESEARCH_POINTS["加速CD时间区域"]))
            if cd:
                set_accelerate_timer(cd, callback=try_click_accelerate)
            else:
                set_accelerate_timer(60, callback=try_click_accelerate)
        else:
            print("📌 当前未检测到研究状态，默认进入新研究流程")
            server_socket.tap(*RESEARCH_POINTS["关闭研究完成页面"])
            time.sleep(0.5)
            server_socket.tap(*detect_ke_yan_fa_with_easyocr(img))
            time.sleep(0.5)
            server_socket.tap(*RESEARCH_POINTS["科技研究按钮"])
            time.sleep(0.5)
            if not has_requested_help:
                server_socket.tap(*RESEARCH_POINTS["联盟求助按钮"])
                has_requested_help = True
                time.sleep(0.5)

    for i in range(3):
        print(f"🔁 第 {i + 1} 次尝试返回主页...")
        server_socket.tap(*RESEARCH_POINTS["关闭研究页面"])
        time.sleep(2.5)
        img = safe_get_screenshot()
        if img is not None:
            region = crop(img, RESEARCH_POINTS["研究主页判断区"])
            if not match_template(region, "icons/YJZY-JS.png"):
                print("✅ 科技图标已消失，成功返回主页")
                research_ready_event.set()
                break
        else:
            print("⏳ 仍在科技页面，继续尝试关闭")

    research_running = True

def stop_research_monitor():
    global research_running
    research_running = False
