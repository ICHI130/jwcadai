# JW AI - Claude Code 引き継ぎ情報

## プロジェクト概要

JW_CAD（日本の建築CADソフト）と連携するAIアシスタント。
自然言語で図面変更を指示するとAIが実行するツール。

## 実行環境

- Python 3.12: `C:\Users\ksnk1\AppData\Local\Programs\Python\Python312\`
- JW_CAD本体: `C:\JWW\Jw_win.exe`
- 実行ファイル置き場: `C:\JWW\`
- 開発リポジトリ: `C:\Users\ksnk1\OneDrive\デスクトップ\cad\`
- GitHub: https://github.com/ICHI130/jwcadai

## ファイル構成

```
C:\JWW\（実行環境）
  jw_ai.py           メインUIアプリ（常駐、tkinter GUI）
  jwai_core.py       共通コアモジュール（parse/write/config）
  jwai_gaihenkei.py  外部変形ブリッジ（--notify-mainで起動）
  JWAI.BAT           JW_CAD外部変形エントリー（CP932必須、REM #jw必須）

C:\Users\ksnk1\OneDrive\デスクトップ\cad\（開発リポジトリ）
  ※上記と同内容 + CLAUDE.md / AGENTS.md / README.md / .gitignore
```

コードを変更したら両方に反映すること（C:\JWW\ と cad\）。

## 一時ファイル（C:\JWW\、Gitに含めない）

| ファイル | 用途 |
|----------|------|
| JWC_TEMP.TXT | JW_CADが書き出す選択図形データ（CP932） |
| jwai_signal.json | 外部変形開始シグナル |
| jwai_done.json | 処理完了通知 |
| jwai_ready.json | jw_ai.py起動完了マーカー（PID入り） |
| jwai_main.lock | PIDロックファイル |
| ~/.jwai_config.json | APIキー設定（絶対にGitにpushしない） |

## 動作フロー

```
JW_CAD → JWAI.BAT → jwai_gaihenkei.py --notify-main
  → jwai_ready.json で jw_ai.py の起動確認
  → 未起動なら自動起動（最大20秒待機）
  → jwai_signal.json でシグナル送信
  → jw_ai.py が JWC_TEMP.TXT を読んで外部変形タブに表示
  → ユーザーがAIに指示 → 「図面に反映」→「JW_CADに返す」
  → jwai_done.json 作成 → jwai_gaihenkei.py が終了 → JW_CAD反映
```

## 重要な実装上の注意

1. **JWAI.BATはCP932（Shift-JIS）で保存**。UTF-8にするとJW_CADが認識しない
2. **「REM #jw」行が必須**。これがないとJW_CADの外部変形リストに出ない
3. **バックグラウンド起動はpythonw.exe**。python.exeはコンソールが出る
4. **tkinterのpack順序**：ボタンは先に`side='bottom'`でpack、ScrolledTextは後に`expand=True`
5. **JWCTempWatcherのmtime初期化**：起動時点のmtimeで初期化（0.0だと古いデータを誤読）
6. **キャプチャは非同期**：threading.Threadで実行（メインスレッドブロック防止）

## 現在の既知の課題（優先度順）

### 高
- [ ] JWWバイナリ解析（parse_jww_full）の精度検証
      → 実際の図面で線・円弧座標が正しく取れているか確認
- [ ] AIの図面認識精度向上
      → 0x30系レコードから文字/寸法/部屋候補抽出を追加済み。実図面で精度検証を継続
- [ ] エンドツーエンドテストが不十分
      → 「図面に反映」→「JW_CADに返す」で実際に図面変更されるか確認

### 中
- [ ] JWW直接編集モード
      → 外部変形操作なしでjw_ai.pyから直接JWWを読み書き
- [ ] AIの変換JSON出力の安定化
      → Few-shotプロンプトやJSON Schema指定で不安定さを解消
- [ ] テスト用スクリプト作成
      → JW_CADなしでJWC_TEMP.TXTを手動配置して外部変形フローをテスト

### 低
- [ ] サブスクリプション課金機能（月額¥1,000、Stripe連携）
- [ ] PyInstallerでのexe化・インストーラー作成

## Gitワークフロー

```bash
# 変更後
git add jw_ai.py jwai_core.py jwai_gaihenkei.py jwai.bat
git commit -m "変更内容の説明"
git push origin main
```

git は `C:\Program Files\Git\bin\git.exe` にある。
PowerShellでは直接 `git` が使えない場合があるため、
Pythonスクリプト経由で実行するか、フルパス指定で実行。

## 2026-02 追加実装メモ（Codex/Claude共通）

- `jw_ai.py`
  - ヘッダーに「❓ はじめてガイド」ボタンを追加
  - 起動時チャットに初回3ステップ（設定→JWW読込→外部変形）を表示
- `jwai_core.py`
  - `parse_jww_full()`:
    - 0x30〜0x35レコードを優先スキャンし、文字列候補を抽出
    - 文字列を「部屋名候補」「寸法候補」に分類して `rooms` / `dims` を生成
    - 既存の可変長文字列スキャンは fallback として維持
  - `build_jww_full_context()`:
    - AI向けコンテキストに「部屋名・用途の候補」「寸法らしき値」を追加
  - `insights` を追加（図面タイプ推定/直交線比率/ドア扇形候補/図面範囲）
  - 全角半角ゆれ・寸法表記（R250, φ100, 1000mm）の分類を強化

- 期待効果:
  - 線・円弧だけでなく、平面図の用途（玄関/LDK/水回り）をAIが説明しやすくなる

- 次担当へのTODO:
  1. 実図面（住宅・店舗など複数）で誤抽出率を計測
  2. 寸法記号（mm, φ, R）付き文字列の分類精度を改善
  3. `0x30` 台レコード内の厳密な座標オフセット確定

## APIキー

~/.jwai_config.json に保存。jw_ai.pyの設定画面から入力・保存する。
このファイルは絶対にGitにpushしないこと（.gitignoreで除外済み）。
