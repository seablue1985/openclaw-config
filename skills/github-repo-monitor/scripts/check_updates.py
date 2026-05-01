#!/usr/bin/env python3
"""
GitHub 仓库更新检查脚本
- 检查所有配置的仓库是否有上游更新
- 区分「上游待更新 / 本地已有更新 / 工作区改动 / 完全同步」
- 按 tier（main / extended）分层报告：飞书摘要只报 main 层
- 分析 commit message 判断是否值得更新
- 有重要更新时推送飞书通知
- 记录状态到 JSON 文件
"""

import json
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ── 路径配置 ──────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = SKILL_DIR / "config" / "repos.json"
STATE_FILE = SKILL_DIR / "state" / "last_check.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
# ── 飞书私聊配置 ─────────────────────────────────────────
FEISHU_APP_ID = "cli_a934da0dde385cba"      # coding-agent app（张玲的 open_id 所属应用）
FEISHU_APP_SECRET = "3ohW4ALIPfswBDwcnIo9RcvNSlKgQf1e"
FEISHU_USER_ID = "ou_47c21eede907b0c4f9fd4d34519d84ae"  # 张玲

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

# ── Tier 自动分类规则 ────────────────────────────────────
# main：量化核心仓、业务直接相关仓
# extended：skill/vendor/工具仓/外部引入仓
TIER_MAIN_PREFIXES = (
    "/quant_projects/",
    "/openclaw_projects/",
    "/apps/",
    "/other_projects/A_Share_investment_Agent",
    "/other_projects/Qbot",
    "/other_projects/TrendRadar",
    "/other_projects/RD-Agent",
)


def auto_tier(path: str) -> str:
    """根据路径自动推断仓库 tier"""
    for prefix in TIER_MAIN_PREFIXES:
        if path.endswith(prefix) or prefix in path:
            return "main"
    return "extended"


def load_config() -> list[dict]:
    """加载仓库配置，支持 `enabled: false` 排除和 `tier` 字段。

    - `enabled: false`：完全跳过，不会被自动发现重新加回
    - `tier`：可选，不填则按路径自动推断（main / extended）
    """
    configured = []
    if CONFIG_FILE.exists():
        configured = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    merged: dict[str, dict] = {}
    disabled_paths: set[str] = set()
    for item in configured:
        repo_path = item.get("path") or item.get("repo_path")
        if not repo_path:
            continue
        resolved = str(Path(repo_path).expanduser().resolve())
        if item.get("enabled", True) is False:
            disabled_paths.add(resolved)
            continue
        normalized = dict(item)
        normalized["path"] = resolved
        tier = item.get("tier") or auto_tier(resolved)
        normalized["tier"] = tier
        merged[resolved] = normalized

    auto_discovered = discover_git_repos()
    for repo in auto_discovered:
        key = str(repo.resolve())
        if key in disabled_paths:
            continue
        merged.setdefault(key, {
            "path": key,
            "tier": auto_tier(key),
        })

    if merged:
        return sorted(merged.values(), key=lambda x: (
            x.get("tier", "extended"),
            x.get("path") or x.get("repo_path") or "",
        ))

    return []


def discover_git_repos() -> list[Path]:
    """自动发现 workspace 下可监控的 git 仓库（有 origin 或 upstream 即纳入）"""
    workspace = Path.home() / ".openclaw" / "workspace"
    found = []
    seen = set()
    for git_dir in workspace.rglob(".git"):
        repo_dir = git_dir.parent
        try:
            has_remote = False
            for remote in ("upstream", "origin"):
                ok, _ = try_git(repo_dir, ["remote", "get-url", remote])
                if ok:
                    has_remote = True
                    break
            if has_remote:
                resolved = str(repo_dir.resolve())
                if resolved not in seen:
                    seen.add(resolved)
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
        try:
            result["local_sha"] = run_git(repo, ["rev-parse", "--short", "HEAD"])
        except Exception:
            pass
        try:
            result["current_branch"] = run_git(repo, ["branch", "--show-current"])
        except Exception:
            pass

        result.update(parse_worktree_status(repo))

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

        try:
            result["local_tag"] = run_git(repo, ["describe", "--tags", "--always"])
        except Exception:
            pass

        try:
            result["upstream_tag"] = run_git(repo, ["describe", "--tags", "--always", upstream_branch])
        except Exception:
            pass

        try:
            behind = run_git(repo, ["rev-list", "--count", f"HEAD..{upstream_branch}"])
            ahead = run_git(repo, ["rev-list", "--count", f"{upstream_branch}..HEAD"])
            result["commits_behind"] = int(behind)
            result["commits_ahead"] = int(ahead)
        except Exception:
            pass

        if result["commits_behind"] > 0:
            result["new_commits"] = collect_commits(repo, f"HEAD..{upstream_branch}")
            result["breaking_changes"] = any(c["breaking"] for c in result["new_commits"])

        if result["commits_ahead"] > 0:
            result["local_commits"] = collect_commits(repo, f"{upstream_branch}..HEAD")

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
            for skip in SKIP_KEYWORDS:
                if skip in msg_lower:
                    return "⚪ 维护"
            return label
    return "⚪ 其他"


