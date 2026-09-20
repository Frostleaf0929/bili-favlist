# bili-favlist · B站收藏夹批量分类工作台

<p align="center">
  <strong>把爆掉的 B 站收藏夹，变成可持续运转的分类流水线</strong><br/>
  多信号规则 · 热词自学习 · 字段权重学习 · 盲测验证 · 三层保护批量写回<br/>
  Python 3.10+ · 纯标准库本地 Web 工作台 · Windows 绿色版
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11%20%7C%20macOS%20%7C%20Linux-blue" alt="platform" />
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="license" />
</p>

---

## 下载使用（普通用户看这里，无需编译）

`bili-favlist` 帮你把已经乱掉的 B 站收藏夹整理成有分类的样子：读你自己的收藏夹 → 用规则/热词/权重判断每个视频该归哪类 → 你复核 → 批量搬回 B 站。整个流程跑在你本机的浏览器里打开的工作台上，数据不上传。

**推荐方式：直接下载 Release 里的绿色版压缩包，解压双击即用，不需要装 Python。**

> 👉 **[前往 Releases 页面下载最新版 →](https://github.com/Frostleaf0929/bili-favlist/releases)**
> ⚠️ 认准本仓库地址 `Frostleaf0929/bili-favlist`。

**使用环境（就这三条）：**

| 要求 | 说明 |
|------|------|
| Windows 10 / 11（64 位） | 绿色版只提供 Windows 构建；其他系统从源码跑 |
| 浏览器 | 任意现代浏览器（界面就是本地网页） |
| 磁盘空间 | 程序约 25 MB；你的收藏夹数据几十 MB |

**四步上手：**

1. 解压 `bili-favlist-v0.1.0-win64.zip` 到一个**单独的文件夹**（比如 `D:\bili-favlist\`）；
2. 把 `config.yaml`（填 B站 Cookie，模板见 `config.example.yaml`）和 `rules.yaml` 放进同一目录；
3. **双击 `启动.bat`** —— 浏览器会自动打开操作界面；
4. 按 **手动分类对比 → 流水线 → 写回与设置** 的顺序操作。用完**关掉那个黑色命令行窗口**就是停止。

**没有 Cookie 也能先玩：** 删掉 `config.yaml` 再启动，会自动进**演示模式**，用内置的虚构示例数据走完整流程（导出与写回不可用）。

**Cookie 怎么拿：** 登录 bilibili.com 后按 F12 → 网络 → 任选一条 `api.bilibili.com` 请求 → 右键「复制 → 以 cURL(bash) 格式复制」→ 从中摘出 `SESSDATA` / `bili_jct` / `DedeUserID` 三个字段填入 `config.yaml`。

## 免责声明（使用前必读）

- 本项目调用 **B站网页端在用的非公开接口**（社区逆向成果），接口随时可能变动；2026 年 1 月 B站曾对 API 文档站发过律师函。**请仅以「个人整理自己账号」为目的低频使用**，勿用于批量爬取或商业用途。
- 批量写操作**有触发风控的可能**（验证码 / 临时限制）。工具内置保守限速与失败熔断，但**请务必从预览开始，小批量试跑后再全量**。
- 本项目**只移动、不删除** —— 代码里没有任何删除接口。
- `config.yaml` 里的 Cookie 等同登录凭证：**不要提交到 git、不要分享**（已被 `.gitignore` 排除）。

## 核心功能

| 模块 | 能力 |
|------|------|
| 导出 | 列出自建收藏夹、分页拉取全量条目（含来源夹、失效标记），增量落盘，限速 + 错误码分级重试 |
| 补标签 | 并发补拉视频 tags（可调并发与冷却），按 bvid 去重，断点落盘防中断 |
| 规则分类 | 标题 / 标签 / UP主 / 简介 四类条件，按字段加权打分；**单一关键词不允许直接命中**，需 ≥2 个关键词或 ≥2 个不同字段佐证 |
| 共现强化 | 每次人工/AI 定类都统计「关键词 ↔ 分类」概率，P≥60% 且样本足够时自动升级为强化规则 |
| 热词自学习 | 从你自己的收藏夹语料统计标题二字组 / 标签 / UP名的共现概率，生成个人化词表（无外部依赖，不从网络取任何词库） |
| 权重学习 | 语料按收藏夹分层做 80/20 切分，网格搜索 title / tag / up 的最优字段权重，输出留出集准确率与重分类一致率 |
| 双学习池 | 池1（客观内容）学出的热词直达对应分类；池2（情绪化/个人化）只学「排他性特征」，命中统一进【个人化】，且原夹自动受保护 |
| 盲测验证 | 忽略收藏夹来源与既有标注，只用规则+热词预测，再与你手动整理的结果比对重合率（细分夹与大分类夹两种口径） |
| 两级归类 | 初始分类（叶）可合并进大分类夹（组），写回时按绑定关系落到具体收藏夹 |
| 多层复查 | 流水线可反复运行，每遍产出改判报告，改判条目自动进入复核队列 |
| AI 兜底 | 导出待分类清单交给任意 LLM 分析后导回；也可配置 OpenAI 兼容接口在线批量分类 |
| 趣味数据 | Top50 标签、Top30 UP主、月度收藏量、分类数量排行、标签覆盖率 |

## 写回安全闸门

写回前请依次确认三件事：

| 闸门 | 说明 |
|------|------|
| 保护名单 | 三级保护：`锁定`（既不能作移动目标、也不能作移动源）/ `软保护`（可以动，但执行时必须额外输入确认串）/ `自由`。池2 的情绪化/个人化夹会自动锁定 |
| 移动范围 | 默认「最小授权」——只有白名单里的收藏夹能作为移动源。首次使用会自动填入条目最多的那个夹（通常是被刷爆的主夹） |
| 限额 | 默认单次 200 条、当日 1000 条。计划生成与执行时各校验一次，当日用量落地统计 |

三层之外还有一道**竞态检查**：计划生成后若保护等级被改动，执行会被拒绝并要求重新生成计划。
另外，执行移动本身需要输入 `APPLY`；若计划涉及软保护夹，还需再输入 `CONFIRM-SOFT`。

## 工作台页面

| 页面 | 作用 |
|------|------|
| 流水线 | 一键跑完整流程（建议连跑两遍）；遍次差异报告；关键词↔分类共现 TOP |
| 待审复核 | 规则改判 / 低置信条目逐条确认，可按「最拿不准」排序 |
| 全部条目 | 状态与分类筛选、搜索、批量标注 |
| 分类体系 | 叶分类 ↔ 大分类夹两级归组，分别绑定 B站收藏夹 |
| 规则 | 手写 / 初筛 / AI / 强化 四个规则块，逐条启停与删除 |
| 手动分类对比 | 勾选学习池1/池2 → 学热词 → 学权重 → 跑盲测重合率 → 规则包导出与回导 |
| 趣味数据 | 六张统计卡片 + 四个排行 |
| 写回与设置 | 保护名单 + 移动范围与限额 → 生成计划 → 输 APPLY 执行 → 查看报告 |

## 分类原理

1. **初筛**：按字段（标题 / 标签 / UP主 / 简介）加权打分，默认权重 `UP主 2.0 > 标题 1.0 > 标签 0.6`（可由权重学习改）；
2. **多信号门槛**：最高分过阈值、领先第二名足够多、且命中证据 ≥2 个，才算规则命中（阈值可调）；
3. **热词兜底**：规则没命中的条目，用从你语料里学到的热词表判断，门槛为得分 ≥0.8 且与次高差 ≥0.3；
4. **个人化优先**：池2 学到的是「排他性特征」（该特征在池1 客观语料中从未出现），命中即归【个人化】，优先级高于规则与热词；
5. **人工/AI 最高优先**：任何人工或 AI 标注都不会被规则覆盖；AI 每次定类又反过来喂给共现统计，让规则自我强化；
6. **两级归组**：叶分类可合并进大分类夹，写回目标 = 叶分类绑定的收藏夹（无则取所属大组的）。

## 从源码运行与构建（开发者）

普通用户**不需要**这一节——直接去 [Releases](https://github.com/Frostleaf0929/bili-favlist/releases) 下载绿色版即可。

**运行环境要求：**

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| [Python](https://www.python.org/) | ≥ 3.10（实测 3.12.11） | 运行时 |
| requests / PyYAML / openpyxl | 见 `requirements.txt` | 全部运行依赖，就这三个 |

**运行步骤：**

```bash
git clone https://github.com/Frostleaf0929/bili-favlist.git
cd bili-favlist

python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 演示模式（无需 Cookie，内置虚构数据）
.venv\Scripts\python.exe src\main.py app --demo

# 正式使用
.venv\Scripts\python.exe src\main.py export --list   # 验证登录态
.venv\Scripts\python.exe src\main.py export --all    # 全量导出 → data/export.json
.venv\Scripts\python.exe src\main.py app             # 启动工作台
```

Windows 下也可以直接双击项目根目录的 `启动工作台.bat`（自动检测有无 `config.yaml`，并自动打开浏览器）。

**打包绿色版：**

```bash
.venv\Scripts\python.exe -m pip install pyinstaller

.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --name bili-favlist ^
  --paths src ^
  --add-data "src/webui;webui" ^
  --add-data "src/sample_data;sample_data" ^
  src/main.py
```

> **两个 `--add-data` 都不能省。** `app_server.py` 是用自己所在目录去找 `webui/` 的，不把前端打进去就会打开白屏；
> `sample_data/` 不打包则演示模式起不来。想打成单文件可换 `--onefile`，但每次启动都要解压、且杀毒误报率明显更高。

**CLI 等价能力：**

```bash
python src/main.py export --list                 # 列出自建收藏夹
python src/main.py export --all                  # 全量导出（--exclude 可排除大夹）
python src/main.py classify --emit-ai            # 规则打分 → xlsx + AI待办清单
python src/main.py classify --merge-ai ai.csv    # AI结果合回
python src/main.py writeback                     # 写回 dry-run 预览
python src/main.py writeback --apply --limit 10  # 小批量试运行
```

> ⚠️ `writeback` 走的是命令行路径，**不检查工作台的保护名单**。为避免误动受保护的收藏夹，建议统一用工作台写回。

## 项目结构

```
bili - favlist/
├── src/
│   ├── bili_api.py         # B站接口封装：Cookie / 限速 / 重试 / 错误码分级（无删除接口）
│   ├── export_fav.py       # 导出收藏夹 → data/export.json / export.csv
│   ├── app_engine.py       # 分类引擎：打分 / 热词 / 权重学习 / 双池 / 盲测 / 三级保护
│   ├── app_server.py       # 本地 Web 服务 + 全部 /api 路由 + 写回计划生成
│   ├── webui/              # 工作台前端（原生 HTML/JS/CSS，无框架）
│   ├── classify.py         # 命令行分类（读 rules.yaml → classified.xlsx + AI 队列）
│   ├── wb_plan.py          # 写回计划（命令行路径，读 classified.xlsx）
│   ├── wb_exec.py          # 写回执行：分批 / 断点续跑 / 熔断 + 事后核对报告
│   ├── writeback.py        # 写回命令行入口（默认 dry-run）
│   ├── main.py             # 统一入口：export / classify / writeback / app
│   └── sample_data/        # 演示模式用的虚构示例数据
├── rules.yaml              # 分类规则（示例，可自行改写）
├── config.example.yaml     # 配置模板（复制为 config.yaml 后填写）
├── userscript/             # 油猴备用方案（浏览器内执行写回）
└── data/                   # 运行产物（已 gitignore）
```

## 隐私与安全

- **没有任何数据上传**：所有请求只发往 `api.bilibili.com`（代码里对请求地址做了 host 白名单校验，强制 https）；工作台只监听 `127.0.0.1`。
- **Cookie 只存本地**：写在 `config.yaml`，已被 `.gitignore` 排除；仅在内存中拼进请求头，日志不打印。
- **只移动、不删除**：`bili_api.py` 只暴露建夹与移动两个写接口，没有删除能力。
- **写操作默认不执行**：命令行需 `--apply`；工作台需输入 `APPLY` 确认串，并受保护名单 / 移动范围 / 当日限额三重约束。
- **LLM 接口校验**：配置在线 AI 分类时强制 https，且禁止指向本机或内网地址。

## 致谢

- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)（社区接口文档，已停维）
- [qianb7/bilibili-favlist](https://github.com/qianb7/bilibili-favlist)、[Junliang-liu-kit/Bili_to_MD](https://github.com/Junliang-liu-kit/Bili_to_MD)：导出思路参考
- [Argilla](https://github.com/argilla-io/argilla) / [Label Studio](https://labelstud.io/)：规则弱监督 + 人工复核的交互模式参考
- 本项目为 **Vibe Coding** 实践，由 [ZCode](https://www.zcode.com) 智能体驱动完成全部开发，主要编码模型为 **GLM**（Z.ai）与 **DeepSeek**。分类算法（多信号打分 / 热词自学习 / 权重网格搜索 / 双池设计）与写回安全闸门的设计均在 AI 协作下迭代得出。

## 作者

**[Frostleaf0929](https://github.com/Frostleaf0929)**

## License

[MIT](./LICENSE)
