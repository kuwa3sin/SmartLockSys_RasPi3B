# Smart Lock (Python版)

Flask + gpiozero + pigpio でMG996R標準サーボを制御するスマートロックのコードです。REST API と簡易Web UIを同一プロセスで提供します。

## 依存関係

- Python 3.9+
- `gpiozero` (`sudo apt install python3-gpiozero`)
- `Flask` (`sudo apt install python3-flask`)
- `pigpio` (`sudo apt install pigpio python3-pigpio`)
- HTTPSを利用する場合: `python3-openssl`

## サーボ配線

- **GPIO 12 (BCM)** → サーボの信号線（ハードウェアPWM対応ピン）
- 5V 電源と GND を共有すること
- 電流が不足する場合は外部電源を利用（GNDを共通に）

### ハードウェアPWM対応ピン

| GPIO | PWMチャンネル |
| ---- | ------------- |
| 12   | PWM0          |
| 13   | PWM1          |
| 18   | PWM0          |
| 19   | PWM1          |

※ GPIO 12 または 18 を推奨（PWM0チャンネル）

## 起動方法

```bash
# pigpioデーモンを起動（初回のみ、または再起動後）
sudo pigpiod

# サーバー起動（GPIO 12でハードウェアPWM）
cd ~/smartlock
GPIOZERO_PIN_FACTORY=pigpio python3 -m smartlock_servo --pin 12
```

### 主要オプション

| オプション            | 説明                           | デフォルト |
| --------------------- | ------------------------------ | ---------- |
| `--pin`               | サーボ信号線のGPIO番号 (BCM)   | 18         |
| `--lock-speed`        | 施錠時の回転速度 (-1.0〜1.0)   | 0.5        |
| `--unlock-speed`      | 解錠時の回転速度 (-1.0〜1.0)   | -0.5       |
| `--rotation-time`     | 回転時間（秒）                 | 0.5        |
| `--return-time-ratio` | 戻り時間の補正係数             | 0.95       |
| `--dry-run`           | ハード無しで挙動をシミュレート | -          |
| `--ssl adhoc`         | 自己署名証明書を即席生成       | -          |
| `--ssl cert`          | 用意した証明書でHTTPS待受      | -          |

### 環境変数

オプションは環境変数でも指定できます。

```bash
export GPIOZERO_PIN_FACTORY=pigpio
export SMARTLOCK_SERVO_PIN=12
export SMARTLOCK_LOCK_SPEED=0.5
export SMARTLOCK_UNLOCK_SPEED=-0.5
export SMARTLOCK_ROTATION_TIME=0.5
export SMARTLOCK_RETURN_TIME_RATIO=0.95
python3 -m smartlock_servo
```

## Web UI / API

- Web UI: `http(s)://<ラズパイIP>:8080/`
- `POST /api/lock` / `POST /api/unlock`
- `POST /api/toggle` (施錠状態に応じて施錠/開錠)
- `POST /api/autolock` (自動施錠秒数を設定: `{"seconds": 10}` / `0`でOFF)
- `GET /api/status`

## リードスイッチ（施錠状態・ドア開閉）

GPIOにリードスイッチを2つ接続し、状態表示と安全制御に利用できます。

- 施錠状態スイッチ: **ONなら施錠 / OFFなら開錠**
- ドア開閉スイッチ: **ONなら閉 / OFFなら開**

配線は環境によって異なりますが、一般的には「GPIO + 内部プルアップ」「リードスイッチをGNDへ落とす」構成が多いです。
この場合、スイッチON（閉回路）時にGPIOがLOWになりやすいため、デフォルト設定は`ACTIVE_LOW=true`になっています。

### 環境変数

| 変数                               | 説明                               | デフォルト     |
| ---------------------------------- | ---------------------------------- | -------------- |
| `SMARTLOCK_LOCK_SWITCH_PIN`        | 施錠状態リードスイッチのGPIO(BCM)  | 未設定（無効） |
| `SMARTLOCK_DOOR_SWITCH_PIN`        | ドア開閉リードスイッチのGPIO(BCM)  | 未設定（無効） |
| `SMARTLOCK_LOCK_SWITCH_ACTIVE_LOW` | 施錠スイッチ: ONをLOWとして扱う    | `true`         |
| `SMARTLOCK_DOOR_SWITCH_ACTIVE_LOW` | ドアスイッチ: ONをLOWとして扱う    | `true`         |
| `SMARTLOCK_LOCK_SWITCH_PULL_UP`    | 施錠スイッチ: 内部プルアップを使う | `true`         |
| `SMARTLOCK_DOOR_SWITCH_PULL_UP`    | ドアスイッチ: 内部プルアップを使う | `true`         |

例:

```bash
export SMARTLOCK_LOCK_SWITCH_PIN=23
export SMARTLOCK_DOOR_SWITCH_PIN=24
export SMARTLOCK_LOCK_SWITCH_ACTIVE_LOW=true
export SMARTLOCK_DOOR_SWITCH_ACTIVE_LOW=true
```

### 動作仕様

- Webのボタンはトグル式です（施錠なら「開錠」、開錠なら「施錠」）。
- ドアが開いている状態で施錠しようとすると、ブラウザ側でダイアログを表示し、サーバー側でも施錠を拒否します。
- 自動施錠は「前回の開錠」からの経過時間と「ドアが閉」の両方を満たした場合に施錠します。

### pigpio と gpiozero の使い分け（推奨）

- **推奨: pigpio**
	- デーモン(`pigpiod`)経由でGPIOを扱うため、負荷が高い状況でも比較的安定しやすい
	- 入力側は`glitch filter`などのノイズ対策が強い
- **gpiozero**
	- Python側の高レベルAPIで扱いやすい
	- ただし本プロジェクトのサーボ制御は、`GPIOZERO_PIN_FACTORY=pigpio`を指定するとgpiozero内部でもpigpioバックエンドを利用できます

本実装ではリードスイッチ入力は **pigpioを優先**し、pigpioが利用できない場合のみgpiozeroへフォールバックします。

## サービス化

`/etc/systemd/system/smartlock.service` を作成：

```ini
[Unit]
Description=Smart Lock Service
After=network.target pigpiod.service
Requires=pigpiod.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/smartlock
Environment=GPIOZERO_PIN_FACTORY=pigpio
ExecStart=/usr/bin/python3 -m smartlock_servo --pin 12
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

有効化：
```bash
sudo systemctl daemon-reload
sudo systemctl enable pigpiod
sudo systemctl enable smartlock
sudo systemctl start smartlock
```

## トラブルシュート

| 症状                    | 対処法                                                           |
| ----------------------- | ---------------------------------------------------------------- |
| サーボが震える/ばらつく | `GPIOZERO_PIN_FACTORY=pigpio` を指定、`sudo pigpiod` を実行      |
| pigpioに接続できない    | `sudo pigpiod` でデーモンを起動                                  |
| 戻り位置がズレる        | `--return-time-ratio` を調整（戻りすぎ→小さく、足りない→大きく） |
| HTTPSで接続拒否         | ブラウザで `https://` を明示、自己署名は例外許可                 |
