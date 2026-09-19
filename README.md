# Directory Structure Generator Ver.2.0.2

フォルダー構成を走査し、必要な項目だけを **TXT / HTML / CSV / JSON** に出力するWindows向けGUIアプリです。

- Version: 2.0.2
- Updated: 2026-09-20
- Author: hiro1960
- UI: PySide6
- 対応OS: Windows 10 / 11（64ビット推奨）
- Python: 3.10以上（Python 3.13対応）

## 今回の主な改善

- Windows 11になじむダーク／ライト対応UI
- 大きなフォルダーでも画面を固めにくいバックグラウンド走査
- 走査の中止
- ツリーの事前プレビューと検索・コピー
- フォルダー数、ファイル数、合計容量、除外数、エラー数の表示
- 出力先が対象フォルダー内にある場合、その出力先を自動除外
- Excelで開きやすいUTF-8 BOM付きCSV
- CSV数式インジェクション対策
- 設定と直近10件のフォルダー履歴をユーザー領域へ保存

## フィルター機能

初期設定の「開発用おすすめ」では、次のような巨大・一時フォルダーを除外します。

```text
.git                 Git内部データ
node_modules         JavaScript依存パッケージ
.venv / venv / env   Python仮想環境
__pycache__          Pythonキャッシュ
.vs / bin / obj      Visual Studio・.NET生成物
dist / build         ビルド出力
.pytest_cache        テストキャッシュ
.idea                IDE設定
target               Rust・Javaなどの生成物
```

次の条件も組み合わせられます。

- 除外フォルダー：1行に1つ指定
- 除外拡張子：`.log, .tmp, .pyc` のように指定
- 対象拡張子：`.py, .md` のように指定。空欄ならすべて
- 除外パターン：`*_backup, *.egg-info, temp/*` のようなワイルドカード
- 隠しファイルを含める／含めない
- 空フォルダーを含める／含めない
- 最大階層
- シンボリックリンクをたどる／たどらない

> シンボリックリンクをたどる設定は、リンクが循環しているフォルダーでは使用しないでください。

## まず試す

1. ZIPを右クリックし、**「すべて展開」**します。
2. 展開したフォルダーの `START_APP.bat` をダブルクリックします。
3. 初回は専用環境とPySide6を自動準備するため、数分かかる場合があります。
4. 「対象フォルダー」と「出力先」を選びます。
5. まず「プレビュー走査」を押します。
6. 内容を確認して「構成ファイルを生成」を押します。

`START_APP.bat`はCMD画面を勝手に閉じません。起動に失敗した場合は、同じフォルダーの`startup_error.log`に原因を保存して画面にも表示します。

> ZIPを開いた画面からBATを直接実行しないでください。必ず「すべて展開」してから使用します。

## EXEを作る

1. `build_exe.bat` をダブルクリックします。
2. `.venv`や必要なパッケージがなければ、自動的に準備されます。
3. 自動テスト後、`dist\DirectoryStructureGeneratorGUI` にEXE一式ができます。
4. `release`に配布用ZIPとZIPのSHA256ができます。

EXEはPyInstallerの`onedir`形式です。`DirectoryStructureGeneratorGUI.exe`だけを取り出さず、フォルダー一式で配布してください。EXEのハッシュは`SHA256_EXE.txt`へ、配布ZIPのハッシュは`.sha256.txt`へ自動出力されます。

## ショートカット

| キー | 動作 |
|---|---|
| `Ctrl+P` | プレビュー走査 |
| `Ctrl+G` | 構成ファイルを生成 |
| `Ctrl+F` | プレビュー検索欄へ移動 |

## 出力ファイル

対象フォルダー名が`MyProject`の場合、次の名前で保存します。

```text
MyProject_tree.txt
MyProject_index.html
MyProject_file_list.csv
MyProject_tree_data.json
```

HTMLには「すべて開く」「すべて閉じる」「名前を検索」があり、単体で閲覧できます。

## 設定の保存場所

設定は配布フォルダーを汚さず、次のユーザー領域に保存します。

```text
%APPDATA%\DirectoryStructureGenerator\config.json
```

設定を初期化したい場合は、アプリ終了後にこのファイルを削除してください。

## フォルダー構成

```text
app.py                 起動ファイル
dsg_app/               アプリ本体
tests/                 自動テスト
setup_dev.bat           初回セットアップ
START_APP.bat            推奨起動（自動準備・エラー記録）
run_app.bat              START_APP.batへの互換入口
run_tests.bat           自動テスト
build_exe.bat           EXE作成
requirements.txt        実行用ライブラリ
requirements-build.txt  ビルド・テスト用ライブラリ
```

## 注意事項

- 本ツールはファイルを読み取って一覧を作ります。元ファイルを変更・削除しません。
- アクセス権がないフォルダーはエラー件数として記録し、可能な範囲で処理を続けます。
- 出力先は対象フォルダーと同じ場所には指定できません。
- 署名なしEXEでは、Windows SmartScreenの確認画面が表示される場合があります。

## 起動できないとき

1. CMD画面を閉じず、最後に表示されたエラーを確認します。
2. アプリと同じフォルダーの`startup_error.log`を開きます。
3. アプリ内部のエラーは`%LOCALAPPDATA%\DirectoryStructureGenerator\app_error.log`にも保存されます。
4. 相談するときは、このログを添付してください。
