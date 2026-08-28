import wave
import struct
import math
import os

# Generate a 12-second test audio file simulating 2 radio transmissions separated by 3.5s silence
sample_rate = 22050
duration = 12.0
num_samples = int(sample_rate * duration)

samples = []

for i in range(num_samples):
    t = i / sample_rate
    # Transmission 1: 0.5s to 3.5s (3 seconds of audio)
    # Transmission 2: 7.0s to 10.5s (3.5 seconds of audio)
    # Silence: 0 to 0.5s, 3.5s to 7.0s (3.5s silence > 2.5s threshold), 10.5s to 12.0s
    if (0.5 <= t <= 3.5) or (7.0 <= t <= 10.5):
        # Generate composite speech-like frequency tones (modulated 300Hz, 800Hz, 1500Hz)
        val = (
            0.5 * math.sin(2 * math.pi * 400 * t) +
            0.3 * math.sin(2 * math.pi * 850 * t) +
            0.2 * math.sin(2 * math.pi * 1800 * t)
        )
        # Apply amplitude modulation
        amp = (0.7 + 0.3 * math.sin(2 * math.pi * 4 * t)) * 0.7
        int_sample = int(val * amp * 32767)
    else:
        # Low noise floor (-55 dBFS)
        int_sample = int(0.002 * (i % 5 - 2) * 32767)
    
    samples.append(max(-32768, min(32767, int_sample)))

wav_file = "test_radio_transmission.wav"
with wave.open(wav_file, "w") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(sample_rate)
    f.writeframes(struct.pack(f"<{len(samples)}h", *samples))

print(f"Created {wav_file} ({duration}s)")
