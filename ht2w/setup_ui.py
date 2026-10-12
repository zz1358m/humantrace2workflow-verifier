"""`ht2w setup`: a local questionnaire where the user connects their servers, ticks which sources may be
read, and starts the analysis. Served on 127.0.0.1 only; every API call needs the per-launch token."""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, consent, store

from .sources.extra import HOST_RE as _HOST_RE

RUN = {"running": False, "stage": "", "log": [], "report": None}


def state(cfg: dict | None = None) -> dict:
    cfg = cfg or config.load()
    d = consent.decisions()
    s = cfg["sources"]
    return {
        "home": str(config.home()),
        "sources": [{"id": x.id, "label": x.label, "reads": x.reads, "available": x.available, "note": x.note,
                     "decision": d.get(x.id)} for x in consent.discover(cfg) if not x.id.startswith(("ssh:", "ssh-agents:"))],
        "hosts": [{"host": h, "history": d.get(f"ssh:{h}"), "agents": d.get(f"ssh-agents:{h}")} for h in consent.ssh_hosts(cfg)],
        "wx_export": s.get("wx_export") or "", "wx_me": s.get("wx_me") or "", "doc_dirs": s.get("doc_dirs") or [],
        "backend": cfg["agent"]["backend"], "budget_usd": cfg["agent"]["budget_usd"], "run": RUN,
    }


def test_host(host: str) -> dict:
    if not _HOST_RE.match(host or ""):
        return {"ok": False, "error": "格式应为 user@host 或 ~/.ssh/config 里的主机名"}
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "echo ht2w-ok; ls -d ~/.claude/projects ~/.codex/sessions 2>/dev/null"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    except FileNotFoundError:
        return {"ok": False, "error": "本机没有 ssh 命令"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "连接超时"}
    if "ht2w-ok" in r.stdout:
        found = [n for n in ("claude", "codex") if f".{n}" in r.stdout]
        return {"ok": True, "detail": "可免密登录" + ("；发现 " + "、".join(found) + " 对话日志" if found else "；没有发现 agent 对话日志")}
    err = (r.stderr or "").strip().splitlines()[-1:] or ["ssh 失败"]
    return {"ok": False, "error": err[0][:200],
            "hint": f"本工具只用密钥登录，不接触密码。请在你自己的终端里先连通一次并装好公钥：\n"
                    f"  ssh {host}        （首次连接确认主机指纹）\n"
                    f"  type $env:USERPROFILE\\.ssh\\id_ed25519.pub | ssh {host} \"cat >> ~/.ssh/authorized_keys\"\n"
                    f"没有密钥就先运行 ssh-keygen -t ed25519。完成后回来点“测试连接”。"}


def save(p: dict) -> dict:
    hosts = [h.strip() for h in p.get("hosts", []) if _HOST_RE.match(h.strip())]
    consent.set_config(["sources", "ssh_hosts"], hosts)
    consent.set_config(["sources", "wx_export"], (p.get("wx_export") or "").strip() or None)
    consent.set_config(["sources", "wx_me"], (p.get("wx_me") or "").strip() or None)
    consent.set_config(["sources", "doc_dirs"], [d.strip() for d in p.get("doc_dirs", []) if d.strip()])
    if p.get("backend") in ("claude", "codex", "manual"):
        consent.set_config(["agent", "backend"], p["backend"])
    known = {s.id for s in consent.discover(config.load())}
    dec = {k: v for k, v in (p.get("decisions") or {}).items() if k in known and v in ("allow", "deny")}
    consent.decide(dec)
    return state()


def _pipeline(days: float, top: int):
    from . import collect, distill
    from .compile import compile_day

    def log(msg):
        RUN["log"].append(f"{time.strftime('%H:%M:%S')} {msg}")

    try:
        cfg = config.load()
        since = time.time() - days * 86400
        RUN["stage"] = "采集"
        rep = collect.collect_allowed(since, cfg)
        for k, v in rep.items():
            if k != "skipped_not_allowed":
                log(f"采集 {k}: {json.dumps(v, ensure_ascii=False)}")
        if rep["skipped_not_allowed"]:
            log("未授权，已跳过: " + ", ".join(rep["skipped_not_allowed"]))
        RUN["stage"] = "编译"
        day_list = [d for d in store.days() if d >= store.day_of(since)]
        for d in day_list:
            c = compile_day(d, cfg)
            log(f"编译 {d}: {c['events']} 个事件，信号 {json.dumps(c['signals'], ensure_ascii=False)}")
        if not day_list:
            log("这段时间内没有采集到任何事件，停止。")
            return
        RUN["stage"] = f"蒸馏（{cfg['agent']['backend']} 会话）"
        log(f"启动 {cfg['agent']['backend']} 会话：先画像，再为前 {top} 个任务各建一个 skill。这一步可能要几十分钟。")
        out = distill.distill(day_list, top, None, 1, False, cfg)
        RUN["report"] = out
        prof = out.get("profile", {})
        log(("画像会话完成" if prof.get("ok") else "画像会话未成功: " + str(prof.get("summary", ""))[:400]))
        for s in out.get("skills", []):
            log(f"skill {s['skill']}: lint {'通过' if s.get('lint_ok') else '未通过'}")
    except BaseException as e:  # noqa: BLE001 - surface anything, including SystemExit from deeper layers, in the page
        log(f"出错: {type(e).__name__}: {e}")
    finally:
        RUN["stage"] = "结束"
        RUN["running"] = False


def start_run(days: float, top: int) -> dict:
    if RUN["running"]:
        return {"ok": False, "error": "已经在运行"}
    RUN.update(running=True, stage="准备", log=[], report=None)
    threading.Thread(target=_pipeline, args=(days, top), daemon=True).start()
    return {"ok": True}


def serve(port: int = 0, open_browser: bool = True, token: str | None = None):
    token = token or secrets.token_urlsafe(16)
    page = (Path(__file__).parent / "web" / "setup.html").read_text(encoding="utf-8")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200, ctype="application/json; charset=utf-8"):
            body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost") and self.headers.get("X-HT2W-Token") == token

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                if f"t={token}" not in self.path:
                    return self._send({"error": "open the link printed by `ht2w setup`"}, 403)
                return self._send(page.replace("__TOKEN__", token).encode("utf-8"), ctype="text/html; charset=utf-8")
            if not self._ok():
                return self._send({"error": "forbidden"}, 403)
            if path == "/api/state":
                return self._send(state())
            self._send({"error": "not found"}, 404)

        def do_POST(self):
            if not self._ok():
                return self._send({"error": "forbidden"}, 403)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                return self._send({"error": "bad json"}, 400)
            if self.path == "/api/test-host":
                return self._send(test_host(str(body.get("host", "")).strip()))
            if self.path == "/api/save":
                return self._send(save(body))
            if self.path == "/api/run":
                save(body)
                return self._send(start_run(float(body.get("days") or 1), int(body.get("top") or 3)))
            self._send({"error": "not found"}, 404)

    config.init_home()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={token}"
    print(f"问卷页面: {url}\n（只在本机可访问；Ctrl+C 结束）")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
