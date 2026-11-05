# bili-favlist · B站收藏夹批量分类工作台

![platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20%7C%20macOS%20%7C%20Linux-blue)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![license](https://img.shields.io/badge/license-MIT-green)

## 1. 项目简介

bili-favlist 是一个在本地运行的 B 站收藏夹分类工作台，用于处理收藏夹数量庞大、缺乏分类体系的场景。完整工作流为：导出收藏夹到本地 → 规则 / 热词 / 字段权重自动分类 → 人工复核 → 批量写回 B 站。

交付形态为本地网页工作台（`127.0.0.1:8787`）与 Windows 绿色版。数据不经任何第三方，仅与 `api.bilibili.com` 通信。

## 2. 快速开始

### 2.1 环境要求

| 要求 | 说明 |
|------|------|
| Windows 10 / 11（64 位） | 绿色版仅提供 Windows 构建，其他系统从源码运行 |
| 浏览器 | 任意现代浏览器，界面为本地网页 |
| B 站 Cookie | 用于导出与写回，仅保存在本地 `config.yaml` |
| 磁盘空间 | 程序约 25 MB，工作数据视收藏量而定 |

### 2.2 绿色版（推荐）

1. 从 [Releases](https://github.com/Frostleaf0929/bili-favlist/releases) 下载 `bili-favlist-v0.2.0-win64.zip`，解压到独立目录；
2. 将 `config.yaml` 与 `rules.yaml` 放入同一目录（模板见 `config.example.yaml`）；
3. 双击 `启动.bat`，浏览器自动打开工作台；
4. 关闭命令行窗口即停止服务。

`config.yaml` 需要填入三个 Cookie 字段：`SESSDATA`、`bili_jct`、`DedeUserID`。获取方式：登录 bilibili.com 后打开浏览器开发者工具（F12），在网络面板任选一条 `api.bilibili.com` 请求，从请求头中复制这三个字段的值。

### 2.3 从源码运行

```bash
git clone https://github.com/Frostleaf0929/bili-favlist.git
cd bili-favlist

python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

.venv\Scripts\python.exe src\main.py app --demo   # 演示模式
.venv\Scripts\python.exe src\main.py app          # 正式使用
```

Windows 下也可双击项目根目录的 `启动工作台.bat`，脚本会自动检测 `config.yaml` 并打开浏览器。

### 2.4 演示模式

目录中不存在 `config.yaml` 时自动进入演示模式，使用内置虚构数据体验完整流程；导出与写回功能不可用。

## 3. 功能总览

| 模块 | 能力 |
|------|------|
| 导出 | 列出自建收藏夹，分页拉取全量条目（含来源夹、失效标记），增量落盘，限速与错误码分级重试 |
| 补标签 | 并发补拉视频 tags（可调并发与冷却），按 bvid 去重，断点落盘 |
| 规则分类 | 标题 / 标签 / UP主 / 简介 四类条件加权打分；单一关键词不允许直接命中，需至少两个关键词或两个不同字段佐证 |
| 共现强化 | 每次人工 / AI 定类累计「关键词 ↔ 分类」概率，达到阈值后自动升级为强化规则 |
| 热词自学习 | 从用户自己的收藏夹语料统计标题二字组 / 标签 / UP名的共现概率，无外部词库依赖 |
| 权重学习 | 语料按收藏夹分层 80/20 切分，网格搜索 title / tag / up 最优权重，输出留出集准确率 |
| 双学习池 | 池1（客观内容）学习结果直达对应分类；池2（个人化）只学排他性特征，命中归入【个人化】且原夹自动保护 |
| 盲测验证 | 忽略收藏夹来源与既有标注，仅用规则与热词预测，与手动分类结果对比重合率 |
| 两级归类 | 叶子分类可合并进大分类夹，写回按绑定关系落到具体收藏夹 |
| 多层复查 | 流水线可反复运行，每遍产出改判报告，改判条目自动进入复核队列 |
| AI 兜底 | 导出待分类清单交由任意 LLM 分析后导回；或配置 OpenAI 兼容接口在线批量分类 |

## 4. 工作台页面

侧栏按「整理 / 智能 / 执行」三组组织，底部为设置；全部页面基于真实数据。默认深色主题配靛蓝强调色，主题 / 强调色 / 毛玻璃 / 密度可在界面切换并自动记忆。

| 页面 | 作用 |
|------|------|
| 总览 | 运行流水线、写回额度与盲测重合率、分类分布、最近改判明细 |
| 条目库 | 状态筛选、搜索、翻页、勾选批量标注 |
| 复核队列 | 改判与低置信条目逐条确认：调整建议分类、确认、标为排除 |
| 分类与规则 | 大分类夹新建 / 绑定 / 删除；叶分类绑定与归组；四块规则增删启停 |
| 学习与评估 | 语料双池勾选、热词与权重学习、盲测报告、规则包导出与回导 |
| 写回 | 保护名单、移动范围与限额、计划预览、二次确认执行 |
| 设置与个性化 | 主题个性化、判定阈值、AI 在线分类配置 |

旧版界面整轮保留作备用，入口 `/legacy.html`（或 `?legacy=1`）。

## 5. 分类判定流程

1. **初筛**：按字段（标题 / 标签 / UP主 / 简介）加权打分，默认权重 `UP主 2.0 > 标题 1.0 > 标签 0.6`，可由权重学习更新；
2. **多信号门槛**：最高分需过阈值、领先第二名足够多、且命中证据不少于两项，方判定为规则命中；
3. **热词兜底**：规则未命中的条目使用自学习热词表判断，门槛为得分 ≥ 0.8 且与次高分差 ≥ 0.3；
4. **个人化优先**：池2 学到的排他性特征命中即归【个人化】，优先级高于规则与热词；
5. **人工 / AI 最高优先**：任何人工或 AI 标注不被规则覆盖；AI 定类结果反哺共现统计；
6. **两级归组**：写回目标为叶分类绑定的收藏夹，未绑定时取所属大组的绑定。

## 6. 写回安全机制

### 6.1 三级保护

| 级别 | 行为 |
|------|------|
| 锁定 | 不能作为移动目标，也不能作为移动源；池2 的情绪化 / 个人化夹自动锁定 |
| 软保护 | 可以移动，但执行时必须额外输入确认串 `CONFIRM-SOFT` |
| 自由 | 正常参与计划 |

### 6.2 移动范围与限额

- 移动范围默认**最小授权**：仅白名单内的收藏夹可作为移动源；首次使用自动填入条目最多的收藏夹；
- 限额默认单次 200 条、当日 1000 条，计划生成与执行时各校验一次，当日用量落地统计。

### 6.3 执行约束

- 计划生成后若保护等级被改动，执行会被拒绝并要求重新生成计划（竞态检查）；
- 执行移动需在弹窗中输入 `APPLY`；计划涉及软保护收藏夹时还需输入 `CONFIRM-SOFT`；
- 只移动、不删除：代码中不存在任何删除接口。

## 7. 命令行工具

```bash
python src/main.py export --list                 # 列出自建收藏夹
python src/main.py export --all                  # 全量导出
python src/main.py classify --emit-ai            # 规则打分 → xlsx + AI待办清单
python src/main.py classify --merge-ai ai.csv    # AI结果合回
python src/main.py writeback                     # 写回 dry-run 预览
python src/main.py writeback --apply --limit 10  # 小批量试运行
python src/main.py app                           # 启动工作台
```

注意：命令行 `writeback` 路径**不检查**工作台的保护名单与限额。为避免误动受保护收藏夹，请统一使用工作台写回。

## 8. 项目结构

```
bili-favlist/
├── src/
│   ├── bili_api.py         # B站接口封装：Cookie / 限速 / 重试 / 错误码分级（无删除接口）
│   ├── export_fav.py       # 导出收藏夹 → data/export.json / export.csv
│   ├── app_engine.py       # 分类引擎：打分 / 热词 / 权重学习 / 双池 / 盲测 / 三级保护
│   ├── app_server.py       # 本地 Web 服务 + API 路由 + 写回计划生成
│   ├── webui/              # 工作台前端（原生 HTML/JS/CSS，无框架）
│   ├── classify.py         # 命令行分类（读 rules.yaml → classified.xlsx）
│   ├── wb_plan.py          # 写回计划（命令行路径）
│   ├── wb_exec.py          # 写回执行：分批 / 断点续跑 / 熔断
│   ├── writeback.py        # 写回命令行入口（默认 dry-run）
│   ├── main.py             # 统一入口：export / classify / writeback / app
│   └── sample_data/        # 演示模式虚构数据
├── rules.yaml              # 分类规则示例
├── config.example.yaml     # 配置模板（复制为 config.yaml 后填写）
├── userscript/             # 油猴备用写回方案
└── data/                   # 运行产物（已 gitignore）
```

## 9. 隐私与安全

- 所有请求仅发往 `api.bilibili.com`，请求地址经 host 白名单校验并强制 https；工作台只监听 `127.0.0.1`；
- Cookie 仅保存在本地 `config.yaml`（已列入 `.gitignore`），只在内存中拼入请求头，日志不打印；
- 写操作默认不执行：命令行需 `--apply`，工作台需输入 `APPLY` 确认串，并受保护名单、移动范围、当日限额三重约束；
- 配置在线 AI 分类时，接口地址强制 https 且禁止指向本机或内网。

## 10. 免责声明

- 本项目调用 B 站网页端在用的非公开接口（社区逆向成果），接口可能随时变动；请仅以个人整理自己账号为目的低频使用，勿用于批量爬取或商业用途；
- 批量写操作存在触发风控的可能（验证码 / 临时限制）。工具内置保守限速与失败熔断，仍请先预览、小批量试跑后再全量；
- `config.yaml` 中的 Cookie 等同登录凭证：不要提交到 git，不要分享给他人。

## 11. 构建绿色版

```bash
.venv\Scripts\python.exe -m pip install pyinstaller

.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --name bili-favlist ^
  --paths src ^
  --add-data "src/webui;webui" ^
  --add-data "src/sample_data;sample_data" ^
  src/main.py
```

两个 `--add-data` 参数不可省略：`app_server.py` 以自身所在目录定位 `webui/`，前端未打包将白屏；`sample_data/` 缺失则演示模式无法启动。

## 12. 致谢

- [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)：社区接口文档
- [qianb7/bilibili-favlist](https://github.com/qianb7/bilibili-favlist)、[Junliang-liu-kit/Bili_to_MD](https://github.com/Junliang-liu-kit/Bili_to_MD)：导出思路参考
- [Argilla](https://github.com/argilla-io/argilla)、[Label Studio](https://labelstud.io/)：规则弱监督与人工复核的交互模式参考
- 本项目为 Vibe Coding 实践，由 [ZCode](https://www.zcode.com) 智能体驱动完成开发，主要编码模型为 GLM（Z.ai）与 DeepSeek；分类算法与写回安全闸门的设计在 AI 协作下迭代得出。

## 许可证

[MIT](./LICENSE) · 作者：[Frostleaf0929](https://github.com/Frostleaf0929)
