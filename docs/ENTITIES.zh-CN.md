# 实体对照

以下对应 main 分支实现，包含尚未发布的修改。CMC301 共 22 个实体，normal3 共 21 个实体。

所有实体都依赖集成已加载且设备更新成功。表中“—”表示当前集成不提供该实体，不等于硬件绝对没有这项能力。“活动期间”包括烹饪、预约及保温；读不到数据时传感器为 `unknown`，控制条件不满足时控件为 `unavailable`。

| 实体 | 类型 | CMC301 | normal3 | 可用条件、格式和区别 |
| --- | --- | --- | --- | --- |
| Start cooking | button | ✓ | ✓ | 未处于活动期间且已选食谱；执行时还会检查设备状态。成功后清空菜单选择。 |
| Stop cooking | button | ✓ | ✓ | 仅活动期间可用。 |
| Cooking menu | select | 13 个食谱 | 11 个食谱 | 非活动期间可选；额外有 `none`（未选择），初始及清空后使用此值。 |
| Fine rice taste（精煮口感） | select | ✓ | ✓ | `soft/middle/hard`；选中精煮饭时默认 `middle`，仅尚未开始时可用，其余情况不可用。 |
| Duration | select | ✓ | ✓ | 已选食谱且非活动期间可用；字符串分钟数，例如 `"25"`；按食谱范围生成 5/10 分钟步进及边界值，固定时长只有一个选项。选食谱时自动选默认时长。 |
| Automatic keep warm | switch | ✓ | ✓ | 开始前仅支持此选项的食谱可用。活动期间两边都不可用；normal3 非待机也不可用，其实际设置仍在内部读取，不以可操作开关呈现。 |
| Scheduled duration | number | ✓ | ✓ | 支持预约的食谱、非活动期间；0–1439 分钟整数，0 为立即开始，其他值还须符合食谱限制。 |
| Custom recipe | select | 13 个候选 | 7 个扩展食谱候选 | 仅待机时可修改，不会开始加热。CMC301 从自选模式读回并在本次加载期间记忆；normal3 独立读取收藏槽。未知为 `unknown`；读到不包含的食谱为 `other`，不能主动选择 `other`。 |
| Panel auto off | select | `off`、2–10 | `off`、5–10 | 数字是分钟、间隔 1 分钟；读回有效设置才可用。normal3 还要求待机。 |
| Panel recipe lights | select | ✓ | — | `selected/all`，显示 Selected/All（当前选择/全部）；读取设备实际值，读回未知时不可用。替换旧 Panel mode lights 开关。 |
| Completion notification | switch | ✓ | ✓ | 小米 App 完成通知设置；normal3 仅待机可改，不是蜂鸣器开关。 |
| Lid open alarm | switch | — | ✓ | 开盖超时报警设置，待机且读回有效时可用。 |
| Lid-open keep-warm timeout | select | — | ✓ | 2/4/6/8/10 分钟；待机且读回有效时可用。 |
| Status | enum sensor | ✓ | ✓ | 两边均有待机、烹饪、保温、自动保温、预约、故障；`keep_warm` 表示手动保温，`automatic_keep_warm` 表示煮后自动保温。CMC301 另有升级、完成；normal3 其他历史过程值仍归入 `busy`，未识别值或无法区分来源的保温为 `unknown`。 |
| Current menu | enum sensor | ✓ | ✓ | 活动期间显示设备读回食谱；不识别的 ID 为 `other`，待机为 `unknown`。两边都不是“准备开始”的菜单选择。 |
| Fine rice taste（精煮口感） | enum sensor | ✓ | ✓ | 仅精煮饭烹饪中显示 `soft/middle/hard`；其他菜单、保温、预约、待机及缺失反馈均为 `unknown`。CMC301 来自 texture 属性，normal3 来自 stage 中的口感字段。 |
| Current duration | duration sensor | ✓ | ✓ | 当前阶段总时长，整数分钟：烹饪/预约为设备读回烹饪时长；手动保温为设备读回设定时长；自动保温为两份插件定义的 1440 分钟上限。待机、无效值或保温来源未知时为 `unknown`，不使用准备参数补值。 |
| Remaining time | duration sensor | ✓ | ✓ | 整数分钟；烹饪/预约为剩余时间，保温为已保温时间。属性 `time_direction` 分别为 `remaining/elapsed`。CMC301 剩余时间向上取整、已保温时间向下取整；normal3 保留设备的分钟反馈。 |
| Cooking finished | event | ✓ | ✓ | 一次可观察到的烹饪完成产生一次 `finished` 事件；实体状态为最后事件时间，属性包含 `event_type`、`recipe` 和 `keep_warm_type`。手动保温结束不算烹饪完成。 |
| Temperature | temperature sensor | ✓ | ✓ | °C。CMC301 仅取温度曲线最后一个样本，不保证实时；normal3 优先直接温度，不能解析时再取曲线。两边无有效数据都为 `unknown`。 |
| Cooking stage | enum sensor | ✓ | ✓ | 仅两种饭在烹饪中且有有效曲线时提供五阶段；附带可翻译的说明属性，其余情况为 `unknown`。 |
| Error | enum sensor | ✓ | — | `none/top_sensor/bottom_sensor/communication/other`；中文无/顶部传感器故障/底部传感器故障/通信故障/其他故障，原始码在 `code` 属性中。 |
| Rice type | sensor | — | ✓ | stage 中的原始数字 ID；尚无可靠的米种名称枚举，不是米种选择器。 |
| Remote Control | binary_sensor | ✓ | — | `on/off`，设备是否允许远程控制，只读。 |
| Water boiled | binary_sensor | ✓ | — | `on/off`，设备的水已煮开提示标志，不代表此刻持续沸腾。 |

