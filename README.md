# iStrip BLE Light Integration for Home Assistant

This custom integration replicates core features of the official iStrip+ app, enabling control of iStrip BLE (Bluetooth Low Energy) LED lights directly from Home Assistant. It communicates over BLE using AES-encrypted commands to provide smooth RGB color and brightness adjustments, just like the original app.

---

## Features

- Turn iStrip BLE light on/off
- Set RGB color with smooth brightness control
- **12 built-in effects**: Fade, Breath, Strobe, Flash (in various colors)
- Adjustable effect speed and brightness
- **State synchronization**: Automatically updates Home Assistant when controlled via infrared remote
- Communicates via AES-encrypted BLE packets
- Supports automatic Bluetooth device discovery
- Fully asynchronous and compatible with Home Assistant's light platform

---

## Tested with

| Component           | Version                  |
| ------------------- | ------------------------ |
| Home Assistant Core | 2025.7.1                 |
| Supervisor          | 2025.07.1                |
| Operating System    | 16.0                     |
| Frontend            | 20250702.1               |
| Installation Method | Home Assistant OS / Core |

---

## Installation

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

## Usage

Once installed, the iStrip BLE light entity will appear in Home Assistant. You can:

- Turn it on/off
- Change its RGB color
- Adjust brightness (0-255)

Commands are sent asynchronously over BLE and encrypted to match the official iStrip+ app protocol.

---

## Effects

The integration supports 12 built-in effects:

| Effect Name           | Description                    |
| --------------------- | ------------------------------ |
| **7-Color Fade**      | Smooth 7-color fade transition |
| **3-Color Fade**      | Smooth 3-color fade transition |
| **Red Breathing**     | Red breathing effect           |
| **Red Strobe**        | Red strobe/flash               |
| **7-Color Breathing** | 7-color breathing effect       |
| **3-Color Breathing** | 3-color breathing effect       |
| **Blue Breathing**    | Blue breathing effect          |
| **Blue Strobe**       | Blue strobe/flash              |
| **7-Color Flash**     | 7-color fast flash             |
| **3-Color Flash**     | 3-color fast flash             |
| **Green Breathing**   | Green breathing effect         |
| **Green Strobe**      | Green strobe/flash             |

### Using Effects on your Dashboard

To control effects and their speed directly from a Lovelace dashboard, we recommend creating two UI Helpers.

**1. Create the Helpers (`Settings` → `Devices & Services` → `Helpers`)**

- **Dropdown (`input_select.istrip_effect`):**

  - **Options:** `Sunset`, `Aurora`, `7-Color Fade`, `3-Color Fade`, `Red Breathing`, `Red Strobe`, `7-Color Breathing`, `3-Color Breathing`, `Blue Breathing`, `Blue Strobe`, `7-Color Flash`, `3-Color Flash`, `Green Breathing`, `Green Strobe`
  - **Icon:** `mdi:palette`

- **Number (`input_number.istrip_effect_speed`):**
  - **Minimum:** `0.0`, **Maximum:** `100.0`, **Step:** `1.0`
  - **Unit of measurement:** `%`
  - **Mode:** Slider
  - **Icon:** `mdi:speedometer`

**2. Add Automations to link the Helpers**

Add the following to your `automations.yaml` to automatically sync these helpers with your light:

```yaml
- alias: iStrip - Sync Effect Speed
  description: Updates effect speed when slider changes
  mode: restart
  triggers:
    - entity_id: input_number.istrip_effect_speed
      trigger: state
  actions:
    - action: istrip.set_speed
      data:
        entity_id: light.istrip_ble_light
        speed: "{{ states('input_number.istrip_effect_speed') | int }}"

- alias: iStrip - Control Effects
  description: Sync effect and speed controls
  mode: restart
  triggers:
    - entity_id: input_select.istrip_effect
      id: effect_changed
      trigger: state
    - entity_id: input_number.istrip_effect_speed
      id: speed_changed
      trigger: state
  actions:
    - choose:
        - conditions:
            - condition: trigger
              id: effect_changed
          sequence:
            - choose:
                - conditions:
                    - condition: template
                      value_template: "{{ states('input_select.istrip_effect') == 'Sunset' }}"
                  sequence:
                    - action: script.istrip_sunrise_sunset
                - conditions:
                    - condition: template
                      value_template: "{{ states('input_select.istrip_effect') == 'Aurora' }}"
                  sequence:
                    - action: script.istrip_aurora_borealis
              default:
                - action: istrip.set_effect
                  data:
                    entity_id: light.istrip_ble_light
                    effect: "{{ states('input_select.istrip_effect') }}"
                    speed: "{{ states('input_number.istrip_effect_speed') | int }}"
        - conditions:
            - condition: trigger
              id: speed_changed
          sequence:
            - action: istrip.set_speed
              data:
                entity_id: light.istrip_ble_light
                speed: "{{ states('input_number.istrip_effect_speed') | int }}"
```

### Using Effects via Services

**Set an effect with optional speed:**

```yaml
service: istrip.set_effect
data:
  entity_id: light.istrip_ble_light
  effect: 7-Color Fade
  speed: 75 # Optional: 1-100
```

**Change speed of current effect:**

```yaml
service: istrip.set_speed
data:
  entity_id: light.istrip_ble_light
  speed: 50
```

**Turn on with effect:**

```yaml
service: light.turn_on
data:
  entity_id: light.istrip_ble_light
  effect: Red Breathing
  brightness: 200
```

> **Note:** Setting an RGB color will disable the current effect, and vice versa. Effects and static colors are mutually exclusive.

---

## State Synchronization

The integration maintains a persistent BLE connection to automatically sync state changes when the light is controlled via the **infrared remote**.

**How it works:**

- When you change the light using the IR remote (color, brightness, power, etc.)
- The device sends a BLE notification with the new state
- Home Assistant automatically updates within 2-3 seconds
- No manual refresh needed!

**Requirements:**

- Bluetooth adapter must remain in range of the device
- The integration maintains a continuous BLE connection

**Supported sync actions:**

- Power on/off
- Color changes
- Brightness adjustments
- Effect activation (if supported by remote)

---

## Code Overview

- `__init__.py` — Minimal setup functions for Home Assistant.
- `const.py` — Domain constants and defaults.
- `config_flow.py` — Handles integration UI and automatic BLE device discovery.
- `light.py` — Implements the IstripLight entity and BLE communication.
- `payload_generator.py` — AES encryption and payload generation for commands.

---

## Dependencies

- Home Assistant
- [Bleak](https://github.com/hbldh/bleak) — Python Bluetooth LE client library
- [PyCryptodome](https://www.pycryptodome.org/) — For AES encryption

---

## Troubleshooting

- Ensure Bluetooth is enabled and your Home Assistant host supports BLE.
- If devices do not appear during discovery, make sure the iStrip light is powered on and nearby.
- Check Home Assistant logs for BLE communication errors if commands fail.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
