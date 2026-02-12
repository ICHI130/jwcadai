"""
JW AI 共有コアモジュール
jwai_gaihenkei.py と jw_ai.py から共通利用される関数・定数
"""
import os
import json

# ========== ファイルパス定数 ==========

JWC_TEMP    = r"C:\JWW\JWC_TEMP.TXT"
SIGNAL_FILE = r"C:\JWW\jwai_signal.json"
DONE_FILE   = r"C:\JWW\jwai_done.json"
LOCK_FILE   = r"C:\JWW\jwai_main.lock"
READY_FILE  = r"C:\JWW\jwai_ready.json"   # jw_ai.py起動完了マーカー
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".jwai_config.json")


# ========== 設定管理 ==========

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ========== JWC_TEMP.TXT 解析 ==========

def parse_jwc_temp(filepath=None):
    """
    JWC_TEMP.TXTを解析して図形要素のリストと生データを返す。
    Returns: (elements, raw_lines, error_str_or_None)
    """
    if filepath is None:
        filepath = JWC_TEMP

    elements = []
    raw_lines = []

    if not os.path.exists(filepath):
        return elements, raw_lines, f"ファイルが見つかりません: {filepath}"

    try:
        with open(filepath, 'r', encoding='cp932', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        return elements, raw_lines, str(e)

    for line in lines:
        line = line.rstrip('\n\r')
        raw_lines.append(line)
        if not line:
            elements.append({'type': 'blank', 'raw': ''})
            continue

        parts = line.split()
        if not parts:
            continue
        code = parts[0]

        if code == 'hq':
            elements.append({'type': 'hq', 'raw': line})
        elif (code.startswith('hk') or code.startswith('hs') or code.startswith('hn')
              or code.startswith('hcw') or code.startswith('hch') or code.startswith('hcd')
              or code.startswith('hcc') or code.startswith('hp')):
            elements.append({'type': 'header', 'raw': line})
        elif (code.startswith('lg') or code.startswith('ly') or code.startswith('lc')
              or code.startswith('lt') or code.startswith('lw')):
            elements.append({'type': 'attr', 'raw': line})
        elif code == 'ci':
            elements.append({'type': 'circle', 'raw': line, 'parts': parts})
        elif (code.startswith('ch') or code.startswith('cv') or code.startswith('cs')
              or code.startswith('cn')):
            elements.append({'type': 'text', 'raw': line, 'parts': parts})
        elif code == 'pt':
            elements.append({'type': 'point', 'raw': line, 'parts': parts})
        elif code == 'hd':
            elements.append({'type': 'hd', 'raw': line})
        elif len(parts) == 4:
            try:
                x1, y1, x2, y2 = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                elements.append({'type': 'line', 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'raw': line})
            except Exception:
                elements.append({'type': 'other', 'raw': line})
        else:
            elements.append({'type': 'other', 'raw': line})

    return elements, raw_lines, None


# ========== AIコンテキスト生成 ==========

def elements_to_context(elements, raw_lines):
    """図形データをAIへのコンテキスト文字列に変換"""
    lines_data   = [e for e in elements if e['type'] == 'line']
    texts_data   = [e for e in elements if e['type'] == 'text']
    circles_data = [e for e in elements if e['type'] == 'circle']

    ctx  = "【選択された図形データ（JWC_TEMP.TXT）】\n"
    ctx += f"線: {len(lines_data)}本  文字: {len(texts_data)}件  円弧: {len(circles_data)}件\n\n"

    if lines_data:
        ctx += "【線データ（座標、単位mm）】\n"
        for i, l in enumerate(lines_data[:30]):
            length = ((l['x2'] - l['x1'])**2 + (l['y2'] - l['y1'])**2) ** 0.5
            ctx += f"  線{i+1}: ({l['x1']:.2f},{l['y1']:.2f})→({l['x2']:.2f},{l['y2']:.2f})  長さ:{length:.2f}mm\n"
        if len(lines_data) > 30:
            ctx += f"  ...他{len(lines_data)-30}本\n"

    if circles_data:
        ctx += "\n【円弧データ（番号付き）】\n"
        ctx += "※変換時は circle_indices でこの番号を指定してください\n"
        for i, c in enumerate(circles_data):
            ctx += f"  [円弧{i}] {c['raw']}\n"
            if len(c.get('parts', [])) >= 4:
                try:
                    cx, cy, r = float(c['parts'][1]), float(c['parts'][2]), float(c['parts'][3])
                    desc = f"    → 中心({cx:.2f},{cy:.2f}) 半径{r:.2f}mm"
                    if len(c['parts']) >= 6:
                        start_a, end_a = float(c['parts'][4]), float(c['parts'][5])
                        desc += f" 始角:{start_a:.1f}° 終角:{end_a:.1f}°"
                        # 角度からドア方向を推定
                        span = (end_a - start_a) % 360
                        if 80 <= span <= 100:
                            desc += " ←ドア扇形(90°)"
                        elif 170 <= span <= 190:
                            desc += " ←半円"
                        elif span < 5:
                            desc += " ←全円"
                    ctx += desc + "\n"
                except Exception:
                    pass

    if texts_data:
        ctx += "\n【文字データ】\n"
        for t in texts_data[:10]:
            ctx += f"  {t['raw']}\n"

    ctx += "\n【生データ先頭30行】\n"
    for line in raw_lines[:30]:
        ctx += f"  {line}\n"

    return ctx


# ========== JWC_TEMP.TXT 書き戻し ==========

def write_result_to_jwc(elements, modified_lines_map, filepath=None,
                         modified_circles_map=None):
    """
    変更済みデータをJWC_TEMP.TXTに書き戻す。
    hqを除去してJW_CADに「実行済み」として認識させる。
    modified_lines_map:   {line_index: {'x1':..,'y1':..,'x2':..,'y2':..}}
    modified_circles_map: {circle_index: raw_line_string}  ← 変換済みの生行文字列
    Returns: (success, error_or_None)
    """
    if filepath is None:
        filepath = JWC_TEMP
    if modified_circles_map is None:
        modified_circles_map = {}

    output = []
    line_idx = 0
    circle_idx = 0
    for elem in elements:
        if elem['type'] == 'hq':
            continue  # hq削除が「実行済み」の合図
        elif elem['type'] == 'line':
            if line_idx in modified_lines_map:
                m = modified_lines_map[line_idx]
                x1 = m.get('x1', elem['x1'])
                y1 = m.get('y1', elem['y1'])
                x2 = m.get('x2', elem['x2'])
                y2 = m.get('y2', elem['y2'])
                output.append(f"{x1} {y1} {x2} {y2}")
            else:
                output.append(elem['raw'])
            line_idx += 1
        elif elem['type'] == 'circle':
            if circle_idx in modified_circles_map:
                output.append(modified_circles_map[circle_idx])
            else:
                output.append(elem['raw'])
            circle_idx += 1
        else:
            output.append(elem['raw'])

    try:
        content = '\n'.join(output) + '\n'
        with open(filepath, 'w', encoding='cp932', errors='replace') as f:
            f.write(content)
        return True, None
    except Exception as e:
        return False, str(e)


# ========== 座標変換エンジン ==========

import math

def _calc_bbox(elements):
    """線要素のバウンディングボックスを計算（変換基準点に使用）"""
    xs, ys = [], []
    for e in elements:
        if e['type'] == 'line':
            xs += [e['x1'], e['x2']]
            ys += [e['y1'], e['y2']]
        elif e['type'] == 'circle' and len(e.get('parts', [])) >= 4:
            try:
                cx, cy, r = float(e['parts'][1]), float(e['parts'][2]), float(e['parts'][3])
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
            except Exception:
                pass
    if not xs:
        return 0, 0, 0, 0
    return min(xs), min(ys), max(xs), max(ys)


def _mirror_x_line(x1, y1, x2, y2, axis_x):
    """x=axis_x を軸に左右反転"""
    return 2*axis_x - x1, y1, 2*axis_x - x2, y2

def _mirror_y_line(x1, y1, x2, y2, axis_y):
    """y=axis_y を軸に上下反転"""
    return x1, 2*axis_y - y1, x2, 2*axis_y - y2

def _mirror_x_circle(parts, axis_x):
    """円弧を x=axis_x 軸で左右反転"""
    # ci cx cy r [start end flat angle]
    cx = 2 * axis_x - float(parts[1])
    cy = float(parts[2])
    r  = float(parts[3])
    if len(parts) >= 6:
        sa = float(parts[4])
        ea = float(parts[5])
        # 角度反転: 元のangle→ 180-angle (mod 360)
        new_sa = (180 - ea) % 360
        new_ea = (180 - sa) % 360
        rest = parts[6:]
        return f"ci {cx} {cy} {r} {new_sa} {new_ea} " + " ".join(rest)
    return f"ci {cx} {cy} {r}"

def _mirror_y_circle(parts, axis_y):
    """円弧を y=axis_y 軸で上下反転"""
    cx = float(parts[1])
    cy = 2 * axis_y - float(parts[2])
    r  = float(parts[3])
    if len(parts) >= 6:
        sa = float(parts[4])
        ea = float(parts[5])
        # 上下反転: 角度を 360-angle (mod360) にして始終角を入れ替え
        new_sa = (360 - ea) % 360
        new_ea = (360 - sa) % 360
        rest = parts[6:]
        return f"ci {cx} {cy} {r} {new_sa} {new_ea} " + " ".join(rest)
    return f"ci {cx} {cy} {r}"


def _flip_arc_angles_x(parts):
    """
    円弧の中心・半径はそのままで、角度だけ左右反転する。
    左開き(90-180°) → 右開き(0-90°)
    右開き(0-90°)   → 左開き(90-180°)
    ci cx cy r sa ea [flat angle]
    """
    if len(parts) < 6:
        return None  # 角度情報なし→変換不可
    cx = float(parts[1])
    cy = float(parts[2])
    r  = float(parts[3])
    sa = float(parts[4])
    ea = float(parts[5])
    # 左右反転: new_sa = (180 - ea) % 360, new_ea = (180 - sa) % 360
    new_sa = (180 - ea) % 360
    new_ea = (180 - sa) % 360
    rest = parts[6:]
    return f"ci {cx} {cy} {r} {new_sa} {new_ea} " + " ".join(rest)

def _flip_arc_angles_y(parts):
    """
    円弧の中心・半径はそのままで、角度だけ上下反転する。
    ci cx cy r sa ea [flat angle]
    """
    if len(parts) < 6:
        return None
    cx = float(parts[1])
    cy = float(parts[2])
    r  = float(parts[3])
    sa = float(parts[4])
    ea = float(parts[5])
    # 上下反転: new_sa = (360 - ea) % 360, new_ea = (360 - sa) % 360
    new_sa = (360 - ea) % 360
    new_ea = (360 - sa) % 360
    rest = parts[6:]
    return f"ci {cx} {cy} {r} {new_sa} {new_ea} " + " ".join(rest)


def apply_transform(elements, transform):
    """
    transform辞書に従って要素に座標変換を適用し、
    (modified_lines_map, modified_circles_map) を返す。

    transform keys:
      "type":   "mirror_x" | "mirror_y" | "rotate" | "arc_flip_x" | "arc_flip_y"
      "target": "all"(デフォルト) | "circles_only" | "lines_only"
      "axis_x": float  (mirror_x用)
      "axis_y": float  (mirror_y用)
      "angle":  float  (rotate用、度)
      "cx": float, "cy": float  (rotate中心)

    type説明:
      mirror_x    : x=axis_x 軸で全要素（or target指定）を左右反転
      mirror_y    : y=axis_y 軸で全要素（or target指定）を上下反転
      rotate      : 指定中心を軸に回転
      arc_flip_x  : 円弧の中心位置はそのままで角度だけ左右反転（ドア勝手変更に最適）
      arc_flip_y  : 円弧の中心位置はそのままで角度だけ上下反転
    """
    t      = transform.get("type", "")
    target = transform.get("target", "all")  # "all" | "circles_only" | "lines_only"
    # circle_indices: 変換対象の円弧インデックスリスト。Noneなら全円弧対象
    circle_indices = transform.get("circle_indices", None)
    if circle_indices is not None:
        circle_indices = set(int(i) for i in circle_indices)

    line_idx   = 0
    circle_idx = 0
    mod_lines   = {}
    mod_circles = {}

    # バウンディングボックスから自動中心を計算
    xmin, ymin, xmax, ymax = _calc_bbox(elements)
    auto_cx = (xmin + xmax) / 2
    auto_cy = (ymin + ymax) / 2

    axis_x = transform.get("axis_x", auto_cx)
    axis_y = transform.get("axis_y", auto_cy)
    angle  = transform.get("angle",  0.0)
    rot_cx = transform.get("cx",    auto_cx)
    rot_cy = transform.get("cy",    auto_cy)

    # arc_flip系はtargetに関係なく円弧のみ変換
    arc_flip_mode = t in ("arc_flip_x", "arc_flip_y")

    for elem in elements:
        if elem['type'] == 'line':
            x1,y1,x2,y2 = elem['x1'],elem['y1'],elem['x2'],elem['y2']
            # arc_flip系 or circles_only の場合は線を変換しない
            if not arc_flip_mode and target != "circles_only":
                if t == "mirror_x":
                    x1,y1,x2,y2 = _mirror_x_line(x1,y1,x2,y2, axis_x)
                elif t == "mirror_y":
                    x1,y1,x2,y2 = _mirror_y_line(x1,y1,x2,y2, axis_y)
                elif t == "rotate":
                    rad = math.radians(angle)
                    cos_a, sin_a = math.cos(rad), math.sin(rad)
                    def _rot(px, py, cx=rot_cx, cy=rot_cy, ca=cos_a, sa=sin_a):
                        dx, dy = px - cx, py - cy
                        return cx + dx*ca - dy*sa, cy + dx*sa + dy*ca
                    x1,y1 = _rot(x1,y1)
                    x2,y2 = _rot(x2,y2)
            mod_lines[line_idx] = {'x1':x1,'y1':y1,'x2':x2,'y2':y2}
            line_idx += 1
        elif elem['type'] == 'circle':
            parts = elem.get('parts', [])
            new_raw = None

            # circle_indicesが指定されていて、このインデックスが含まれていなければスキップ
            if circle_indices is not None and circle_idx not in circle_indices:
                new_raw = elem['raw']  # 変換しない
            elif arc_flip_mode:
                # 円弧の中心・半径はそのまま、角度だけ反転
                if t == "arc_flip_x":
                    new_raw = _flip_arc_angles_x(parts)
                else:
                    new_raw = _flip_arc_angles_y(parts)
            elif target != "lines_only":
                # 通常の座標変換
                if t == "mirror_x":
                    new_raw = _mirror_x_circle(parts, axis_x)
                elif t == "mirror_y":
                    new_raw = _mirror_y_circle(parts, axis_y)

            if new_raw is None:
                new_raw = elem['raw']  # 変換不可 or 対象外は原データ維持
            mod_circles[circle_idx] = new_raw
            circle_idx += 1

    return mod_lines, mod_circles


def parse_ai_transform(ai_response_text):
    """
    AIのレスポンスから ```json ... ``` ブロックを探し、
    transform辞書を抽出して返す。見つからなければNone。
    """
    import re
    pattern = r'```json\s*([\s\S]*?)\s*```'
    match = re.search(pattern, ai_response_text)
    if not match:
        # フォールバック: {...} だけでも試す
        match = re.search(r'\{[\s\S]*?"type"[\s\S]*?\}', ai_response_text)
        if not match:
            return None
    try:
        data = json.loads(match.group(1) if '```' in ai_response_text else match.group(0))
        if "type" in data:
            return data
    except Exception:
        pass
    return None


# ========== JW_CAD 画面キャプチャ ==========

def _find_jwcad_hwnd():
    """JW_CADのウィンドウハンドルを探す（最小化・非表示でも検出）"""
    import win32gui
    # JW_CADのウィンドウタイトルパターン
    # 実際のタイトル例: "建築一般図 - jw_win"、"Jw_cad"、"JW_CAD" など
    JW_KEYWORDS = ('jw_win', 'jw_cad', 'jw cad', 'jww')
    candidates = []
    def _cb(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        tl = title.lower()
        if any(kw in tl for kw in JW_KEYWORDS):
            candidates.append((hwnd, title))
    win32gui.EnumWindows(_cb, None)
    if not candidates:
        return None
    # 表示中のものを優先、なければ最初のものを返す
    for hwnd, _ in candidates:
        if win32gui.IsWindowVisible(hwnd):
            return hwnd
    return candidates[0][0]


def capture_jwcad_window():
    """
    JW_CADのウィンドウをキャプチャしてbase64文字列として返す。
    PrintWindow API を使用するため、最小化・背面・隠れていても正確にキャプチャできる。
    JW_CADが見つからない場合は (None, None) を返す。
    Returns: (base64_str, media_type) or (None, None)
    """
    try:
        import win32gui
        import win32ui
        import win32con
        import ctypes
        from PIL import Image
        import io, base64

        hwnd = _find_jwcad_hwnd()
        if not hwnd:
            return None, None

        # 最小化されている場合は一時的に復元してサイズを取得し、すぐ戻す
        placement = win32gui.GetWindowPlacement(hwnd)
        was_minimized = (placement[1] == win32con.SW_SHOWMINIMIZED)
        if was_minimized:
            # SW_SHOWNOACTIVATE: フォーカスを奪わずに復元
            win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)

        # クライアント領域のサイズを取得（タイトルバー・枠を除いた図面表示部分）
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        width  = right - left
        height = bottom - top

        # クライアント領域が取れなければウィンドウ全体にフォールバック
        if width <= 0 or height <= 0:
            wleft, wtop, wright, wbottom = win32gui.GetWindowRect(hwnd)
            width  = wright - wleft
            height = wbottom - wtop

        if width <= 0 or height <= 0:
            if was_minimized:
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            return None, None

        # PrintWindow でキャプチャ
        # PW_CLIENTONLY(0x1) | PW_RENDERFULLCONTENT(0x2) = 0x3
        # PW_RENDERFULLCONTENT はDirect3D/GPU描画も含めてキャプチャ（Win8.1以降）
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc  = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp     = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bmp)

        # PrintWindow呼び出し（PW_CLIENTONLY=1でクライアント領域のみ）
        result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 1)

        # BitmapをPIL Imageに変換
        bmp_info = bmp.GetInfo()
        bmp_data = bmp.GetBitmapBits(True)
        img = Image.frombuffer('RGB',
                               (bmp_info['bmWidth'], bmp_info['bmHeight']),
                               bmp_data, 'raw', 'BGRX', 0, 1)

        # クリーンアップ
        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)

        # 最小化していたら元に戻す
        if was_minimized:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

        # PrintWindowが失敗した場合（result==0）は黒画像になるので確認
        # 画像が真っ黒（全ピクセルの平均輝度が5以下）なら失敗とみなす
        import struct
        sample = list(bmp_data[:300])  # 先頭100ピクセル分
        avg = sum(sample) / len(sample) if sample else 0
        if avg < 5:
            return None, None

        # 大きすぎる場合はリサイズ（API制限対策・1280px以内）
        max_width = 1280
        if img.width > max_width:
            ratio = max_width / img.width
            new_h = int(img.height * ratio)
            img = img.resize((max_width, new_h), Image.LANCZOS)

        # base64エンコード
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        return b64, 'image/png'

    except Exception:
        return None, None


