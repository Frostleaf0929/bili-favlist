# bili-favlist · B站收藏夹批量分类工作台

[![CI](https://github.com/YOUR_NAME/bili-favlist/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

把爆掉的B站收藏夹，变成一套**可持续运转的分类流水线**：

> 导出 → 标题关键词初筛 → AI 细化 → 共现概率强化规则 → 人工复核 → 两级归类（初始分类合并为大分类夹）→ 批量写回B站

核心特性：

- 🖥️ **本地交互式工作台**（纯标准库 Web 服务，浏览器操作，见下方截图位）
- 🛡️ **三层写回保护**：`锁定 / 软保护 / 自由`——锁定夹既不能作移动目标也不能作移动源（池2 情绪化/个人化夹自动锁定）；软保护夹执行时需额外输入确认串
- 🚦 **移动范围最小授权**：默认只有白名单里的收藏夹能作为"移动源"，可显式放开
- ⛔ **写回限额**：单次 / 当日双重上限，计划生成与执行时各校验一次
- 🚦 **多信号判定**：单一关键词不允许直接命中，需 ≥2 个关键词/字段佐证（阈值可调）
- 📈 **共现强化**：AI/人工每次定类都统计「关键词↔分类」概率，P≥60% 且样本足够时自动升级为强化规则
- 🔥 **个人化热词学习**：从你自己的收藏夹语料里统计标题二字组 / 标签 / UP 名的共现概率（自举词表，无外部依赖）
- ⚖️ **字段权重学习**：语料按夹分层 80/20 切分，网格搜索 title/tag/up 的最优权重
- 🧫 **双学习池**：池1（客观内容）学出的热词直达对应分类；池2（情绪化/个人化）只学"排他性特征"，命中统一进【个人化】，且原夹自动受保护
- 🔬 **盲测验证**：忽略收藏夹来源与标注，只用规则+热词预测，再与你手动分类对比重合率（细分夹 64% / 大分类夹 79%）
- 🗂️ **两级分类**：初始分类手动合并进大分类夹，写回以大分类夹为准——管理几十个同类项，而不是几万个视频
- 🔁 **多遍复查**：流水线可反复运行，每遍产出改判报告，改判条目自动进入复核队列
- 🧪 **手动分类对比**：用你手动整理过的收藏夹当标准答案，量化这套思路链与你人工分类的一致率
- 🛡️ **安全边界**：只移动、不删除；写操作默认 dry-run；限速+失败熔断+断点续跑；Cookie 仅存本地

<!-- 截图位：运行后截两张图替换（流水线页 / 评估页）
![screenshot](docs/screenshot-dash.png)
-->

## ⚠️ 免责声明（使用前必读）

- 本项目调用 **B站网页端在用的非公开接口**（社区逆向成果），接口随时可能变动；2026年1月B站曾对API文档站发过律师函，请仅以**个人整理自己账号**为目的低频使用，勿用于批量爬取或商业用途。
- 批量写操作有触发风控的可能（验证码/临时限制）。工具已内置保守限速与熔断，但**请从 dry-run 预览开始，小批量试运行后再全量**。
- `config.yaml` 里的 Cookie 等同登录凭证：**不要提交、不要分享**（已被 .gitignore 排除）。

## 🚀 快速开始

### 方式一：Windows 绿色版（免装 Python）

下载 release 里的 `bili-favlist-v0.1.0-win64.zip`，解压后：

1. 把 `config.yaml`、`rules.yaml` 放到 `bili-favlist.exe` 同目录（`config.yaml` 填 Cookie，模板见 `config.example.yaml`）
2. **双击 `启动.bat`**（或直接双击 `bili-favlist.exe`）
3. 浏览器会自动打开 http://127.0.0.1:8787 —— 这就是操作界面
4. 用完**关掉那个黑色命令行窗口**就是停止

> 原目录可整体拷贝到 U 盘或别的电脑。没有 `config.yaml` 时会自动进**演示模式**（内置虚构数据，导出/写回不可用）。

### 方式二：从源码运行

```bash
git clone https://github.com/YOUR_NAME/bili-favlist.git
cd bili-favlist
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt

# ① 没有Cookie也能玩：演示模式（内置虚构示例数据，写回不可用）
.venv\Scripts\python src\main.py app --demo      # 打开 http://127.0.0.1:8787

# ② 正式使用：配置 Cookie 后启动
copy config.example.yaml config.yaml             # 填入 SESSDATA / bili_jct / DedeUserID
.venv\Scripts\python src\main.py export --list   # 验证登录态，列出收藏夹
.venv\Scripts\python src\main.py export --all    # 导出全部收藏夹 → data/export.json
.venv\Scripts\python src\main.py app             # 启动工作台
```

也可以直接双击项目根目录的 **`启动工作台.bat`**（自动检测有无 `config.yaml`，并自动打开浏览器）。

Cookie 三件套获取：登录 bilibili.com 后 F12 → 网络 → 任选一条 `api.bilibili.com` 请求 →
右键「复制 → 以 cURL(bash) 格式复制」→ 从中摘出三个字段填入 `config.yaml`（也可从 应用→Cookie 面板复制）。

## 🧭 工作台功能速览

| 页面 | 作用 |
|---|---|
| 流水线 | 一键跑完整流程（建议连跑两遍）；遍次差异报告；关键词↔分类共现TOP |
| 待审复核 | 规则改判/低置信条目逐条确认 |
| 全部条目 | 筛选/搜索/批量标注 |
| 分类体系 | 初始分类 ↔ 大分类夹 两级归组，绑定B站收藏夹 |
| 规则 | 手写/初筛/AI/强化 四个规则块，逐条启停 |
| 手动分类对比 | 勾选学习池1/池2 → 学热词 → 学权重 → 盲测重合率 → 规则包导出/导入 |
| 趣味数据 | Top50 标签、Top30 UP主、月度收藏量、分类数量排行 |
| 写回与设置 | **🛡 保护名单（锁定/软保护/自由）** + **🚦 移动范围与限额** → 计划预览 → 输入 APPLY 执行 |

### 写回安全闸门（v0.1.0）

写回前请依次确认三件事：

1. **保护名单**——池2 的情绪化/个人化夹会自动设为「锁定」，锁定的夹既不会被写入、也不会被搬出。
   想动某个夹，需在下拉框里显式改成「软保护」（执行时需额外输入 `CONFIRM-SOFT`）或「自由」。
2. **移动范围**——默认「最小授权」，只有白名单里的收藏夹能作为移动源。想放开需显式勾选。
3. **限额**——默认单次 200 条、当日 1000 条，防止手滑或异常批量搬运。

三层之外还有一道竞态检查：计划生成后若有人改了保护等级，执行会被拒绝并要求重新生成计划。

## 🧠 分类原理

1. **初筛**：`rules.yaml` 的关键词/正则按字段（标题/标签/UP主/简介）加权打分；
2. **多信号门槛**：单一关键词不自动命中；最高分过阈值、领先第二名足够多、且命中证据 ≥2 才算规则命中（全部可调）；
3. **AI 细化**：未命中条目导出 AI 队列（CSV）交给任意 LLM 分析后导回；或在设置里配 OpenAI 兼容接口直接在线批量分类；
4. **共现强化**：每次 AI/人工定类都会更新「关键词↔分类」共现统计，P≥60%（可调）且样本≥5 的组合自动升级为强化规则；
5. **两级归类**：初始分类可合并进大分类夹，写回目标 = 初始分类绑定的收藏夹，否则大分类夹的收藏夹。

## 🛠️ CLI（等价能力，适合脚本化）

```bash
python src/main.py export --list                 # 列出自建收藏夹
python src/main.py export --all                  # 全量导出（--exclude 可排除大夹）
python src/main.py classify --emit-ai            # 规则打分 → xlsx + AI待办清单
python src/main.py classify --merge-ai ai.csv    # AI结果合回
python src/main.py writeback                     # 写回 dry-run 预览
python src/main.py writeback --apply --limit 10  # 小批量试运行（强烈建议先做）
```

## 📦 打包

```bash
# 标准 wheel
pip install build && python -m build

# Windows 绿色版（推荐 --onedir：启动快、杀毒误报少）
pip install pyinstaller
pyinstaller --noconfirm --onedir --name bili-favlist --paths src ^
  --add-data "src/webui;webui" ^
  --add-data "src/sample_data;sample_data" ^
  src/main.py
# 产物 dist/bili-favlist/（配 启动.bat 使用）；config.yaml / rules.yaml / data/ 放 exe 同目录
```

> ⚠️ **两个 `--add-data` 都不能省。** `app_server.py` 是用自己所在目录去找 `webui/` 的，
> 不把前端打进去 → 打开页面 404 白屏；`sample_data/` 不打包 → 演示模式起不来。
> 想打成单文件可以换 `--onefile`，但每次启动都要解压、且杀毒误报率明显更高。

打包用的依赖：`pyinstaller`（已在 `pyproject.toml` 的 `[project.optional-dependencies]` 里声明）。

## 📁 目录说明

```
├── src/            # 全部源码（bili_api/export/classify/writeback/app_*）
│   ├── webui/      # 工作台前端（原生 HTML/JS/CSS）
│   └── sample_data/  # 演示模式用的虚构示例数据
├── rules.yaml        # 分类规则（人工维护）
├── config.example.yaml
├── data/             # 运行产物（gitignore：含 Cookie 的 config 与个人数据）
└── userscript/       # 油猴备用方案（浏览器内执行写回）
```

## 🙏 致谢与参考

- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)（社区接口文档，已停维，备份见 pskdje fork）
- [qianb7/bilibili-favlist](https://github.com/qianb7/bilibili-favlist)、[Junliang-liu-kit/Bili_to_MD](https://github.com/Junliang-liu-kit/Bili_to_MD)：导出思路参考
- [Argilla](https://github.com/argilla-io/argilla) / [Label Studio](https://labelstud.io/)：规则弱监督 + 人工复核的交互模式参考

## License

[MIT](LICENSE)
