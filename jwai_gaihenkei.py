"""
JW AI 外部変形スクリプト
JW_CADから呼び出されて選択図形データを処理する
"""
import sys
import os
import json
import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import anthropic

# ========== 設定読み込み ==========

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".jwai_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

# ========== JW_CAD 外部変形データ解析 ==========

def parse_jwf_input(filepath):
    """
    JW_CADが出力する外部変形用一時ファイルを解析する
    形式: テキストベースのデータ
    """
    elements = []
    raw_lines = []

    try:
        with open(filepath, 'r', encoding='cp932', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        return [], [], str(e)

    for line in lines:
        line = line.rstrip('\n\r')
        raw_lines.append(line)

        if not line:
            continue

        parts = line.split()
        if not parts:
            continue

        code = parts[0]

        # 線データ (hd=0)
        if code == 'hd' and len(parts) >= 1:
            elements.append({'type': 'header', 'raw': line})

        # 線 (座標4つ)
        elif len(parts) == 4:
            try:
                x1, y1, x2, y2 = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                elements.append({
                    'type': 'line',
                    'x1': x1, 'y1': y1,
                    'x2': x2, 'y2': y2,
                    'raw': line
                })
            except:
                elements.append({'type': 'unknown', 'raw': line})

        # 文字データ
        elif len(parts) >= 3 and parts[0] == 'cn':
            elements.append({'type': 'text', 'content': ' '.join(parts[1:]), 'raw': line})

        else:
            elements.append({'type': 'unknown', 'raw': line})

    return elements, raw_lines, None


def elements_to_context(elements, raw_lines):
    """解析した図形データをAIへのコンテキスト文字列に変換"""
    lines_data = [e for e in elements if e['type'] == 'line']
    texts_data = [e for e in elements if e['type'] == 'text']

    ctx = "【選択された図形データ】\n"
    ctx += f"線の数: {len(lines_data)}本\n"
    ctx += f"文字要素: {len(texts_data)}件\n\n"

    if lines_data:
        ctx += "【線データ（座標）】\n"
        for i, l in enumerate(lines_data[:20]):
            length = ((l['x2']-l['x1'])**2 + (l['y2']-l['y1'])**2) ** 0.5
            ctx += f"  線{i+1}: ({l['x1']:.2f},{l['y1']:.2f}) → ({l['x2']:.2f},{l['y2']:.2f})  長さ:{length:.2f}\n"
        if len(lines_data) > 20:
            ctx += f"  ... 他{len(lines_data)-20}本\n"

    if texts_data:
        ctx += "\n【文字データ】\n"
        for t in texts_data:
            ctx += f"  {t['content']}\n"

    ctx += "\n【生データ（先頭20行）】\n"
    for line in raw_lines[:20]:
        ctx += f"  {line}\n"

    return ctx


def build_output(elements, modifications):
    """
    AIの指示をもとに変更後のデータを生成する
    modificationsは {'line_index': N, 'new_x1':..., 'new_y1':..., ...} のリスト
    """
    output_lines = []
    line_elements = [e for e in elements if e['type'] == 'line']

    mod_map = {m['line_index']: m for m in modifications}

    for i, elem in enumerate(line_elements):
        if i in mod_map:
            m = mod_map[i]
            x1 = m.get('new_x1', elem['x1'])
            y1 = m.get('new_y1', elem['y1'])
            x2 = m.get('new_x2', elem['x2'])
            y2 = m.get('new_y2', elem['y2'])
            output_lines.append(f"{x1} {y1} {x2} {y2}")
        else:
            output_lines.append(elem['raw'])

    return '\n'.join(output_lines)


# ========== AIチャットUI ==========

class GaihenkeiUI:
    def __init__(self, root, input_file):
        self.root = root
        self.input_file = input_file
        self.config = load_config()
        self.chat_history = []
        self.elements = []
        self.raw_lines = []
        self.context = ""

        self.root.title("JW AI - 外部変形アシスタント")
        self.root.geometry("700x600")
        self.root.configure(bg="#1a1a2e")

        self.build_ui()
        self.load_data()

    def build_ui(self):
        # ヘッダー
        header = tk.Frame(self.root, bg="#0f3460", height=50)
        header.pack(fill='x')
        header.pack_propagate(False)
        tk.Label(header, text="⚡ JW AI  外部変形アシスタント",
                 font=('Meiryo UI', 14, 'bold'),
                 fg='#00d4ff', bg='#0f3460').pack(side='left', padx=15, pady=10)

        # 図形情報
        self.info_label = tk.Label(self.root,
            text="図形データ読み込み中...",
            font=('Meiryo UI', 9),
            fg='#00d4ff', bg='#0d1b2a',
            anchor='w', padx=10)
        self.info_label.pack(fill='x')

        # チャット表示
        self.chat_display = scrolledtext.ScrolledText(
            self.root,
            font=('Meiryo UI', 10),
            bg='#0d1b2a', fg='#e0e0e0',
            relief='flat', wrap=tk.WORD,
            state='disabled', padx=10, pady=8)
        self.chat_display.pack(fill='both', expand=True, padx=8, pady=5)

        self.chat_display.tag_configure('user', foreground='#00d4ff', font=('Meiryo UI', 10, 'bold'))
        self.chat_display.tag_configure('ai', foreground='#e0e0e0')
        self.chat_display.tag_configure('system', foreground='#666', font=('Meiryo UI', 9, 'italic'))
        self.chat_display.tag_configure('error', foreground='#ff6b6b')

        # 入力エリア
        input_frame = tk.Frame(self.root, bg="#1a1a2e")
        input_frame.pack(fill='x', padx=8, pady=(0, 8))

        self.input_field = tk.Text(
            input_frame,
            font=('Meiryo UI', 11),
            bg='#ffffff', fg='#111111',
            insertbackground='#0066cc',
            relief='flat', height=3,
            padx=10, pady=8, wrap=tk.WORD)
        self.input_field.pack(side='left', fill='both', expand=True, padx=(0, 5))
        self.input_field.bind('<Return>', self.on_enter)
        self.input_field.bind('<Shift-Return>', lambda e: None)

        btn_frame = tk.Frame(input_frame, bg="#1a1a2e")
        btn_frame.pack(side='right', fill='y')

        tk.Button(btn_frame,
            text="送信\n▶",
            font=('Meiryo UI', 10, 'bold'),
            bg='#00d4ff', fg='#1a1a2e',
            relief='flat', width=6, cursor='hand2',
            command=self.send_message).pack(fill='both', expand=True, pady=(0, 3))

        tk.Button(btn_frame,
            text="図面に\n反映",
            font=('Meiryo UI', 9, 'bold'),
            bg='#27ae60', fg='#ffffff',
            relief='flat', width=6, cursor='hand2',
            command=self.apply_to_jwcad).pack(fill='both', expand=True)

    def load_data(self):
        if not self.input_file or not os.path.exists(self.input_file):
            self.append_chat("system",
                "⚠️ 入力ファイルが指定されていません。\n"
                "JW_CADの外部変形から呼び出してください。\n\n"
                "テストモード: 図面ファイルなしでAIと会話できます。")
            self.info_label.config(text="テストモード（入力ファイルなし）")
            self.append_chat("system", "JW AIへようこそ！何でも聞いてください。")
            return

        elements, raw_lines, error = parse_jwf_input(self.input_file)
        if error:
            self.append_chat("error", f"❌ データ読み込みエラー: {error}")
            return

        self.elements = elements
        self.raw_lines = raw_lines
        self.context = elements_to_context(elements, raw_lines)

        line_count = len([e for e in elements if e['type'] == 'line'])
        text_count = len([e for e in elements if e['type'] == 'text'])
        self.info_label.config(text=f"選択図形: 線{line_count}本  文字{text_count}件")

        self.append_chat("system",
            f"✅ 選択図形を読み込みました\n"
            f"  線: {line_count}本  文字: {text_count}件\n\n"
            "AIに指示を入力してください。\n"
            "例：「選択した線の長さを1200mmにして」「この寸法を教えて」")

    def append_chat(self, role, text):
        self.chat_display.config(state='normal')
        if role == 'user':
            self.chat_display.insert('end', "\n👤 あなた:\n", 'user')
            self.chat_display.insert('end', text + "\n", 'ai')
        elif role == 'ai':
            self.chat_display.insert('end', "\n🤖 JW AI:\n", 'user')
            self.chat_display.insert('end', text + "\n", 'ai')
        elif role == 'system':
            self.chat_display.insert('end', "\n" + text + "\n", 'system')
        elif role == 'error':
            self.chat_display.insert('end', "\n" + text + "\n", 'error')
        self.chat_display.config(state='disabled')
        self.chat_display.see('end')

    def on_enter(self, event):
        if not event.state & 0x1:
            self.send_message()
            return 'break'

    def send_message(self):
        user_text = self.input_field.get("1.0", "end-1c").strip()
        if not user_text:
            return

        mode = self.config.get('mode', 'claude')
        key_map = {'claude': 'claude_api_key', 'openai': 'openai_api_key', 'gemini': 'gemini_api_key'}
        api_key = self.config.get(key_map.get(mode, 'claude_api_key'), '').strip()

        if not api_key and mode != 'ollama':
            messagebox.showwarning("APIキー未設定",
                "jw_ai.py の設定タブでAPIキーを設定してください")
            return

        self.input_field.delete("1.0", "end")
        self.append_chat("user", user_text)
        self.chat_history.append({"role": "user", "content": user_text})
        self.root.config(cursor='wait')

        threading.Thread(
            target=self.call_api,
            args=(user_text, api_key),
            daemon=True).start()

    def call_api(self, user_text, api_key):
        try:
            mode = self.config.get('mode', 'claude')
            system = (
                "あなたはJW_CADの図面作業をサポートするAIアシスタント「JW AI」です。\n"
                "ユーザーが選択した図形データをもとに、寸法変更・要素の説明・作図指示などを行います。\n"
                "図面の変更を行う場合は、変更内容を明確に説明してから「図面に反映」ボタンを使うよう案内してください。\n"
                "日本語で回答してください。\n\n"
                + self.context
            )

            if mode == 'claude':
                client = anthropic.Anthropic(api_key=api_key)
                response = client.messages.create(
                    model="claude-opus-4-5-20251101",
                    max_tokens=2000,
                    system=system,
                    messages=self.chat_history)
                ai_response = response.content[0].text

            elif mode == 'openai':
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                msgs = [{"role": "system", "content": system}] + self.chat_history
                response = client.chat.completions.create(
                    model="gpt-4o", max_tokens=2000, messages=msgs)
                ai_response = response.choices[0].message.content

            elif mode == 'gemini':
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-pro', system_instruction=system)
                history = []
                for msg in self.chat_history[:-1]:
                    history.append({'role': 'user' if msg['role'] == 'user' else 'model',
                                    'parts': [msg['content']]})
                chat = model.start_chat(history=history)
                ai_response = chat.send_message(user_text).text

            elif mode == 'ollama':
                import urllib.request, json as jlib
                payload = {"model": "qwen2.5:7b",
                           "messages": [{"role": "system", "content": system}] + self.chat_history,
                           "stream": False}
                req = urllib.request.Request(
                    'http://localhost:11434/api/chat',
                    data=jlib.dumps(payload).encode(),
                    headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=60) as res:
                    ai_response = jlib.loads(res.read())['message']['content']
            else:
                ai_response = "不明なモードです"

            self.chat_history.append({"role": "assistant", "content": ai_response})
            self.root.after(0, lambda: self.on_api_response(ai_response))

        except Exception as e:
            err = str(e)
            self.root.after(0, lambda: self.on_api_error(err))

    def on_api_response(self, response):
        self.append_chat("ai", response)
        self.root.config(cursor='')

    def on_api_error(self, error):
        self.append_chat("error", f"❌ エラー: {error}")
        self.root.config(cursor='')

    def apply_to_jwcad(self):
        """
        現在の会話内容をもとに変更をJWWファイルに書き戻す（将来実装）
        今はダイアログで確認表示
        """
        if not self.elements:
            messagebox.showinfo("情報", "図形データがありません")
            return
        messagebox.showinfo("図面に反映",
            "この機能は次のバージョンで実装予定です。\n\n"
            "現在はAIのアドバイスをもとに\n"
            "JW_CADで手動修正してください。")


# ========== 起動 ==========

if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    app = GaihenkeiUI(root, input_file)
    root.mainloop()
