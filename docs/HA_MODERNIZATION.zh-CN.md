# HA 现代化与重构（0.4.0）

最低支持 **Home Assistant 2026.8.0**，使用 Python 3.14。2026-09-24 完成本轮实现；本轮未操作电饭煲或部署 HA，0.4.0 尚未发布 Release。保留实体 unique ID、集成 domain、服务名称、食谱程序和启动/停止协议。

## 设备注册表与生命周期

HA 2026.8 改为每个设备属于单个配置项。本轮完全移除 2026.8 之前的兼容分支，不再读取 `DeviceEntry.config_entries`。直接使用 `config_entry_id`；自动化中保存的旧复合设备 ID，通过 2026.8 已提供的 `async_get_devices_for_composite_device_id()` 解析。只定位已加载的本集成配置项；若一个旧 ID 匹配到多台本集成设备，要求用户明确指定设备，不任意选取。

较新的 `async_get_device_and_config_entry_for_domain()` 并不存在于 2026.8.0，因此没有用它冒充最低版本兼容。依据：[HA 2026.8 设备注册表改动](https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/)、[后续弃用公告](https://developers.home-assistant.io/blog/2026/09/15/device-entry-config-entries-deprecation/)，并对照安装的 2026.8.0 源码与测试验证。

coordinator 存放在带类型的 `ConfigEntry.runtime_data`，不再在 `hass.data` 重复维护。服务在 `async_setup` 注册，每次调用定位当前已加载的 coordinator；卸载设备不删除全局服务。`services.py` 管服务，`__init__.py` 管加载卸载。

原来的 update listener 已移除：重新配置使用 HA 的 `async_update_reload_and_abort()`，由该 helper 安排一次重载，避免重复重载及 HA 2026.12 将移除的组合用法。

## 重新配置连接

在设备与服务页面打开该集成配置项的“重新配置”：

- 可修改 IP 和 Token，Token 输入框为密码字段，且不显示或预填已保存值。
- Token 留空或只填空白/BOM 时沿用原值；新值按原有规则清理 BOM、换行与空格。
- 保存前进行只读连通性检查，比较设备身份。另一台设备、缺少 MAC 身份或连接失败时均不覆盖原配置。
- 成功只更新连接信息并重载，不改配置项身份、实体 unique ID 或菜单状态规则。

此流程不发送启动、停止或设置命令。miIO 无法可靠区分错误 Token 与设备离线，因此没有伪造“自动认证失效”判断。

## 脱敏诊断

支持 HA 的“下载诊断”。只从 coordinator 缓存生成报告，不读取 Token 文件、不触发设备轮询或控制。

采用字段白名单，包含型号/固件、运行状态、阶段、选中的食谱及准备参数、最近更新是否成功；不序列化配置项或 API 对象，不包含 Token、IP、MAC、配置项 ID、设备 unique ID 或原始异常消息。异常只保留类型名称，未知 properties 字段不会自动进入报告。

## 翻译与类型契约

- 服务、按钮和参数控件的错误采用 HA 可翻译异常，提供完整中英文文本。
- 食谱范围错误携带数值占位符；不支持预约、口感或保温分别有明确提示。
- CMC301 的远程控制禁止、非待机/故障、启动结果未确认、设置写入未确认保留独立错误语义；未知传输失败使用统一提示，不把原始设备回复直接显示给用户。
- 协议层通过独立的错误类型提供错误码，不依赖 HA 翻译实现；食谱异常仍属于 ValueError，设备命令异常仍属于 DeviceException。
- 新增 `CookerBackend`、`RecipeCodec` 及可选设置/面板能力的 Protocol。API 与 coordinator 使用这些契约；静态测试检查两个 backend 和两个 codec 的接口兼容，不代表全仓库已通过严格类型检查。

六个平台显式声明并发策略，实际设备访问继续由每台设备的命令锁和 API 锁串行化。保留现代实体命名、翻译、CoordinatorEntity、单位枚举和可用性逻辑；不再提供虚假的电饭煲 HTTP 管理链接。

## 验证与依赖限制

Python 3.14.7 下，**HA 2026.8.0 和 2026.9.3 各 196 项测试通过**。覆盖连接修改成功/失败/换错设备/缺失身份、Token 清理与不回显、只读脱敏诊断、错误翻译及占位符、配置项生命周期、复合设备 ID、重复目标去重、启动前完整校验，以及原有设备与食谱测试。设备网络被测试夹具阻断。

Ruff、格式检查、`git diff --check` 及两个 backend/codec 的 mypy 严格契约检查通过。CI 使用最低版和当前版两个依赖文件运行测试与契约检查。最低版不是只改 HACS 声明而未经验证。

两套环境均有 43 条外部依赖警告：python-miio 的 `datetime.utcnow()` / Click `MultiCommand` 和 HA 的 aiohttp Application 继承警告。截至审查日 python-miio 最新版仍是 0.5.12；没有隐藏警告或修改 site-packages。保留已验证的传输层，待上游修复或另行开展完整协议库迁移。本轮不宣称解决所有第三方依赖警告，也不替代用户 HA 安装验收。
