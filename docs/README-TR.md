# esplink

[English README](../README.md)

Bir ESP32'ye tek bir firmware'i bir kez yükleyin, ardından **tüm çevre
birimlerini** Python veya JavaScript ile USB, Bluetooth ya da Wi-Fi üzerinden
sürün. GPIO, PWM, ADC, DAC, dokunmatik, I2C, SPI, UART, RMT, 1-Wire, CAN, I2S,
dosyalar, NVS, uyku, Wi-Fi soketleri, BLE, ESP-NOW, Ethernet, kamera, OTA.
Proje başına yeniden flash yok.

Firmware küçük donanım ilkelleri sunar; cihaz protokolleri (WS2812, NEC IR, DHT,
1-Wire arama, step motor rampaları) okunması ve değiştirilmesi kolay olan
bilgisayar tarafında yaşar.

![Köprü üzerinden sürülen OLED](img/oled.png)

## Kurulum

```sh
pip install esplink               # USB + Bluetooth + Wi-Fi
pip install "esplink[oled]"       # + ekranlar için Pillow   ([mcp], [flash], [all])
npm i @hamzayslmn/esplink         # JavaScript: tarayıcı ve Node
```

**Firmware'i bir kez yükleyin** — hazır imaj, Arduino IDE gerekmez:

```sh
uvx --from "esplink[flash]" flash
```

Ya da derleyin: Arduino IDE'de **esplink** kütüphanesini kurun (core 3.x) ve
*File → Examples → esplink → Bridge* örneğini yükleyin. arduino-cli ile depodaki
`sketch.yaml` kartı seçer, `--fqbn` gerekmez:

```sh
arduino-cli compile examples/Bridge && arduino-cli upload -p COM3 examples/Bridge
```

Ayrıntılar ve derleme bayrakları: [FIRMWARE.md](FIRMWARE.md).

## Kullanım

```python
from esplink import Bridge

with Bridge() as esp:                     # önce USB, sonra Bluetooth, sonra Wi-Fi
    esp.gpio.mode(esp.pins.led, "output") # kartın LED'i (S3/C3: esp.pins.rgb'de bir WS2812)
    esp.gpio.write(esp.pins.led, 1)       # pinin geri okunan seviyesini döndürür
    print(esp.adc.read_mv(34), "mV")
    esp.pwm.servo(13, angle=90)
    esp.i2c.init()                        # kartın SDA/SCL'si; ya da init(sda=1, scl=2)
    print(esp.i2c.scan())
```

### Kart ve bağlantı seçimi

```python
Bridge("relays")                    # ada göre (esplink set-name relays) veya MAC
Bridge(port="COM7")                 # bir seri port
Bridge(ble=True)                    # yalnız Bluetooth   (ble=False: yalnız USB)
Bridge(host="192.168.1.50")         # Wi-Fi; wifi=True kartları yayınla bulur
Bridge(ble=True, password="...")    # kablosuz bağlantılar kimlik doğrular (varsayılan "esplink")
```

Bir bağlantı anahtarı o bağlantıyı sabitler — sessiz geri dönüş yok. Komut
satırında: `esplink` (bilgi), `esplink ports`, `esplink scan [--ble]`,
`esplink set-name AD`.

### Çevre birimleri

| | |
|---|---|
| `esp.gpio` | modlar, okuma/yazma, `write_many`, `status`, kenar kesmeleri → callback'ler (µs zaman damgası) |
| `esp.adc` / `dac` / `touch` | mV okumaları, gerçek 8-bit DAC + kosinüs üreteci, dokunmatik pedler |
| `esp.pwm` / `mcpwm` | LEDC duty/ton/servo; deadtime'lı tamamlayıcı çiftler |
| `esp.i2c` / `spi` / `uart` | kartın varsayılan pinlerinde (`esp.pins`) ya da verdiğiniz pinlerde veri yolları; UART portları pyserial gibi davranır |
| `esp.rmt` / `onewire` | darbe dizileri ve 1-Wire ilkelleri (aşağıdaki sürücüler) |
| `esp.can` / `i2s` | TWAI veri yolu; PCM giriş/çıkış |
| `esp.fs` / `nvs` / `ota` | LittleFS/SD dosyaları; anahtar/değer deposu; bağlantı üzerinden firmware güncelleme |
| `esp.wifi` / `net` / `eth` | bağlanma/AP/tarama; kart üzerinden TCP/UDP soketleri; Ethernet |
| `esp.ble` / `espnow` | tarama, yayın, GATT sunucu/istemci; ESP-NOW mesajlaşma |
| `esp.watch` | kartın kendisinin değerlendirdiği — ve uyguladığı — kurallar, `do=("gpio", 26, 1)` |
| `esp.camera` | JPEG anlık görüntüler (ESP32-CAM, XIAO-S3-Sense) |
| `esp.deep_sleep` / `light_sleep` / `cpu_freq` / `radio_off` | güç |

