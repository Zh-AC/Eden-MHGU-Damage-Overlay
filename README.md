# Eden 模拟器 怪物猎人 GU 伤害飘字插件(Eden MHGU Damage Overlay)

> [English](README_EN.md)

在 **Eden 模拟器**(Nintendo Switch 模拟器)上运行《怪物猎人 GU》时,把游戏中的伤害数字实时叠加显示在画面上(类似《怪物猎人:世界 / 崛起》的效果)。

我不是专业开发人员，我确信很多规则我不懂，如果我做错了什么事情请指正我。

入坑这个游戏的时候发现老怪猎没有伤害显示很难受，幸好有前辈指了路让我能试着做一下伤害显示。本来想自用后面借助AI发出来希望能帮助其他GU猎人。

Eden模拟器中的XX表现如何我没有测试过。反馈BUG的话可能会修的很慢，如果太难而且不影响游戏可能会不修，我会尽力。

## 怎么工作

通过 AOB(字节特征码)扫描,在 eden.exe 的进程内存里定位每只怪物的血量地址,持续读取血量;**血量下降的差值就是伤害数值**,渲染成屏幕上的飘字。

## 功能

- 怪物和小动物的伤害都显示(小怪默认降级显示:小字号、低透明度,不挡视线)
- 伤害分级配色:低伤害白色、中伤害黄色、高伤害橙色(阈值可配置)

## 使用方式

1. 启动 Eden 模拟器(`eden.exe`),加载 MHGU。
2. 启动插件,二选一:
   - **方式 A(免 Python 环境)**:双击插件目录下的 `MHGUDamageOverlay.exe`
   - **方式 B(源码运行)**:
     ```
     cd <插件所在目录>
     pip install -r requirements.txt     :: 首次运行需要(pywin32 + numpy + Pillow)
     python mhgu_damage_overlay.py
     ```
3. 插件启动后几秒到十几秒内会自动扫描并追踪怪物,之后打出伤害就能看到飘字
4. 关闭:直接关掉插件窗口,不影响游戏

### 命令行参数(方式 B 可用)

- `--no-overlay`:控制台模式,只在日志里打印伤害数字,不显示叠加层(调试用)
- `--config <路径>`:指定其他 config.ini
- `--emulator <进程名>`:指定其他模拟器进程(默认 eden.exe)

### 常见问题

- **没有数字跳出**:确认游戏已进到怪物在场的场景;插件只会在检测到怪物后开始工作。可查看 `overlay_error.log` 确认是否出现 `Monster tracked` 字样
- **需要管理员吗**:通常不需要(同一用户权限即可读 Eden 内存)。如果日志出现 `access denied`,用管理员身份运行插件
- **日志文件**:`overlay_error.log` 在插件目录下,排障先看它
- **重新打包**:改动源码后运行 `python -m PyInstaller --onefile --name MHGUDamageOverlay --clean --noconfirm --add-binary "core/scanmodule.pyd;core" --version-file dev/version_info.txt mhgu_damage_overlay.py`(`--add-binary` 必须带上,它把核心扫描模块打进 exe),并把 `dist\MHGUDamageOverlay.exe` 复制回插件目录

## 配置说明(config.ini,全部带中文注释)

打开 `config.ini` 即见每一项的注释。关键功能:

| 功能 | 配置项 | 默认值 |
|---|---|---|
| 伤害数字分级配色 | `DamageColorLow / Mid / High`(白/黄/橙) | `#FFFFFF / #FFD93B / #E49124` |
| 分级边界 | `DamageThresholdMid / High` | `40 / 80`(白 &lt;40,橙 ≥80) |
| 数字出现位置(锚点) | `AnchorXRatio / AnchorYRatio`(屏幕比例 0~1) | `0.5 / 0.5`(屏幕中央) |
| 小怪数字降级 | `SmallFontScale`(字号比例)、`SmallOpacity`(最大不透明度) | `0.6 / 0.65` |
| 字体与字号 | `FontPath`、`FontSize` | 系统 Bahnschrift / `70` |
| 阴影 | `DamageShadowEnabled / Color / OffsetX / OffsetY / Thickness` | 开 / 黑 / 2,2 / 3 |
| 飘字节奏 | `[Logic]` 段:停留帧数、淡出帧数、错开距离、同屏上限 | 90 / 30 / 45 / 10 |
| 扫描 | `[Scanner]` 段:HP 上限、扫描间隔、模拟器进程名 | 70000 / 50ms / eden.exe |

## 已知限制

- **无法区分玩家伤害和随从伤害**:内存里只有怪物总血量,没有伤害来源
- **无法识别暴击**:同理,没有暴击标志位,只有血量差值
- **无法在命中部位显示数字**:拿不到怪物 3D 坐标和相机矩阵,数字显示在可配置锚点(默认画面中央)附近
- 怪物睡觉时的自然回血会被识别(血量上升),不会显示为伤害,属正常现象
- 小怪伤害的数字不区分具体种类(只按「大怪/小怪」两级降级显示)

## 致谢 / 参考来源

**首先要感谢 Alexander-Lancellott 的 [`MHGU-MHXX-HP-Overlay-For-Switch-Emulator`](https://github.com/Alexander-Lancellott/MHGU-MHXX-HP-Overlay-For-Switch-Emulator)(GPL v3)。**

**分工提示**:这位作者的工具负责显示怪物血量,本插件只做伤害飘字、不显示血量;两者互不冲突,可以同时开启、互补使用,玩家不用二选一。

这个插件的**核心内存部分全部来自这位作者的心血**:

- AOB 特征码、血量 / 初始血量 / 怪物 ID / 可见性字节的内存偏移
- eden 内存区域地址(0x9BBF000 等)的定位方法
- `scanmodule` C 扩展(加速内存区域枚举和 AOB 扫描)—— 本项目中的 `core/scanmodule.pyd` 即其编译产物,对应源码 `modules/scanmodule.c` 已一并保留在本仓库中
- Microsoft Windows API 文档(MSDN):`UpdateLayeredWindow`、`ReadProcessMemory` 等,用于透明叠加层渲染和进程内存读取

**没有这位作者公开的工具和源码,这个插件不可能存在。**在此向作者和所有开源贡献者致谢。

## 开源许可

本项目基于 **GPL v3** 发布(与参考工具的许可证一致)。

- 依据 GPL v3,本项目是参考工具(也是 GPL v3)的衍生作品
- 本仓库包含:全部源码、`LICENSE`(GPL v3 全文)、`scanmodule` 的 C 源码(`modules/scanmodule.c`,来自参考工具)
- 本插件的 exe 可以自由分发,但分发时必须同时提供上述源码与许可证
- 若你修改后分发,也必须以 GPL v3 公开你的修改

> 附:项目里的 `dev/` 文件夹存放开发期辅助脚本(诊断、渲染对比、回归测试),与插件运行无关,可整体删除。
