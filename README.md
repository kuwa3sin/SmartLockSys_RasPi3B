# SmartLock_FU_raspi3

Raspberry Pi上でサーボ（MG996R想定）を動かしてサムターンを回し、Web UI/REST APIで施錠・開錠するためのアプリです。
リードスイッチ2つ（施錠状態/ドア開閉）を使って状態表示・安全制御・自動施錠・完了確認を行います。

## できること

- 施錠/開錠（サーボを「中立→ターゲット→中立」に動かすモーメンタリー動作）
- 状態表示
	- 施錠状態: リードスイッチON=施錠 / OFF=開錠
	- ドア開閉: リードスイッチON=閉 / OFF=開
- Webのトグルボタン
	- 施錠中は「開錠」ボタン、開錠中は「施錠」ボタン
- 安全制御
	- ドアが開いているのに施錠しようとしたら拒否（サーバーは409、UIはダイアログ）
- 自動施錠
	- 「前回の開錠から指定秒数経過」かつ「ドアが閉」のときに施錠
- 完了確認
	- 施錠/開錠コマンド実行後、施錠状態リードスイッチで完了を確認（タイムアウト付き）
- 手動操作の反映
	- 指で施錠/開錠（サムターン手動）しても、リードスイッチの変化がWebに反映されます

## 依存関係

- Python 3.9+（Raspberry Pi OS推奨）
- Flask
- pigpio（推奨: `pigpiod`を使用）
- gpiozero（サーボ制御で使用。`GPIOZERO_PIN_FACTORY=pigpio`推奨）

例（Raspberry Pi OS）:

```bash
sudo apt update
sudo apt install -y python3-flask python3-gpiozero pigpio python3-pigpio
```

## 配線

### サーボ

- サーボ信号線: `servo.pin`（デフォルトはGPIO 12）
- 5V電源とGNDは必ず共有
- 電流が不足する場合は外部電源を利用（GND共通）

ハードウェアPWM対応ピン例:

| GPIO | PWM  |
| ---- | ---- |
| 12   | PWM0 |
| 13   | PWM1 |
| 18   | PWM0 |
| 19   | PWM1 |

### リードスイッチ（2つ）

設定は [SmartLock_FU_raspi3/config.json](SmartLock_FU_raspi3/config.json) の `sensors.lock` と `sensors.door` に書きます。

- 施錠状態スイッチ: ONなら施錠 / OFFなら開錠
- ドア開閉スイッチ: ONなら閉 / OFFなら開

多くの構成では「GPIO内部プルアップ + スイッチでGNDへ落とす」ため、
その場合は `pull_up=true` / `active_low=true` が合います。

## 設定（config.json）

設定は原則すべて [SmartLock_FU_raspi3/config.json](SmartLock_FU_raspi3/config.json) に集約しています。

主な項目:

- サーボ: `servo.*`
- センサー: `sensors.lock.*` / `sensors.door.*`
- Web: `web.*` / `web.ssl.*`
- 機能: `features.auto_lock_seconds` / `features.action_confirm_timeout_seconds`

## 起動

1) pigpioデーモン起動

```bash
sudo pigpiod
```

2) サーバー起動

```bash
cd SmartLock_FU_raspi3
GPIOZERO_PIN_FACTORY=pigpio python3 -m smartlock_servo --config config.json
```

## Web UI / API

- Web UI: `http(s)://<raspi-ip>:8080/`

API:

- `GET /api/status`
- `POST /api/lock`
- `POST /api/unlock`
- `POST /api/toggle`
- `POST /api/autolock`（例: `{"seconds": 10}`、`0`でOFF）

完了確認について:

- `POST /api/lock` / `POST /api/unlock` / `POST /api/toggle` は、実行後に施錠状態スイッチで完了を確認します。
- 確認できない場合は、コマンド自体は実行しつつレスポンスに `warning` と `message` を付与します。

## pigpio と gpiozero

- 入力（リードスイッチ）は pigpio を優先します（ノイズ対策の `glitch filter` が使えるため）。
- サーボ出力は gpiozero（AngularServo）を利用しますが、`GPIOZERO_PIN_FACTORY=pigpio` を指定すると内部バックエンドがpigpioになります。

## systemd サービス化

例: `/etc/systemd/system/smartlock.service`

```ini
[Unit]
Description=SmartLock service
After=network.target pigpiod.service
Requires=pigpiod.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/SmartLock_FU_raspi3
Environment=GPIOZERO_PIN_FACTORY=pigpio
ExecStart=/usr/bin/python3 -m smartlock_servo --config /home/pi/SmartLock_FU_raspi3/config.json
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

有効化:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pigpiod
sudo systemctl enable smartlock
sudo systemctl start smartlock
```

## トラブルシュート

| 症状                                             | 対処                                                                                                                       |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| センサーが反映されない                           | `pigpiod`が起動しているか確認（`sudo systemctl status pigpiod`）/ `config.json`のGPIO番号・`pull_up`・`active_low`を見直す |
| 「ドアが開いているため施錠できません」が出続ける | ドアスイッチの配線/論理（`active_low`）が逆の可能性                                                                        |
| 施錠/開錠の完了確認がタイムアウトする            | `features.action_confirm_timeout_seconds`を増やす / 施錠状態スイッチの位置を調整                                           |
| サーボが震える/ばらつく                          | `GPIOZERO_PIN_FACTORY=pigpio`を指定 / `pigpiod`を起動                                                                      |
| HTTPSを使いたい                                  | `web.ssl.mode`を`adhoc`または`cert`にして、必要なら`cert/key`を設定                                                        |