### Sürücüler

24 sürücü dahil, hepsi saf Python: `neopixel`, `dht`, `ds18b20`, `hcsr04`,
`ir_sender`, `stepper`, `oled`, `bme280`, `mpu6050`, `ads1115`, `pca9685`,
`motor`, `nrf24`, `sx127x`… (`esplink drivers` hepsini listeler).

```python
strip = esp.neopixel(pin=5, n=30)
strip.fill((0, 0, 64)); strip.show()
print(esp.dht(4).read())                          # (23.1, 65.5)
with esp.oled(sda=21, scl=22).draw() as d:        # PIL ile çizim
    d.text((0, 0), "Merhaba!", fill=1)
```

Sürücü, köprüyü ilk argüman olarak alan herhangi bir sınıftır;
`register_driver("ad", sinif)` `esp.ad(...)` kısayolunu ekler. Rehber:
[DRIVERS.md](DRIVERS.md).

### Raspberry Pi kodu, değiştirmeden

Pi'nin kendi API'leri ESP32'nin pinlerinde çalışır — **gpiozero**, **RPi.GPIO**,
**spidev**, **smbus2**, **Adafruit CircuitPython** ve **luma**. Pin numaraları
ESP32 GPIO numaralarıdır.

```sh
python -m esplink.compat --board relays blink.py    # değiştirilmemiş bir Pi betiği
```

```python
from esplink import Bridge, compat

compat.install(Bridge())             # RPi.GPIO, spidev, smbus2 + gpiozero artık ESP32'yi sürer
from gpiozero import LED, Button
led, btn = LED(2), Button(4)
btn.when_pressed = led.toggle        # callback'ler pinleri serbestçe sürebilir
```

Bir Pi'de olmayanlar: gerçek ADC ve DAC, kapasitif dokunmatik, her pinde PWM,
ESP-NOW, kart üstü kurallar (`esp.watch`), uyku, OTA — üstelik Bluetooth
üzerinden de çalışır.

### Thread'ler ve asyncio

Tek bir `Bridge` thread-safe'tir ve eşzamanlı istekleri boru hattına alır;
firmware'in RTOS görevleri bunları yan yana çalıştırır, böylece yavaş bir Wi-Fi
çağrısı GPIO okumasını asla bekletmez.

```python
import esplink, asyncio
from esplink import AsyncBridge, constants as C
from esplink.gpio import EdgeEvent

async def main():
    async with AsyncBridge(ble=False) as esp:     # veya AsyncBridge.wrap(esplink.connect())
        level, mv = await asyncio.gather(esp.gpio.write(2, 1), esp.adc.read_mv(34))
        await esp.gpio.watch(4, edge="falling")
        async for ev in esp.events(C.GPIO_EDGE_EVT, EdgeEvent.parse):
            print(ev.pin, ev.level)

asyncio.run(main())
```

### Çok sayıda kart, Wi-Fi

```python
with Bridge.all() as boards:                      # masadaki her kart
    boards.each(lambda esp: esp.ping())           # -> {kimlik: sonuç}
    boards["relays"].gpio.write(2, 1)

with Bridge(port="COM3") as usb:                  # Wi-Fi'yi bir kez tanımlayın
    usb.wifi.link_setup("ssid", "sifre")          # ya da eve bağlanmak için server="10.0.0.5"
with Bridge.all(wifi=True) as boards:
    boards.wait_for(100, timeout=60)              # eve bağlanan kartlar gelmeye devam eder
```

