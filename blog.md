Sure! I’ll merge your detailed technical article with the blog-post style narrative into a smooth, unified blog article that’s both readable and technical — great for an audience interested in reverse engineering and DIY smart home hacks.

Here’s the combined and polished version:

---

# Reverse Engineering the Sunset Lamp: From Unboxing to Encrypted Bluetooth Control

## Introduction

In this article, I take you through my journey of reverse engineering a Bluetooth-enabled sunset lamp. Starting from unboxing, exploring the official mobile application, analyzing the Bluetooth communication, and finally decoding the AES encryption used to control the lamp’s colors and effects. Along the way, I’ll share how I built a message generator in C# and successfully sent commands using `gatttool`. This lays the groundwork for a future Home Assistant integration for seamless smart home control.

---

## Unboxing and First Impressions

Inside the box, you’ll find:

- The sunset lamp
- A stand
- A remote control
- A QR code sheet linking to the official app

The lamp’s design features three concentric color rings of LEDs visible through its lens:

- **Outer ring:** blue LEDs
- **Middle ring:** green LEDs
- **Inner ring:** red LEDs

This tri-color layering allows for rich color effects.

---

## Exploring the Official Application

I installed the app on a Samsung A8 (2018) and found the user interface straightforward:

- Power on/off
- Group multiple lamps for synchronized control
- Choose colors via an RGB palette and adjust brightness
- Select preset lighting effects (breathing, blinking, smooth transitions) with adjustable speed
- Set a timer for automated shutoff
- Sync light effects to music using either a phone audio file or live microphone input

Once the lamp is connected via USB, the app immediately detects it and lets you control all these features seamlessly.

---

## Preparing for Reverse Engineering

To peek under the hood, I took the APK file directly from the manufacturer’s distribution instead of extracting it from the phone.

Initial decompilation attempts with JADX yielded heavily obfuscated code, making direct analysis difficult.

So, I turned to **Bluetooth traffic sniffing**:

1. Enabled Developer Mode on the phone
2. Activated Bluetooth HCI logging and USB debugging
3. Captured Bluetooth traffic during color changes with ADB
4. Analyzed the traffic dump in Wireshark filtered for Bluetooth ATT protocol

---

## Discovering the Encrypted Protocol

By matching sent commands to color changes, I found the raw packets were encrypted:

| Color | Encrypted Payload (Hex)          |
| ----- | -------------------------------- |
| Red   | 0b193631a1c203cfadfdbad7820f3856 |
| Green | 1273622a87797e5c768211ee59308e5b |
| Blue  | 42c9e15436faf27b95fb68d3159c93e2 |

No obvious pattern between the colors and sent data meant encryption was applied on the client side.

---

## Deeper Dive into the APK

I extracted the APK from the phone and reopened it in JADX, this time with better results.

Inside the `ble` package, the `BleProtocol` class revealed the key `sendColor` method:

```java
public static void sendColor(DataManager dataManager, int i) {
    int curColor = dataManager.getCurColor();
    byte[] bArr = {
        84, 82, 0, 87, (byte) 2, (byte) dataManager.getGroupId(), (byte) i,
        (byte) Color.red(curColor), (byte) Color.green(curColor), (byte) Color.blue(curColor),
        (byte) dataManager.getLight(), (byte) dataManager.getSpeed(), 0, 0, 0, 0
    };
    BleManager.getInstance().writeAll(Agreement.getEncryptData(bArr));
}
```

The data packet consists of:

| Byte # | Description                          |
| ------ | ------------------------------------ |
| 1-4    | Request header (fixed values)        |
| 5      | Command type (e.g., 2 for RGB)       |
| 6      | Group ID (must be >1)                |
| 7      | Unknown (mode)                       |
| 8-10   | Colors (note: green and red swapped) |
| 11     | Brightness (0-100)                   |
| 12     | Effect speed (0-100)                 |
| 13-16  | Timer values                         |

---

## AES Encryption in Native Code

The app uses a native C/C++ library for AES encryption (`libAES.so`). The encryption key isn’t in Java code but hardcoded in the native library.

The key is set once on app start by calling `keyExpansionDefault()`, indicating the key is embedded inside the native code.

---

## Extracting the AES Key with IDA

Using IDA Freeware, I loaded `libAES.so` and found the 16-byte AES key inside the `keyExpansionDefault` function.

This key allows generating properly encrypted control messages for the lamp.

---

## Writing a Payload Generator in C\#

I created a simple C# class to generate encrypted payloads matching the app’s protocol:

```csharp
public class PayloadGenerator
{
    private static readonly byte[] Key = { /* 16-byte AES key */ };
    private static readonly byte[] Header = { 0x54, 0x52, 0x00, 0x57 };
    private readonly ICryptoTransform _crypt;
    private const int GroupId = 1;

    public PayloadGenerator()
    {
        var aes = Aes.Create();
        aes.Mode = CipherMode.ECB;
        _crypt = aes.CreateEncryptor(Key, null);
    }

    public string GetRgbPayload(byte red, byte green, byte blue, byte brightness = 100, byte speed = 100)
    {
        var payload = new byte[16]
        {
            Header[0], Header[1], Header[2], Header[3],
            2, GroupId, 0,
            green, red, blue,
            brightness, speed,
            0, 0, 0, 0
        };
        var result = new byte[16];
        _crypt.TransformBlock(payload, 0, payload.Length, result, 0);
        return BitConverter.ToString(result).Replace("-", "").ToLower();
    }
}
```

---

## Testing with gatttool

On a Raspberry Pi, I connected to the lamp and sent encrypted commands:

```bash
sudo gatttool -I
[LE]> connect <lamp_mac_address>
[LE]> char-write-cmd 0x0009 <encrypted_payload_hex>
```

The lamp reacted immediately, changing brightness and color as expected!

---

## Conclusion and Next Steps

I successfully reverse engineered the Bluetooth communication and AES encryption used by the sunset lamp.

The next goal is to develop a **Home Assistant integration**, allowing seamless control via UI and automations.

---

If you’re interested in the code or want to contribute, check out the [GitHub repository](#) (link coming soon).

---

Would you like me to help with code formatting or setting this up on your blog platform?
