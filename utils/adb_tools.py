import socket
import time
import struct
from PIL import Image
import io
import numpy as np
from datetime import datetime
from utils.frame_listener import FrameListener

# === 日志控制 ===
DEBUG_MODE = False

def log(msg):
    if DEBUG_MODE:
        print(msg)

class TouchServerSocket:
    def __init__(self, host="127.0.0.1", port=6100):
        self.host = host
        self.port = port
        self.sock = None
        self.is_connected = False  # 新增标识连接状态的变量

    def connect(self):
        try:
            if self.sock is None:
                self.sock = socket.socket()
                self.sock.connect((self.host, self.port))
                self.is_connected = True
                log("✅ 成功连接到 TouchServer")
        except Exception as e:
            log(f"❌ 连接失败：{e}")
            self.is_connected = False

    def close(self):
        try:
            if self.is_connected and self.sock:
                self.sock.close()
                self.is_connected = False
                log("✅ 关闭 Socket 连接")
        except Exception as e:
            log(f"❌ 关闭连接失败：{e}")

    def send_command(self, cmd, timeout=0.1):
        try:
            if self.is_connected:
                self.sock.sendall(cmd.encode())
                self.sock.settimeout(timeout)
                resp = self.sock.recv(128).decode().strip()
                return resp
            else:
                log("❌ Socket 未连接")
                return None
        except socket.timeout:
            log(f"⚠️ 接收超时（指令：{cmd.strip()}）")
            return None
        except Exception as e:
            log(f"❌ 发送失败：{e}")
            return None

    def tap(self, x, y, delay=0.05):
        try:
            if not self.is_connected:
                self.connect()
            cmd = f"tap {x} {y}\n"
            start = time.time()
            send_ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            resp = self.send_command(cmd)
            end = time.time()
            cost_ms = int((end - start) * 1000)
            if resp:
                log(f"{send_ts} | tap({x},{y}) → {resp} ✅ 延迟: {cost_ms}ms")
            time.sleep(delay)
        except Exception as e:
            log(f"❌ 点击失败：{e}")

    def swipe(self, x1, y1, x2, y2, duration=500):
        if not self.is_connected:
            self.connect()
        duration = int(duration)
        cmd = f"swipe {x1} {y1} {x2} {y2} {duration}\n"
        resp = self.send_command(cmd)
        if resp:
            log(f"发送: {cmd.strip()} → 返回: {resp}")
        time.sleep(duration / 1000.0)

class ScreenshotSocket:
    def __init__(self, host="127.0.0.1", port=6101):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        try:
            self.sock = socket.socket()
            self.sock.connect((self.host, self.port))
            log(f"✅ 成功连接到 {self.host}:{self.port}")
        except Exception as e:
            log(f"❌ ScreenshotSocket 连接失败: {e}")
            self.sock = None

    def _recvall(self, length):
        data = b""
        while len(data) < length:
            try:
                packet = self.sock.recv(length - len(data))
                if not packet:
                    return None
                data += packet
            except Exception as e:
                log(f"❌ 接收异常: {e}")
                self.sock = None
                self.sock.close()
                return None
        return data

    def request_screenshot(self):
        if self.sock is None:
            self.connect()
        if self.sock is None:
            return None

        try:
            self.sock.sendall(b"screenshot\n")
            raw_len = self._recvall(4)
            if not raw_len:
                log("❌ 未收到图像长度信息")
                return None

            total_length = int.from_bytes(raw_len, byteorder="big")
            log(f"✅ 收到图像长度信息: {total_length} 字节")

            if total_length < 1024 or total_length > 10 * 1024 * 1024:
                log(f"⚠️ 图像数据长度异常: {total_length}")
                return None

            data = self._recvall(total_length)
            if data is None or len(data) != total_length:
                log(f"❌ 图像接收不完整，期望 {total_length} 字节，实际 {len(data) if data else 0}")
                return None

            if len(data) > 5 * 1024 * 1024:
                log(f"❌ 数据长度异常，图像数据过大，长度：{len(data)}")
                return None

            log(f"✅ 完整图像接收成功: {len(data)} 字节")
            return data

        except Exception as e:
            log(f"❌ 截图接收失败: {e}")
            return None
        finally:
            if self.sock:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)   
                except Exception:
                    pass
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None

class ControlSocket:
    def __init__(self, host="127.0.0.1", port=6102):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        try:
            if self.sock is None:
                self.sock = socket.socket()
                self.sock.connect((self.host, self.port))
                log("✅ 成功连接到 ControlSocket")
        except Exception as e:
            log(f"❌ ControlSocket 连接失败: {e}")
            self.sock = None

    def close(self):
        try:
            if self.sock:
                self.sock.close()
                log("✅ 关闭 ControlSocket 连接")
        except Exception as e:
            log(f"❌ ControlSocket 关闭失败: {e}")
        finally:
            self.sock = None

    def send_command(self, cmd):
        if self.sock is None:
            self.connect()
        if self.sock is None:
            return None
        self.sock.sendall(cmd.encode())
        log(f"📡 ControlSocket 已发送: {cmd.strip()}")
        try:
            response = self.sock.recv(128).decode(errors="ignore").strip()
            log(f"📡 ControlSocket 收到响应: {response}")
            return response
        except Exception as e:
            log(f"[ControlSocket] ❌ 等待响应失败: {e}")
            return None

    def switch_to_video(self):
        resp = self.send_command("switch_to_video\n")
        log(f"📡 切换到视频流响应: {resp}")

    def switch_to_screenshot(self):
        resp = self.send_command("switch_to_screenshot\n")
        log(f"📡 切换到截图模式响应: {resp}")

    def query_status(self):
        return self.send_command("query_status\n")

_rift_listener = None
_rift_listener_enabled = True  # 初始默认关闭

def enable_rift_listener():
    global _rift_listener_enabled
    _rift_listener_enabled = True
    print("✅ 裂隙模块已启用")

def disable_rift_listener():
    global _rift_listener_enabled
    _rift_listener_enabled = False
    print("🚫 裂隙模块已禁用")

def get_rift_stream_listener():
    global _rift_listener
    if not _rift_listener_enabled:
        print("⚠️ get_rift_stream_listener 调用被屏蔽（未启用裂隙模块）")
        return None
    if _rift_listener is None:
        _rift_listener = FrameListener(host="127.0.0.1", port=6101)
    if not _rift_listener.running:
        _rift_listener.start()
    return _rift_listener
