# iStrip BLE Light Integration for Home Assistant

This custom integration replicates core features of the official iStrip+ app, enabling control of iStrip BLE (Bluetooth Low Energy) LED lights directly from Home Assistant. It communicates over BLE using AES-encrypted commands to provide smooth RGB color and brightness adjustments, just like the original app.

---

## ✨ Features

- Turn iStrip BLE light on/off
- Set RGB color with smooth brightness control
- Communicates via AES-encrypted BLE packets
- Supports automatic Bluetooth device discovery
- Fully asynchronous and compatible with Home Assistant’s light platform

---

## ✅ Tested with

| Component           | Version                  |
| ------------------- | ------------------------ |
| Home Assistant Core | 2025.7.1                 |
| Supervisor          | 2025.07.1                |
| Operating System    | 16.0                     |
| Frontend            | 20250702.1               |
| Installation Method | Home Assistant OS / Core |

---

## 🛠️ Installation

1. **Download the integration:**  
   Clone or download this repository.

2. **Copy files:**  
   Copy the `istrip` directory into your Home Assistant `custom_components` folder.

3. **Restart Home Assistant.**

4. **Add the integration via Home Assistant UI:**

- Go to **Settings → Devices & Services → Add Integration**
- Search for **iStrip BLE Light**
- Home Assistant will scan for nearby BLE devices and list them
- Select your device to complete the setup (device name might be something like "SSL-XXXX")

The integration will handle device discovery and configuration automatically.

---

## 🧑‍💻 Usage

Once installed, the iStrip BLE light entity will appear in Home Assistant. You can:

- Turn it on/off
- Change its RGB color
- Adjust brightness (0-255)

Commands are sent asynchronously over BLE and encrypted to match the official iStrip+ app protocol.

---

## 📁 Code Overview

- `__init__.py` — Minimal setup functions for Home Assistant.
- `const.py` — Domain constants and defaults.
- `config_flow.py` — Handles integration UI and automatic BLE device discovery.
- `light.py` — Implements the IstripLight entity and BLE communication.
- `payload_generator.py` — AES encryption and payload generation for commands.

---

## 📦 Dependencies

- Home Assistant
- [Bleak](https://github.com/hbldh/bleak) — Python Bluetooth LE client library
- [PyCryptodome](https://www.pycryptodome.org/) — For AES encryption

---

## ❓ Troubleshooting

- Ensure Bluetooth is enabled and your Home Assistant host supports BLE.
- If devices do not appear during discovery, make sure the iStrip light is powered on and nearby.
- Check Home Assistant logs for BLE communication errors if commands fail.

---

## 📝 License

MIT License — see [LICENSE](LICENSE) for details.
