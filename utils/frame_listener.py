# utils/frame_listener.py
import socket
import struct
import threading
import av
import numpy as np
import time
from datetime import datetime

class FrameListener:
    def __init__(self, host="127.0.0.1", port=6101):  # ✅ 注意这里是 6101
        self.host = host
        self.port = port
        self.sock = None
        self.decoder = av.codec.CodecContext.create("h264", "r")
        self.latest_frame = None
        self.running = False
        self._lock = threading.Lock()
        self.ready_event = threading.Event()  # ✅ 首帧 ready 标志

    def _recv_exact(self, length):
        data = b""
        while len(data) < length and self.running:
            try:
                packet = self.sock.recv(length - len(data))
                if not packet:
                    return None
                data += packet
            except Exception as e:
                print(f"[FrameListener] ❌ _recv_exact 异常: {e}")
                return None
        return data if len(data) == length else None

    def _loop(self):
        print(f"[FrameListener] 🚀 开始接收帧循环")
        while self.running:
            try:
                len_bytes = self._recv_exact(4)
                if not len_bytes:
                    if self.running:
                        print(f"[FrameListener] ❌ 未收到帧长度，退出循环")
                    break

                frame_len = struct.unpack(">I", len_bytes)[0]
                payload = self._recv_exact(frame_len)
                if not payload:
                    if self.running:
                        print(f"[FrameListener] ❌ 未收到完整帧，退出循环")
                    break

                packet = av.packet.Packet(payload)
                try:
                    frames = self.decoder.decode(packet)
                    for frame in frames:
                        img = frame.to_ndarray(format="bgr24")
                        with self._lock:
                            self.latest_frame = img
                        if not self.ready_event.is_set():
                            print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 🎬 首帧已解码，标记 ready")
                            self.ready_event.set()
                except Exception as e:  # 用 Exception，兼容所有 pyav 版本
                    print(f"[FrameListener] ⚠️ 解码异常（跳过此包）: {e}")
                    continue

            except Exception as e:
                print(f"[FrameListener] ⚠️ _loop 外层异常，退出: {e}")
                break
        self.running = False
        print(f"[FrameListener] ⛔️ 帧循环已退出")

    def start(self):
        if self.running:
            print("[FrameListener] ⚠️ 已在运行，先停止再重新启动")
            self.stop()
            time.sleep(0.05)  # 稍微短一点就好

        try:
            self.sock = socket.socket()
            self.sock.connect((self.host, self.port))
            self.running = True
            self.ready_event.clear()
            threading.Thread(target=self._loop, daemon=True).start()
            print("[FrameListener] ✅ 成功连接并启动帧监听线程")
        except Exception as e:
            print(f"[FrameListener] ❌ 无法连接推流端口: {e}")
            self.running = False

    def get_latest_frame(self):
        """外部调用：获取最近一帧图像（OpenCV 格式）"""
        with self._lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def stop(self):
        if not self.running:
            print("[FrameListener] ⚠️ stop 调用时已是非运行状态")
            return
        self.running = False
        try:
            if self.sock:
                self.sock.close()
                print("[FrameListener] ✅ 已关闭 socket 并停止监听")
        except:
            pass
        self.sock = None

    def is_ready(self):
        """是否首帧已解码"""
        return self.ready_event.is_set()
