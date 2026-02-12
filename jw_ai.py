import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import struct
import re
import json
import os
import sys
import threading

# jwai_core.py が C:\JWW にある場合にimport可能にする
sys.path.insert(0, r"C:\JWW")
try:
    from jwai_core import (
        load_config, save_config, CONFIG_FILE,
        parse_jwc_temp, elements_to_context, write_result_to_jwc,
        JWC_TEMP, SIGNAL_FILE, DONE_FILE, LOCK_FILE,
        create_lock, remove_lock, write_done, cleanup_signal_files,
        apply_transform, parse_ai_transform,
        parse_jww_full, build_jww_full_context,
    )
    CORE_AVAILABLE = True
except ImportError:
    CORE_AVAILABLE = False
    JWC_TEMP    = r"C:\JWW\JWC_TEMP.TXT"
    SIGNAL_FILE = r"C:\JWW\jwai_signal.json"
    DONE_FILE   = r"C:\JWW\jwai_done.json"
    LOCK_FILE   = r"C:\JWW\jwai_main.lock"
    CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".jwai_config.json")

    def load_config():
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"mode": "claude"}

    def save_config(config):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f)

    def create_lock():
        try:
            with open(LOCK_FILE, 'w') as f:
                f.write(str(os.getpid()))
        except Exception: pass

    def remove_lock():
        try:
            if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)
        except Exception: pass

    def write_done():
        import time
        try:
            with open(DONE_FILE, 'w') as f:
                json.dump({"done": True, "timestamp": time.time()}, f)
        except Exception: pass

    def cleanup_signal_files():
        for f in [SIGNAL_FILE, DONE_FILE]:
            try:
                if os.path.exists(f): os.remove(f)
            except Exception: pass

    def apply_transform(elements, transform): return {}, {}
    def parse_ai_transform(text): return None

import anthropic

# ========== JWWファイル解析 ==========

def read_cstring(data, pos):
    if pos >= len(data): return "", pos
    length = data[pos]; pos += 1
    if pos + length > len(data): return "", pos
    text_bytes = data[pos:pos+length]
    try: text = text_bytes.decode('cp932')
    except: text = text_bytes.decode('latin-1', errors='replace')
    return text, pos + length