select 的候选项通过 HA 的 `options` 暴露；枚举 sensor 使用 `device_class: enum` 与 `options`。前端按语言翻译名称，自动化使用稳定的内部状态键。二元传感器和开关使用 `on/off`；button 的状态是最后触发时间，不是开关状态。

## 时长显示

Remaining time 和 Current duration 都使用 HA 的 duration 类型，原生单位为 `min`。HA 前端对分钟单位拆成分钟/秒，不会把总分钟数进位成小时；对 `h` 单位则拆成小时/分钟。用户可在这两个传感器的实体设置中将单位改为 `h`。这是数值单位转换，也会改变 HA 中状态的单位，不是纯文字装饰；依赖分钟数的自动化需相应考虑。

集成也可建议默认显示单位，但目前保留 `min`。Duration 选择器的选项是字符串，不适用 duration 传感器的单位转换。

依据：[HA 前端格式化实现](https://github.com/home-assistant/frontend/blob/dev/src/common/datetime/format_duration.ts)、[HA 传感器单位属性](https://developers.home-assistant.io/docs/core/entity/sensor/)。

## CMC301 保温温度与保温来源

CMC301 当前通过 MIoT 2.28 获取曲线，切换状态时重新读取，保温状态没有被代码排除。空曲线、无有效样本或读取失败均会得到未知温度；即使有样本，也可能是最后一笔烹饪温度，不能保证持续反映保温温度。尚未找到可替代的独立实时温度属性。

Status 直接使用 `keep_warm`（保温）与 `automatic_keep_warm`（自动保温），不再附加重复的保温类型属性。CMC301 插件 10202 在保温状态下按 `recipeId == 4` 区分手动保温，其他有效食谱 ID 为煮后自动保温。normal3 插件 11030 同样区分菜单 4，其他菜单的 `autokeepwarm` 为自动保温；历史兼容状态无法确定来源时不猜测。内部协议状态保留，以免改变启动、停止与完成检测的判断。

Current duration 在自动保温时统一为 1440 分钟，依据 CMC301 插件 10187 的 `autoKeepWarmSubtitle` 和 normal3 插件 10556 的 `cookSetAutoKeepwarnMsg`，两者都明确说明自动保温 24 小时。这是正常保温上限，不是实时测得的保证持续时长；开盖保护、取消、故障等可提前结束。手动保温时分别使用 CMC301 的 2.20 和 normal3 的 `t_cook`。当前食谱继续显示原食谱或保温，不随此调整改变。

CMC301 插件 10187 明确说明自动保温最长 24 小时，结合设备的倒计时反馈，已保温分钟按 `(86400 - 剩余秒数) // 60` 换算；手动保温改用设备报告的本次保温时长作为基准。无效时长、负数或超过基准的倒计时返回未知。normal3 的保温分钟本来就是正走时，保持不变。本轮未进行新的加热测试，CMC301 新换算仍需实际运行确认。

例如判断自动保温：

```jinja2
{{ is_state('sensor.xiaomi_rice_cooker_status', 'automatic_keep_warm') }}
```

## 烹饪完成自动化

两台设备统一使用 Cooking finished 事件实体，不再需要自动化解析 Cooking stage 的原始阶段码。事件必须先观察到烹饪/预约，再读到明确完成标志或煮后自动保温；同一轮只触发一次。停止命令、单纯返回待机、手动保温、加载时已经完成以及断线重连时读到旧完成状态均不会触发。

这是轮询设备得出的事件，不是设备推送：如果不开自动保温且完成状态在两次轮询之间已消失，或者完成发生在离线期间，可能漏报。集成不会把所有“运行 → 待机”变化当作完成，以免取消操作产生通知。

下面可替换原通知自动化的触发器，保留 `FINISHED` 分支和通知动作；实体 ID 以 HA 中实际生成的为准。过滤初次加载和恢复可用状态，同时允许首次完成事件从 `unknown` 变为时间戳。事件类型不会每轮变化，因此应监听实体的时间戳，不能只监听 `event_type` 属性。

```yaml
triggers:
  - trigger: state
    entity_id: event.xiaomi_rice_cooker_cooking_finished
    not_from:
      - unavailable
    not_to:
      - unavailable
      - unknown
    id: FINISHED
conditions:
  - condition: template
    value_template: >-
      {{ trigger.from_state is not none
         and trigger.to_state.attributes.get('event_type') == 'finished' }}
```

如果同一自动化还接受手动调用（例如停止并保温），不要把上面的条件放在全局 `conditions` 中；放到 `FINISHED` 分支中，与原来的触发器 ID 条件并列，避免影响手动调用。

事件实体语义依据：[Home Assistant Event entity](https://developers.home-assistant.io/docs/core/entity/event/)。

## Completion notification 与设备事件

Completion notification 是米家完成消息推送开关。CMC301 插件通过 `get_setting/set_setting` 保存推送位，normal3 对应 `en_push`；开关本身不负责把事件送进 HA，也未证明关闭它会同时关闭协议事件。

CMC301 官方 MIoT 规格另有 `siid=2, eiid=1` 的 `cooking-finished` 事件，参数列表为空。若能够接收它，可用作比状态轮询更直接的完成信号；现有集成尚未订阅。官方 SDK 支持 `event.2.1` 形式的订阅，小米官方 HA 实现还提供 `miIO.sub` 本地订阅与事件接收，但未验证这台设备的固件兼容性，也未找到 normal3 对等的事件定义。不能将手机推送、米家 SDK 订阅和当前本地请求/响应连接视为同一个通道。

依据：[MIoT 事件订阅 SDK](https://miecosystem.github.io/miot-plugin-sdk/module-miot_Device.IDeviceWifi.html)、[小米官方本地订阅实现](https://github.com/XiaoMi/ha_xiaomi_home/blob/main/custom_components/xiaomi_home/miot/miot_lan.py)。

## 2026-09-26 插件与接口复核

- CMC301 插件 1041640 v1 的通信模块 10196 未读取或写入 2.32，插件中也未找到蜂鸣器控制入口、触发条件或说明。设备曾接受属性写入不等于实际有响铃效果；已移除 Buzzer 实体、写入接口及其轮询，并清理旧实体注册。
- CMC301 先前 `heating_mode4_live.jsonl` 记录中，状态码 4 时的 2.28 返回空字符串，停止后状态码 1 时仍为空。旧 `get_prop ["temp"]` 返回 `undefined command`。这些是具体样本，不是对所有固件与所有保温时刻的保证。HA 菜单选择器的“未选择”只是本地准备状态，不会决定设备是否返回温度。
- normal3 插件 10451 明确将 `precook` 映射为预约、`error` 映射为故障，现已补齐。插件虽然声明了 FINISH 界面状态，但这份插件的 `cStatus`/`currentStatusNum` 并没有对应的设备返回值映射；也未找到独立升级状态映射。因此不据界面常量猜测设备状态。
- normal3 插件 10994 内置默认米种 `id=1`、名称“东北米”。10124/10562 从 `https://gateway.joyami.com/mijia-pot-service/rice/list` 获取列表，从 `/mijia-pot-service/device/cook/getRice` 获取云端保存的选择；11030 的运行页也是用后者取名称，并非解析设备 stage 得到名称。
- 已按插件签名方式完成上述两个只读查询，无须用户再通过 HA 代理查询。列表包含 12 个米种条目：东北米、丝苗米、糯米、珍珠米、泰国香米、秋田小町、湖南米、江浙米，以及知吾煮五常有机米、胚芽米、响水大米、雪米。返回同时包含条目 `id` 与分类 `riceTypeId`，不能将它们混作设备 stage 的数字 ID。当前集成仍保留设备原始米种反馈，不把云端保存的偏好当作当前烹饪反馈。
