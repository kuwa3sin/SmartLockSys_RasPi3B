# Smart Lock (Python版)

Flask + gpiozero + pigpio でFS90R連続回転サーボを制御するスマートロックサービスです。REST API と簡易Web UIを同一プロセスで提供します。

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
|------|--------------|
| 12   | PWM0         |
| 13   | PWM1         |
| 18   | PWM0         |
| 19   | PWM1         |

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

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--pin` | サーボ信号線のGPIO番号 (BCM) | 18 |
| `--lock-speed` | 施錠時の回転速度 (-1.0〜1.0) | 0.5 |
| `--unlock-speed` | 解錠時の回転速度 (-1.0〜1.0) | -0.5 |
| `--rotation-time` | 回転時間（秒） | 0.5 |
| `--return-time-ratio` | 戻り時間の補正係数 | 0.95 |
| `--dry-run` | ハード無しで挙動をシミュレート | - |
| `--ssl adhoc` | 自己署名証明書を即席生成 | - |
| `--ssl cert` | 用意した証明書でHTTPS待受 | - |

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
- `GET /api/status`

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

| 症状 | 対処法 |
|------|--------|
| サーボが震える/ばらつく | `GPIOZERO_PIN_FACTORY=pigpio` を指定、`sudo pigpiod` を実行 |
| pigpioに接続できない | `sudo pigpiod` でデーモンを起動 |
| 戻り位置がズレる | `--return-time-ratio` を調整（戻りすぎ→小さく、足りない→大きく） |
| HTTPSで接続拒否 | ブラウザで `https://` を明示、自己署名は例外許可 |
