# 实体对照

以下对应 main 分支实现，不代表已发布的 v0.5.0。CMC301 共 21 个实体，normal3 共 19 个实体。

所有实体都依赖集成已加载且设备更新成功。表中“—”表示当前集成不提供该实体，不等于硬件绝对没有这项能力。“活动期间”包括烹饪、预约及保温；读不到数据时传感器为 `unknown`，控制条件不满足时控件为 `unavailable`。

| 实体 | 类型 | CMC301 | normal3 | 可用条件、格式和区别 |
| --- | --- | --- | --- | --- |
| Start cooking | button | ✓ | ✓ | 未处于活动期间且已选食谱；执行时还会检查设备状态。成功后清空菜单选择。 |
| Stop cooking | button | ✓ | ✓ | 仅活动期间可用。 |
| Cooking menu | select | 13 个食谱 | 11 个食谱 | 非活动期间可选；额外有 `none`（未选择），初始及清空后使用此值。 |
| Fine rice taste（精煮口感） | select | ✓ | ✓ | `soft/middle/hard`；仅选中精煮饭且尚未开始时可用，其余情况不可用。 |
| Duration | select | ✓ | ✓ | 已选食谱且非活动期间可用；字符串分钟数，例如 `"25"`；按食谱范围生成 5/10 分钟步进及边界值，固定时长只有一个选项。选食谱时自动选默认时长。 |
| Automatic keep warm | switch | ✓ | ✓ | 开始前仅支持此选项的食谱可用。活动期间两边都不可用；normal3 非待机也不可用，其实际设置仍在内部读取，不以可操作开关呈现。 |
| Scheduled duration | number | ✓ | — | 支持预约的食谱、非活动期间；0–1439 分钟整数，0 为立即开始，其他值还须符合食谱限制。 |
| Custom recipe | select | 13 个候选 | 7 个扩展食谱候选 | 仅待机时可修改，不会开始加热。CMC301 从自选模式读回并在本次加载期间记忆；normal3 独立读取收藏槽。未知为 `unknown`；读到不包含的食谱为 `other`，不能主动选择 `other`。 |
| Panel auto off | select | `off`、2–10 | `off`、5–10 | 数字是分钟、间隔 1 分钟；读回有效设置才可用。normal3 还要求待机。 |
| Panel recipe lights | select | ✓ | — | `selected/all`，显示 Selected/All（当前选择/全部）；读取设备实际值，读回未知时不可用。替换旧 Panel mode lights 开关。 |
| Completion notification | switch | ✓ | ✓ | 小米 App 完成通知设置；normal3 仅待机可改，不是蜂鸣器开关。 |
| Lid open alarm | switch | — | ✓ | 开盖超时报警设置，待机且读回有效时可用。 |
| Lid-open keep-warm timeout | select | — | ✓ | 2/4/6/8/10 分钟；待机且读回有效时可用。 |
| Status | enum sensor | ✓ | ✓ | 两边均有待机、烹饪、保温、预约、故障；CMC301 另有明确的升级、完成状态读回。normal3 其他历史协议过程值仍归入 `busy`，未识别值为 `unknown`。 |
| Current menu | enum sensor | ✓ | ✓ | 活动期间显示设备读回食谱；不识别的 ID 为 `other`，待机为 `unknown`。两边都不是“准备开始”的菜单选择。 |
| Fine rice taste（精煮口感） | enum sensor | ✓ | ✓ | 仅精煮饭烹饪中显示 `soft/middle/hard`；其他菜单、保温、预约、待机及缺失反馈均为 `unknown`。CMC301 来自 texture 属性，normal3 来自 stage 中的口感字段。 |
| Current duration | duration sensor | ✓ | ✓ | 活动期间的设备读回时长，数值分钟；待机为 `unknown`，不使用准备参数补值。 |
| Remaining time | duration sensor | ✓ | ✓ | 数值分钟。CMC301 的秒读回除以 60，可能有小数；normal3 使用设备的整数分钟反馈。 |
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

Current menu 直接显示设备报告的食谱，保温来源没有独立枚举。自动保温时若固件仍报告原食谱，菜单会继续显示该食谱；显式保温食谱则显示保温。这个区分依赖实际读回，不能将所有 `keep_warm` 状态一概视为自动保温。normal3 的原始协议存在 `autokeepwarm`，目前归一化后也显示 `keep_warm`；CMC301 没有已确认的独立来源字段。当前实现不能在所有情形下可靠报告自动/手动来源。

## 2026-09-26 插件与接口复核

- CMC301 插件 1041640 v1 的通信模块 10196 未读取或写入 2.32，插件中也未找到蜂鸣器控制入口、触发条件或说明。设备曾接受属性写入不等于实际有响铃效果；已移除 Buzzer 实体、写入接口及其轮询，并清理旧实体注册。
- CMC301 先前 `heating_mode4_live.jsonl` 记录中，状态码 4 时的 2.28 返回空字符串，停止后状态码 1 时仍为空。旧 `get_prop ["temp"]` 返回 `undefined command`。这些是具体样本，不是对所有固件与所有保温时刻的保证。HA 菜单选择器的“未选择”只是本地准备状态，不会决定设备是否返回温度。
- normal3 插件 10451 明确将 `precook` 映射为预约、`error` 映射为故障，现已补齐。插件虽然声明了 FINISH 界面状态，但这份插件的 `cStatus`/`currentStatusNum` 并没有对应的设备返回值映射；也未找到独立升级状态映射。因此不据界面常量猜测设备状态。
- normal3 插件 10994 内置默认米种 `id=1`、名称“东北米”。10124/10562 从 `https://gateway.joyami.com/mijia-pot-service/rice/list` 获取列表，从 `/mijia-pot-service/device/cook/getRice` 获取云端保存的选择；11030 的运行页也是用后者取名称，并非解析设备 stage 得到名称。
- 已按插件签名方式完成上述两个只读查询，无须用户再通过 HA 代理查询。列表包含 12 个米种条目：东北米、丝苗米、糯米、珍珠米、泰国香米、秋田小町、湖南米、江浙米，以及知吾煮五常有机米、胚芽米、响水大米、雪米。返回同时包含条目 `id` 与分类 `riceTypeId`，不能将它们混作设备 stage 的数字 ID。当前集成仍保留设备原始米种反馈，不把云端保存的偏好当作当前烹饪反馈。
