#!/usr/bin/env python3
"""
GitHub 仓库更新检查脚本
- 检查所有配置的仓库是否有上游更新
- 区分「上游待更新 / 本地已有更新 / 工作区改动 / 完全同步」
- 分析 CHANGELOG / Release Notes 判断是否建议更新
- 有重要更新时推送飞书通知
- 记录状态到 JSON 文件
"""

import json
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from typing import Optional

# ── 路径配置 ──────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = SKILL_DIR / "config" / "repos.json"
STATE_FILE = SKILL_DIR / "state" / "last_check.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/f54d31a7-226d-4fac-aeaf-44b84c5c85b7"

# ── 判断规则：commit message 关键词 → 优先级 ───────────────
COMMIT_PRIORITY_KEYWORDS = {
    "breaking": "🔴 Breaking",
    "feat:": "🟢 新功能",
    "fix:": "🟡 Bug修复",
    "refactor:": "🔵 重构",
    "docs:": "📝 文档",
    "perf:": "⚡ 性能",
    "test:": "🧪 测试",
    "chore:": "🔧 维护",
    "security": "🔴 安全",
    "hotfix": "🔴 热修复",
}

# 低优先级关键字（自动跳过）
SKIP_KEYWORDS = ["chore(deps)", "ci", "build:", "style:", "lint:"]


def load_config() -> list[dict]:
    """加载仓库配置"""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    # 默认配置：如果有 upstream remote 的 git 仓库
    default_repos = discover_git_repos()
    return [{"path": str(r)} for r in default_repos]


def discover_git_repos() -> list[Path]:
    """自动发现 workspace 下有 upstream 的 git 仓库"""
    workspace = Path.home() / ".openclaw" / "workspace"
    found = []
    for git_dir in workspace.rglob(".git"):
        repo_dir = git_dir.parent
        try:
            # 检查是否有 upstream remote
            r = run_git(repo_dir, ["remote", "get-url", "upstream"])
            upstream = r.strip() if r else ""
            r2 = run_git(repo_dir, ["remote", "get-url", "origin"])
            origin = r2.strip() if r2 else ""
            if upstream or "ZhuLinsen" in origin or "seablue1985" in origin:
                found.append(repo_dir)
        except Exception:
            pass
    return found


def run_git(repo_dir: Path, args: list[str], timeout: int = 15) -> str:
    """运行 git 命令"""
    full_cmd = ["git", "-C", str(repo_dir)] + args
    r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git failed: {r.stderr.strip()}")
    return r.stdout.strip()


def try_git(repo_dir: Path, args: list[str], timeout: int = 15) -> tuple[bool, str]:
    """运行 git 命令，失败时返回 stderr，不抛异常"""
    full_cmd = ["git", "-C", str(repo_dir)] + args
    try:
        r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"git timeout after {timeout}s: {' '.join(full_cmd)}"
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()
    return True, r.stdout.strip()


def remote_exists(repo_dir: Path, remote: str) -> bool:
    ok, _ = try_git(repo_dir, ["remote", "get-url", remote])
    return ok


def fetch_remote(repo_dir: Path, remote: str) -> tuple[bool, Optional[str]]:
    """刷新远端引用，避免只比较到本地陈旧的 remote-tracking refs"""
    ok, output = try_git(repo_dir, ["fetch", "--prune", remote], timeout=120)
    if ok:
        return True, None
    return False, output or f"fetch {remote} failed"


def resolve_upstream_branch(repo_dir: Path) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """解析对比用的远端分支，优先 upstream，其次 origin"""
    for remote in ("upstream", "origin"):
        if not remote_exists(repo_dir, remote):
            continue

        fetch_ok, fetch_error = fetch_remote(repo_dir, remote)

        for branch in ("main", "master"):
            ref = f"{remote}/{branch}"
            ok, _ = try_git(repo_dir, ["rev-parse", "--verify", ref])
            if ok:
                return remote, ref, None if fetch_ok else fetch_error

    return None, None, None


def parse_worktree_status(repo_dir: Path) -> dict:
    """解析 working tree 状态"""
    try:
        porcelain = run_git(repo_dir, ["status", "--porcelain"])
    except Exception as exc:
        return {
            "working_tree_dirty": False,
            "staged_count": 0,
            "modified_count": 0,
            "untracked_count": 0,
            "worktree_error": str(exc),
        }

    staged_count = 0
    modified_count = 0
    untracked_count = 0

    for line in porcelain.splitlines():
        if not line:
            continue
        if line.startswith("??"):
            untracked_count += 1
            continue
        if len(line) >= 1 and line[0] != " ":
            staged_count += 1
        if len(line) >= 2 and line[1] != " ":
            modified_count += 1

    return {
        "working_tree_dirty": bool(porcelain.strip()),
        "staged_count": staged_count,
        "modified_count": modified_count,
        "untracked_count": untracked_count,
    }


