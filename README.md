# ESY Sunhome for Home Assistant

A Home Assistant integration for ESY Sunhome battery systems, providing monitoring and control via MQTT.

> ### ☁️ Don't want to run Home Assistant?
> This integration is for self-hosting on Home Assistant. If you'd rather not set up and
> maintain HA yourself, **[SolanIQ](https://solaniq.ai)** is a hosted service that optimises
> your ESY Sunhome battery against live wholesale prices and solar forecasts — no Home
> Assistant required. → **[Try it at solaniq.ai](https://solaniq.ai)**

![Example Screenshot](/screenshot.png)

## ⚠️ Important: Firmware Requirement

**Version 2.x requires newer ESY battery firmware with MQTT support.**

The ESY web portal has information about the firmware that your inverter is using, you can also just try the integration.. if you're not seeing data in one then its likely you have the other.

## Features

- **Real-time updates** via MQTT (fast refresh)
- **Mode control** - Change operating modes from Home Assistant
- **Comprehensive sensors** - Power, energy, battery status, temperatures
- **Secure connection** - mTLS authentication

## Sensors

| Category | Sensors |
|----------|---------|
| **Power** | PV Power, DC PV, AC PV (CT2), Battery, Grid, Load |
| **Battery** | SOC, SOH, Voltage, Current, Status, Charging/Discharging Power |
| **Energy** | Daily/Total Generation, Consumption, Grid Export, Battery Charge/Discharge |
| **System** | Grid Voltage/Frequency, Inverter Temperature, Operating Mode |

## Mode Control

Control your battery mode directly from Home Assistant:

| Mode | Description |
|------|-------------|
| Regular Mode | Normal self-consumption |
| Emergency Mode | Charge from grid (storm prep) |
| Electricity Sell Mode | Maximize grid export |
| Battery Energy Management | Server-side scheduling |

Configure API or direct MQTT mode changes in the integration options.

## Installation

### HACS (Recommended)

1. Go to **HACS → Integrations**
2. Click the **⋮** menu → **Custom repositories**
3. Add: `https://github.com/branko-lazarevic/esysunhome`
4. Select category: **Integration** → Click **ADD**
5. Find "ESY Sunhome" in HACS and click **Download**
6. **Restart Home Assistant**

### Manual Installation

1. Download the latest release
2. Copy `custom_components/esy_sunhome` to your `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services**
2. Click **Add Integration** → Search for "ESY Sunhome"
3. Enter your ESY app username and password
4. Select your inverter (or leave blank to use the first one)

### Options

After setup, click **Configure** on the integration to set:

- **Mode Change Method**: API (default, like the app) or Direct MQTT (faster)

## Troubleshooting

### Enable Debug Logging

```yaml
logger:
  logs:
    custom_components.esy_sunhome: debug
```

### Download Diagnostics

**Developer Tools → Actions → esy_sunhome.dump_debug → Copy output from (Settings → System → Logs)**

## Referral Codes

If you're purchasing an ESY Sunhome battery, get **$50 off** using code: **AU1587** when registering in the ESY app.

Switching to Amber for wholesale electricity rates? Use code **QVLA4DT4** for **$120 off**.

## Resources

- [Project Documentation](https://branko-lazarevic.github.io/esysunhome)
- [Changelog](CHANGES.md)
- [Release Notes](RELEASE_NOTES_v2.md)

## License

This project is licensed under the MIT License.
