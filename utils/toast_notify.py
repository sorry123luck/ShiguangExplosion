# utils/toast_notify.py

# 预留 log 回调
main_log_callback = None

def register_log_callback(log_func):
    global main_log_callback
    main_log_callback = log_func

def show_toast(title, message, duration=2.5):
    msg = f"[通知] {title} - {message}"
    print(msg)  # 保留打印，方便调试
    if main_log_callback:
        try:
            import main_controller
            # 判断 root 是否还在 mainloop 中
            if main_controller.root.winfo_exists():
                main_controller.root.after(0, lambda: main_log_callback(msg))
            else:
                print("⚠️ root 窗口不存在，跳过日志回调")
        except Exception as e:
            print(f"⚠️ 调用 main_log_callback 失败: {e}")
