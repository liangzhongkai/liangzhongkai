"""
update_readme.py  —  v2
修复：加调试输出，处理 GraphQL 返回空数据的情况，fallback 到 REST API
"""

import os
import re
import sys
import requests
from datetime import datetime, timezone

USERNAME = os.environ.get("GITHUB_USERNAME", "liangzhongkai")
TOKEN    = os.environ.get("GITHUB_TOKEN", "")

if not TOKEN:
    print("ERROR: GITHUB_TOKEN is not set", flush=True)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ── REST API fallback（比 GraphQL 更宽松）────────────────────────────────────

def get_user():
    r = requests.get(f"https://api.github.com/users/{USERNAME}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def get_repos():
    repos, page = [], 1
    while True:
        r = requests.get(
            f"https://api.github.com/users/{USERNAME}/repos",
            params={"type": "owner", "per_page": 100, "page": page, "sort": "pushed"},
            headers=HEADERS, timeout=15,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return repos

# ── GraphQL：贡献数据 ────────────────────────────────────────────────────────

GQL = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { contributionCount date }
        }
      }
    }
  }
}
"""

def get_contributions():
    try:
        r = requests.post(
            "https://api.github.com/graphql",
            json={"query": GQL, "variables": {"login": USERNAME}},
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            print(f"GraphQL errors: {data['errors']}", flush=True)
            return None
        return data["data"]["user"]["contributionsCollection"]
    except Exception as e:
        print(f"GraphQL failed: {e}", flush=True)
        return None

# ── 组装数据 ─────────────────────────────────────────────────────────────────

def bar(count, max_count, width=18):
    if max_count == 0:
        return "░" * width
    filled = round(count / max_count * width)
    return "█" * filled + "░" * (width - filled)

def collect():
    print(f"Fetching data for: {USERNAME}", flush=True)

    user  = get_user()
    repos = get_repos()
    print(f"  user OK  |  repos: {len(repos)}", flush=True)

    total_stars = sum(r.get("stargazers_count", 0) for r in repos if not r.get("fork"))
    own_repos   = [r for r in repos if not r.get("fork")]

    # language distribution
    lang_count: dict[str, int] = {}
    for r in own_repos:
        lang = r.get("language")
        if lang:
            lang_count[lang] = lang_count.get(lang, 0) + 1
    top_langs = sorted(lang_count.items(), key=lambda x: -x[1])[:5]

    # recently active repos (top 5 by pushed_at)
    active = sorted(own_repos, key=lambda r: r.get("pushed_at") or "", reverse=True)[:5]

    # contributions via GraphQL
    cc = get_contributions()
    if cc:
        year_contribs  = cc["contributionCalendar"]["totalContributions"]
        total_commits  = cc["totalCommitContributions"]
        total_prs      = cc["totalPullRequestContributions"]
        total_issues   = cc["totalIssueContributions"]

        # last-30-days commits
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        recent = sum(
            d["contributionCount"]
            for w in cc["contributionCalendar"]["weeks"]
            for d in w["contributionDays"]
            if d["date"] >= cutoff
        )
        print(f"  contributions OK  |  year={year_contribs}  recent30={recent}", flush=True)
    else:
        year_contribs = total_commits = total_prs = total_issues = recent = 0
        print("  contributions: fallback to 0 (GraphQL unavailable)", flush=True)

    return dict(
        followers      = user.get("followers", 0),
        following      = user.get("following", 0),
        total_repos    = user.get("public_repos", len(own_repos)),
        total_stars    = total_stars,
        year_contribs  = year_contribs,
        total_commits  = total_commits,
        total_prs      = total_prs,
        total_issues   = total_issues,
        recent_commits = recent,
        top_langs      = top_langs,
        active_repos   = active,
        updated_at     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

# ── 渲染 ─────────────────────────────────────────────────────────────────────

def render(s: dict) -> str:
    # languages bar
    lang_lines = ""
    if s["top_langs"]:
        max_c = s["top_langs"][0][1]
        for lang, cnt in s["top_langs"]:
            lang_lines += f"  {lang:<14}{bar(cnt, max_c)}  {cnt} repos\n"
    else:
        lang_lines = "  (no language data)\n"

    # active repos
    repo_lines = ""
    for r in s["active_repos"]:
        name   = r["name"][:32]
        lang   = r.get("language") or "—"
        stars  = r.get("stargazers_count", 0)
        pushed = (r.get("pushed_at") or "")[:10]
        desc   = (r.get("description") or "")[:48]
        repo_lines += f"  ◈ {name:<32} ★{stars:<3} [{lang}]  {pushed}\n"
        if desc:
            repo_lines += f"    {desc}\n"

    return f"""```
┌──────────────────────────────────────────────────────┐
│  GITHUB STATS  ·  {s['updated_at']}
├──────────────────────────────────────────────────────┤
│  Public repos   {s['total_repos']:<6}  Stars        {s['total_stars']:<6}  │
│  Followers      {s['followers']:<6}  Following    {s['following']:<6}  │
│  Commits(year)  {s['year_contribs']:<6}  PRs          {s['total_prs']:<6}  │
│  Commits(30d)   {s['recent_commits']:<6}  Issues       {s['total_issues']:<6}  │
└──────────────────────────────────────────────────────┘
```

**Top languages**
```
{lang_lines.rstrip()}
```

**Recently active repos**
```
{repo_lines.rstrip()}
```"""

# ── 写回 README.md ────────────────────────────────────────────────────────────

START   = "<!--START_SECTION:stats-->"
END     = "<!--END_SECTION:stats-->"
PATTERN = re.compile(rf"{re.escape(START)}.*?{re.escape(END)}", re.DOTALL)

def update_readme(path="README.md"):
    with open(path, encoding="utf-8") as f:
        original = f.read()

    stats   = collect()
    content = render(stats)
    block   = f"{START}\n{content}\n{END}"

    if PATTERN.search(original):
        updated = PATTERN.sub(block, original)
    else:
        updated = original.rstrip() + "\n\n" + block + "\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)

    # 验证写入成功
    with open(path, encoding="utf-8") as f:
        verify = f.read()
    if START in verify and "GITHUB STATS" in verify:
        print("README.md updated and verified OK.", flush=True)
    else:
        print("ERROR: README.md update verification failed!", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    update_readme()
