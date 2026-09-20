# 贡献指南

欢迎 Issue / PR。约定很简单：

1. **改动前先跑通**：`python src/main.py app --demo` 能启动、演示数据能跑完整流水线。
2. **只移动、不删除**：任何写回相关的改动不得引入删除类接口调用。
3. **写操作必须 dry-run 默认**：新功能如涉及对B站的写操作，必须预览在前、显式确认在后。
4. **限速与熔断**：对 api.bilibili.com 的批量调用必须带随机间隔与失败熔断，禁止去掉限速。
5. **不提交隐私**：`config.yaml`（Cookie）与 `data/` 已被 .gitignore 排除，PR 里不要包含
   任何真实 mid/SESSDATA/个人收藏数据；示例一律用 `src/sample_data/` 的虚构数据。

## 本地开发

```bash
uv venv .venv && uv pip install -r requirements.txt   # 或 pip install -r requirements.txt
python src/main.py app --demo        # 无 Cookie 体验
python src/main.py export --list     # 需要已配置 config.yaml
```

## 打包

```bash
pip install build && python -m build   # 或 uv build
# 产物 dist/bili_favlist-*.whl；绿色单文件 exe：
pyinstaller --onefile --name bili-favlist --paths src src/main.py
```
