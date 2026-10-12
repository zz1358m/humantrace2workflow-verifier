# HumanTrace2Workflow&Verifier (ht2wv)

从一个人**已有的访问记录**里编译出 **(workflow, verifier)**：怎么做，以及这个人认为怎样算做对。
产出是标准的 Agent Skill，自带可执行的个人验收，能装进 Claude Code 或 Codex。

访问记录指的是电脑上本来就有的东西，不需要额外录制：

- coding agent 对话日志（Claude Code、Codex，本机和服务器上的）
- shell 命令历史（本机和服务器）
- 浏览器历史
- 导出的聊天记录（微信等）
- 最近打开的文件、文档改动时间、git 提交

其中 agent 对话是最密的验收信号：每一次打回、追问“你核对过吗”、中断、拒绝工具调用，都是这个人用自己的话说出来的验收标准。
录屏和录屏视频是可选的补充来源。

- 提案：[HumanTrace2Workflow-proposal.pdf](HumanTrace2Workflow-proposal.pdf)
- 相关工作：[docs/related-work.md](docs/related-work.md)
- 框架设计：[docs/framework.md](docs/framework.md)

本项目自己不调模型 API。它先让用户逐项授权，确定性地采集和压缩这些记录，然后在用户已有的 Claude Code / Codex 里开无头会话去读、去写 skill，
再用确定性的检查卡住会话的产出。

## 安装

需要 Python 3.10+；蒸馏那一步还需要本机已登录的 Claude Code 或 Codex CLI。

```bash
git clone https://github.com/zz1358m/humantrace2workflow-verifier.git
cd humantrace2workflow-verifier
pip install -e .
ht2wv init
```

可选的录屏来源另装：`pip install -e ".[screen]"`（实时录屏，仅 Windows）、`pip install -e ".[video]"`（录屏视频导入）。

## 最快的用法

```bash
ht2wv setup
```

会在浏览器里打开一个只在本机可访问的问卷页面，分四步：

1. **连接服务器**：填 `user@host`，点“测试连接”。只用密钥登录；连不上时页面会给出在你自己终端里装公钥的命令。
2. **勾选本机记录**：Claude Code / Codex 对话、Chrome / Edge 历史、本机 shell 历史、最近打开的文件、git 提交。每项写明会读什么。
3. **填路径的来源**：微信导出文件、工作目录。
4. **交给 coding agent 分析**：选天数和后端，点“保存并开始分析”，页面显示采集 → 编译 → 蒸馏的进度。

没勾的来源不会被读取。同样的事也可以用命令行做：`ht2wv sources --ask`，然后 `ht2wv run --days 1`。


## 分步用法

```bash
ht2wv init                          # 建数据目录 data/ 和 config.yaml

# 1. 采集（按需选）
ht2wv sources                       # 列出来源和授权状态；--ask 逐项询问，--allow/--deny <id>，--add-host user@host
ht2wv collect allowed --days 1      # 采集所有已授权的来源
ht2wv mark "刚才那版数字抄错了"       # 随手标一句

# 2. 编译成时间线与信号（不调模型）
ht2wv compile

# 3. 蒸馏：开 agent 会话，先画像，再每个任务建一个 skill
ht2wv distill --top 3               # --backend claude|codex|manual，--parallel N
ht2wv tasks; ht2wv skills

# 4. 用
ht2wv install weekly-report --to claude      # 拷到 ~/.claude/skills/；--to codex 同理
ht2wv verify weekly-report --input in/ --output out/

# 5. 闭环
ht2wv optimize weekly-report                 # 冻结 verifier，改进 workflow
ht2wv shadow weekly-report --input in/ --human 我自己做的/
ht2wv feedback <run> reject --note "没写数据来源"
ht2wv evolve weekly-report && ht2wv approve weekly-report
ht2wv eval weekly-report
```

不想用自己的数据也能试：`ht2wv synth` 会写入一天的合成轨迹。[examples/demo/](examples/demo/) 是在它上面跑出来的完整结果。

## 可选：录屏

访问记录里看不到撤销、返工、切窗口核对这类屏幕行为。想要这些信号，可以加上：

```bash
ht2wv record --watch D:\work        # 实时录屏，Ctrl+C 停；--watch 的目录里文件保存会留版本
ht2wv collect video rec.mp4         # 已有的录屏视频 → 去重后的关键帧
```

## 隐私

- 一切在本地 `data/`（已 gitignore）。`ht2wv forget <day>` 删一天，删目录即全删。
- 所有文本入库前脱敏（密钥、口令、卡号、身份证、邮箱、手机号）；浏览器网址不保留 ? 后的参数。
- 录屏（可选）不记录按键内容，只记次数和快捷键组合；密码管理器、无痕窗口等不截图、不留标题。
- 微信：只导入你自己导出的聊天文件，不读它的本地加密数据库。
- 服务器：只走密钥 ssh、只读；不读终端软件（Xshell、PuTTY）里保存的会话和密码，主机由你自己填。
- 每个来源都要先授权（`data/consent.yaml`），未决定等同于不允许。
- **蒸馏时轨迹会被你选的 agent（Claude Code / Codex）读取，也就是发给对应的模型服务商。** 想先看会发什么，
  用 `--backend manual`：只生成任务书，不启动会话。

## 花费

Claude 后端的每次会话花费记在 `data/ledger.jsonl`，累计达到 `config.yaml` 里的 `agent.budget_usd`（默认 10）就不再开新会话。
Codex CLI 不报告花费，这个上限对它不起作用。

## 已知限制

- 不能在 Claude Code 会话内部用 Claude 后端（Claude Code 禁止嵌套启动）；在普通终端里运行，或用 `--backend codex`。
- 来源路径目前按 Windows 写的（浏览器、PowerShell 历史、最近文件）；可选的实时录屏也只支持 Windows。其余见 [docs/framework.md](docs/framework.md) 末尾。

## 测试

```bash
pytest
```