def should_update(status: dict) -> tuple[bool, str, int]:
    """
    判断是否值得从上游更新。
    返回：(是否纳入上游更新关注, 更新判断, 优先级 1-5)
    """
    s = status.get("status", "")
    commits = status.get("commits_behind", 0)
    breaking = status.get("breaking_changes", False)
    ahead = status.get("commits_ahead", 0)

    if s == "no_upstream":
        return False, "不作更新判断：无 upstream/origin 主分支", 0
    if s == "synced":
        return False, "无需更新：与上游同步，工作区干净", 0
    if s == "working_tree_dirty":
        return False, "无需拉取上游：当前仅本地工作区有未提交改动", 0
    if s == "local_commits":
        return False, f"无需拉取上游：本地领先上游 {ahead} 个 commits", 0
    if s == "local_commits_dirty":
        return False, f"无需拉取上游：本地领先上游 {ahead} 个 commits，且工作区有改动", 0

    if s == "diverged":
        return True, f"值得关注但不建议直接更新：与上游已分叉（behind {commits} / ahead {ahead}），应先评估再合并", 5
    if breaking:
        return True, f"值得更新：包含 Breaking Changes，需优先评估并安排更新（{commits} commits）", 5
    if commits >= 10:
        return True, f"值得更新：落后 {commits} 个 commits，建议一次性合并", 4
    if commits >= 5:
        return True, f"建议更新：落后 {commits} 个 commits，可择机更新", 3
    if commits >= 1:
        return True, f"按需更新：落后 {commits} 个 commits，先看变更内容再决定", 2
    return False, f"暂不更新：落后 {commits} 个 commits，影响不大", 1


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
    """生成完整更新报告（含 main 层 + extended 层两段）"""
    today = date.today().strftime("%Y-%m-%d")
    lines = [f"# GitHub 仓库更新报告 — {today}", ""]

    main_results = [r for r in all_results if r.get("tier", "extended") == "main"]
    ext_results = [r for r in all_results if r.get("tier", "extended") == "extended"]

    for tier_name, tier_results in [("主仓", main_results), ("扩展仓", ext_results)]:
        if not tier_results:
            continue
        tier_label = "🔵" if tier_name == "主仓" else "⚪"
        recommend = [r for r in tier_results if should_update(r)[0]]
        local = [r for r in tier_results if has_local_changes(r)]
        synced = [r for r in tier_results if is_synced_clean(r)]
        skipped = [r for r in tier_results if r.get("status") == "no_upstream"]
        errored = [r for r in tier_results if r.get("error")]

        header = f"## {tier_label} {tier_name}（{len(tier_results)}仓）\n"
        if tier_name == "主仓":
            lines.append(f"**检查仓库数：{len(tier_results)}** | 上游待更新：{len(recommend)} | 本地有变化：{len(local)} | 已同步：{len(synced)}")
        else:
            lines.append(header)
            lines.append(f"检查仓库数：{len(tier_results)} | 上游待更新：{len(recommend)} | 本地有变化：{len(local)} | 已同步：{len(synced)}")
        lines.append("")

        if recommend:
            lines.append(f"### 🔔 {tier_name}上游待更新\n")
            for r in sorted(recommend, key=lambda x: should_update(x)[2], reverse=True):
                _, reason, priority = should_update(r)
                stars = "⭐" * priority
                lines.append(f"#### {r['name']} {stars}")
                lines.append(f"- 当前版本：{r.get('local_tag', '?')} | 上游版本：{r.get('upstream_tag', '?')}")
                lines.append(f"- behind {r['commits_behind']} | ahead {r['commits_ahead']} | 工作区：{format_worktree_brief(r)}")
                lines.append(f"- **更新判断：{reason}**")
                if r.get("fetch_error"):
                    lines.append(f"- ⚠️ fetch 失败：{r['fetch_error']}")
                if r.get("breaking_changes"):
                    lines.append("- ⚠️ **包含 Breaking Changes**")
                if r.get("new_commits"):
                    lines.append("")
                    lines.append("**上游主要变更：**")
                    for c in r["new_commits"][:5]:
                        lines.append(f"- {c['priority']} `{c['short']}` {c['message']}")
                lines.append("")

        if local:
            lines.append(f"### 🛠️ {tier_name}本地有变化\n")
            for r in sorted(local, key=lambda x: (x.get("commits_ahead", 0), x.get("working_tree_dirty", False)), reverse=True):
                lines.append(f"#### {r['name']}")
                lines.append(f"- behind {r['commits_behind']} | ahead {r['commits_ahead']} | 工作区：{format_worktree_brief(r)}")
                if r.get("local_commits"):
                    lines.append("- 本地未推送提交：")
                    for c in r["local_commits"][:5]:
                        lines.append(f"  - {c['priority']} `{c['short']}` {c['message']}")
                lines.append("")

        if synced:
            lines.append(f"### ✅ {tier_name}已同步（{len(synced)}）")
            lines.append("、".join(r["name"] for r in synced))
            lines.append("")

        if skipped:
            lines.append(f"### ⚪ {tier_name}无远端（{len(skipped)}）")
            for r in skipped:
                lines.append(f"- {r['name']}")
            lines.append("")

        if errored:
            lines.append(f"### ❌ {tier_name}异常（{len(errored)}）")
            for r in errored:
                lines.append(f"- {r.get('name', r.get('path', '?'))}：{r.get('error')}")
            lines.append("")

        lines.append("")

    lines.append("---")
    lines.append(f"*由 github-repo-monitor 自动生成 | {datetime.now().strftime('%H:%M')}*")
    return "\n".join(lines)


