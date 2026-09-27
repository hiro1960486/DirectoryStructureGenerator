# Directory Structure Generator Ver.2.10.0

## 変更内容

- メイン画面上部に「関連アプリ」を追加しました。
- DirectoryStructureGenerator.PresetManagerとRenameWizardの実行ファイルを個別に指定できます。
- 「起動」ボタンから選んだアプリを直接起動できます。
- 実行ファイルの場所はユーザー設定に保存され、次回起動後も保持されます。
- 既存の設定ファイルとプリセットはそのまま読み込みます。

## 使い方

1. メイン画面上部の「関連アプリ」を開きます。
2. 各アプリの「参照…」から `.exe` を選びます。
3. 「起動」を押します。実行ファイルを移動した場合は、参照し直してください。

## 設定互換性

- 既存の設定形式とプリセット形式は変更していません。
- 実行ファイルの場所は `%APPDATA%/DirectoryStructureGenerator/config.json` に追加保存します。