## JavaScript

Aynı protokol ve Python ile aynı adlar (`esp.info.fw_version`, `esp.adc.read_mv`, …) — [js/README.md](../js/README.md).

```js
import { connect_serial, connect_ble } from "@hamzayslmn/esplink/web";   // veya "@hamzayslmn/esplink/node"
const esp = await connect_serial();                          // bir tıklama işleyicisinden
await esp.gpio.write(2, 1);
console.log(await esp.adc.read_mv(34));
```

## Yapay zekâ ajanları (MCP)

`esplink-mcp`, her API metodunu Claude Code, Gemini CLI, Codex, Cursor ve Ollama
istemcilerine bir araç olarak sunar ([MCP.md](MCP.md)):

```sh
uv tool install "esplink[mcp]"
```

## Hız

Gerçek kartlarda ölçüldü, Windows 11 bilgisayar:

| | klasik ESP32 (CP2102) | ESP32-S3 (native USB) | nRF52840 Pro Micro |
|---|---|---|---|
| USB ping p50 / p99 | 1,9 / 2,1 ms | 0,23 / 0,36 ms | 0,30 / 0,43 ms |
| USB bağlantı süresi | 1–2,5 sn (kartı resetler) | 0,01 sn | 0,01 sn |
| USB boru hattı (8 thread) | 3.800 istek/sn | 7.500–9.200 istek/sn | 4.400 istek/sn |
| BLE ping p50 | 15 ms | 15 ms | 15 ms |
| dosya okuma USB / BLE | 142 / 40 KB/sn | 749 / 67 KB/sn | 246 / 27 KB/sn |
| GPIO kenarı → bilgisayar olayı | | +0,16 ms | |
| I2C register okuma | | 0,38 ms | |
| OLED 128×64, tipik / tam kare | | 477 / 33 fps (1 MHz I2C'de 58) | |

Bilgisayar istek başına yaklaşık 20 µs harcar. Bir BLE gidiş-dönüşü iki bağlantı
aralığıdır: kart tam 7,5 ms ister, Windows bunu bağlandıktan yaklaşık 2 sn sonra
verir (7,5–15 ms aralığı sunulunca 15'i seçer).

## Donanım

| kart | derleme | notlar |
|---|---|---|
| klasik **ESP32** (CP2102/CH340) | `arduino-cli compile examples/Bridge` | her şey; BLE varken SD'ye yer yok (LittleFS çalışır) |
| **ESP32-S3** (native USB veya UART portu) | `--profile esp32s3` | iki USB portu da bağlantıdır; light sleep USB dışı bir bağlantı ister |
| **ESP32-C3** | `--fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc,PartitionScheme=min_spiffs` | derleme kontrolü yapıldı |
| **nRF52840** Pro Micro | `--profile promicro examples/Bridge_nRF52` | BLE, GPIO, ADC, PWM, I2C, SPI, UART, 1-Wire, dosyalar, NVS, uyku |

arduino-esp32 core 3.x (3.3.12 ile test edildi). Firmware her çipin neye sahip
olduğunu bildirir; eksik olan her şey `UnsupportedError` yükseltir. Kartın
bilgisayar bağlantısı için kullandığı pinler `BAD_PIN` ile reddedilir.
Ayrıntılar: [FIRMWARE.md](FIRMWARE.md).

## Sorun giderme

Hatalar komutu ve neye bakılacağını söyler; zaman aşımında kart ping'lenir,
böylece bağlantının mı koptuğu yoksa tek bir çerçevenin mi kaybolduğu anlaşılır.
`ESPLINK_DEBUG=1 python app.py` her isteği izler; `esp.free_heap()` heap ve
kaybolan çerçeve sayaçlarını bildirir.

## Yapı

| yol | |
|---|---|
| `src/`, `examples/Bridge/` | Arduino kütüphanesi: firmware ve sketch'i |
| `python/` | Python paketi `esplink`, testler, örnekler |
| `js/` | JavaScript paketi `esplink` |
| `docs/` | [protokol](PROTOCOL.md), [firmware](FIRMWARE.md), [sürücüler](DRIVERS.md), [MCP](MCP.md) |