def collect_commits(repo_dir: Path, revision_range: str, limit: int = 20) -> list[dict]:
    commits = []
    commits_raw = run_git(
        repo_dir,
        ["log", revision_range, "--format=%s|||%h", f"-{limit}"],
    )
    for line in commits_raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("|||")
        msg = parts[0].strip()
        short = parts[1].strip() if len(parts) > 1 else ""
        priority = classify_commit(msg)
        is_break = "breaking" in priority.lower() or "🔴" in priority
        commits.append(
            {
                "message": msg,
                "short": short,
                "priority": priority,
                "breaking": is_break,
            }
        )
    return commits


def has_local_changes(status: dict) -> bool:
    return bool(
        status.get("commits_ahead", 0) > 0
        or status.get("working_tree_dirty", False)
    )


def is_synced_clean(status: dict) -> bool:
    return bool(
        status.get("status") == "synced"
        and status.get("commits_behind", 0) == 0
        and status.get("commits_ahead", 0) == 0
        and not status.get("working_tree_dirty", False)
    )


def get_repo_status(repo_path: str) -> dict:
    """检查单个仓库的更新状态"""
    repo = Path(repo_path)
    if not repo.exists() or not (repo / ".git").exists():
        return {"error": "Not a git repository", "path": repo_path}

    result = {
        "path": repo_path,
        "name": repo.name,
        "local_tag": None,
        "upstream_tag": None,
        "commits_behind": 0,
        "commits_ahead": 0,
        "status": "unknown",
        "new_commits": [],
        "local_commits": [],
        "new_tags": [],
        "breaking_changes": False,
        "working_tree_dirty": False,
        "staged_count": 0,
        "modified_count": 0,
        "untracked_count": 0,
        "fetch_error": None,
        "upstream_remote": None,
    }

    try:
        # 获取当前 HEAD / branch
        try:
            result["local_sha"] = run_git(repo, ["rev-parse", "--short", "HEAD"])
        except Exception:
            pass
        try:
            result["current_branch"] = run_git(repo, ["branch", "--show-current"])
        except Exception:
            pass

        result.update(parse_worktree_status(repo))

        # 获取上游分支（优先 upstream，fallback 到 origin），并先 fetch 刷新引用
        remote_name, upstream_branch, fetch_error = resolve_upstream_branch(repo)
        if not upstream_branch:
            result["status"] = "no_upstream"
            return result

        result["upstream_remote"] = remote_name
        result["upstream_branch"] = upstream_branch
        result["fetch_error"] = fetch_error

        try:
            result["upstream_sha"] = run_git(repo, ["rev-parse", "--short", upstream_branch])
        except Exception:
            pass

        # 获取当前 tag（最近的一个）
        try:
            result["local_tag"] = run_git(repo, ["describe", "--tags", "--always"])
        except Exception:
            pass

        # 获取 upstream 最新 tag
        try:
            result["upstream_tag"] = run_git(repo, ["describe", "--tags", "--always", upstream_branch])
        except Exception:
            pass

        # 计算 ahead / behind
        try:
            behind = run_git(repo, ["rev-list", "--count", f"HEAD..{upstream_branch}"])
            ahead = run_git(repo, ["rev-list", "--count", f"{upstream_branch}..HEAD"])
            result["commits_behind"] = int(behind)
            result["commits_ahead"] = int(ahead)
        except Exception:
            pass

        # 获取上游新增 commits
        if result["commits_behind"] > 0:
            result["new_commits"] = collect_commits(repo, f"HEAD..{upstream_branch}")
            result["breaking_changes"] = any(c["breaking"] for c in result["new_commits"])

        # 获取本地新增 commits
        if result["commits_ahead"] > 0:
            result["local_commits"] = collect_commits(repo, f"{upstream_branch}..HEAD")

        # 状态判断
        if result["commits_behind"] > 0 and result["commits_ahead"] > 0:
            result["status"] = "diverged"
        elif result["commits_behind"] > 0:
            if result["breaking_changes"]:
                result["status"] = "breaking_update"
            elif result["commits_behind"] <= 3:
                result["status"] = "minor_update"
            elif result["commits_behind"] <= 10:
                result["status"] = "major_update"
            else:
                result["status"] = "far_behind"
        elif result["commits_ahead"] > 0 and result["working_tree_dirty"]:
            result["status"] = "local_commits_dirty"
        elif result["commits_ahead"] > 0:
            result["status"] = "local_commits"
        elif result["working_tree_dirty"]:
            result["status"] = "working_tree_dirty"
        else:
            result["status"] = "synced"

    except Exception as e:
        result["error"] = str(e)

    return result


