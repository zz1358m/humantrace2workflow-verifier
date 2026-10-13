"""Source registry with per-source consent. Nothing is read from a source until the user has said yes to it.

Discovery only checks that something exists (a path, a host name); it never opens the data.
Decisions live in consent.yaml: {source id: "allow" | "deny"}. Undecided means not collected.
"""
from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import config


@dataclass
class Source:
    id: str
    label: str
    reads: str  # exactly what would be read, shown to the user before they decide
    available: bool
    note: str = ""


def _exists(p: str) -> bool:
    return config.expand(p).exists()


def ssh_hosts(cfg: dict) -> list[str]:
    """Hosts the user listed in config plus plain Host entries of ~/.ssh/config. We do not go looking in
    terminal apps' session stores (they hold saved passwords)."""
    hosts = list(cfg["sources"].get("ssh_hosts") or [])
    p = Path.home() / ".ssh" / "config"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*Host\s+(.+)", line, re.I)
            if m:
                hosts += [h for h in m.group(1).split() if not re.search(r"[*?!]", h)]
    return list(dict.fromkeys(hosts))


def wsl_distros() -> list[str]:
    """Enumerate registered distributions without starting WSL or accessing its shares."""
    if sys.platform != "win32":
        return []
    try:
        import winreg

        names = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Lxss") as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                with winreg.OpenKey(key, winreg.EnumKey(key, i)) as distro:
                    name = winreg.QueryValueEx(distro, "DistributionName")[0]
                    if not name.lower().startswith("docker-desktop"):
                        names.append(name)
        return list(dict.fromkeys(names))
    except Exception:  # registry access is optional; discovery must never boot WSL
        return []


def discover(cfg: dict | None = None) -> list[Source]:
    cfg = cfg or config.load()
    s = cfg["sources"]
    out = [
        Source("claude", "Claude Code 对话（本机）", f"{s['claude_dir']} 下的会话日志：你的每条消息、agent 每轮最后的回复、中断与拒绝", _exists(s["claude_dir"])),
        Source("codex", "Codex 对话（本机）", f"{s['codex_dir']} 下的会话日志，同上", _exists(s["codex_dir"])),
    ]
    for name, path in s["browsers"].items():
        out.append(Source(name, f"{name.capitalize()} 浏览历史", "访问时间、标题、网址的域名与路径（不含 ?后的参数）", _exists(path)))
    local_hist = [p for p in config.local_shell_history(cfg) if p.exists()]
    out.append(Source("shell", "本机 shell 历史", "PowerShell / bash / zsh 的命令历史（脱敏后）", bool(local_hist),
                      "" if local_hist else "没找到历史文件"))
    if sys.platform == "win32":
        registered = [d for d in wsl_distros() if not d.lower().startswith("docker-desktop")]
        selected = s.get("wsl", {}).get("distros", "auto")
        selected = registered if selected == "auto" else selected
        for distro in dict.fromkeys(selected):
            if distro.lower().startswith("docker-desktop"):
                continue
            available = distro in registered
            note = "" if available else "此 WSL 发行版未注册"
            out.append(Source(f"wsl:{distro}", f"WSL {distro} 的 shell 历史",
                              "/home 下每个用户及可读的 /root 中的 ~/.bash_history、~/.zsh_history 与 "
                              "~/.local/share/powershell/PSReadLine/ConsoleHost_history.txt（命令脱敏后，只读）",
                              available, note))
            out.append(Source(f"wsl-agents:{distro}", f"WSL {distro} 的 agent 对话",
                              "/home 下每个用户及可读的 /root 中的 ~/.claude/projects 与 ~/.codex/sessions："
                              "你的消息、agent 每轮最后的回复、中断与拒绝（只读）", available, note))
    has_ssh = shutil.which("ssh") is not None
    hosts = ssh_hosts(cfg)
    for h in hosts:
        out.append(Source(f"ssh:{h}", f"服务器 {h} 的 shell 历史", "~/.bash_history 与 ~/.zsh_history 的末尾若干行（只读，免密登录）", has_ssh))
        out.append(Source(f"ssh-agents:{h}", f"服务器 {h} 上的 agent 对话", "~/.claude/projects 与 ~/.codex/sessions 里近几天的会话日志（只读）", has_ssh))
    if not hosts:
        out.append(Source("ssh:<host>", "服务器的 shell 历史与 agent 对话", "需要你先告诉我有哪些服务器", False,
                          "用 `ht2wv sources --add-host user@host` 添加，或写进 ~/.ssh/config"))
    wx = s.get("wx_export")
    out.append(Source("wx", "微信聊天记录", "你导出的聊天文件（csv / jsonl / txt）", bool(wx and _exists(wx)),
                      "" if wx else "微信本地库是加密的，本工具不解密；请先用导出工具导出，再 `ht2wv sources --wx-export <路径> --wx-me <昵称>`"))
    recent = config.platform_defaults()["recent"]
    out.append(Source("recent", "最近打开的文件", "Windows“最近使用”里的文件名与打开时间（不读文件内容）",
                      _exists(recent) if recent else False, "" if recent else "仅 Windows 提供“最近使用”记录"))
    out.append(Source("git", "git 提交记录", "从 agent 对话的工作目录里发现的仓库，加上配置里列的：提交时间、标题、文件列表（不含 diff）",
                      shutil.which("git") is not None))
    out.append(Source("docs", "工作目录里的文档改动时间", "sources.doc_dirs 下文档类文件的文件名与修改时间（不读内容）", bool(s.get("doc_dirs")),
                      "" if s.get("doc_dirs") else "用 `ht2wv sources --add-doc-dir <目录>` 指定"))
    return out