def capture_jwcad_screenshot_file(save_path=None):
    """
    JW_CADの画面をキャプチャしてファイルに保存。
    save_path指定なしの場合は C:\JWW\jwai_screenshot.png に保存。
    Returns: save_path or None
    """
    if save_path is None:
        save_path = r"C:\JWW\jwai_screenshot.png"

    b64, _ = capture_jwcad_window()
    if b64 is None:
        return None

    import base64
    try:
        with open(save_path, 'wb') as f:
            f.write(base64.b64decode(b64))
        return save_path
    except Exception:
        return None


# ========== シグナルファイル操作 ==========

def write_signal(message="ready"):
    """jwai_signal.json を書き出す（外部変形→常駐アプリへの通知）"""
    import time
    data = {
        "message": message,
        "timestamp": time.time(),
        "jwc_temp": JWC_TEMP,
    }
    try:
        with open(SIGNAL_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        return True
    except Exception:
        return False

def write_done():
    """jwai_done.json を書き出す（常駐アプリ→外部変形プロセスへの完了通知）"""
    import time
    data = {"done": True, "timestamp": time.time()}
    try:
        with open(DONE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return True
    except Exception:
        return False

def is_main_running():
    """
    jwai_main.lock が存在し、かつそのPIDのプロセスが実際に生きている場合のみ True。
    クラッシュ・強制終了でlockが残った場合は自動で削除して False を返す。
    """
    if not os.path.exists(LOCK_FILE):
        return False
    try:
        with open(LOCK_FILE, 'r') as f:
            pid = int(f.read().strip())
    except Exception:
        # 読み取れない壊れたlockは削除
        try: os.remove(LOCK_FILE)
        except Exception: pass
        return False

    # PIDが実際に生きているか確認
    try:
        import ctypes
        # OpenProcess: アクセス権SYNCHRONIZE(0x100000)で試みる
        handle = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
        if handle == 0:
            # プロセスが存在しない
            try: os.remove(LOCK_FILE)
            except Exception: pass
            return False
        # ExitCodeを取得して実行中かチェック
        exit_code = ctypes.c_ulong(0)
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        STILL_ACTIVE = 259
        if exit_code.value != STILL_ACTIVE:
            # プロセスは終了済み
            try: os.remove(LOCK_FILE)
            except Exception: pass
            return False
        return True
    except Exception:
        # ctypes失敗時は os.kill で確認（Unix互換フォールバック）
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            try: os.remove(LOCK_FILE)
            except Exception: pass
            return False

def create_lock():
    """常駐アプリ起動時にロックファイルとREADYファイルを作成"""
    try:
        import time
        pid = os.getpid()
        with open(LOCK_FILE, 'w') as f:
            f.write(str(pid))
        # READYファイルも作成（jwai_gaihenkei.pyが起動確認に使う）
        with open(READY_FILE, 'w') as f:
            json.dump({"pid": pid, "timestamp": time.time()}, f)
        return True
    except Exception:
        return False

def remove_lock():
    """常駐アプリ終了時にロックファイルとREADYファイルを削除"""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
        if os.path.exists(READY_FILE):
            os.remove(READY_FILE)
    except Exception:
        pass

def cleanup_signal_files():
    """シグナル・完了ファイルを削除（次回実行のためのクリーンアップ）"""
    for f in [SIGNAL_FILE, DONE_FILE]:
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception:
            pass


# ========== JWWファイル フル解析 ==========

def parse_jww_full(filepath):
    """
    JWWバイナリファイルから線・円弧・文字の座標データを解析する。
    JWWフォーマット: 各レコードは レコードタイプ(2byte) + データ長(2byte) + データ で構成。
    Returns: (info_dict, error_str_or_None)
    info_dict = {
        "lines": [{"x1","y1","x2","y2","length"},...],
        "arcs":  [{"cx","cy","r","start_a","end_a"},...],
        "texts": [{"x","y","text","source","kind"},...],
        "dims":  [{"value","x","y"},...],
        "rooms": [{"name","count"},...],
        "insights": {
            "drawing_type": "floor_plan_like"|"unknown",
            "orthogonality_ratio": float,
            "door_like_arcs": int,
            "bbox": {"min_x","min_y","max_x","max_y","width","height"}|None,
            "room_labels_with_coord": int,
        },
        "stats": {"lines":N,"arcs":N,"texts":N,"dims":N,"rooms":N},
    }
    """
    import struct
    import os
    import re
    import unicodedata

    def is_reasonable_coord(*vals):
        return all(abs(v) < 1000000 for v in vals)

    def normalize_text(raw):
        if not raw:
            return ""
        return ''.join(c for c in raw if c.isprintable()).strip()

    def normalize_for_match(text):
        # 全角/半角ゆれを抑える（３０００ -> 3000, ＬＤＫ -> LDK）
        return unicodedata.normalize('NFKC', text).strip()

    def classify_text(clean):
        if not clean:
            return None
        n = normalize_for_match(clean)
        compact = re.sub(r'\s+', '', n)
        lower = compact.lower()

        # 寸法値（1000, 900.5, 1200x600, R250, φ100, 1000mm）
        if re.fullmatch(r'[+-]?\d+(?:\.\d+)?(?:mm)?', lower):
            return "dim"
        if re.fullmatch(r'[+-]?\d+(?:\.\d+)?x[+-]?\d+(?:\.\d+)?(?:mm)?', lower):
            return "dim"
        if re.fullmatch(r'(?:r|φ|d)?[+-]?\d+(?:\.\d+)?(?:mm)?', lower):
            return "dim"

        room_keywords = (
            '玄関', 'ホール', '廊下', 'ポーチ', '洗面', '脱衣', '浴室', '風呂', 'トイレ',
            '便所', 'キッチン', '台所', 'ダイニング', 'リビング', '和室', '洋室',
            '寝室', '納戸', '収納', '押入', '階段', 'バルコニー', 'ベランダ',
            'ps', 'mb', 'cl', 'wic', 'sic', 'ldk'
        )
        low = n.lower()
        if any(k in low for k in room_keywords):
            return "room"

        has_jp = any('぀' <= c <= '鿿' or '＀' <= c <= '￯' for c in clean)
        if has_jp:
            return "text"
        return None

    def append_text(clean, source, coord=None):
        cls = classify_text(clean)
        if not cls:
            return
        item = {"text": clean, "source": source, "kind": cls}
        if coord:
            item["x"], item["y"] = coord
        texts.append(item)
        seen_texts.add(clean)

        if cls == "dim":
            dim = {"value": clean}
            if coord:
                dim["x"], dim["y"] = coord
            dims.append(dim)
        elif cls == "room":
            rooms.append({"name": clean, **({"x": coord[0], "y": coord[1]} if coord else {})})

    if not os.path.exists(filepath):
        return None, f"ファイルが見つかりません: {filepath}"

    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except Exception as e:
        return None, str(e)

    if len(data) < 8 or not data[:7].decode('ascii', errors='ignore').startswith('JwwData'):
        return None, "JWWファイルではありません"

    lines, arcs, texts, dims, rooms = [], [], [], [], []

    i = 0
    max_items = 2000
    while i < len(data) - 4:
        try:
            rec_type = struct.unpack_from('<H', data, i)[0]
            rec_size = struct.unpack_from('<H', data, i + 2)[0]
            if rec_size == 0 or rec_size > 512 or i + 4 + rec_size > len(data):
                i += 1
                continue

            rec_data = data[i + 4: i + 4 + rec_size]

            if rec_type in (0x10, 0x11, 0x12, 0x13) and rec_size >= 32:
                try:
                    x1, y1, x2, y2 = struct.unpack_from('<dddd', rec_data, 0)
                    if is_reasonable_coord(x1, y1, x2, y2):
                        length = ((x2-x1)**2 + (y2-y1)**2) ** 0.5
                        if length > 0.1:
                            lines.append({
                                "x1": round(x1, 2), "y1": round(y1, 2),
                                "x2": round(x2, 2), "y2": round(y2, 2),
                                "length": round(length, 2)
                            })
                            if len(lines) >= max_items:
                                i += 4 + rec_size
                                continue
                except Exception:
                    pass

            elif rec_type in (0x20, 0x21, 0x22, 0x23) and rec_size >= 40:
                try:
                    cx, cy, r, sa, ea = struct.unpack_from('<ddddd', rec_data, 0)
                    if is_reasonable_coord(cx, cy) and 0 < r < 100000:
                        arcs.append({
                            "cx": round(cx, 2), "cy": round(cy, 2), "r": round(r, 2),
                            "start_a": round(sa, 2), "end_a": round(ea, 2)
                        })
                            
                        if len(arcs) >= max_items:
                            i += 4 + rec_size
                            continue
                except Exception:
                    pass

            i += 4 + rec_size
        except Exception:
            i += 1

    seen_texts = set()

    # type 0x30台（文字/寸法系を想定）優先
    i = 0
    while i < len(data) - 4 and len(texts) < 500:
        try:
            rec_type = struct.unpack_from('<H', data, i)[0]
            rec_size = struct.unpack_from('<H', data, i + 2)[0]
            if rec_type not in (0x30, 0x31, 0x32, 0x33, 0x34, 0x35) or rec_size < 6 or rec_size > 1024:
                i += 1
                continue
            if i + 4 + rec_size > len(data):
                i += 1
                continue

            rec_data = data[i + 4:i + 4 + rec_size]
            coord = None
            if rec_size >= 16:
                try:
                    x, y = struct.unpack_from('<dd', rec_data, 0)
                    if is_reasonable_coord(x, y):
                        coord = (round(x, 2), round(y, 2))
                except Exception:
                    coord = None

            for start in range(0, min(96, rec_size - 2)):
                length = rec_data[start]
                if not 2 <= length <= 120 or start + 1 + length > rec_size:
                    continue
                raw = rec_data[start + 1:start + 1 + length]
                try:
                    clean = normalize_text(raw.decode('cp932'))
                except Exception:
                    continue
                if len(clean) < 2 or clean in seen_texts:
                    continue
                append_text(clean, f"0x{rec_type:02x}", coord)

            i += 4 + rec_size
        except Exception:
            i += 1

    # fallback: 可変長文字列スキャン
    j = 0
    while j < len(data) - 2 and len(texts) < 500:
        length = data[j]
        if 2 <= length <= 80:
            chunk = data[j+1:j+1+length]
            try:
                clean = normalize_text(chunk.decode('cp932'))
                if len(clean) >= 2 and clean not in seen_texts:
                    append_text(clean, "fallback")
                    if clean in seen_texts:
                        j += 1 + length
                        continue
            except Exception:
                pass
        j += 1

    # 重複整理
    seen_dim = set()
    dedup_dims = []
    for d in dims:
        key = normalize_for_match(d.get('value', ''))
        if not key or key in seen_dim:
            continue
        seen_dim.add(key)
        dedup_dims.append(d)
    dims = dedup_dims

    room_counts = {}
    room_labels_with_coord = 0
    for r in rooms:
        name = normalize_for_match(r['name'])
        if not name:
            continue
        room_counts[name] = room_counts.get(name, 0) + 1
        if 'x' in r and 'y' in r:
            room_labels_with_coord += 1
    room_summary = [
        {"name": name, "count": count}
        for name, count in sorted(room_counts.items(), key=lambda x: (-x[1], x[0]))
    ]

    # 図面理解に有効な幾何学ヒント
    bbox = None
    if lines:
        xs = [l['x1'] for l in lines] + [l['x2'] for l in lines]
        ys = [l['y1'] for l in lines] + [l['y2'] for l in lines]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        bbox = {
            "min_x": round(min_x, 2), "min_y": round(min_y, 2),
            "max_x": round(max_x, 2), "max_y": round(max_y, 2),
            "width": round(max_x - min_x, 2), "height": round(max_y - min_y, 2),
        }

    hv = 0
    for l in lines:
        dx = abs(l['x2'] - l['x1'])
        dy = abs(l['y2'] - l['y1'])
        if dx < 1.0 or dy < 1.0:
            hv += 1
    orthogonality_ratio = round((hv / len(lines)), 3) if lines else 0.0

    door_like_arcs = 0
    for a in arcs:
        span = (a['end_a'] - a['start_a']) % 360
        if 80 <= span <= 100:
            door_like_arcs += 1

    drawing_type = "unknown"
    if room_summary and orthogonality_ratio >= 0.45:
        drawing_type = "floor_plan_like"

    insights = {
        "drawing_type": drawing_type,
        "orthogonality_ratio": orthogonality_ratio,
        "door_like_arcs": door_like_arcs,
        "bbox": bbox,
        "room_labels_with_coord": room_labels_with_coord,
    }

    info = {
        "lines": lines,
        "arcs": arcs,
        "texts": texts,
        "dims": dims,
        "rooms": room_summary,
        "insights": insights,
        "stats": {
            "lines": len(lines),
            "arcs": len(arcs),
            "texts": len(texts),
            "dims": len(dims),
            "rooms": len(room_summary),
        }
    }
    return info, None


def build_jww_full_context(jww_full, max_lines=50, max_arcs=30):
    """
    parse_jww_full()の結果をAI向けのテキストコンテキストに変換する。
    線・円弧・テキスト + 推定ヒントをまとめて返す。
    """
    if not jww_full:
        return ""

    stats = jww_full.get("stats", {})
    lines = jww_full.get("lines", [])
    arcs  = jww_full.get("arcs", [])
    texts = jww_full.get("texts", [])
    rooms = jww_full.get("rooms", [])
    dims = jww_full.get("dims", [])
    insights = jww_full.get("insights", {})

    ctx  = "【図面全体データ】\n"
    ctx += (
        f"線: {stats.get('lines',0)}本  円弧: {stats.get('arcs',0)}件  "
        f"テキスト: {stats.get('texts',0)}件  寸法候補: {stats.get('dims',0)}件\n\n"
    )

    if insights:
        ctx += "【図面理解ヒント（推定）】\n"
        dtype = insights.get('drawing_type', 'unknown')
        dtype_ja = "平面図に近い" if dtype == 'floor_plan_like' else "不明"
        ortho = insights.get('orthogonality_ratio', 0)
        door = insights.get('door_like_arcs', 0)
        ctx += f"  図面タイプ推定: {dtype_ja}\n"
        ctx += f"  直交線比率: {ortho:.3f}  ドア扇形候補: {door}件\n"
        bbox = insights.get('bbox')
        if bbox:
            ctx += f"  図面範囲: X[{bbox['min_x']},{bbox['max_x']}] Y[{bbox['min_y']},{bbox['max_y']}]"
            ctx += f"  幅:{bbox['width']} 高さ:{bbox['height']}\n"
        ctx += "\n"

    if rooms:
        ctx += "【部屋名・用途の候補】\n"
        ctx += "  " + "、".join(f"{r['name']}({r['count']})" for r in rooms[:25]) + "\n\n"

    if dims:
        ctx += "【寸法らしき値】\n"
        ctx += "  " + "、".join(d["value"] for d in dims[:40]) + "\n\n"

    if texts:
        room_like_texts = [t["text"] for t in texts if t.get("kind") == "room"]
        other_texts = [t["text"] for t in texts if t.get("kind") != "room"]
        if room_like_texts:
            ctx += "【部屋候補テキスト】\n"
            ctx += "  " + "、".join(room_like_texts[:30]) + "\n\n"
        if other_texts:
            ctx += "【その他テキスト】\n"
            ctx += "  " + "、".join(other_texts[:30]) + "\n\n"

    if lines:
        ctx += f"【主要な線（上位{min(max_lines, len(lines))}本）】\n"
        sorted_lines = sorted(lines, key=lambda l: l["length"], reverse=True)
        for l in sorted_lines[:max_lines]:
            ctx += f"  ({l['x1']},{l['y1']})→({l['x2']},{l['y2']}) 長さ:{l['length']}mm\n"
        ctx += "\n"

    if arcs:
        ctx += f"【円弧データ（{min(max_arcs, len(arcs))}件）】\n"
        for a in arcs[:max_arcs]:
            span = (a['end_a'] - a['start_a']) % 360
            hint = " ←ドア扇形" if 80 <= span <= 100 else ""
            ctx += f"  中心({a['cx']},{a['cy']}) 半径{a['r']}mm 角度{a['start_a']}°〜{a['end_a']}°{hint}\n"
        ctx += "\n"

    return ctx