def build_summary(results: list[dict]) -> str:
    """生成飞书摘要，只报 main 层；extended 层仅在有 main 层更新时才附加一行"""
    main_results = [r for r in results if r.get("tier", "extended") == "main"]
    ext_results = [r for r in results if r.get("tier", "extended") == "extended"]

    # --- main 层 ---
    main_recommend = [r for r in main_results if should_update(r)[0]]
    main_local = [r for r in main_results if has_local_changes(r)]
    main_synced = [r for r in main_results if is_synced_clean(r)]
    main_breaking = [r for r in main_results if r.get("breaking_changes")]

    ext_recommend = [r for r in ext_results if should_update(r)[0]]

    if main_recommend:
        top = sorted(main_recommend, key=lambda x: should_update(x)[2], reverse=True)[0]
        _, top_reason, _ = should_update(top)
        msg = (
            f"🔔 GitHub 仓库检查 | 主仓待更新 {len(main_recommend)} | 本地变化 {len(main_local)} | 已同步 {len(main_synced)}"
            f"\n最高优先：{top['name']}（behind {top['commits_behind']} / ahead {top['commits_ahead']}）"
            f"\n判断：{top_reason}"
        )
        if main_breaking:
            msg += f"\n⚠️ 含 Breaking Changes：{'、'.join(r['name'] for r in main_breaking)}"
        if ext_recommend:
            ext_names = "、".join(r["name"] for r in ext_recommend[:3])
            msg += f"\n（扩展仓另有 {len(ext_recommend)} 个待更新：{ext_names}）"
        return msg

    if main_local:
        changed_names = "、".join(r["name"] for r in main_local[:4])
        if len(main_local) > 4:
            changed_names += " 等"
        msg = (
            f"🛠️ GitHub 仓库检查 | 主仓上游无需更新 | 本地有变化 {len(main_local)} | 已同步 {len(main_synced)}"
            f"\n本地变化：{changed_names}"
        )
        if ext_recommend:
            msg += f"\n（扩展仓另有 {len(ext_recommend)} 个待更新）"
        return msg

    # main 全部干净
    if ext_recommend:
        ext_names = "、".join(r["name"] for r in ext_recommend[:3])
        return (
            f"✅ GitHub 主仓全部同步 | 扩展仓另有 {len(ext_recommend)} 个待更新"
            f"\n扩展仓待更新：{ext_names}"
        )

    return f"✅ GitHub 仓库检查 | 主仓 {len(main_synced)} 个同步 | 扩展仓 {len(ext_results)} 个同步 | 无需拉取更新"


