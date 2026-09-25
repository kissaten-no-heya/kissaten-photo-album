# 喫茶店の部屋 · フォトアルバム

Google Drive → GitHub Actions → GitHub Pages → VRChat。

- 公開 JSON: https://kissaten-no-heya.github.io/kissaten-photo-album/album.json
- ページ一覧: https://kissaten-no-heya.github.io/kissaten-photo-album/

## 普段の使い方

Drive に PNG / JPEG / WebP を追加するだけ。毎時17分（UTC・日本時間とも分は同じ）に更新を試みます。GitHub の混雑で遅れる場合があります。すぐ更新する場合は Actions → Update photo album → Run workflow。

Drive のフォルダと写真は、リンクを知っている人が閲覧できる設定が必要です。取得できない場合は処理を失敗させ、前回の公開版を保持します。Drive の共有設定はこのプログラムでは変更しません。子フォルダも対象です。

## 配置と保存

新しい写真をファイル名順（同名は Drive ID 順）に並べ、縦横比に合わせて1〜3枚ずつ配置。写真全体を収め、切り抜きません。A4比率の1448×2048 JPEGです。

`album_state.json` に写真IDのSHA-256ハッシュ・配置・画像ハッシュを保存し、`public/pages` に完成画像を保存します。元のDrive IDとファイル名は保存しません。次回は既存ページに空きがあっても変更せず、新しいページを追加します。写真の改名・削除・同じIDでの差し替えは、既に確定したページへ反映しません。削除が必要な場合は公開済み画像と履歴を含め別途対応してください。

同じ写真でも別の Drive ID でアップロードし直すと新規写真として追加されます。元画像そのものはリポジトリに保存せず、合成ページと配置記録のみ保存します。

## Unity V1.2 との接続

Builder の `album.json URL` に上記URLを設定して作成・更新します。JSONの数値 `pageCount` と `pages/page_0001.jpg` からの連番が既存Controllerの契約です。現在のUnity側予約URLは100ページなので、上限を超える更新は停止します。増やす際はUnityの予約数と `album_config.json` の `maxPages` を一緒に増やして再アップロードしてください。

## 開発・復旧

Python 3.12で `pip install -r requirements.txt`、`python -m unittest -v`。ローカル実行時は環境変数 `DRIVE_FOLDER_ID` を設定してから `python build_album.py`。

入力フォルダIDはGitHubの Settings → Secrets and variables → Actions にあるRepository secret `DRIVE_FOLDER_ID` で管理します。公開ファイルやログに値を書かないでください。Secret未設定時は更新を停止し、前回の公開版を保持します。

この設定は元写真を非公開にするアクセス制御ではありません。Driveは匿名取得可能な共有設定を引き続き必要とし、完成ページも公開です。過去のコミットに記載された情報は、現在のファイルから削除してもGit履歴に残ります。ハッシュ化も過去の公開IDを無効化するものではありません。

Pages の Source は **GitHub Actions**。ワークフローが状態と画像を main に保存した後、同じ内容を公開します。保存や取得が失敗すれば公開しません。並行更新は直列化し、通常の push が競合した場合は失敗させて既存データを保護します。

既存画像が欠けたりハッシュが違う場合は、Git履歴から `album_state.json` と `public/pages` を同じコミットの状態へ戻してください。状態ファイルの削除・初期化は既存配置を失わせるため行わないでください。公開済みページは再描画せず、そのバイト列を保持します。
