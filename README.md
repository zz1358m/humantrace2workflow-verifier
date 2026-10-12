# HumanTrace2Workflow (ht2w)

从一个人的电脑使用轨迹里编译出 **(workflow, verifier)**：怎么做，以及这个人认为怎样算做对。
产出是标准的 Agent Skill，自带可执行的个人验收，能装进 Claude Code 或 Codex。

- 提案：[HumanTrace2Workflow-proposal.pdf](HumanTrace2Workflow-proposal.pdf)
- 相关工作：[docs/related-work.md](docs/related-work.md)
- 框架设计：[docs/framework.md](docs/framework.md)

本项目自己不调模型 API。它确定性地采集和压缩轨迹，然后在你已有的 Claude Code / Codex 里开无头会话去读轨迹、写 skill，
再用确定性的检查卡住会话的产出。

## 安装

需要 Python 3.10+；蒸馏那一步还需要本机已登录的 Claude Code 或 Codex CLI。

```bash
git clone https://github.com/zz1358m/humantrace2workflow.git
cd humantrace2workflow
pip install -e ".[screen,video]"
ht2w init
```

`screen` 是实时录屏（仅 Windows），`video` 是录屏视频导入；只用对话日志和浏览器历史的话 `pip install -e .` 就够。

## 用法

```bash
ht2w init                          # 建数据目录 data/ 和 config.yaml

# 1. 采集（按需选）
ht2w record --watch D:\work        # 实时录屏，Ctrl+C 停；--watch 的目录里文件保存会留版本
ht2w collect all --days 1          # Claude Code / Codex 对话日志 + Chrome / Edge 历史 + git
ht2w collect video rec.mp4         # 已有的录屏视频
ht2w collect chat wx导出.csv --me 我的昵称
ht2w mark "刚才那版数字抄错了"       # 随手标一句

# 2. 编译成时间线与信号（不调模型）
ht2w compile

# 3. 蒸馏：开 agent 会话，先画像，再每个任务建一个 skill
ht2w distill --top 3               # --backend claude|codex|manual，--parallel N
ht2w tasks; ht2w skills

# 4. 用
ht2w install weekly-report --to claude      # 拷到 ~/.claude/skills/；--to codex 同理
ht2w verify weekly-report --input in/ --output out/

# 5. 闭环
ht2w optimize weekly-report                 # 冻结 verifier，改进 workflow
ht2w shadow weekly-report --input in/ --human 我自己做的/
ht2w feedback <run> reject --note "没写数据来源"
ht2w evolve weekly-report && ht2w approve weekly-report
ht2w eval weekly-report
```

不想录自己也能试：`ht2w synth` 会写入一天的合成轨迹。[examples/demo/](examples/demo/) 是在它上面跑出来的完整结果。

## 隐私

- 一切在本地 `data/`（已 gitignore）。`ht2w forget <day>` 删一天，删目录即全删。
- 不记录按键内容，只记次数和快捷键组合。
- 密码管理器、无痕窗口等命中 denylist 的窗口不截图、不留标题；文本入库前脱敏。
- 微信：只导入你自己导出的聊天文件，不读它的本地加密数据库。
- **蒸馏时轨迹会被你选的 agent（Claude Code / Codex）读取，也就是发给对应的模型服务商。** 想先看会发什么，
  用 `--backend manual`：只生成任务书，不启动会话。

## 花费

Claude 后端的每次会话花费记在 `data/ledger.jsonl`，累计达到 `config.yaml` 里的 `agent.budget_usd`（默认 10）就不再开新会话。
Codex CLI 不报告花费，这个上限对它不起作用。

## 已知限制

- 不能在 Claude Code 会话内部用 Claude 后端（Claude Code 禁止嵌套启动）；在普通终端里运行，或用 `--backend codex`。
- 实时录屏只支持 Windows。其余见 [docs/framework.md](docs/framework.md) 末尾。

## 测试

```bash
pytest
```
