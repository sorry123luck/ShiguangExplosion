# utils/toast_notify.py

# ✅ 日志输出模块，不再 import 主控，改用注册回调方式
main_log_callback = None
_log_callback = None

def log(msg):
    if _log_callback:
        _log_callback(msg)
    print(msg)  # 控制台打印也保留
    
def register_log_callback(log_func):
    global main_log_callback
    main_log_callback = log_func

def show_toast(title, message, duration=2.5):
    msg = f"[通知] {title} - {message}"
    print(msg)  # 保留打印，方便调试
    if main_log_callback:
        try:
            main_log_callback(msg)  # ✅ 仅调用注册的回调，不依赖 UI 框架
        except Exception as e:
            print(f"⚠️ 调用 main_log_callback 失败: {e}")
