# JW AI - Codex Agent 引き継ぎ情報

## プロジェクト概要

JW_CAD（日本の建築CADソフト）と連携するAIアシスタント。
自然言語で図面変更を指示するとAIが実行するツール。
Windows専用。Python 3.12 + tkinter GUI。

## 実行環境

- OS: Windows 10/11
- Python: `C:\Users\ksnk1\AppData\Local\Programs\Python\Python312\python.exe`
- pythonw: `C:\Users\ksnk1\AppData\Local\Programs\Python\Python312\pythonw.exe`
- JW_CAD: `C:\JWW\Jw_win.exe`
- 実行ファイル: `C:\JWW\`
- リポジトリ: `C:\Users\ksnk1\OneDrive\デスクトップ\cad\`
- GitHub: https://github.com/ICHI130/jwcadai

## ファイル構成

```
jw_ai.py           メインUIアプリ（tkinter、常駐プロセス）
jwai_core.py       共通コアモジュール
jwai_gaihenkei.py  外部変形ブリッジ（JW_CADから呼ばれる）
jwai.bat           JW_CAD外部変形エントリー
CLAUDE.md          Claude Code用引き継ぎ（このファイルと同内容）
AGENTS.md          このファイル
README.md          ユーザー向けドキュメント
.gitignore         APIキー・図面ファイル等の除外
```

コードを変更したら `C:\JWW\` にも同じファイルをコピーすること。

## アーキテクチャ

### ファイル通信方式

JW_CADとjw_ai.pyはJSONファイル経由で通信する（パイプ・ソケット不使用）。

```
JW_CAD
  ↓ JWC_TEMP.TXT 書き出し（選択図形データ、CP932エンコード）
jwai_gaihenkei.py（--notify-mainで起動）
  ↓ jwai_ready.json でjw_ai.py起動確認（PIDチェック）
  ↓ 未起動なら pythonw.exe で jw_ai.py を自動起動
  ↓ jwai_signal.json にシグナル書き出し
jw_ai.py（JWCTempWatcherが1秒ポーリング）
  ↓ JWC_TEMP.TXT 読み込み → 外部変形タブに表示
  ↓ AIが変換JSONを生成
  ↓ JWC_TEMP.TXT に書き戻し
  ↓ jwai_done.json 作成
jwai_gaihenkei.py
  ↓ jwai_done.json 検知 → プロセス終了
JW_CAD → 図面反映
```

### 主要クラス（jw_ai.py）

- `JwAiApp` : メインアプリクラス
  - `_build_gaihenkei_panel()` : 外部変形タブUI
  - `on_jwc_updated()` : JWC_TEMP.TXT更新時のコールバック
  - `gaihenkei_ask_ai()` : AIへの問い合わせ
  - `gaihenkei_apply_changes()` : 「図面に反映」ボタン処理
  - `gaihenkei_return_to_jwcad()` : 「JW_CADに返す」ボタン処理
  - `load_jww()` : JWWファイルを開いてAI解析
- `JWCTempWatcher` : JWC_TEMP.TXTの変更監視（1秒ポーリング）

### 主要関数（jwai_core.py）

- `parse_jwc_temp(filepath)` : JWC_TEMP.TXT解析
- `elements_to_context(elements, raw_lines)` : AIコンテキスト生成
- `write_result_to_jwc(elements, modified_lines_map)` : JWC_TEMP.TXTへの書き戻し
- `apply_transform(elements, transform_json)` : 変換JSON適用
- `parse_jww_full(filepath)` : JWWバイナリから線・円弧座標を抽出
- `build_jww_full_context(jww_full)` : AI向けテキスト生成
- `create_lock() / remove_lock()` : jwai_main.lock と jwai_ready.json の管理
- `write_done()` : jwai_done.json の作成

## 重要な制約・注意事項

1. **JWAI.BATはCP932（Shift-JIS）で保存すること**
   UTF-8だとJW_CADが外部変形として認識しない

2. **JWAI.BATの先頭付近に「REM #jw」が必須**
   この行がないとJW_CADの外部変形リストに表示されない

3. **バックグラウンド起動はpythonw.exe**
   python.exeだとコンソールウィンドウが出てしまう

4. **tkinter pack順序に注意**
   ボタン等の固定要素は先に `side='bottom'` でpack。
   その後に `expand=True` のScrolledTextをpack。
   逆だとScrolledTextが全スペースを占有してボタンが隠れる。

5. **JWCTempWatcherのmtime初期化**
   `self.last_jwc_mtime` は起動時点のファイルmtimeで初期化する。
   0.0で初期化すると起動時に古いJWC_TEMP.TXTを誤読する。

6. **スクリーンショット取得は非同期で行う**
   `capture_jwcad_window()` はメインスレッドで呼ぶと「応答なし」になる。
   必ず `threading.Thread` で非同期実行すること。

7. **git操作**
   `C:\Program Files\Git\bin\git.exe` にgitがある。
   PowerShellでそのままgitコマンドを使えない場合は、
   Pythonのsubprocessで実行するか、フルパス指定で実行する。

## 現在の課題（優先度順）

### 高優先度
1. **JWWバイナリ解析の精度検証**
   `parse_jww_full()` が実際の図面で正しく動くか未検証。
   実際の.jwwファイルでテストして線・円弧座標の正確性を確認する。

2. **AIの図面認識精度向上**
   現状：座標データ＋JW_CADキャプチャ画像でAIに認識させている。
   課題：文字・寸法・注記データの抽出が未実装。
   対応：JWWバイナリから文字データ（レコードタイプ0x30台）も抽出する。

3. **エンドツーエンドテスト**
   「図面に反映」→「JW_CADに返す」→実際にJW_CADの図面が変わるか
   十分な確認ができていない。実図面でのテストが必要。

### 中優先度
4. **テスト用スクリプト作成**
   JW_CADを使わずに外部変形フロー全体をテストできるスクリプト。
   サンプルのJWC_TEMP.TXTを用意してjwai_signal.jsonを手動送信する仕組み。

5. **JWW直接編集モード**
   外部変形（範囲選択→実行）の操作なしに、
   jw_ai.pyから直接JWWバイナリを読み書きして図面変更する機能。

6. **AIの変換JSON安定化**
   AIが返す変換JSONの形式が不安定。
   Few-shotプロンプトやJSON Schema指定で安定化する。

### 低優先度
7. サブスクリプション課金機能（月額¥1,000）
8. PyInstallerでのexe化・インストーラー作成

## テスト方法

### JW_CADなしでのテスト

```python
import json, shutil, time

# 1. サンプルJWC_TEMP.TXTをC:\JWWに置く
shutil.copy("sample_jwc_temp.txt", r"C:\JWW\JWC_TEMP.TXT")

# 2. jw_ai.pyが起動していることを確認（jwai_ready.jsonが存在する）

# 3. シグナルを手動送信
with open(r"C:\JWW\jwai_signal.json", "w") as f:
    json.dump({"event": "gaihenkei_started", "timestamp": time.time()}, f)

# 4. jw_ai.pyの外部変形タブに通知が出ることを確認
# 5. AIに指示→「図面に反映」→「JW_CADに返す」
# 6. jwai_done.jsonが作成されることを確認
```

## Gitワークフロー

変更後は必ずコミット＆プッシュ：

```bash
git add jw_ai.py jwai_core.py jwai_gaihenkei.py jwai.bat
git commit -m "作業内容の説明"
git push origin main
```

このリポジトリはClaude CodeとOpenAI Codexが交互に作業する。
コミット前に `git pull` で最新を取得すること。
