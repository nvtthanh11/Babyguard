# 🍼 BABYGUARD AI - SMART PEDIATRIC SENTRY (COMMERCIAL EDITION)
### Complete Installation & User Operation Manual

---

## 1. PRODUCT OVERVIEW

**BabyGuard AI** is a state-of-the-art, privacy-first smart infant monitoring system engineered for parents, pediatric clinics, and daycares. It runs 100% locally on your host computer (Edge AI) paired with Google Gemini multimodal intelligence:

* 🫁 **Contactless Respiration Monitoring**: Real-time chest micromovement detection via computer vision without wearables, straps, or sensors on the baby.
* 💤 **24h Pediatric Sleep Analytics (AAP & AASM)**: Continuous sleep tracking anchored strictly at 07:00 AM daily, featuring Wake Window calculations, daytime nap distribution, and over-tiredness alerts.
* 🏥 **Medical First-Aid Protocol (RAG Engine)**: Instant verbatim American Heart Association (AHA) and American Academy of Pediatrics (AAP) first-aid guidance for infant choking, aspiration, prone sleep suffocation, and respiratory distress.
* 🚨 **Zero-Latency Sentry Alerts**: Immediate alerts for prone sleeping (face down into mattress), covered airway/face by blankets or pillows, and roll-out-of-crib danger zone boundaries.
* 🎵 **Closed-Loop Soothing System**: Automatic white/pink/brown noise and classical lullabies with room noise adaptive volume limiting (medical safe ~45-50 dB).
* 📸 **Curated Cute Moments Album**: Smart privacy critic that auto-captures and crops high-quality baby portraits (4:5 ratio) while filtering out poorly-lit or intrusive adult shots.
* ☁️ **Google Drive Auto-Sync**: Seamless local cloud synchronization preserving moments structured as `BabyGuard_Moments/YYYY/MM/DD/HH-MM-SS.jpg`.
* 📖 **Daily Bedtime Story (1 Story per Day)**: Aesop & Andersen world classics focusing on moral character development and early childhood values with voice read-aloud.

---

## 2. HARDWARE & SYSTEM PREREQUISITES

| Component | Minimum Specification | Recommended |
| :--- | :--- | :--- |
| **Host System** | Mac (M1/M2/M3/M4 or Intel), Linux PC | **Mac mini (Apple Silicon M1/M2/M4)** running 24/7 with ultra-low power consumption (~5W) |
| **Camera** | USB 720p 15 FPS Webcam | USB 1080p wide-angle camera or Home Wi-Fi IP Camera (RTSP / ONVIF) |
| **Microphone** | Integrated Mac mic / webcam mic | USB nursery directional room microphone |
| **Speaker** | Mac built-in speaker | Mac speaker or external nursery Bluetooth/USB speaker |
| **Environment** | Python 3.10 or 3.11 | Python 3.11 installed via Homebrew (`brew install python@3.11`) |

---

## 3. QUICK SETUP (2 MINUTES)

### Step 1: Open Terminal and navigate to the directory
```bash
cd /path/to/BabyGuard_AI
```

### Step 2: Install required Python dependencies
```bash
pip install -r requirements.txt
```

*(Recommended for macOS)*: Install `ffmpeg` for smooth video and audio encoding:
```bash
brew install ffmpeg
```

### Step 3: Launch BabyGuard AI
Double click **`Start_BabyGuard.command`** or run:
```bash
./start.sh
```
Safari / Chrome will automatically open `http://localhost:8080`.

---

## 4. ACTIVATING YOUR COMMERCIAL LICENSE

1. Click the **🔑 License** icon on the top navigation bar.
2. You will see your unique **Hardware Machine ID** (e.g. `BG-MAC-XXXX-XXXX-XXXX`). Click the copy icon to copy it.
3. If you have purchased a license key, paste it into the **License Key** field (e.g. `BG-LFT-99999999-XXXX-XXXXXXXX`) and click **⚡ Activate License**.
4. Enjoy lifetime updates and full priority pediatric AI access!
5. *Note:* BabyGuard AI comes with an automatic **14-day unrestricted Free Trial** so you can test all features with zero commitment.

---

## 5. REMOTE ACCESS FROM SMARTPHONE (4G / 5G / WI-FI)

### Method A: Built-in Cloudflare Zero-Trust Tunnel (Zero Setup)
When BabyGuard AI starts up, it displays an encrypted remote tunnel link:
👉 `https://your-temporary-name.trycloudflare.com`
Bookmark this on your smartphone browser to view your nursery camera and sleep analytics securely from anywhere in the world!

### Method B: Tailscale WireGuard Mesh VPN (Ultra-Fast 60 FPS & Private)
1. Install **Tailscale** on your host Mac and sign in with Google or Apple ID.
2. Install **Tailscale** on your iPhone or Android and sign in with the **same account**.
3. Open your mobile browser and type your Mac's Tailscale IP:
   👉 `http://100.x.y.z:8080`
4. Tap **"Add to Home Screen"** on iOS Safari or Android Chrome to get a full-screen, standalone app experience!

---

## 6. AI SETUP & PEDIATRIC SLEEP CONFIGURATION

Open the **⚙️ Settings** modal to customize:
1. **Baby Profile**: Set baby's name, birthdate, and gender. The AI automatically computes baby's age down to days and applies exact AAP wake window standards.
2. **Google Gemini Multimodal AI**:
   - Enter your free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).
   - Enables the 07:00 AM Pediatric Sleep Doctor report, acute cough/choke cluster triage, and cute moments critic.
3. **Telegram Emergency Bot**:
   - Set `telegram_bot_token` and `telegram_chat_id` to receive instant photo alerts and 30s emergency video recordings directly on your smartphone.
4. **Google Drive Sync**:
   - Automatically detects your macOS Google Drive directory to back up baby moments organized by year, month, and day.

---

## 7. MEDICAL DISCLAIMER

> [!CAUTION]
> **BabyGuard AI is an advanced assistive sentry system, not a regulated medical diagnostic device.**
> All sleep guidelines and first-aid instructions are derived verbatim from AHA and AAP published protocols. In any real-life choking, respiratory distress, or severe illness event, always dial emergency services (**911 in the US/Canada**, **112 in Europe**, **115 in Vietnam**) or proceed immediately to the nearest pediatric emergency hospital.
