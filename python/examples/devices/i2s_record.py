"""Record 5 s from an I2S MEMS mic (INMP441: BCLK -> 14, WS -> 15, SD -> 32)
into recording.wav on this computer.

    uv run devices/i2s_record.py
"""
import wave

from esplink import Bridge

with Bridge() as esp:
    esp.i2s.begin_input(bclk=14, ws=15, din=32, rate=16_000)
    pcm = esp.i2s.read(seconds=5)
    esp.i2s.end()

with wave.open("recording.wav", "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16_000)
    w.writeframes(pcm)
print(f"saved recording.wav ({len(pcm)} bytes)")
