# Xiaomi Cooker

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-yellow.svg)](https://hacs.xyz/)
[![Maintainer](https://img.shields.io/badge/maintainer-%40myhades-green)](https://github.com/myhades)
[![Release](https://img.shields.io/github/v/release/myhades/ha-xiaomi-cooker)](https://github.com/myhades/ha-xiaomi-cooker/releases)

Xiaomi Cooker integrates Xiaomi rice cookers into Home Assistant through local communication.

## Supported Devices

| Name | Model |
|------|-------|
| Mi Smart Small Rice Cooker 2 | xiaomi.cooker.cmc301 |
| Mi Rice Cooker | chunmi.cooker.normal3 |

## Installation

Home Assistant Core must be `2026.8.0` or newer.

Choose your preferred installation method, and reboot Home Assistant afterward.

### Method 1: Through HACS

This repository is not in the default list yet. To add it, use the My button below, or navigate to `HACS > Overflow menu > Custom repositories` and enter:

- `Repository`: `https://github.com/myhades/ha-xiaomi-cooker`
- `Type`: Integration

Then, navigate to `HACS > Xiaomi Cooker` and install the integration.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=myhades&repository=ha-xiaomi-cooker&category=integration)

### Method 2: Manually

Download the repository and copy the `/custom_components/xiaomi_miio_cooker` folder into your Home Assistant `/config/custom_components` directory.

## Configuration

To add the integration, navigate to `Settings > Devices & services > Add integration > Xiaomi Cooker`, or use the My button below. Then follow the configuration flow.

[![Add Xiaomi Cooker to Home Assistant.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=xiaomi_miio_cooker)

Enter the cooker IP address and token, then select its model or use automatic detection. To change the IP address or token later, select **Reconfigure** from the integration menu. Leave the token blank to keep its current value. The integration verifies the cooker identity before saving changes, preserving existing entities.

## Cooking

Select a **Cooking menu** first. The duration selector automatically chooses that recipe's default duration, and the supported taste and automatic keep-warm controls become available. These controls prepare the next cook; selecting a menu or changing its options does not start heating.

Press **Start cooking** to submit the selected recipe. Press **Stop cooking** to stop independently of the menu selection. After a successful start, the preparation controls reset. On CMC301, the selection also clears if the start result is uncertain; check the cooker state before retrying.

| Feature | CMC301 | normal3 |
|---------|--------|---------|
| Bundled recipes | 13 | 11 |
| Cooking duration | Recipe-specific options | Recipe-specific options |
| Taste | Fine rice only | Fine rice only |
| Automatic keep-warm | Supported recipes | Supported recipes |
| Scheduled completion | Supported recipes | Not exposed as a preparation control |
| Save recipe to panel | Supported | Not exposed |
| Cooking stage and description | Fine and quick rice | Fine and quick rice |

Duration choices use 5- or 10-minute intervals and include each recipe's bounds and default. Fixed-duration recipes provide one option. Automatic keep-warm is a parameter for the next recipe, not a general live toggle during cooking.

## Additional Configuration

### Scheduled Completion

On CMC301, **Scheduled completion** is the number of minutes until the meal finishes, not the delay before cooking starts. Set it to 0 for an immediate start. The selected recipe determines whether scheduling is available and the minimum completion time.

Clear scheduled completion before pressing **Save selected recipe to panel**. Saving changes the cooker's custom recipe without starting it.

### Feedback and Device Settings

Feedback includes the current menu, working status, remaining time and duration. CMC301 also exposes fault codes, remote-control permission, boiling feedback, buzzer and display settings. Other entities depend on the model.

Temperature comes from recorded temperature history when no direct reading is available; it is not an instantaneous heater or power measurement. Fine and quick rice show five cooking stages based on the official plugin's temperature-history method. Other recipes do not use that stage mapping.

## Actions

### Start a Recipe

Use `xiaomi_miio_cooker.start_recipe` to submit a recipe and its parameters together, without changing the preparation controls. For example, schedule a 120-minute congee recipe on CMC301 to finish in 480 minutes:

```yaml
action: xiaomi_miio_cooker.start_recipe
data:
  device_id: YOUR_CMC301_DEVICE_ID
  recipe: zhuzhou
  duration: 120
  auto_keep_warm: true
  finish_in: 480
```

Both CMC301 and normal3 support this action. Only CMC301 accepts `finish_in`; omit it for normal3. Only `jingzhu` accepts `taste: soft|middle|hard`. Omitted parameters use the bundled recipe defaults. Specify `device_id` when more than one cooker is loaded.

### Start a Custom Profile

`xiaomi_miio_cooker.start` accepts `profile` and an optional `device_id`. normal3 uses its own profile format. CMC301 accepts only bundled heating programs with supported parameter changes.

## Feedback

When reporting an issue, include your setup, diagnostics, and logs.

Select **Download diagnostics** from the integration menu to export cached feedback without tokens, network addresses or device identifiers. This does not poll or control the cooker.

You can enable debug logging in the UI when available, or add the following to your Home Assistant configuration:

```yaml
logger:
  logs:
    custom_components.xiaomi_miio_cooker: debug
```

## Thanks

Thanks to [Syssi](https://github.com/syssi/xiaomi_cooker) for the original integration and [Rytilahti and the python-miio contributors](https://github.com/rytilahti/python-miio) for the device communication library. This project retains the original Apache 2.0 license.

## Disclaimer

This is an unofficial community integration and is not affiliated with, endorsed by, or supported by Xiaomi or Chunmi. Xiaomi and Chunmi are trademarks of their respective owners.
