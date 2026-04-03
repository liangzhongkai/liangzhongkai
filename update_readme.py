"""
update_readme.py
自动拉取 GitHub 数据并更新 README.md 中的动态区域。
动态内容写在 <!--START_SECTION:stats--> ... <!--END_SECTION:stats--> 之间。
"""

import os
import re
import requests
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

USERNAME = os.environ.get("GITHUB_USERNAME", "liangzhongkai")
TOKEN    = os.environ.get("GITHUB_TOKEN", "")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ── GraphQL: 一次请求拿到所有核心数据 ──────────────────────────────────────

GQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    followers { totalCount }
    following  { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, orderBy: {field: STARGAZERS, direction: DESC}) {
      totalCount
      nodes {
        name
        description
        stargazerCount
        primaryLanguage { name }
        pushedAt
        url
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""

def graphql(query, variables):
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def get_stats():
    data = graphql(GQL_QUERY, {"login": USERNAME})
    user = data["user"]

    repos = user["repositories"]["nodes"]
    total_stars = sum(r["stargazerCount"] for r in repos)

    # 最近推送的 top-5 非 fork 仓库
    active_repos = sorted(repos, key=lambda r: r["pushedAt"] or "", reverse=True)[:5]

    # 语言分布（按仓库数量）
    lang_count: dict[str, int] = {}
    for r in repos:
        lang = (r["primaryLanguage"] or {}).get("name")
        if lang:
            lang_count[lang] = lang_count.get(lang, 0) + 1
    top_langs = sorted(lang_count.items(), key=lambda x: -x[1])[:5]

    # 最近 30 天贡献
    all_days = [
        day
        for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]
        for day in week["contributionDays"]
    ]
    cutoff = (datetime.now(timezone.utc) - relativedelta(days=30)).date()
    recent_commits = sum(
        d["contributionCount"] for d in all_days
        if d["date"] >= str(cutoff)
    )

    cc = user["contributionsCollection"]

    return {
        "followers":       user["followers"]["totalCount"],
        "following":       user["following"]["totalCount"],
        "total_repos":     user["repositories"]["totalCount"],
        "total_stars":     total_stars,
        "total_commits":   cc["totalCommitContributions"],
        "total_prs":       cc["totalPullRequestContributions"],
        "total_issues":    cc["totalIssueContributions"],
        "year_contribs":   cc["contributionCalendar"]["totalContributions"],
        "recent_commits":  recent_commits,
        "top_langs":       top_langs,
        "active_repos":    active_repos,
        "updated_at":      datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


# ── 渲染动态区块 ────────────────────────────────────────────────────────────

def bar(count, max_count, width=20):
    filled = round(count / max_count * width) if max_count else 0
    return "█" * filled + "░" * (width - filled)


def render(s: dict) -> str:
    lang_section = ""
    if s["top_langs"]:
        max_c = s["top_langs"][0][1]
        for lang, cnt in s["top_langs"]:
            lang_section += f"  {lang:<12} {bar(cnt, max_c, 16)}  {cnt} repos\n"

    repo_section = ""
    for r in s["active_repos"]:
        name  = r["name"][:30]
        lang  = (r["primaryLanguage"] or {}).get("name", "—")
        stars = r["stargazerCount"]
        desc  = (r["description"] or "")[:50]
        pushed = r["pushedAt"][:10] if r["pushedAt"] else "—"
        repo_section += f"  ◈ {name:<30} ★{stars}  [{lang}]  {pushed}\n"
        if desc:
            repo_section += f"    {desc}\n"

    return f"""```
┌─────────────────────────────────────────────────────┐
│  GITHUB STATS  ·  auto-updated {s['updated_at']}
├─────────────────────────────────────────────────────┤
│  Repos          {s['total_repos']:<6}   Stars       {s['total_stars']:<6}  │
│  Followers      {s['followers']:<6}   Following   {s['following']:<6}  │
│  Commits(year)  {s['year_contribs']:<6}   PRs         {s['total_prs']:<6}  │
│  Commits(30d)   {s['recent_commits']:<6}   Issues      {s['total_issues']:<6}  │
└─────────────────────────────────────────────────────┘
```

**Top languages**
```
{lang_section.rstrip()}
```

**Recently active**
```
{repo_section.rstrip()}
```"""


# ── 写回 README.md ──────────────────────────────────────────────────────────

START = "<!--START_SECTION:stats-->"
END   = "<!--END_SECTION:stats-->"
PATTERN = re.compile(
    rf"{re.escape(START)}.*?{re.escape(END)}",
    re.DOTALL,
)

def update_readme(content: str) -> str:
    block = f"{START}\n{render(get_stats())}\n{END}"
    if PATTERN.search(content):
        return PATTERN.sub(block, content)
    # 如果 README 里还没有占位符，追加到末尾
    return content.rstrip() + "\n\n" + block + "\n"


if __name__ == "__main__":
    readme_path = "README.md"
    with open(readme_path, encoding="utf-8") as f:
        original = f.read()

    updated = update_readme(original)

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(updated)

    print("README.md updated successfully.")
