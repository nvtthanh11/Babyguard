import os
import re
import sys
import time
import json
import shutil
import subprocess
import threading

class TunnelManager:
    def __init__(self, config_path: str, port: int = 8080, on_tunnel_ready=None):
        self.config_path = config_path
        self.port = port
        self.on_tunnel_ready = on_tunnel_ready
        self.tunnel_process = None
        self.current_url = None
        self.running = False
        self.lock = threading.Lock()
        self.cloudflared_bin = self._find_cloudflared()

    def _find_cloudflared(self) -> str:
        candidates = [
            "/opt/homebrew/bin/cloudflared",
            "/usr/local/bin/cloudflared",
            shutil.which("cloudflared")
        ]
        for c in candidates:
            if c and os.path.exists(c) and os.access(c, os.X_OK):
                return c
        return None

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def stop(self, kill_process: bool = False):
        self.running = False
        if kill_process:
            with self.lock:
                if self.tunnel_process:
                    try:
                        self.tunnel_process.terminate()
                        self.tunnel_process.wait(timeout=3)
                    except Exception:
                        try:
                            self.tunnel_process.kill()
                        except Exception:
                            pass
                    self.tunnel_process = None
            self.current_url = None

    def restart(self) -> str:
        with self.lock:
            if self.tunnel_process:
                try:
                    self.tunnel_process.terminate()
                except Exception:
                    pass
                self.tunnel_process = None
        for _ in range(25):
            time.sleep(0.5)
            if self.current_url:
                return self.current_url
        return self.current_url

    def get_status(self) -> dict:
        return {
            "active": bool(self.current_url),
            "url": self.current_url,
            "type": "cloudflared" if self.cloudflared_bin else "none",
            "has_binary": bool(self.cloudflared_bin)
        }

    def _get_custom_url(self) -> str:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return str(data.get("remote_access_url", "")).strip()
            except Exception:
                pass
        return ""

    def _persist_url(self, url: str):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["remote_access_url"] = url
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"[TunnelManager] Lỗi lưu remote_access_url: {e}")

    def _is_url_reachable(self, url: str) -> bool:
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            return False
        import requests
        try:
            r = requests.get(f"{url}/api/tunnel-status", timeout=4)
            return r.status_code == 200
        except Exception:
            return False

    def _monitor_loop(self):
        while self.running:
            if not self.cloudflared_bin:
                print("[TunnelManager] ⚠️ Không tìm thấy cloudflared. Cần cài đặt để xem từ xa ngoài WiFi.")
                time.sleep(60)
                continue

            named_config = os.path.expanduser("~/.cloudflared/config.yml")
            if os.path.exists(named_config):
                cmd = [self.cloudflared_bin, "tunnel", "run", "babyguard"]
                print(f"[TunnelManager] 🌟 Đang kết nối Tên Miền Riêng babyguard.site: {' '.join(cmd)}")
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1
                    )
                    with self.lock:
                        self.tunnel_process = proc

                    self.current_url = "https://babyguard.site"
                    print(f"[TunnelManager] 🚀 TÊN MIỀN CỐ ĐỊNH CHÍNH THỨC: {self.current_url}")
                    self._persist_url(self.current_url)
                    if self.on_tunnel_ready:
                        try:
                            self.on_tunnel_ready(self.current_url)
                        except Exception as e:
                            print(f"[TunnelManager] Lỗi gọi on_tunnel_ready: {e}")

                    for line in proc.stdout:
                        if not self.running:
                            break
                        if "Registered tunnel connection" in line:
                            print(f"[TunnelManager] ✅ Cloudflare Tunnel đã kết nối thành công tới trạm mạng!")

                    proc.wait()
                except Exception as e:
                    print(f"[TunnelManager] Lỗi chạy Named Tunnel: {e}")

                with self.lock:
                    self.tunnel_process = None
                if self.running:
                    time.sleep(5)
                continue

            custom_url = self._get_custom_url()
            # 1. Kiểm tra nếu URL hiện tại trong config vẫn đang hoạt động tốt (tránh đổi link liên tục)
            if custom_url and self._is_url_reachable(custom_url):
                if self.current_url != custom_url:
                    self.current_url = custom_url
                    print(f"[TunnelManager] ♻️ Tái sử dụng link xem từ xa hiện có: {custom_url}")
                    if self.on_tunnel_ready:
                        try:
                            self.on_tunnel_ready(custom_url)
                        except Exception as e:
                            print(f"[TunnelManager] Lỗi gọi on_tunnel_ready: {e}")
                time.sleep(15)
                continue

            # 2. Nếu người dùng cấu hình domain riêng tĩnh (không phải trycloudflare)
            if custom_url and "trycloudflare.com" not in custom_url and ("http://" in custom_url or "https://" in custom_url):
                self.current_url = custom_url
                if self.on_tunnel_ready:
                    try:
                        self.on_tunnel_ready(custom_url)
                    except Exception:
                        pass
                time.sleep(30)
                continue

            try:
                cmd = [
                    self.cloudflared_bin, "tunnel",
                    "--url", f"http://127.0.0.1:{self.port}",
                    "--no-autoupdate"
                ]
                print(f"[TunnelManager] 🌐 Đang khởi tạo Cloudflare Tunnel: {' '.join(cmd)}")
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                with self.lock:
                    self.tunnel_process = proc

                found_url = False
                url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

                for line in proc.stdout:
                    if not self.running:
                        break
                    match = url_pattern.search(line)
                    if match and not found_url:
                        found_url = True
                        url = match.group(0).strip()
                        self.current_url = url
                        print(f"[TunnelManager] 🚀 Cloudflare Tunnel ĐÃ SẴN SÀNG: {url}")
                        self._persist_url(url)
                        if self.on_tunnel_ready:
                            try:
                                self.on_tunnel_ready(url)
                            except Exception as e:
                                print(f"[TunnelManager] Lỗi gọi on_tunnel_ready callback: {e}")

                    if "Unauthorized: Tunnel not found" in line:
                        print("[TunnelManager] ⚠️ Tunnel cũ hết hạn, đang tự động khởi tạo lại...")
                        break

                proc.wait()
            except Exception as e:
                print(f"[TunnelManager] Lỗi tiến trình tunnel: {e}")

            with self.lock:
                self.tunnel_process = None

            if self.running:
                time.sleep(5)
