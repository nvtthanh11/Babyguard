import os
import wave
import numpy as np
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MUSIC_DIR = os.path.join(BASE_DIR, "music")
os.makedirs(MUSIC_DIR, exist_ok=True)
SAMPLE_RATE = 22050

def save_wav(filename, samples):
    samples = np.clip(samples, -1.0, 1.0)
    int_samples = (samples * 32767).astype(np.int16)
    path = os.path.join(MUSIC_DIR, filename)
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int_samples.tobytes())
    print(f"Generated: {path} ({len(samples)/SAMPLE_RATE:.1f}s)")

# 1. Nhịp tim mẹ trầm ấm (Heartbeat - 65 BPM)
def gen_heartbeat(duration=20):
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    audio = np.zeros_like(t)
    beat_interval = 60.0 / 65.0 # ~0.923s
    num_beats = int(duration / beat_interval)
    
    for i in range(num_beats):
        t0 = i * beat_interval
        # Lub (first heart sound: ~55 Hz, 0.12s)
        dt1 = t - t0
        m1 = (dt1 >= 0) & (dt1 < 0.14)
        if np.any(m1):
            env1 = np.sin(np.pi * (dt1[m1] / 0.14)) ** 2
            tone1 = np.sin(2 * np.pi * 55 * dt1[m1])
            audio[m1] += 0.8 * tone1 * env1
        
        # Dub (second heart sound: ~70 Hz, 0.10s, starts 0.28s after lub)
        dt2 = t - (t0 + 0.28)
        m2 = (dt2 >= 0) & (dt2 < 0.12)
        if np.any(m2):
            env2 = np.sin(np.pi * (dt2[m2] / 0.12)) ** 2
            tone2 = np.sin(2 * np.pi * 70 * dt2[m2])
            audio[m2] += 0.55 * tone2 * env2
            
    # Soft background womb whoosh
    womb_noise = np.random.normal(0, 0.04, len(t))
    womb_mod = 0.5 + 0.5 * np.sin(2 * np.pi * (1.0 / beat_interval) * t)
    audio += womb_noise * womb_mod
    save_wav("Nhip_tim_me_Heartbeat.wav", audio)

# 2. Sóng biển vỗ rì rào (Ocean Waves - 8s swell)
def gen_ocean_waves(duration=24):
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    # Generate pink-like noise
    noise = np.cumsum(np.random.normal(0, 1, len(t)))
    noise = noise - np.mean(noise)
    noise = noise / np.max(np.abs(noise))
    
    # 8-second wave period
    envelope = (np.sin(2 * np.pi * t / 8.0 - np.pi/2) + 1.0) / 2.0
    envelope = envelope ** 1.8 # sharper peak for wave crash, gentle trough
    
    # Add gentle sea foam sizzle on crest
    foam = np.random.normal(0, 0.12, len(t)) * (envelope ** 2)
    audio = noise * envelope * 0.7 + foam
    save_wav("Song_bien_vo_Ocean_Waves.wav", audio)

# 3. Tiếng ồn hồng (Pink Noise - 1/f)
def gen_pink_noise(duration=15):
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    white = np.random.normal(0, 1, len(t))
    # Approximation of pink filter via simple IIR filter
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    # Generate pink noise via 1/sqrt(f) filter in frequency domain
    X_white = np.fft.rfft(white)
    S = np.sqrt(np.arange(len(X_white)) + 1.0) # 1/sqrt(f) amplitude
    X_pink = X_white / S
    pink = np.fft.irfft(X_pink, n=len(white))
    pink = pink / np.max(np.abs(pink)) * 0.6
    save_wav("Tieng_on_hong_Pink_Noise.wav", pink)

# 4. Tiếng ồn nâu (Brown Noise - Deep rumble)
def gen_brown_noise(duration=15):
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    white = np.random.normal(0, 0.08, len(t))
    brown = np.cumsum(white)
    brown = brown - np.mean(brown)
    brown = brown / np.max(np.abs(brown)) * 0.65
    save_wav("Tieng_on_nau_Brown_Noise.wav", brown)

# 5. Tiếng suối róc rách (Water Stream)
def gen_water_stream(duration=20):
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    base = np.random.normal(0, 0.25, len(t))
    # Modulate water bubbling frequencies (400 - 1200 Hz random droplets)
    bubbles = np.zeros_like(t)
    num_drops = int(duration * 25)
    for _ in range(num_drops):
        dt_idx = np.random.randint(0, len(t) - 1500)
        freq = np.random.uniform(500, 1100)
        dur = np.random.uniform(0.02, 0.06)
        n_pts = int(dur * SAMPLE_RATE)
        sub_t = np.linspace(0, dur, n_pts)
        drop = np.sin(2 * np.pi * freq * sub_t) * (1.0 - sub_t/dur)**2 * np.random.uniform(0.08, 0.25)
        bubbles[dt_idx:dt_idx+n_pts] += drop
    audio = base * 0.35 + bubbles * 0.5
    save_wav("Tieng_suoi_chay_Water_Stream.wav", audio)

# 6. Nhạc ru kinh điển Brahms Lullaby (Wiegenlied)
def gen_brahms_lullaby(duration=22):
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    audio = np.zeros_like(t)
    
    # Melody: Brahms Wiegenlied (G, G, Bb, G, G, Bb, G, Bb, Eb, D, C, C, Bb...)
    melody = [
        (392.00, 0.8), (392.00, 0.8), (466.16, 1.4), # G4, G4, Bb4
        (392.00, 0.8), (392.00, 0.8), (466.16, 1.4), # G4, G4, Bb4
        (392.00, 0.6), (466.16, 0.6), (622.25, 1.2), (587.33, 0.8), # G4, Bb4, Eb5, D5
        (523.25, 0.8), (523.25, 0.8), (466.16, 1.6), # C5, C5, Bb4
        (349.23, 0.6), (392.00, 0.6), (440.00, 1.0), (349.23, 0.8), # F4, G4, A4, F4
        (392.00, 0.6), (440.00, 0.6), (466.16, 1.2), (392.00, 1.6), # G4, A4, Bb4, G4
    ]
    cur_t = 0.5
    for freq, note_dur in melody:
        if cur_t + note_dur >= duration:
            break
        idx_start = int(cur_t * SAMPLE_RATE)
        idx_end = int((cur_t + note_dur) * SAMPLE_RATE)
        if idx_end > len(t):
            break
        note_t = np.linspace(0, note_dur, idx_end - idx_start)
        # Celesta / Music Box chime harmonic bell envelope
        bell = (np.sin(2 * np.pi * freq * note_t) * 0.6 +
                np.sin(2 * np.pi * (freq * 2.0) * note_t) * 0.25 +
                np.sin(2 * np.pi * (freq * 3.01) * note_t) * 0.12)
        env = np.exp(-note_t * 2.8) # gentle decay
        audio[idx_start:idx_end] += bell * env * 0.5
        cur_t += note_dur + 0.15
        
    save_wav("Nhac_ru_Brahms_Lullaby.wav", audio)

if __name__ == "__main__":
    print("Generating enriched sound library...")
    gen_heartbeat()
    gen_ocean_waves()
    gen_pink_noise()
    gen_brown_noise()
    gen_water_stream()
    gen_brahms_lullaby()
    print("All tracks generated successfully!")
