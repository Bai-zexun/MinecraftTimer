import json
import os
import sys  # 新增导入 sys
import time
import hashlib
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime
import psutil
import requests
from requests.auth import HTTPBasicAuth

class MinecraftTimerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Minecraft 游玩时长统计")
        self.root.geometry("700x500")
        self.root.resizable(False, False)

        # ========== 修改 base_dir 获取方式（兼容 PyInstaller 打包） ==========
        if getattr(sys, 'frozen', False):
            # 打包后的 exe 路径
            self.base_dir = os.path.dirname(sys.executable)
        else:
            # 开发环境下的脚本路径
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        # =================================================================

        self.data_dir = os.path.join(self.base_dir, "data")
        self.config_dir = os.path.join(self.base_dir, "config")
        self.temp_dir = os.path.join(self.base_dir, "temp_sync")
        self.config_file = os.path.join(self.config_dir, "settings.json")
        self.upload_flag_file = os.path.join(self.config_dir, "upload_success.flag")

        for d in [self.data_dir, self.config_dir, self.temp_dir]:
            os.makedirs(d, exist_ok=True)

        self.config = self.load_config()

        self.local_data_file = os.path.join(self.data_dir, "mc_timer_data.json")
        self.temp_data_file = os.path.join(self.temp_dir, "mc_timer_data.json")
        self.current_data_file = self.local_data_file if not self.config.get("cloud_enabled", False) else self.temp_data_file

        # 初始化数据
        self.data = {
            "java": {"total_seconds": 0, "last_end_time": None},
            "bedrock": {"total_seconds": 0, "last_end_time": None}
        }

        # 云端就绪标记
        self.cloud_ready = False

        # 云端模式启动时仅下载数据
        if self.config.get("cloud_enabled", False):
            self.download_from_cloud()

        self.load_data()

        self.running = {"java": False, "bedrock": False}
        self.session_start = {"java": None, "bedrock": None}
        self.session_seconds = {"java": 0, "bedrock": 0}

        self.detect_interval = 3
        self.message_timers = {"java": None, "bedrock": None}

        self.create_ui()
        self.detect_processes(initial=True, force_refresh=True)
        self.root.after(self.detect_interval * 1000, self.detection_loop)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ==================== 配置管理 ====================
    def load_config(self):
        default_config = {
            "cloud_enabled": False,
            "webdav_url": "",
            "webdav_username": "",
            "webdav_password": "",
            "remote_path": "/mc_timer"
        }
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    default_config.update(cfg)
            except Exception as e:
                print(f"加载配置失败: {e}")
        return default_config

    def save_config(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存配置失败: {e}")

    # ==================== 数据哈希 ====================
    def data_hash(self, data=None):
        if data is None:
            data = self.data
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(json_str.encode('utf-8')).hexdigest()

    def save_upload_flag(self, hash_str):
        try:
            with open(self.upload_flag_file, 'w') as f:
                f.write(hash_str)
        except Exception as e:
            print(f"写入上传标记失败: {e}")

    def load_upload_flag(self):
        try:
            if os.path.exists(self.upload_flag_file):
                with open(self.upload_flag_file, 'r') as f:
                    return f.read().strip()
        except Exception as e:
            print(f"读取上传标记失败: {e}")
        return ""

    # ==================== 数据持久化 ====================
    def load_data(self):
        try:
            if os.path.exists(self.current_data_file):
                with open(self.current_data_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    if "java" in loaded:
                        self.data["java"]["total_seconds"] = loaded["java"].get("total_seconds", 0)
                        self.data["java"]["last_end_time"] = loaded["java"].get("last_end_time", None)
                    if "bedrock" in loaded:
                        self.data["bedrock"]["total_seconds"] = loaded["bedrock"].get("total_seconds", 0)
                        self.data["bedrock"]["last_end_time"] = loaded["bedrock"].get("last_end_time", None)
        except Exception as e:
            print(f"加载数据失败: {e}")

    def save_data(self):
        try:
            with open(self.current_data_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存数据失败: {e}")

    # ==================== 云端同步 ====================
    def download_from_cloud(self):
        base_url = self.config.get("webdav_url", "").rstrip('/')
        remote_dir = self.config.get("remote_path", "/mc_timer").rstrip('/')
        main_file = remote_dir + "/mc_timer_data.json"
        url = base_url + main_file
        auth = HTTPBasicAuth(self.config.get("webdav_username", ""), self.config.get("webdav_password", ""))
        try:
            resp = requests.get(url, auth=auth, timeout=10)
            if resp.status_code == 200:
                with open(self.temp_data_file, 'wb') as f:
                    f.write(resp.content)
                print("云端数据下载成功")
                self.cloud_ready = True
            elif resp.status_code == 404:
                print("云端无数据文件，使用空数据")
                if os.path.exists(self.temp_data_file):
                    os.remove(self.temp_data_file)
                self.cloud_ready = True
            else:
                print(f"下载失败，状态码: {resp.status_code}")
                self.cloud_ready = False
        except Exception as e:
            print(f"下载异常: {e}")
            self.cloud_ready = False

    def upload_to_cloud(self):
        if not self.cloud_ready:
            print("云端未就绪，禁止上传")
            return False

        base_url = self.config.get("webdav_url", "").rstrip('/')
        remote_dir = self.config.get("remote_path", "/mc_timer").rstrip('/')
        main_file = remote_dir + "/mc_timer_data.json"
        backup_file = remote_dir + "/mc_timer_data_backup.json"
        auth = HTTPBasicAuth(self.config.get("webdav_username", ""), self.config.get("webdav_password", ""))

        dir_url = base_url + remote_dir
        try:
            requests.request('MKCOL', dir_url, auth=auth, timeout=5)
        except:
            pass

        main_url = base_url + main_file
        backup_url = base_url + backup_file

        check_resp = requests.head(main_url, auth=auth, timeout=10)
        if check_resp.status_code == 200:
            move_resp = requests.request('MOVE', main_url, auth=auth,
                                         headers={'Destination': backup_url, 'Overwrite': 'T'},
                                         timeout=10)
            if move_resp.status_code not in (200, 201, 204):
                print(f"重命名主文件失败，状态码: {move_resp.status_code}，将继续直接上传主文件")
        elif check_resp.status_code == 404:
            print("云端无主文件，首次上传，不创建备份")
        else:
            print(f"检查主文件状态异常: {check_resp.status_code}，继续尝试上传")

        json_str = json.dumps(self.data, ensure_ascii=False, indent=4)
        try:
            resp = requests.put(main_url, data=json_str.encode('utf-8'), auth=auth, timeout=10)
            if resp.status_code in (200, 201, 204):
                print("上传成功")
                self.save_upload_flag(self.data_hash())
                if os.path.exists(self.temp_data_file):
                    os.remove(self.temp_data_file)
                return True
            else:
                print(f"上传失败，状态码: {resp.status_code}")
                return False
        except Exception as e:
            print(f"上传异常: {e}")
            return False

    # ==================== 自定义居中提示框 ====================
    def show_centered_message(self, title, message, msg_type="info", buttons=("确定",)):
        """在主窗口中央显示自定义模态提示框，返回点击的按钮文本"""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        if msg_type == "error":
            icon = "❌"
        elif msg_type == "warning":
            icon = "⚠️"
        else:
            icon = "ℹ️"

        frame = tk.Frame(win, padx=20, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        msg_frame = tk.Frame(frame)
        msg_frame.pack(pady=(0, 10))
        tk.Label(msg_frame, text=icon, font=("Segoe UI Emoji", 20)).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(msg_frame, text=message, font=("Microsoft YaHei UI", 11), justify=tk.LEFT,
                 wraplength=300).pack(side=tk.LEFT)

        result = tk.StringVar()
        btn_frame = tk.Frame(frame)
        btn_frame.pack(pady=(5, 0))
        for btn_text in buttons:
            btn = tk.Button(btn_frame, text=btn_text, font=("Microsoft YaHei UI", 10),
                            padx=15, pady=3, command=lambda t=btn_text: [result.set(t), win.destroy()])
            btn.pack(side=tk.LEFT, padx=5)

        win.update_idletasks()
        width = win.winfo_reqwidth()
        height = win.winfo_reqheight()
        self.center_window(win, width, height)

        self.root.wait_window(win)
        return result.get()

    # ==================== 进程检测 ====================
    def check_java_minecraft(self):
        java_keywords = ['minecraft', 'net.minecraft', 'launcher']
        netease_keywords = ['netease', '网易', 'neteasemc', 'mc.163']
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    name = proc.info['name'] or ''
                    cmdline = proc.info['cmdline'] or []
                    if name.lower() not in ('javaw.exe', 'java.exe'):
                        continue
                    cmd_str = ' '.join(cmdline).lower()
                    if any(kw in cmd_str for kw in netease_keywords):
                        continue
                    if any(kw in cmd_str for kw in java_keywords):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception as e:
            print(f"检测 Java 进程时出错: {e}")
        return False

    def check_bedrock_minecraft(self):
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    name = proc.info['name'] or ''
                    name_lower = name.lower()
                    if 'java' in name_lower:
                        continue
                    if 'launcher' in name_lower:
                        continue
                    if name_lower == 'minecraft.windows.exe' or 'minecraft' in name_lower:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception as e:
            print(f"检测基岩版进程时出错: {e}")
        return False

    def detect_processes(self, initial=False, force_refresh=False):
        java_running = self.check_java_minecraft()
        bedrock_running = self.check_bedrock_minecraft()
        changed = False

        if java_running and not self.running["java"]:
            self.running["java"] = True
            self.session_start["java"] = time.time()
            self.session_seconds["java"] = 0
            self.show_panel_message("java", "游戏已启动，开始计时")
            changed = True
        elif not java_running and self.running["java"]:
            self.running["java"] = False
            elapsed = time.time() - self.session_start["java"]
            self.session_seconds["java"] = elapsed
            self.data["java"]["total_seconds"] += elapsed
            self.data["java"]["last_end_time"] = time.time()
            self.session_start["java"] = None
            self.save_data()
            self.show_panel_message("java", f"游戏已退出，本次时长：{self.format_duration(elapsed)}")
            changed = True

        if bedrock_running and not self.running["bedrock"]:
            self.running["bedrock"] = True
            self.session_start["bedrock"] = time.time()
            self.session_seconds["bedrock"] = 0
            self.show_panel_message("bedrock", "游戏已启动，开始计时")
            changed = True
        elif not bedrock_running and self.running["bedrock"]:
            self.running["bedrock"] = False
            elapsed = time.time() - self.session_start["bedrock"]
            self.session_seconds["bedrock"] = elapsed
            self.data["bedrock"]["total_seconds"] += elapsed
            self.data["bedrock"]["last_end_time"] = time.time()
            self.session_start["bedrock"] = None
            self.save_data()
            self.show_panel_message("bedrock", f"游戏已退出，本次时长：{self.format_duration(elapsed)}")
            changed = True

        if changed or initial or force_refresh:
            self.update_ui_display()

    def detection_loop(self):
        self.detect_processes()
        self.root.after(self.detect_interval * 1000, self.detection_loop)

    def show_panel_message(self, version_key, message):
        labels = self.ui_labels[version_key]
        labels['message'].config(text=message)
        if self.message_timers[version_key]:
            self.root.after_cancel(self.message_timers[version_key])
        self.message_timers[version_key] = self.root.after(5000, lambda: labels['message'].config(text=""))

    # ==================== UI 创建 ====================
    def create_ui(self):
        self.title_font = tkfont.Font(family="Microsoft YaHei UI", size=16, weight="bold")
        self.label_font = tkfont.Font(family="Microsoft YaHei UI", size=11)
        self.value_font = tkfont.Font(family="Microsoft YaHei UI", size=12, weight="bold")
        self.big_value_font = tkfont.Font(family="Microsoft YaHei UI", size=20, weight="bold")
        self.status_font = tkfont.Font(family="Microsoft YaHei UI", size=12)
        self.message_font = tkfont.Font(family="Microsoft YaHei UI", size=10, slant="italic")

        main_frame = tk.Frame(self.root, padx=20, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        content_frame = tk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(content_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        separator = tk.Frame(content_frame, width=2, bg="#cccccc")
        separator.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        right_frame = tk.Frame(content_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.create_version_panel(left_frame, "java", "☕ Java 版")
        self.create_version_panel(right_frame, "bedrock", "⛏ 基岩版")

        # 底部按钮框架
        button_frame = tk.Frame(main_frame, pady=10)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)

        refresh_btn = tk.Button(button_frame, text="更新数据", font=self.label_font,
                                command=self.manual_refresh, padx=10, pady=5)
        refresh_btn.pack(side=tk.LEFT, padx=5)

        settings_btn = tk.Button(button_frame, text="⚙️ 设置", font=self.label_font,
                                 command=self.open_settings, padx=10, pady=5)
        settings_btn.pack(side=tk.RIGHT, padx=5)

    def create_version_panel(self, parent, version_key, title_text):
        title_label = tk.Label(parent, text=title_text, font=self.title_font, fg="#2c3e50")
        title_label.pack(pady=(0, 15), anchor='center')

        total_frame = tk.Frame(parent)
        total_frame.pack(fill=tk.X, pady=8)
        tk.Label(total_frame, text="总时长", font=self.label_font, fg="#555555").pack(anchor='center')
        total_value = tk.Label(total_frame, text="0 小时 0 分钟", font=self.big_value_font, fg="#2980b9")
        total_value.pack(anchor='center', pady=(2, 0))

        session_frame = tk.Frame(parent)
        session_frame.pack(fill=tk.X, pady=8)
        tk.Label(session_frame, text="本次游戏时长", font=self.label_font, fg="#555555").pack(anchor='center')
        session_value = tk.Label(session_frame, text="0 秒", font=self.value_font, fg="#27ae60")
        session_value.pack(anchor='center', pady=(2, 0))

        status_frame = tk.Frame(parent)
        status_frame.pack(fill=tk.X, pady=8)
        tk.Label(status_frame, text="运行状态", font=self.label_font, fg="#555555").pack(anchor='center')
        status_value = tk.Label(status_frame, text="未运行", font=self.status_font, fg="#7f8c8d")
        status_value.pack(anchor='center', pady=(2, 0))

        last_frame = tk.Frame(parent)
        last_frame.pack(fill=tk.X, pady=8)
        tk.Label(last_frame, text="上次游戏", font=self.label_font, fg="#555555").pack(anchor='center')
        last_relative = tk.Label(last_frame, text="暂无记录", font=self.value_font, fg="#e67e22")
        last_relative.pack(anchor='center', pady=(2, 0))
        last_absolute = tk.Label(last_frame, text="", font=self.label_font, fg="#999999")
        last_absolute.pack(anchor='center', pady=(1, 0))

        message_label = tk.Label(parent, text="", font=self.message_font, fg="#8e44ad",
                                 wraplength=250, justify=tk.CENTER)
        message_label.pack(fill=tk.X, pady=(10, 0), anchor='center')

        if not hasattr(self, 'ui_labels'):
            self.ui_labels = {}
        self.ui_labels[version_key] = {
            'total': total_value,
            'session': session_value,
            'status': status_value,
            'last_relative': last_relative,
            'last_absolute': last_absolute,
            'message': message_label
        }

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.geometry("500x350")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        self.center_window(win, 500, 350)

        cloud_var = tk.BooleanVar(value=self.config.get("cloud_enabled", False))
        cloud_check = tk.Checkbutton(win, text="启用坚果云同步", variable=cloud_var, font=self.label_font)
        cloud_check.pack(anchor='w', padx=20, pady=10)

        url_frame = tk.Frame(win)
        url_frame.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(url_frame, text="WebDAV 地址:", font=self.label_font).pack(side=tk.LEFT)
        url_entry = tk.Entry(url_frame, width=40, font=self.label_font)
        url_entry.pack(side=tk.LEFT, padx=5)
        url_entry.insert(0, self.config.get("webdav_url", ""))

        user_frame = tk.Frame(win)
        user_frame.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(user_frame, text="坚果云邮箱:", font=self.label_font).pack(side=tk.LEFT)
        user_entry = tk.Entry(user_frame, width=40, font=self.label_font)
        user_entry.pack(side=tk.LEFT, padx=5)
        user_entry.insert(0, self.config.get("webdav_username", ""))

        pass_frame = tk.Frame(win)
        pass_frame.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(pass_frame, text="应用密码:", font=self.label_font).pack(side=tk.LEFT)
        pass_entry = tk.Entry(pass_frame, width=40, show="*", font=self.label_font)
        pass_entry.pack(side=tk.LEFT, padx=5)
        pass_entry.insert(0, self.config.get("webdav_password", ""))

        path_frame = tk.Frame(win)
        path_frame.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(path_frame, text="远程路径:", font=self.label_font).pack(side=tk.LEFT)
        path_entry = tk.Entry(path_frame, width=40, font=self.label_font)
        path_entry.pack(side=tk.LEFT, padx=5)
        path_entry.insert(0, self.config.get("remote_path", "/mc_timer"))

        upload_btn = tk.Button(win, text="立即上传", font=self.label_font,
                               command=self.manual_upload_from_settings, padx=20, pady=5)
        upload_btn.pack(pady=(15, 0))

        warning_label = tk.Label(win, text="⚠️ 请不要重复点击，避免备份被覆盖", 
                                 font=("Microsoft YaHei UI", 9), fg="red")
        warning_label.pack(pady=(5, 0))

        def save_settings():
            self.config["cloud_enabled"] = cloud_var.get()
            self.config["webdav_url"] = url_entry.get().strip()
            self.config["webdav_username"] = user_entry.get().strip()
            self.config["webdav_password"] = pass_entry.get().strip()
            self.config["remote_path"] = path_entry.get().strip()
            self.save_config()
            self.show_centered_message("成功", "设置已保存，重启程序生效", "info")
            win.destroy()

        save_btn = tk.Button(win, text="保存", command=save_settings, font=self.label_font,
                             padx=20, pady=5)
        save_btn.pack(pady=20)

    def center_window(self, win, width, height):
        self.root.update_idletasks()
        parent_x = self.root.winfo_x()
        parent_y = self.root.winfo_y()
        parent_width = self.root.winfo_width()
        parent_height = self.root.winfo_height()
        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        win.geometry(f"{width}x{height}+{x}+{y}")

    def manual_upload_from_settings(self):
        if not self.config.get("cloud_enabled", False):
            self.show_centered_message("提示", "未启用云端同步，无法上传", "warning")
            return
        if not self.cloud_ready:
            self.show_centered_message("警告", "云端数据未就绪，无法上传。\n请重启程序以连接云端。", "warning")
            return
        self.save_data()
        if self.upload_to_cloud():
            self.show_centered_message("成功", "数据已上传到坚果云", "info")
        else:
            self.show_centered_message("失败", "上传失败，请检查网络和配置", "error")

    def manual_refresh(self):
        self.detect_processes(force_refresh=True)

    def update_ui_display(self):
        for key in ("java", "bedrock"):
            labels = self.ui_labels[key]
            data = self.data[key]
            labels['total'].config(text=self.format_duration(data["total_seconds"]))
            if self.running[key]:
                labels['status'].config(text="● 运行中", fg="#27ae60")
                labels['session'].config(text="计时中...", fg="#27ae60")
            else:
                if self.session_seconds[key] > 0 and self.session_start[key] is None:
                    labels['session'].config(text=self.format_duration(self.session_seconds[key]))
                else:
                    labels['session'].config(text="0 秒")
                labels['status'].config(text="○ 未运行", fg="#7f8c8d")
            if data["last_end_time"]:
                elapsed_since = time.time() - data["last_end_time"]
                relative_str = self.format_relative_time(elapsed_since)
                dt = datetime.fromtimestamp(data["last_end_time"])
                absolute_str = dt.strftime("%Y-%m-%d")
                labels['last_relative'].config(text=relative_str, fg="#e67e22")
                labels['last_absolute'].config(text=absolute_str)
            else:
                labels['last_relative'].config(text="暂无记录", fg="#999999")
                labels['last_absolute'].config(text="")

    def format_duration(self, seconds):
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours} 小时 {minutes} 分钟 {secs} 秒"
        elif minutes > 0:
            return f"{minutes} 分钟 {secs} 秒"
        else:
            return f"{secs} 秒"

    def format_relative_time(self, seconds):
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds} 秒前"
        elif seconds < 3600:
            return f"{seconds // 60} 分钟前"
        elif seconds < 86400:
            return f"{seconds // 3600} 小时前"
        else:
            return f"{seconds // 86400} 天前"

    def on_close(self):
        # 处理运行中的计时
        for key in ("java", "bedrock"):
            if self.running[key] and self.session_start[key]:
                elapsed = time.time() - self.session_start[key]
                self.data[key]["total_seconds"] += elapsed
                self.data[key]["last_end_time"] = time.time()
                self.running[key] = False
                self.session_start[key] = None
        self.save_data()

        if self.config.get("cloud_enabled", False):
            if not self.cloud_ready:
                self.show_centered_message("警告", "云端数据未就绪，本次数据未上传。\n请重启程序以连接云端。", "warning")
                self.root.destroy()
                return
            if self.upload_to_cloud():
                self.show_centered_message("成功", "数据已上传到坚果云", "info")
                self.root.destroy()
            else:
                choice = self.show_centered_message(
                    "上传失败",
                    "退出时上传数据到坚果云失败，请检查网络和配置。\n点击“重试”重新上传，或“取消”强制退出（数据可能丢失）。",
                    "error",
                    buttons=("重试", "取消")
                )
                if choice == "重试":
                    if self.upload_to_cloud():
                        self.show_centered_message("成功", "数据已上传到坚果云", "info")
                    else:
                        self.show_centered_message("失败", "仍然上传失败，将强制退出。数据未上传。", "error")
                    self.root.destroy()
                else:
                    self.root.destroy()
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    app = MinecraftTimerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