def _path() -> Path:
    return config.home() / "consent.yaml"


def decisions() -> dict[str, str]:
    p = _path()
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def decide(updates: dict[str, str]) -> dict[str, str]:
    d = decisions()
    d.update(updates)
    config.home().mkdir(parents=True, exist_ok=True)
    _path().write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return d


def allowed(sid: str) -> bool:
    return decisions().get(sid) == "allow"


def ask(cfg: dict | None = None) -> dict[str, str]:
    """Walk the user through every available source, one at a time."""
    d = decisions()
    updates = {}
    for src in discover(cfg):
        if not src.available:
            print(f"- {src.label}：不可用。{src.note}")
            continue
        cur = d.get(src.id)
        hint = {"allow": "Y/n", "deny": "y/N"}.get(cur, "y/n")
        while True:
            ans = input(f"\n{src.label}\n  会读取：{src.reads}\n  允许吗？[{hint}] ").strip().lower()
            if ans in ("y", "yes", "是", "允许"):
                updates[src.id] = "allow"
            elif ans in ("n", "no", "否", "不"):
                updates[src.id] = "deny"
            elif ans == "" and cur:
                pass
            else:
                continue
            break
    return decide(updates)


def set_config(path: list[str], value, append: bool = False):
    """Persist a single setting into config.yaml (used for hosts, export paths, doc dirs)."""
    config.init_home()
    p = config.home() / "config.yaml"
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    node = cfg
    for k in path[:-1]:
        node = node.setdefault(k, {})
    if append:
        cur = node.get(path[-1]) or []
        if value not in cur:
            cur.append(value)
        node[path[-1]] = cur
    else:
        node[path[-1]] = value
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


def status_lines(cfg: dict | None = None) -> list[str]:
    d = decisions()
    mark = {"allow": "[x]", "deny": "[ ]", None: "[?]"}
    lines = []
    for s in discover(cfg):
        state = mark[d.get(s.id)] if s.available else "[-]"
        lines.append(f"{state} {s.id:<22} {s.label}" + (f"  — {s.note}" if s.note else ""))
    lines.append("\n[x] 允许  [ ] 不允许  [?] 还没决定（不会采集）  [-] 不可用")
    return lines