def parse_jww(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    info = {"ファイル名": os.path.basename(filepath), "バージョン": 0,
            "メモ": "", "図面サイズ": "", "テキスト要素": [], "寸法値": []}
    header = data[:8].decode('ascii', errors='ignore')
    if not header.startswith('JwwData'):
        return None, "JWWファイルではありません"
    info["バージョン"] = struct.unpack_from('<I', data, 8)[0]
    memo, _ = read_cstring(data, 12)
    info["メモ"] = memo.strip()
    sizes = {0:'A0',1:'A1',2:'A2',3:'A3',4:'A4',8:'2A',9:'3A',10:'4A',11:'5A',12:'10m',13:'50m',14:'100m'}
    texts = []
    i = 0
    while i < len(data) - 2:
        length = data[i]
        if 2 <= length <= 100:
            chunk = data[i+1:i+1+length]
            try:
                text = chunk.decode('cp932')
                clean = ''.join(c for c in text if c.isprintable()).strip()
                if len(clean) >= 2:
                    has_jp = any('\u3040'<=c<='\u9fff' or '\uff00'<=c<='\uffef' for c in clean)
                    has_alnum = re.search(r'[A-Za-z0-9]{2,}', clean)
                    if has_jp:
                        texts.append(clean); i += 1+length; continue
                    elif has_alnum and len(clean)>=3 and not any(ord(c)<32 for c in clean):
                        skip = ['continuous','dashed','dotted','chain','undefined','black','red','green','blue','white','yellow','magenta','cyan','pink','brown','orange','lavender','gray','pen']
                        if not any(clean.lower().startswith(w) for w in skip):
                            texts.append(clean); i += 1+length; continue
                    elif re.search(r'^\d+\.?\d*$', clean):
                        info["寸法値"].append(clean); texts.append(clean); i += 1+length; continue
            except: pass
        i += 1
    seen = set()
    info["テキスト要素"] = [t for t in texts if t not in seen and not seen.add(t)][:100]
    memo_pos = 12
    _, after_memo = read_cstring(data, memo_pos)
    if after_memo + 4 <= len(data):
        zv = struct.unpack_from('<I', data, after_memo)[0]
        info["図面サイズ"] = sizes.get(zv, f"不明({zv})")
    return info, None

def build_jww_context(jww_info):
    return (
        f"あなたはJW_CADの図面作業をサポートするAIアシスタント「JW AI」です。\n"
        f"【図面情報】ファイル名:{jww_info['ファイル名']} 図面サイズ:{jww_info['図面サイズ']}\n"
        f"【テキスト】{', '.join(jww_info['テキスト要素'][:30])}\n"
        f"【寸法値】{', '.join(jww_info['寸法値'][:20])}\n"
        "日本語で回答してください。"
    )

# ========== JWC_TEMP監視 ==========

class JWCTempWatcher:
    POLL_MS = 1000
    def __init__(self, app):
        self.app = app
        # 起動時点の既存ファイルのmtimeで初期化 → 古いデータを読み込まない
        try:
            self.last_jwc_mtime = os.path.getmtime(JWC_TEMP) if os.path.exists(JWC_TEMP) else 0.0
        except:
            self.last_jwc_mtime = 0.0
        try:
            self.last_sig_mtime = os.path.getmtime(SIGNAL_FILE) if os.path.exists(SIGNAL_FILE) else 0.0
        except:
            self.last_sig_mtime = 0.0
        self.active = False

    def start(self):
        self.active = True
        self._poll()

    def stop(self):
        self.active = False

    def _poll(self):
        if not self.active: return
        if os.path.exists(JWC_TEMP):
            try:
                mtime = os.path.getmtime(JWC_TEMP)
                if mtime > self.last_jwc_mtime:
                    self.last_jwc_mtime = mtime
                    self._check_jwc()
            except: pass
        if os.path.exists(SIGNAL_FILE):
            try:
                smtime = os.path.getmtime(SIGNAL_FILE)
                if smtime > self.last_sig_mtime:
                    self.last_sig_mtime = smtime
                    self.app.on_signal_received()
            except: pass
        self.app.root.after(self.POLL_MS, self._poll)

    def _check_jwc(self):
        try:
            with open(JWC_TEMP, 'r', encoding='cp932', errors='replace') as f:
                first_line = f.readline().strip()
            if first_line == 'hq':
                self.app.on_jwc_updated()
        except: pass


# ========== メインアプリ ==========

class JWAIApp:
    def __init__(self, root):
        self.root = root
        self.root.title("JW AI - CAD作図アシスタント")
        self.root.geometry("1280x750")
        self.root.minsize(900, 600)
        self.root.configure(bg="#1a1a2e")

        self.config = load_config()
        self.jww_info = None
        self.chat_history = []
        self.system_prompt = ""
        self.gaihenkei_elements = []
        self.gaihenkei_raw_lines = []
        self.gaihenkei_context = ""
        self.gaihenkei_applied = False
        self.gaihenkei_last_ai_response = None
        self.gaihenkei_screenshot_b64 = None   # JW_CAD画面キャプチャ (base64)

        self.setup_styles()
        self.build_ui()

        create_lock()
        cleanup_signal_files()

        self.watcher = JWCTempWatcher(self)
        self.watcher.start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self.watcher.stop()
        remove_lock()
        cleanup_signal_files()
        self.root.destroy()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#1a1a2e')
        style.configure('TLabel', background='#1a1a2e', foreground='#e0e0e0', font=('Meiryo UI', 10))
        style.configure('TButton', background='#16213e', foreground='#00d4ff',
            font=('Meiryo UI', 10, 'bold'), borderwidth=1, relief='flat')
        style.map('TButton', background=[('active','#0f3460')], foreground=[('active','#ffffff')])
        style.configure('TNotebook', background='#1a1a2e', borderwidth=0)
        style.configure('TNotebook.Tab', background='#16213e', foreground='#888',
            font=('Meiryo UI', 10), padding=[12, 6])
        style.map('TNotebook.Tab', background=[('selected','#0f3460')], foreground=[('selected','#00d4ff')])
        style.configure('TSeparator', background='#333')
        style.configure('TPanedwindow', background='#1a1a2e')

    def build_ui(self):
        # ===== ヘッダー =====
        header = tk.Frame(self.root, bg="#0f3460", height=50)
        header.pack(fill='x')
        header.pack_propagate(False)

        tk.Label(header, text="JW AI", font=('Meiryo UI', 18, 'bold'),
            fg='#00d4ff', bg='#0f3460').pack(side='left', padx=15, pady=8)
        tk.Label(header, text="CAD作図AIアシスタント", font=('Meiryo UI', 10),
            fg='#888', bg='#0f3460').pack(side='left', padx=5)

        # 設定ボタン（ヘッダー右側）
        tk.Button(header, text="⚙ 設定", font=('Meiryo UI', 9),
            bg='#16213e', fg='#00d4ff', relief='flat', cursor='hand2',
            padx=12, pady=4, command=self.open_settings_dialog
        ).pack(side='right', padx=10, pady=10)

        # JWWファイル読み込みボタン（ヘッダー右側）
        tk.Button(header, text="📂 JWWを開く", font=('Meiryo UI', 9),
            bg='#16213e', fg='#00d4ff', relief='flat', cursor='hand2',
            padx=12, pady=4, command=self.load_jww
        ).pack(side='right', padx=5, pady=10)

        self.file_label = tk.Label(header, text="図面未読み込み",
            font=('Meiryo UI', 9), fg='#555', bg='#0f3460')
        self.file_label.pack(side='right', padx=10)

        # ===== 外部変形ステータスバー（ヘッダー下） =====
        self.status_bar = tk.Frame(self.root, bg="#2d1b0e", height=28)
        self.status_bar.pack(fill='x')
        self.status_bar.pack_propagate(False)

        self.status_label = tk.Label(self.status_bar,
            text="  待機中  JW_CADで範囲選択後、外部変形(JWAI.BAT)を実行してください",
            font=('Meiryo UI', 9), fg='#ff9944', bg='#2d1b0e', anchor='w')
        self.status_label.pack(side='left', fill='x', expand=True, padx=5)

        self.status_summary = tk.Label(self.status_bar, text="",
            font=('Meiryo UI', 9, 'bold'), fg='#00d4ff', bg='#2d1b0e')
        self.status_summary.pack(side='right', padx=10)

        # ===== メイン分割エリア（左:チャット / 右:外部変形） =====
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
            bg='#333', sashwidth=5, sashrelief='flat', bd=0)
        paned.pack(fill='both', expand=True)

        # --- 左パネル: チャット ---
        left_frame = tk.Frame(paned, bg='#1a1a2e')
        paned.add(left_frame, minsize=380)

        self._build_chat_panel(left_frame)

        # --- 右パネル: 外部変形 ---
        right_frame = tk.Frame(paned, bg='#0d1b2a')
        paned.add(right_frame, minsize=320)

        self._build_gaihenkei_panel(right_frame)

        # デフォルトの分割位置（起動時に左:右 = 60:40）
        self.root.update_idletasks()
        paned.sash_place(0, int(self.root.winfo_width() * 0.60), 0)

    # ===== 左パネル: チャット =====

    def _build_chat_panel(self, parent):
        tk.Label(parent, text="AIチャット",
            font=('Meiryo UI', 9, 'bold'), fg='#555', bg='#1a1a2e',
            anchor='w').pack(fill='x', padx=8, pady=(4, 0))

        self.chat_display = scrolledtext.ScrolledText(parent,
            font=('Meiryo UI', 10), bg='#0d1b2a', fg='#e0e0e0',
            insertbackground='#00d4ff', relief='flat', wrap=tk.WORD,
            state='disabled', padx=12, pady=8)
        self.chat_display.pack(fill='both', expand=True, padx=5, pady=(2, 3))

        self.chat_display.tag_configure('user', foreground='#00d4ff', font=('Meiryo UI', 10, 'bold'))
        self.chat_display.tag_configure('ai', foreground='#e0e0e0', font=('Meiryo UI', 10))
        self.chat_display.tag_configure('system', foreground='#666', font=('Meiryo UI', 9, 'italic'))
        self.chat_display.tag_configure('error', foreground='#ff6b6b')
        self.chat_display.tag_configure('success', foreground='#27ae60', font=('Meiryo UI', 9, 'bold'))

        input_frame = tk.Frame(parent, bg='#1a1a2e')
        input_frame.pack(fill='x', padx=5, pady=(0, 2))

        self.input_field = tk.Text(input_frame,
            font=('Meiryo UI', 11), bg='#ffffff', fg='#111111',
            insertbackground='#0066cc', relief='flat', height=2,
            padx=8, pady=6, wrap=tk.WORD)
        self.input_field.pack(side='left', fill='both', expand=True, padx=(0, 4))
        self.input_field.bind('<Return>', self.on_enter)
        self.input_field.bind('<Shift-Return>', lambda e: None)

        tk.Button(input_frame, text="送信▶",
            font=('Meiryo UI', 10, 'bold'), bg='#00d4ff', fg='#1a1a2e',
            relief='flat', width=5, cursor='hand2',
            command=self.send_message).pack(side='right', fill='y')

        self.append_chat("system",
            "JW AI へようこそ！\n"
            "右パネル: 外部変形データ表示・図面変更\n"
            "⚙設定でAPIキーを入力 → JWWを開く → AIと会話\n"
            "Shift+Enter: 改行  /  Enter: 送信")

    # ===== 右パネル: 外部変形 =====

    def _build_gaihenkei_panel(self, parent):
        tk.Label(parent, text="外部変形  /  選択図形",
            font=('Meiryo UI', 9, 'bold'), fg='#555', bg='#0d1b2a',
            anchor='w').pack(fill='x', padx=8, pady=(4, 0))

        # ===== 下部固定エリア（先にpackすることで確実に表示） =====

        # 図面反映ボタン（一番下）
        btn_frame = tk.Frame(parent, bg='#0d1b2a')
        btn_frame.pack(side='bottom', fill='x', padx=5, pady=(4, 6))

        self.gaihenkei_apply_btn = tk.Button(btn_frame,
            text="図面に反映",
            font=('Meiryo UI', 10, 'bold'),
            bg='#555', fg='#aaa', relief='flat',
            cursor='hand2', padx=15, pady=6,
            command=self.gaihenkei_apply)
        self.gaihenkei_apply_btn.pack(side='left', padx=(0, 6))

        self.gaihenkei_return_btn = tk.Button(btn_frame,
            text="JW_CADに返す",
            font=('Meiryo UI', 10, 'bold'),
            bg='#555', fg='#aaa', relief='flat',
            cursor='hand2', padx=15, pady=6,
            command=self.gaihenkei_return_to_jwcad)
        self.gaihenkei_return_btn.pack(side='left')

        # AI指示入力（ボタンの上）
        gi_frame = tk.Frame(parent, bg='#0d1b2a')
        gi_frame.pack(side='bottom', fill='x', padx=5, pady=(0, 2))

        self.gaihenkei_input = tk.Text(gi_frame,
            font=('Meiryo UI', 10), bg='#ffffff', fg='#111111',
            insertbackground='#0066cc', relief='flat', height=2,
            padx=8, pady=6, wrap=tk.WORD)
        self.gaihenkei_input.pack(side='left', fill='both', expand=True, padx=(0, 4))
        self.gaihenkei_input.bind('<Return>', self.on_gaihenkei_enter)
        self.gaihenkei_input.bind('<Shift-Return>', lambda e: None)

        tk.Button(gi_frame, text="相談▶",
            font=('Meiryo UI', 10, 'bold'), bg='#00d4ff', fg='#1a1a2e',
            relief='flat', width=5, cursor='hand2',
            command=self.gaihenkei_ask_ai).pack(side='right', fill='y')

        # AIへの指示ラベル（入力欄の上）
        tk.Label(parent, text="AIへの指示 (Enterで送信):",
            font=('Meiryo UI', 9), fg='#888', bg='#0d1b2a',
            anchor='w').pack(side='bottom', fill='x', padx=8, pady=(4, 1))

        # 区切り線
        tk.Frame(parent, bg='#333', height=1).pack(side='bottom', fill='x', padx=5)

        # ===== 上部可変エリア：選択図形の詳細表示（残り全スペースを使用） =====
        self.gaihenkei_detail = scrolledtext.ScrolledText(parent,
            font=('Meiryo UI', 8), bg='#060e1a', fg='#aaaaaa',
            relief='flat', wrap=tk.WORD, state='disabled',
            padx=8, pady=6)
        self.gaihenkei_detail.pack(fill='both', expand=True, padx=5, pady=(2, 3))

        # 右パネルに待機メッセージ表示
        self._update_gaihenkei_detail("JW_CADで範囲を選択し\n外部変形(JWAI.BAT)を実行してください。\n\n選択した図形データがここに表示されます。")

    def _update_gaihenkei_detail(self, text):
        self.gaihenkei_detail.configure(state='normal')
        self.gaihenkei_detail.delete('1.0', 'end')
        self.gaihenkei_detail.insert('end', text)
        self.gaihenkei_detail.configure(state='disabled')

    def _set_status(self, status, summary=""):
        if status == "waiting":
            self.status_bar.configure(bg='#2d1b0e')
            self.status_label.configure(
                text="  待機中  JW_CADで範囲選択後、外部変形(JWAI.BAT)を実行してください",
                fg='#ff9944', bg='#2d1b0e')
            self.status_summary.configure(text="", bg='#2d1b0e')
            self.gaihenkei_apply_btn.configure(state='disabled', bg='#555', fg='#aaa', text="図面に反映")
            self.gaihenkei_return_btn.configure(state='disabled', bg='#555', fg='#aaa')
        elif status == "data_ready":
            self.status_bar.configure(bg='#0d2e0d')
            self.status_label.configure(
                text="  選択データあり  右パネルの指示欄にAIへの指示を入力してください",
                fg='#27ae60', bg='#0d2e0d')
            self.status_summary.configure(text=summary, fg='#00d4ff', bg='#0d2e0d')
            self.gaihenkei_apply_btn.configure(state='normal', bg='#27ae60', fg='#fff', text="図面に反映")
            self.gaihenkei_return_btn.configure(state='normal', bg='#8e44ad', fg='#fff')
        elif status == "transform_ready":
            self.status_bar.configure(bg='#2e1a00')
            self.status_label.configure(
                text="  変換指示あり  「図面に反映」ボタンをクリックしてください",
                fg='#ff9944', bg='#2e1a00')
            self.status_summary.configure(text=summary, fg='#ff9944', bg='#2e1a00')
            self.gaihenkei_apply_btn.configure(state='normal', bg='#e74c3c', fg='#fff',
                text="▶ 図面に反映")
            self.gaihenkei_return_btn.configure(state='normal', bg='#8e44ad', fg='#fff')
        elif status == "done":
            self.status_bar.configure(bg='#0d1b2e')
            self.status_label.configure(
                text="  処理完了  JW_CADに反映されました  次の外部変形を待機中...",
                fg='#00d4ff', bg='#0d1b2e')
            self.status_summary.configure(text="", bg='#0d1b2e')
            self.gaihenkei_apply_btn.configure(state='disabled', bg='#555', fg='#aaa', text="図面に反映")
            self.gaihenkei_return_btn.configure(state='disabled', bg='#555', fg='#aaa')

    # ===== 外部変形データ受信 =====

    def on_jwc_updated(self):
        if not CORE_AVAILABLE: return
        elements, raw_lines, error = parse_jwc_temp(JWC_TEMP)
        if error: return

        self.gaihenkei_elements = elements
        self.gaihenkei_raw_lines = raw_lines
        self.gaihenkei_context = elements_to_context(elements, raw_lines)
        self.gaihenkei_applied = False
        self.gaihenkei_last_ai_response = None
        self.gaihenkei_screenshot_b64 = None  # 先にリセット

        line_count   = len([e for e in elements if e['type'] == 'line'])
        text_count   = len([e for e in elements if e['type'] == 'text'])
        circle_count = len([e for e in elements if e['type'] == 'circle'])
        summary = f"線:{line_count}本 文字:{text_count}件 円弧:{circle_count}件"

        self._update_gaihenkei_detail(self.gaihenkei_context)
        self._set_status("data_ready", summary)
        self.append_chat("system",
            f"外部変形データを受信しました ({summary})\n"
            "右パネルに指示を入力してください。")

        # JW_CAD画面キャプチャはスレッドで非同期実行（UIブロック防止）
        def _do_capture():
            try:
                from jwai_core import capture_jwcad_window
                b64, _ = capture_jwcad_window()
                self.gaihenkei_screenshot_b64 = b64
                if b64:
                    self.root.after(0, lambda: self.append_chat("system", "📷 図面画像キャプチャ完了"))
            except Exception:
                self.gaihenkei_screenshot_b64 = None
        threading.Thread(target=_do_capture, daemon=True).start()

    def on_signal_received(self):
        self.on_jwc_updated()

    # ===== 外部変形AI相談 =====

    def on_gaihenkei_enter(self, event):
        if not (event.state & 0x1):
            self.gaihenkei_ask_ai()
            return 'break'

    def gaihenkei_ask_ai(self):
        user_text = self.gaihenkei_input.get("1.0", "end-1c").strip()
        if not user_text:
            return

        config = load_config()
        mode = config.get('mode', 'claude')
        key_map = {'claude': 'claude_api_key', 'openai': 'openai_api_key', 'gemini': 'gemini_api_key'}
        api_key = config.get(key_map.get(mode, 'claude_api_key'), '').strip()

        if not api_key and mode != 'ollama':
            messagebox.showwarning("APIキー未設定", "⚙設定ボタンからAPIキーを入力してください")
            return

        self.gaihenkei_input.delete("1.0", "end")
        self.gaihenkei_last_ai_response = None

        self.append_chat("user", f"[外部変形] {user_text}")
        self.chat_history.append({"role": "user", "content": f"[外部変形] {user_text}"})

        # システムプロンプト
        base_system = (
            "あなたはJW_CAD（日本の建築CADソフト）と直接連携して動作するAIアシスタント「JW AI」です。\n"
            "あなたはJW_CADの図面を直接編集・操作する能力を持っています。\n"
            "ユーザーから「〇〇を変更して」と言われたら、手順を説明するのではなく、\n"
            "自分が実際に変更を実行します。回答の末尾に変換JSONを出力することで図面に反映されます。\n"
            "「JW_CADで〜してください」「〜ツールを選択して」などの手順説明は絶対にしないでください。\n"
            "座標はmm単位です。日本語で回答してください。\n\n"
            "=== 図形変換のルール ===\n\n"
            "図形の変換（反転・回転）を行う場合は、回答の末尾に必ず以下のJSON形式を含めてください。\n"
            "変換しない場合はJSONを含めないでください。\n\n"
            "【★重要★ 円弧の番号指定】\n"
            "図形データには [円弧0], [円弧1], [円弧2]... と番号が振られています。\n"
            "複数の円弧がある場合、どの円弧を変換するかを必ず circle_indices で指定してください。\n"
            "指定がない場合、すべての円弧が変換されてしまいます。\n\n"
            "【変換タイプ一覧】\n"
            "1. arc_flip_x（推奨：ドア勝手の左右変更）\n"
            "   円弧の中心・半径は動かさず、向き（角度）だけ左右反転します。\n"
            "   線（壁・ドア枠）は一切動きません。\n"
            '   → {"type": "arc_flip_x", "circle_indices": [0]}\n\n'
            "2. arc_flip_y（ドア勝手の上下変更）\n"
            "   円弧の向きを上下反転します。線は動きません。\n"
            '   → {"type": "arc_flip_y", "circle_indices": [0]}\n\n'
            "3. mirror_x（左右反転 - 線も円弧もすべて移動）\n"
            "   ※ドア勝手変更にはarc_flip_xを使ってください\n"
            '   → {"type": "mirror_x", "axis_x": <反転軸のX座標>}\n\n'
            "4. mirror_y（上下反転 - 線も円弧もすべて移動）\n"
            '   → {"type": "mirror_y", "axis_y": <反転軸のY座標>}\n\n'
            "5. rotate（回転）\n"
            '   → {"type": "rotate", "angle": <度数>, "cx": <中心X>, "cy": <中心Y>}\n\n'
            "【ドアの勝手（開く向き）を変える場合の正しい手順】\n"
            "JW_CADのドアは: ドア枠線（複数の線）+ 扇形（円弧 ci）で構成されます。\n"
            "手順:\n"
            "1. 図形データの【円弧データ（番号付き）】欄を確認する\n"
            "2. ドアの扇形に該当する円弧を特定する\n"
            "   - 始角と終角の差が約90°の円弧（←ドア扇形）\n"
            "   - 半径700〜1000mm程度（標準的なドア幅）\n"
            "   - 「←ドア扇形(90°)」と表示されている円弧\n"
            "3. その円弧番号だけを circle_indices に指定する\n"
            "4. arc_flip_x を使う（mirror_x は絶対に使わない）\n\n"
            "JSONの例（円弧0番だけを変換）：\n"
            "```json\n"
            '{"type": "arc_flip_x", "circle_indices": [0]}\n'
            "```\n\n"
        )
        if self.gaihenkei_screenshot_b64:
            base_system += (
                "【図面画像について】\n"
                "最初のメッセージにJW_CADの図面画像が添付されています。\n"
                "画像を見て、ユーザーが指示している図形（ドア・窓・部屋など）の位置を特定し、\n"
                "対応する円弧番号（circle_indices）を正確に選んでください。\n\n"
            )
        if self.system_prompt:
            base_system += "【図面全体情報（JWWファイル）】\n" + self.system_prompt + "\n\n"
        if self.gaihenkei_context:
            base_system += "【現在選択されている範囲の図形データ（これを変換対象とする）】\n" + self.gaihenkei_context

        self.root.config(cursor='wait')
        threading.Thread(
            target=self._call_api_gaihenkei,
            args=(user_text, api_key, mode, base_system, self.gaihenkei_screenshot_b64),
            daemon=True).start()

    def _call_api_gaihenkei(self, user_text, api_key, mode, system, screenshot_b64=None):
        try:
            if mode == 'claude':
                client = anthropic.Anthropic(api_key=api_key)
                # 画像あり: 最初のユーザーメッセージに画像を添付
                messages = []
                for i, msg in enumerate(self.chat_history):
                    if i == 0 and msg['role'] == 'user' and screenshot_b64:
                        # 最初のユーザーメッセージに図面画像を添付
                        messages.append({
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": screenshot_b64,
                                    }
                                },
                                {"type": "text", "text": msg['content']}
                            ]
                        })
                    else:
                        messages.append(msg)
                response = client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=2000,
                    system=system,
                    messages=messages)
                ai_response = response.content[0].text
            elif mode == 'openai':
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                # GPT-4o: 最初のユーザーメッセージに画像を添付
                msgs_raw = [{"role": "system", "content": system}] + self.chat_history
                msgs = []
                first_user_done = False
                for m in msgs_raw:
                    if m['role'] == 'user' and not first_user_done and screenshot_b64:
                        msgs.append({
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}"}},
                                {"type": "text", "text": m['content']}
                            ]
                        })
                        first_user_done = True
                    else:
                        msgs.append(m)
                response = client.chat.completions.create(
                    model="gpt-4o", max_tokens=2000, messages=msgs)
                ai_response = response.choices[0].message.content
            elif mode == 'gemini':
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-pro', system_instruction=system)
                history = [{'role': 'user' if m['role']=='user' else 'model', 'parts':[m['content']]}
                           for m in self.chat_history[:-1]]
                chat = model.start_chat(history=history)
                # Gemini: 最後のメッセージに画像を追加
                if screenshot_b64:
                    import base64, io
                    from PIL import Image as PilImage
                    img_data = base64.b64decode(screenshot_b64)
                    pil_img = PilImage.open(io.BytesIO(img_data))
                    ai_response = chat.send_message([pil_img, user_text]).text
                else:
                    ai_response = chat.send_message(user_text).text
            elif mode == 'ollama':
                import urllib.request, json as jlib
                payload = {"model": "qwen2.5:7b",
                    "messages": [{"role":"system","content":system}] + self.chat_history,
                    "stream": False}
                req = urllib.request.Request('http://localhost:11434/api/chat',
                    data=jlib.dumps(payload).encode(),
                    headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=60) as res:
                    ai_response = jlib.loads(res.read())['message']['content']
            else:
                ai_response = "不明なモードです"

            self.chat_history.append({"role": "assistant", "content": ai_response})
            self.gaihenkei_last_ai_response = ai_response
            self.root.after(0, lambda: self._on_gaihenkei_response(ai_response))
        except Exception as e:
            err = str(e)
            self.root.after(0, lambda: self._on_api_error(err))

    def _on_gaihenkei_response(self, response):
        self.append_chat("ai", response)
        self.root.config(cursor='')
        if CORE_AVAILABLE:
            transform = parse_ai_transform(response)
            if transform:
                ttype = transform.get('type','')
                # タイプ別の日本語説明
                type_labels = {
                    'arc_flip_x': '円弧の向きを左右反転（ドア勝手変更）',
                    'arc_flip_y': '円弧の向きを上下反転（ドア勝手変更）',
                    'mirror_x':   '全体を左右反転',
                    'mirror_y':   '全体を上下反転',
                    'rotate':     f"回転 {transform.get('angle',0)}°",
                }
                label = type_labels.get(ttype, ttype)
                self._set_status("transform_ready", f"変換準備完了: {label}")
                self.append_chat("success",
                    f"✅ 変換指示を検出しました\n"
                    f"変換内容: {label}\n"
                    "「▶ 図面に反映」ボタンをクリックしてください。")

    def gaihenkei_apply(self):
        if not self.gaihenkei_elements:
            messagebox.showinfo("データなし", "外部変形データがありません")
            return
        if not CORE_AVAILABLE:
            messagebox.showerror("エラー", "jwai_core.py が見つかりません")
            return

        transform = None
        if self.gaihenkei_last_ai_response:
            transform = parse_ai_transform(self.gaihenkei_last_ai_response)

        if transform:
            ttype = transform.get('type', '')
            type_labels = {
                'arc_flip_x': '円弧の向きを左右反転',
                'arc_flip_y': '円弧の向きを上下反転',
                'mirror_x':   '全体を左右反転',
                'mirror_y':   '全体を上下反転',
                'rotate':     f"回転 {transform.get('angle',0)}°",
            }
            label = type_labels.get(ttype, ttype)
            try:
                mod_lines, mod_circles = apply_transform(self.gaihenkei_elements, transform)
                ok, err = write_result_to_jwc(
                    self.gaihenkei_elements, mod_lines,
                    modified_circles_map=mod_circles)
                if ok:
                    self.gaihenkei_applied = True
                    self._set_status("data_ready", "反映済み - JW_CADに返してください")
                    self.gaihenkei_apply_btn.configure(bg='#555', fg='#aaa', text="図面に反映")
                    arc_count = len([e for e in self.gaihenkei_elements if e['type']=='circle'])
                    line_count = len([e for e in self.gaihenkei_elements if e['type']=='line'])
                    circle_indices = transform.get('circle_indices', None)
                    if ttype in ('arc_flip_x', 'arc_flip_y'):
                        if circle_indices is not None:
                            detail = (f"円弧[{','.join(str(i) for i in circle_indices)}]番のみ変換、"
                                      f"他{arc_count - len(circle_indices)}件と線{line_count}本は変更なし")
                        else:
                            detail = f"円弧{arc_count}件の向きを変換、線{line_count}本は変更なし"
                    else:
                        detail = f"円弧{arc_count}件・線{line_count}本を変換"
                    self.append_chat("success",
                        f"✅ {label}をJWC_TEMP.TXTに書き込みました。\n"
                        f"{detail}\n"
                        "「JW_CADに返す」をクリックで図面に反映されます。")
                else:
                    messagebox.showerror("エラー", f"書き込みに失敗:\n{err}")
            except Exception as e:
                messagebox.showerror("変換エラー", str(e))
        else:
            # 変換なし → hq除去のみ
            ok, err = write_result_to_jwc(self.gaihenkei_elements, {})
            if ok:
                self.gaihenkei_applied = True
                self.append_chat("system", "変更なしでJWC_TEMP.TXTを更新しました。\n「JW_CADに返す」で完了します。")
            else:
                messagebox.showerror("エラー", f"書き込みに失敗:\n{err}")

    def gaihenkei_return_to_jwcad(self):
        if not self.gaihenkei_applied:
            if not messagebox.askyesno("確認",
                "まだ「図面に反映」を押していません。\nそのままJW_CADに返しますか？（変更なし）"):
                return
        try:
            ok = write_done()
            if not ok:
                self.append_chat("error",
                    "❌ jwai_done.json の書き込みに失敗しました。\n"
                    "C:\\JWW フォルダへの書き込み権限を確認してください。")
                return
            self.append_chat("success", "✅ jwai_done.json を書き出しました。JW_CADに制御を返しています...")
        except Exception as e:
            self.append_chat("error", f"❌ write_done() 例外: {e}")
            return
        self._set_status("done")
        self._update_gaihenkei_detail("処理完了。次の外部変形を待機中...\n\nJW_CADで次の範囲を選択してください。")
        self.gaihenkei_elements = []
        self.gaihenkei_raw_lines = []
        self.gaihenkei_context = ""
        self.gaihenkei_applied = False
        self.gaihenkei_last_ai_response = None
        self.append_chat("system", "外部変形の処理完了。JW_CADに制御を返しました。")

    # ===== チャット =====

    def append_chat(self, role, text):
        self.chat_display.config(state='normal')
        if role == 'user':
            self.chat_display.insert('end', "\nあなた:\n", 'user')
            self.chat_display.insert('end', text + "\n", 'ai')
        elif role == 'ai':
            self.chat_display.insert('end', "\nJW AI:\n", 'user')
            self.chat_display.insert('end', text + "\n", 'ai')
        elif role == 'system':
            self.chat_display.insert('end', "\n" + text + "\n", 'system')
        elif role == 'error':
            self.chat_display.insert('end', "\n" + text + "\n", 'error')
        elif role == 'success':
            self.chat_display.insert('end', "\n" + text + "\n", 'success')
        self.chat_display.config(state='disabled')
        self.chat_display.see('end')

    def on_enter(self, event):
        if not event.state & 0x1:
            self.send_message()
            return 'break'

    def send_message(self):
        user_text = self.input_field.get("1.0", "end-1c").strip()
        if not user_text: return

        config = load_config()
        mode = config.get('mode', 'claude')
        key_map = {'claude': 'claude_api_key', 'openai': 'openai_api_key', 'gemini': 'gemini_api_key'}
        api_key = config.get(key_map.get(mode, 'claude_api_key'), '').strip()

        if not api_key and mode != 'ollama':
            messagebox.showwarning("APIキー未設定", "⚙設定からAPIキーを入力してください")
            return

        self.input_field.delete("1.0", "end")
        self.append_chat("user", user_text)
        self.chat_history.append({"role": "user", "content": user_text})
        self.root.config(cursor='wait')

        system = self.system_prompt if self.system_prompt else \
            "あなたはJW_CADの作図をサポートするAIアシスタントです。日本語で回答してください。"

        threading.Thread(target=self._call_api_generic,
            args=(user_text, api_key, mode, system), daemon=True).start()

    def _call_api_generic(self, user_text, api_key, mode, system):
        try:
            if mode == 'claude':
                client = anthropic.Anthropic(api_key=api_key)
                response = client.messages.create(
                    model="claude-sonnet-4-5-20250929", max_tokens=2000,
                    system=system, messages=self.chat_history)
                ai_response = response.content[0].text
            elif mode == 'openai':
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                response = client.chat.completions.create(
                    model="gpt-4o", max_tokens=2000,
                    messages=[{"role":"system","content":system}]+self.chat_history)
                ai_response = response.choices[0].message.content
            elif mode == 'gemini':
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-pro', system_instruction=system)
                history = [{'role': 'user' if m['role']=='user' else 'model','parts':[m['content']]}
                           for m in self.chat_history[:-1]]
                ai_response = model.start_chat(history=history).send_message(user_text).text
            elif mode == 'ollama':
                import urllib.request, json as jlib
                payload = {"model":"qwen2.5:7b",
                    "messages":[{"role":"system","content":system}]+self.chat_history,"stream":False}
                req = urllib.request.Request('http://localhost:11434/api/chat',
                    data=jlib.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req, timeout=60) as res:
                    ai_response = jlib.loads(res.read())['message']['content']
            else:
                ai_response = "不明なモードです"

            self.chat_history.append({"role": "assistant", "content": ai_response})
            self.root.after(0, lambda: self._on_api_response(ai_response))
        except Exception as e:
            err = str(e)
            self.root.after(0, lambda: self._on_api_error(err))

    def _on_api_response(self, response):
        self.append_chat("ai", response)
        self.root.config(cursor='')

    def _on_api_error(self, error):
        self.append_chat("error", f"エラー: {error}")
        self.root.config(cursor='')

    # ===== JWW読み込み =====

    def load_jww(self):
        filepath = filedialog.askopenfilename(
            title="JWWファイルを選択",
            filetypes=[("JW_CAD Files", "*.jww *.jwc"), ("All Files", "*.*")])
        if not filepath: return

        info, error = parse_jww(filepath)
        if error:
            self.append_chat("error", f"エラー: {error}"); return

        self.jww_info = info
        # フル解析（線・円弧・テキスト座標）も実行
        full_info, _ = parse_jww_full(filepath) if CORE_AVAILABLE else (None, None)
        base_ctx = build_jww_context(info)
        full_ctx  = build_jww_full_context(full_info) if full_info else ""
        self.system_prompt = base_ctx + "\n\n" + full_ctx if full_ctx else base_ctx

        self.chat_history = []
        self.file_label.config(text=os.path.basename(filepath), fg='#00d4ff')
        stats = f"線:{full_info['stats']['lines']}本 円弧:{full_info['stats']['arcs']}件 テキスト:{full_info['stats']['texts']}件" if full_info else f"テキスト:{len(info['テキスト要素'])}件"
        self.append_chat("system",
            f"図面を読み込みました: {info['ファイル名']}\n"
            f"サイズ:{info['図面サイズ']}  {stats}\n"
            "JW_CADで図面を開いています...")

        # JW_CADで図面を開く
        def _open_and_analyze():
            try:
                import subprocess, time
                import win32gui
                jww_exe = r"C:\JWW\Jw_win.exe"
                fname = os.path.splitext(os.path.basename(filepath))[0]
                if os.path.exists(jww_exe):
                    subprocess.Popen([jww_exe, filepath])
                    # タイトルバーに図面名が表示されるまで最大15秒待つ
                    deadline = time.time() + 15
                    found = False
                    while time.time() < deadline:
                        time.sleep(0.5)
                        def _check(hwnd, _):
                            t = win32gui.GetWindowText(hwnd).lower()
                            if 'jw_win' in t and fname.lower()[:6] in t:
                                _check.found = True
                        _check.found = False
                        win32gui.EnumWindows(_check, None)
                        if _check.found:
                            time.sleep(1.0)
                            found = True
                            break
                    if not found:
                        time.sleep(3.0)
                else:
                    self.root.after(0, lambda: self.append_chat("error",
                        f"Jw_win.exe が見つかりません: {jww_exe}"))
                    return
            except Exception as e:
                self.root.after(0, lambda: self.append_chat("error", f"JW_CAD起動エラー: {e}"))
                return

            # JW_CADウィンドウをキャプチャ
            screenshot_b64 = None
            try:
                from jwai_core import capture_jwcad_window
                b64, _ = capture_jwcad_window()
                screenshot_b64 = b64
                if b64:
                    self.root.after(0, lambda: self.append_chat("system", "📷 図面画像キャプチャ完了 → AIが図面を解析中..."))
            except Exception:
                pass

            # AIに図面概要を説明させる
            config = load_config()
            mode = config.get('mode', 'claude')
            key_map = {'claude': 'claude_api_key', 'openai': 'openai_api_key', 'gemini': 'gemini_api_key'}
            api_key = config.get(key_map.get(mode, 'claude_api_key'), '').strip()
            if not api_key and mode != 'ollama':
                self.root.after(0, lambda: self.append_chat("system",
                    "⚙ APIキーが未設定です。設定からAPIキーを入力してください。"))
                return

            try:
                system = (
                    "あなたはJW_CAD（日本の建築CADソフト）の図面作業をサポートするAIアシスタント「JW AI」です。\n"
                    "添付された図面画像を見て、この図面がどのような図面か（建物の平面図、立面図、詳細図など）、\n"
                    "どこに何が配置されているかを日本語で簡潔に説明してください。\n"
                    "その後「この図面についてどのような作業をしますか？」と聞いてください。\n\n"
                    + self.system_prompt
                )
                prompt = "この図面を見て、どのような図面か教えてください。"

                if mode == 'claude':
                    import anthropic
                    client = anthropic.Anthropic(api_key=api_key)
                    content = []
                    if screenshot_b64:
                        content.append({"type": "image", "source": {
                            "type": "base64", "media_type": "image/png", "data": screenshot_b64}})
                    content.append({"type": "text", "text": prompt})
                    response = client.messages.create(
                        model="claude-sonnet-4-5-20250929",
                        max_tokens=1000,
                        system=system,
                        messages=[{"role": "user", "content": content}])
                    ai_response = response.content[0].text

                elif mode == 'openai':
                    from openai import OpenAI
                    client = OpenAI(api_key=api_key)
                    content = []
                    if screenshot_b64:
                        content.append({"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{screenshot_b64}"}})
                    content.append({"type": "text", "text": prompt})
                    response = client.chat.completions.create(
                        model="gpt-4o", max_tokens=1000,
                        messages=[{"role": "system", "content": system},
                                  {"role": "user", "content": content}])
                    ai_response = response.choices[0].message.content

                elif mode == 'gemini':
                    import google.generativeai as genai
                    genai.configure(api_key=api_key)
                    model_g = genai.GenerativeModel('gemini-1.5-pro', system_instruction=system)
                    if screenshot_b64:
                        import base64
                        img_bytes = base64.b64decode(screenshot_b64)
                        from PIL import Image
                        import io
                        img = Image.open(io.BytesIO(img_bytes))
                        ai_response = model_g.generate_content([prompt, img]).text
                    else:
                        ai_response = model_g.generate_content(prompt).text
                else:
                    ai_response = "図面を読み込みました。作業内容を指示してください。"

                self.chat_history.append({"role": "user", "content": prompt})
                self.chat_history.append({"role": "assistant", "content": ai_response})
                self.root.after(0, lambda: self.append_chat("ai", ai_response))

            except Exception as e:
                err = str(e)
                self.root.after(0, lambda: self.append_chat("error", f"AI解析エラー: {err}"))

        threading.Thread(target=_open_and_analyze, daemon=True).start()

    # ===== 設定ダイアログ =====

    def open_settings_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("JW AI 設定")
        dlg.geometry("500x480")
        dlg.configure(bg='#1a1a2e')
        dlg.transient(self.root)
        dlg.grab_set()

        config = load_config()

        inner = tk.Frame(dlg, bg='#1a1a2e')
        inner.pack(fill='both', expand=True, padx=25, pady=20)

        tk.Label(inner, text="使用するAI", font=('Meiryo UI', 11, 'bold'),
            fg='#00d4ff', bg='#1a1a2e').pack(anchor='w', pady=(0, 6))

        mode_frame = tk.Frame(inner, bg='#16213e', pady=10, padx=12)
        mode_frame.pack(fill='x', pady=(0, 18))

        mode_var = tk.StringVar(value=config.get('mode', 'claude'))
        for value, label in [
            ('claude',  'Claude（Anthropic）- 推奨'),
            ('openai',  'GPT-4o（OpenAI）'),
            ('gemini',  'Gemini（Google）'),
            ('ollama',  'ローカルLLM（Ollama）'),
        ]:
            tk.Radiobutton(mode_frame, text=label, variable=mode_var, value=value,
                font=('Meiryo UI', 10), bg='#16213e', fg='#e0e0e0',
                selectcolor='#0f3460', activebackground='#16213e').pack(anchor='w', pady=2)

        entries = {}
        for config_key, label, hint in [
            ('claude_api_key',  'Claude API キー',  'console.anthropic.com'),
            ('openai_api_key',  'OpenAI API キー',  'platform.openai.com'),
            ('gemini_api_key',  'Gemini API キー',  'aistudio.google.com'),
        ]:
            tk.Label(inner, text=label, font=('Meiryo UI', 10, 'bold'),
                fg='#e0e0e0', bg='#1a1a2e').pack(anchor='w', pady=(8, 1))
            tk.Label(inner, text=hint, font=('Meiryo UI', 8),
                fg='#666', bg='#1a1a2e').pack(anchor='w', pady=(0, 2))
            row = tk.Frame(inner, bg='#16213e', pady=6, padx=8)
            row.pack(fill='x', pady=(0, 4))
            e = tk.Entry(row, font=('Meiryo UI', 10), bg='#0d1b2a', fg='#e0e0e0',
                insertbackground='#00d4ff', relief='flat', show='*')
            e.pack(side='left', fill='x', expand=True, ipady=4, padx=(0, 6))
            if config.get(config_key):
                e.insert(0, config[config_key])
            tk.Button(row, text="表示", font=('Meiryo UI', 8), bg='#0f3460', fg='#888',
                relief='flat', command=lambda x=e: x.config(show='' if x.cget('show')=='*' else '*')
            ).pack(side='left')
            entries[config_key] = e

        def save():
            config['mode'] = mode_var.get()
            for k, e in entries.items():
                config[k] = e.get().strip()
            save_config(config)
            self.config = config
            messagebox.showinfo("完了", "設定を保存しました！", parent=dlg)
            dlg.destroy()

        tk.Button(inner, text="✅  保存して閉じる",
            font=('Meiryo UI', 11, 'bold'), bg='#00d4ff', fg='#1a1a2e',
            relief='flat', cursor='hand2', padx=18, pady=8,
            command=save).pack(anchor='w', pady=15)


# ========== 起動 ==========

if __name__ == "__main__":
    root = tk.Tk()
    app = JWAIApp(root)
    root.mainloop()
