# JW AI - JW_CAD AIアシスタント

JW_CAD（日本の建築CADソフト）と連携して、AIを使って図面作業を自然言語でアシストするツールです。

## 概要

- JWWファイルを読み込んでAIが図面を把握
- 自然言語で図面変更を指示（例：「玄関ドアの勝手を反転して」）
- AIが変換内容を提案し、承認すると図面に反映
- Claude / OpenAI / Gemini / Ollama 対応

## ファイル構成

```
C:\JWW\
├── jw_ai.py            # メインUIアプリ（常駐）
├── jwai_core.py        # 共通コアモジュール（JWC解析・変換・キャプチャ等）
├── jwai_gaihenkei.py   # 外部変形ブリッジスクリプト
├── JWAI.BAT            # JW_CAD外部変形エントリーポイント
└── JW_AI起動.bat       # jw_ai.py起動ショートカット（デスクトップに配置）
```

## セットアップ

### 必要環境

- Windows 10/11
- Python 3.10以上
- JW_CAD（Jw_win.exe が `C:\JWW\` にあること）

### Pythonパッケージのインストール

```bash
pip install anthropic openai google-generativeai pillow pywin32
```

### ファイルの配置

1. `jw_ai.py` `jwai_core.py` `jwai_gaihenkei.py` `JWAI.BAT` を `C:\JWW\` に配置
2. デスクトップに `JW_AI起動.bat` を配置

```bat
# JW_AI起動.bat の中身
@echo off
C:\Users\[ユーザー名]\AppData\Local\Programs\Python\Python312\pythonw.exe C:\JWW\jw_ai.py
```

### APIキーの設定

1. `JW_AI起動.bat` をダブルクリックして起動
2. 右上の「⚙ 設定」をクリック
3. 使用するAIを選択してAPIキーを入力
4. 「保存して閉じる」

## 使い方

### 基本フロー

```
1. JW_AI起動.bat をダブルクリック → jw_ai.py が起動

2. 右上「📂 JWWを開く」→ 図面ファイルを選択
   → JW_CADが自動で開く
   → AIが図面を解析して概要を説明

3. JW_CADで変更したい部分を範囲選択
   → 外部変形 → JWAI.BAT を実行
   → 右パネルに選択図形データが表示される

4. 右パネル「AIへの指示」欄に自然言語で指示を入力
   例：「玄関ドアの勝手を反転して」
       「この壁を100mm右に移動して」

5. AIが変更内容を返答
   → 「図面に反映」ボタンで確認
   → 「JW_CADに返す」ボタンでJW_CADに反映
```

### 対応している変換操作

| 操作 | 説明 |
|------|------|
| `arc_flip_x` | 円弧の向きを左右反転（ドア勝手変更に使用） |
| `arc_flip_y` | 円弧の向きを上下反転 |
| `mirror_x` | 図形全体を左右反転 |
| `mirror_y` | 図形全体を上下反転 |
| `rotate` | 図形を指定角度回転 |

## 技術仕様

### ファイル通信の仕組み

```
JW_CAD
  ↓ JWC_TEMP.TXT（選択図形データ）を書き出す
JWAI.BAT
  ↓ jwai_gaihenkei.py --notify-main を起動
jwai_gaihenkei.py
  ↓ jwai_ready.json でjw_ai.pyの起動確認
  ↓ jwai_signal.json でシグナルを送る
jw_ai.py（常駐）
  ↓ JWC_TEMP.TXTを読み込んで右パネルに表示
  ↓ AIが変換JSONを返す
  ↓ JWC_TEMP.TXTに変換結果を書き込む
  ↓ jwai_done.json で完了通知
jwai_gaihenkei.py
  ↓ 完了を確認してJW_CADに制御を返す
JW_CAD
  → 変換後のデータを図面に反映
```

### 使用する一時ファイル（すべて `C:\JWW\` 以下）

| ファイル | 用途 |
|----------|------|
| `JWC_TEMP.TXT` | JW_CADが書き出す選択図形データ（CP932） |
| `jwai_signal.json` | 外部変形開始シグナル |
| `jwai_done.json` | 処理完了通知 |
| `jwai_ready.json` | jw_ai.py起動完了マーカー（PID入り） |
| `jwai_main.lock` | jw_ai.pyのPIDロックファイル |

## 対応AIモデル

| AI | モデル | 備考 |
|----|--------|------|
| Claude | claude-sonnet-4-5 | 画像認識対応、推奨 |
| OpenAI | gpt-4o | 画像認識対応 |
| Gemini | gemini-1.5-pro | 画像認識対応 |
| Ollama | qwen2.5:7b | ローカル実行、画像なし |

## 既知の制限・今後の課題

- JWWバイナリの線・円弧座標の完全解析（実装中）
- 外部変形を使わないJWW直接編集モード（計画中）
- キャプチャ画像だけではAIの図面認識精度が低い → JWWデータ解析で補完予定

## ライセンス

MIT License

## 作者

ICHI130