def classify_commit(message: str) -> str:
    """根据 commit message 分类优先级"""
    msg_lower = message.lower()
    for kw, label in COMMIT_PRIORITY_KEYWORDS.items():
        if kw in msg_lower:
            # 跳过低优先级
            for skip in SKIP_KEYWORDS:
                if skip in msg_lower:
                    return "⚪ 维护"
            return label
    return "⚪ 其他"


def should_update(status: dict) -> tuple[bool, str, int]:
    """
    判断是否建议更新
    返回：(建议更新, 理由, 优先级 1-5)
    """
    s = status.get("status", "")
    commits = status.get("commits_behind", 0)
    breaking = status.get("breaking_changes", False)
    ahead = status.get("commits_ahead", 0)

    if s == "no_upstream":
        return False, "无 upstream/origin 主分支，跳过", 0
    if s == "synced":
        return False, "与上游同步，工作区干净", 0
    if s == "working_tree_dirty":
        return False, "上游无差异，但工作区有未提交改动", 0
    if s == "local_commits":
        return False, f"本地领先上游 {ahead} 个 commits", 0
    if s == "local_commits_dirty":
        return False, f"本地领先上游 {ahead} 个 commits，且工作区有改动", 0

    if s == "diverged":
        return True, f"与上游已分叉（behind {commits} / ahead {ahead}），建议先评估再合并", 5
    if breaking:
        return True, f"包含 Breaking Changes，强烈建议更新（{commits} commits）", 5
    if commits >= 10:
        return True, f"落后 {commits} 个 commits，建议一次性合并", 4
    if commits >= 5:
        return True, f"落后 {commits} 个 commits，可择机更新", 3
    if commits >= 1:
        return True, f"落后 {commits} 个 commits，可按需更新", 2
    return False, f"落后 {commits} 个 commits，影响不大", 1


def format_worktree_brief(status: dict) -> str:
    parts = []
    if status.get("staged_count", 0):
        parts.append(f"staged {status['staged_count']}")
    if status.get("modified_count", 0):
        parts.append(f"modified {status['modified_count']}")
    if status.get("untracked_count", 0):
        parts.append(f"untracked {status['untracked_count']}")
    if not parts:
        return "干净"
    return " / ".join(parts)


def build_report(all_results: list[dict]) -> str:
    """生成更新报告"""
    today = date.today().strftime("%Y-%m-%d")
    lines = [f"# GitHub 仓库更新报告 — {today}", ""]

    recommend_updates = [r for r in all_results if should_update(r)[0]]
    local_changes = [r for r in all_results if has_local_changes(r)]
    synced_clean = [r for r in all_results if is_synced_clean(r)]
    skipped = [r for r in all_results if r.get("status") == "no_upstream"]
    errored = [r for r in all_results if r.get("error")]

    lines.append(
        f"**检查仓库数：{len(all_results)}** | 上游待更新：{len(recommend_updates)} | 本地有变化：{len(local_changes)} | 已同步：{len(synced_clean)}"
    )
    lines.append("")

    if recommend_updates:
        lines.append("## 🔔 需要关注的上游更新\n")
        for r in sorted(recommend_updates, key=lambda x: should_update(x)[2], reverse=True):
            _, reason, priority = should_update(r)
            stars = "⭐" * priority
            lines.append(f"### {r['name']} {stars}（{r.get('upstream_tag', '?')}）")
            lines.append(f"- 当前版本：{r.get('local_tag', '?')}")
            lines.append(f"- 上游版本：{r.get('upstream_tag', '?')}")
            lines.append(f"- 相对上游：behind {r['commits_behind']} | ahead {r['commits_ahead']}")
            lines.append(f"- 工作区：{format_worktree_brief(r)}")
            lines.append(f"- **建议：{reason}**")
            if r.get("fetch_error"):
                lines.append(f"- ⚠️ fetch 失败：{r['fetch_error']}")
            if r.get("breaking_changes"):
                lines.append("- ⚠️ **包含 Breaking Changes**")
            if r.get("new_commits"):
                lines.append("")
                lines.append("**上游主要变更：**")
                for c in r["new_commits"][:5]:
                    lines.append(f"- {c['priority']} `{c['short']}` {c['message']}")
            if r.get("local_commits"):
                lines.append("")
                lines.append("**本地未推送 / 未合并提交：**")
                for c in r["local_commits"][:3]:
                    lines.append(f"- {c['priority']} `{c['short']}` {c['message']}")
            lines.append("")
    else:
        lines.append("## ✅ 当前没有发现需要从上游拉取的更新\n")

    if local_changes:
        lines.append("## 🛠️ 检测到本地变化\n")
        for r in sorted(local_changes, key=lambda x: (x.get("commits_ahead", 0), x.get("working_tree_dirty", False)), reverse=True):
            lines.append(f"### {r['name']}")
            lines.append(f"- 相对上游：behind {r['commits_behind']} | ahead {r['commits_ahead']}")
            lines.append(f"- 工作区：{format_worktree_brief(r)}")
            if r.get("local_commits"):
                lines.append("- 本地新增提交：")
                for c in r["local_commits"][:5]:
                    lines.append(f"  - {c['priority']} `{c['short']}` {c['message']}")
            if r.get("fetch_error"):
                lines.append(f"- ⚠️ fetch 失败：{r['fetch_error']}")
            lines.append("")

    if synced_clean:
        lines.append(f"## ✅ 与上游同步且工作区干净（{len(synced_clean)}）\n")
        lines.append("、".join(r["name"] for r in synced_clean))
        lines.append("")

    if skipped:
        lines.append(f"## ⚪ 未纳入对比（{len(skipped)}）\n")
        for r in skipped:
            lines.append(f"- {r['name']}：无 upstream/origin 主分支")
        lines.append("")

    if errored:
        lines.append(f"## ❌ 异常（{len(errored)}）\n")
        for r in errored:
            lines.append(f"- {r.get('name', r.get('path', '?'))}：{r.get('error')} ")
        lines.append("")

    lines.append("---")
    lines.append(f"*由 github-repo-monitor 自动生成 | {datetime.now().strftime('%H:%M')}*")
    return "\n".join(lines)


