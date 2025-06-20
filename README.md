# iStrip BLE Light Integration for Home Assistant

This custom integration replicates core features of the official iStrip+ app, enabling control of iStrip BLE (Bluetooth Low Energy) LED lights directly from Home Assistant. It communicates over BLE using AES-encrypted commands to provide smooth RGB color and brightness adjustments, just like the original app.

> **⚠️ Note:**  
> This project is under active development and **not yet production-ready**. Features may change, bugs may exist, and breaking changes could occur. Use at your own risk.  
> **Contributions, suggestions, and testing feedback are very welcome!**

---

## ✨ Features

- Turn iStrip BLE light **on/off**
- Set **RGB color** with smooth **brightness** control
- Communicates via **AES-encrypted BLE packets**
- Configurable **BLE MAC address** and **characteristic UUID**
- Fully **asynchronous** and compatible with Home Assistant’s `light` platform

---

## 🛠️ Installation

1. **Download the integration:**

   - Clone or download this repository.

2. **Copy files:**

   - Copy the `istrip` directory to your Home Assistant `custom_components` folder.

3. **Find your lamp’s BLE MAC address:**

   Run on any Linux machine (or your HA host) with BLE support:

   ```bash
   sudo hcitool lescan
   ```

   Look for your iStrip device in the output and copy its MAC address.

   ```bash
   LE Scan ...
   AA:BB:CC:DD:EE:FF SSL-C551BE
   ```

4. Update `const.py` to use your lamp’s Bluetooth MAC address and characteristic UUID:

   ```python
   BLE_ADDRESS = "AA:BB:CC:DD:EE:FF"  # Replace with your device's MAC address found in step 3
   CHAR_UUID = "00000000-0000-0000-0000-000000000000"  # Write characteristic UUID can be found with an app like nRF Connect
   ```

5. Add the iStrip light platform to your `configuration.yaml`:

   ```yaml
   light:
     - platform: istrip
   ```

6. Restart Home Assistant.

## 🧑‍💻 Usage

Once installed, the iStrip BLE light entity will appear in Home Assistant. You can:

- Turn it on/off
- Change its RGB color
- Adjust brightness (0-255)

Commands are sent over BLE asynchronously with encryption matching the iStrip+ app protocol.

## 📁 Code Overview

- **`__init__.py`**  
  Minimal setup functions required by Home Assistant.

- **`const.py`**  
  Contains the domain and device-specific constants like BLE MAC address and characteristic UUID.

- **`light.py`**  
  Defines the `IstripLight` class implementing `LightEntity` for Home Assistant.  
  Manages the light state, color, brightness, and sends encrypted BLE commands via `BleakClient`.

- **`payload_generator.py`**  
  Implements AES-ECB encryption and payload formatting according to the reverse engineered protocol.  
  Generates payloads for RGB color changes and turning off the light.

## 📦 Dependencies

- Home Assistant
- [Bleak](https://github.com/hbldh/bleak) - Python Bluetooth LE client library
- [PyCryptodome](https://www.pycryptodome.org/) - For AES encryption

## ❓ Troubleshooting

- Ensure Bluetooth is enabled and your Home Assistant host supports BLE.
- Verify the BLE MAC address and characteristic UUID match your specific device.
- If commands fail, check Home Assistant logs for BLE communication errors.

## 📝 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
