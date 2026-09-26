# 实体对照

以下对应 main 分支实现，不代表已发布的 v0.5.0。CMC301 共 22 个实体，normal3 共 19 个实体。

所有实体都依赖集成已加载且设备更新成功。表中“—”表示当前集成不提供该实体，不等于硬件绝对没有这项能力。“活动期间”包括烹饪、预约及保温；读不到数据时传感器为 `unknown`，控制条件不满足时控件为 `unavailable`。

| 实体 | 类型 | CMC301 | normal3 | 可用条件、格式和区别 |
| --- | --- | --- | --- | --- |
| Start cooking | button | ✓ | ✓ | 未处于活动期间且已选食谱；执行时还会检查设备状态。成功后清空菜单选择。 |
| Stop cooking | button | ✓ | ✓ | 仅活动期间可用。 |
| Cooking menu | select | 13 个食谱 | 11 个食谱 | 非活动期间可选；额外有 `none`（未选择），初始及清空后使用此值。 |
| Taste | select | ✓ | ✓ | 精煮饭为 `soft/middle/hard`，其他情况仅 `default`；活动期间不可用。 |
| Duration | select | ✓ | ✓ | 已选食谱且非活动期间可用；字符串分钟数，例如 `"25"`；按食谱范围生成 5/10 分钟步进及边界值，固定时长只有一个选项。选食谱时自动选默认时长。 |
| Automatic keep warm | switch | ✓ | ✓ | 开始前仅支持此选项的食谱可用。活动期间 CMC301 无独立读回而不可用；normal3 有有效反馈时显示实际设置，但拒绝修改。 |
| Scheduled duration | number | ✓ | — | 支持预约的食谱、非活动期间；0–1439 分钟整数，0 为立即开始，其他值还须符合食谱限制。 |
| Custom recipe | select | 13 个候选 | 7 个扩展食谱候选 | 非活动期间可修改，不会开始加热。CMC301 从自选模式读回并在本次加载期间记忆；normal3 独立读取收藏槽。未知为 `unknown`；读到不包含的食谱为 `other`，不能主动选择 `other`。 |
| Panel auto off | select | `off`、2–10 | `off`、5–10 | 数字是分钟、间隔 1 分钟；读回有效设置才可用。normal3 还要求待机。 |
| Panel recipe lights | select | ✓ | — | `selected/all`，显示 Selected/All（当前选择/全部）；读取设备实际值，读回未知时不可用。替换旧 Panel mode lights 开关。 |
| Completion notification | switch | ✓ | ✓ | 小米 App 完成通知设置；normal3 仅待机可改，不是蜂鸣器开关。 |
| Buzzer | switch | ✓ | — | 设备蜂鸣器开关。 |
| Lid open alarm | switch | — | ✓ | 开盖超时报警设置，待机且读回有效时可用。 |
| Lid-open keep-warm timeout | select | — | ✓ | 2/4/6/8/10 分钟；待机且读回有效时可用。 |
| Status | enum sensor | ✓ | ✓ | 共用待机、烹饪、保温等名称；CMC301 另有明确的预约、故障、升级、完成状态；normal3 部分协议过程值归入 `busy`，未识别值为 `unknown`。 |
| Current menu | enum sensor | ✓ | ✓ | 活动期间显示设备读回食谱；不识别的 ID 为 `other`，待机为 `unknown`。两边都不是“准备开始”的菜单选择。 |
| Current taste | enum sensor | ✓ | ✓ | 活动期间：精煮饭显示 `soft/middle/hard`，其他已知食谱显示 `default`；缺失数据或待机为 `unknown`。CMC301 来自 texture 属性，normal3 来自 stage 中的口感字段。 |
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