def build_summary(results: list[dict]) -> str:
    """生成飞书摘要"""
    recommend = [r for r in results if should_update(r)[0]]
    local_changes = [r for r in results if has_local_changes(r)]
    synced_clean = [r for r in results if is_synced_clean(r)]
    breaking = [r for r in results if r.get("breaking_changes")]

    if recommend:
        top = sorted(recommend, key=lambda x: should_update(x)[2], reverse=True)[0]
        msg = (
            f"🔔 GitHub 仓库检查 | 上游待更新 {len(recommend)} | 本地有变化 {len(local_changes)} | 已同步 {len(synced_clean)}"
            f"\n最高优先：{top['name']}（behind {top['commits_behind']} / ahead {top['commits_ahead']}）"
        )
        if breaking:
            msg += f"\n⚠️ 含 Breaking Changes：{'、'.join(r['name'] for r in breaking)}"
        return msg

    if local_changes:
        changed_names = "、".join(r["name"] for r in local_changes[:4])
        if len(local_changes) > 4:
            changed_names += " 等"
        return (
            f"🛠️ GitHub 仓库检查 | 上游无需更新 | 本地有变化 {len(local_changes)} | 已同步 {len(synced_clean)}"
            f"\n本地变化：{changed_names}"
        )

    return f"✅ GitHub 仓库检查 | {len(synced_clean)} 个与上游同步 | 无需拉取更新"


def save_report(report: str, results: list[dict]):
    """保存报告"""
    today = date.today().strftime("%Y%m%d")
    out_dir = Path.home() / ".openclaw" / "workspace" / "research" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    f1 = out_dir / f"github_repo_update_report_{today}.md"
    f2 = out_dir / "github_repo_update_latest.md"
    f1.write_text(report, encoding="utf-8")
    f2.write_text(report, encoding="utf-8")

    # 保存 JSON
    state = {
        "checked_at": datetime.now().isoformat(),
        "results": results,
    }
    state_file = out_dir / f"github_repo_update_state_{today}.json"
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"报告已保存: {f1.name}")
    return str(f1)


def send_feishu(summary: str) -> bool:
    """推送飞书摘要"""
    try:
        import requests
        resp = requests.post(
            FEISHU_WEBHOOK,
            json={"msg_type": "text", "content": {"text": summary}},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[飞书推送失败] {e}", file=sys.stderr)
        return False


def main():
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 检查 GitHub 仓库更新...")

    repos = load_config()
    print(f"监控仓库数：{len(repos)}")

    results = []
    for repo_cfg in repos:
        path = repo_cfg.get("path") or repo_cfg.get("repo_path")
        if not path:
            continue
        print(f"  检查: {path}...", end=" ", flush=True)
        status = get_repo_status(path)
        results.append(status)
        behind = status.get("commits_behind", "?")
        ahead = status.get("commits_ahead", "?")
        local = status.get("local_tag", "?")
        upstream = status.get("upstream_tag", "?")
        worktree = format_worktree_brief(status)
        print(
            f"本地={local} 上游={upstream} behind={behind} ahead={ahead} 工作区={worktree} [{status.get('status', '?')}]"
        )

    report = build_report(results)
    report_path = save_report(report, results)
    summary = build_summary(results)

    # 保存状态
    STATE_FILE.write_text(
        json.dumps(
            {
                "checked_at": datetime.now().isoformat(),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 飞书推送
    ok = send_feishu(summary)
    print(f"飞书推送: {'成功' if ok else '失败'}")
    print(f"\n报告路径: {report_path}")

    return results


if __name__ == "__main__":
    main()