def save_report(report: str, results: list[dict]):
    """保存报告"""
    today = date.today().strftime("%Y%m%d")
    out_dir = Path.home() / ".openclaw" / "workspace" / "research" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    f1 = out_dir / f"github_repo_update_report_{today}.md"
    f2 = out_dir / "github_repo_update_latest.md"
    f1.write_text(report, encoding="utf-8")
    f2.write_text(report, encoding="utf-8")

    state = {
        "checked_at": datetime.now().isoformat(),
        "results": results,
    }
    state_file = out_dir / f"github_repo_update_state_{today}.json"
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"报告已保存: {f1.name}")
    return str(f1)


def _get_tenant_access_token() -> Optional[str]:
    """获取飞书 tenant access token"""
    try:
        import urllib.request, json as jsonlib
        data = jsonlib.dumps({
            "app_id": FEISHU_APP_ID,
            "app_secret": FEISHU_APP_SECRET,
        }).encode()
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = jsonlib.loads(resp.read())
            if result.get("code") == 0:
                return result.get("tenant_access_token")
        print(f"[飞书token失败] code={result.get('code')}", file=sys.stderr)
    except Exception as e:
        print(f"[飞书token异常] {e}", file=sys.stderr)
    return None


def send_feishu(summary: str) -> bool:
    """推送飞书摘要到用户私聊"""
    token = _get_tenant_access_token()
    if not token:
        return False
    try:
        import urllib.request, json as jsonlib
        payload = {
            "receive_id": FEISHU_USER_ID,
            "msg_type": "text",
            "content": jsonlib.dumps({"text": summary}),
        }
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
            data=jsonlib.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = jsonlib.loads(resp.read())
            if result.get("code") == 0:
                return True
            print(f"[飞书私聊推送失败] code={result.get('code')}, msg={result.get('msg')}", file=sys.stderr)
    except Exception as e:
        print(f"[飞书推送异常] {e}", file=sys.stderr)
    return False


def main():
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 检查 GitHub 仓库更新...")

    repos = load_config()
    print(f"监控仓库数：{len(repos)}")

    # 统计 tier 分布
    tier_counts = {}
    for cfg in repos:
        tier = cfg.get("tier", "extended")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    for tier, cnt in sorted(tier_counts.items()):
        print(f"  tier={tier}: {cnt}仓")

    results = []
    for repo_cfg in repos:
        path = repo_cfg.get("path") or repo_cfg.get("repo_path")
        if not path:
            continue
        print(f"  检查: {path}...", end=" ", flush=True)
        status = get_repo_status(path)
        status["tier"] = repo_cfg.get("tier", "extended")
        results.append(status)
        behind = status.get("commits_behind", "?")
        ahead = status.get("commits_ahead", "?")
        local = status.get("local_tag", "?")
        upstream = status.get("upstream_tag", "?")
        worktree = format_worktree_brief(status)
        print(
            f"本地={local} 上游={upstream} behind={behind} ahead={ahead} "
            f"工作区={worktree} [{status.get('status','?')}] [{status.get('tier')}]"
        )

    report = build_report(results)
    report_path = save_report(report, results)
    summary = build_summary(results)

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

    ok = send_feishu(summary)
    print(f"飞书推送: {'成功' if ok else '失败'}")
    print(f"\n报告路径: {report_path}")

    return results


if __name__ == "__main__":
    main()
