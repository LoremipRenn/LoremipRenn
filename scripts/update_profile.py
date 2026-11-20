"""Auto-update GitHub profile stats SVGs and paginated projects table in README.md."""

from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

USERNAME = os.getenv("GITHUB_USERNAME", "LoremipRenn")
TOKEN = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or ""
PAGE_SIZE = 4

ROOT_DIR = Path(__file__).resolve().parent.parent
README_PATH = ROOT_DIR / "README.md"
PROJECTS_META_PATH = ROOT_DIR / "data" / "projects.json"
ASSETS_DIR = ROOT_DIR / "assets"

LANG_COLORS = {
    "PHP": "#4F5D95",
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Svelte": "#ff3e00",
    "Python": "#3572A5",
    "Blade": "#f7523f",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Vue": "#41b883",
    "C#": "#178600",
    "Smarty": "#f0c040",
    "Shell": "#89e051",
    "Dockerfile": "#384d54",
    "SCSS": "#c6538c",
}
FALLBACK_COLOR = "#8b949e"

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestContributions
      totalIssueContributions
    }
    repositories(
      first: 100
      ownerAffiliations: OWNER
      isFork: false
      orderBy: { field: PUSHED_AT, direction: DESC }
    ) {
      totalCount
      nodes {
        name
        description
        url
        stargazerCount
        pushedAt
        isPrivate
        primaryLanguage {
          name
        }
        repositoryTopics(first: 6) {
          nodes {
            topic {
              name
            }
          }
        }
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges {
            size
            node {
              name
              color
            }
          }
        }
      }
    }
  }
}
"""


def api_request(url: str, method: str = "GET", body: dict | None = None) -> dict | list:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-profile-updater",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    data = json.dumps(body).encode("utf-8") if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_via_graphql() -> dict | None:
    if not TOKEN:
        return None
    try:
        payload = api_request(
            "https://api.github.com/graphql",
            method="POST",
            body={"query": GRAPHQL_QUERY, "variables": {"login": USERNAME}},
        )
        if not isinstance(payload, dict) or payload.get("errors") or not payload.get("data", {}).get("user"):
            return None

        user = payload["data"]["user"]
        contrib = user["contributionsCollection"]
        repo_nodes = user["repositories"]["nodes"]

        total_stars = sum(r["stargazerCount"] for r in repo_nodes)
        total_commits = contrib["totalCommitContributions"] + contrib["restrictedContributionsCount"]

        lang_bytes: dict[str, int] = {}
        lang_colors: dict[str, str] = {}
        public_repos = []

        for r in repo_nodes:
            for edge in r.get("languages", {}).get("edges", []):
                lname = edge["node"]["name"]
                lang_bytes[lname] = lang_bytes.get(lname, 0) + edge["size"]
                if edge["node"].get("color"):
                    lang_colors[lname] = edge["node"]["color"]

            if not r["isPrivate"]:
                topics = [t["topic"]["name"] for t in r.get("repositoryTopics", {}).get("nodes", [])]
                public_repos.append(
                    {
                        "name": r["name"],
                        "url": r["url"],
                        "description": r["description"],
                        "stars": r["stargazerCount"],
                        "language": (r.get("primaryLanguage") or {}).get("name"),
                        "topics": topics,
                        "pushed_at": r["pushedAt"],
                    }
                )

        return {
            "total_repos": user["repositories"]["totalCount"],
            "total_stars": total_stars,
            "total_commits": total_commits,
            "total_prs": contrib["totalPullRequestContributions"],
            "total_issues": contrib["totalIssueContributions"],
            "lang_bytes": lang_bytes,
            "lang_colors": lang_colors,
            "public_repos": public_repos,
        }
    except (urllib.error.URLError, KeyError, TypeError, ValueError):
        return None


def fetch_via_rest() -> dict:
    user = api_request(f"https://api.github.com/users/{USERNAME}")
    repos = api_request(
        f"https://api.github.com/users/{USERNAME}/repos?per_page=100&sort=pushed&direction=desc"
    )
    own_repos = [r for r in repos if not r.get("fork")]

    total_stars = sum(r.get("stargazers_count", 0) for r in own_repos)
    total_commits = 0
    lang_bytes: dict[str, int] = {}
    public_repos = []

    for r in own_repos:
        rname = r["name"]
        try:
            langs = api_request(f"https://api.github.com/repos/{USERNAME}/{rname}/languages")
            for lname, size in langs.items():
                lang_bytes[lname] = lang_bytes.get(lname, 0) + size
        except urllib.error.URLError:
            pass

        try:
            contributors = api_request(f"https://api.github.com/repos/{USERNAME}/{rname}/contributors")
            if isinstance(contributors, list):
                for c in contributors:
                    if c.get("login", "").lower() == USERNAME.lower():
                        total_commits += c.get("contributions", 0)
        except urllib.error.URLError:
            pass

        public_repos.append(
            {
                "name": rname,
                "url": r["html_url"],
                "description": r.get("description"),
                "stars": r.get("stargazers_count", 0),
                "language": r.get("language"),
                "topics": r.get("topics") or [],
                "pushed_at": r.get("pushed_at") or "",
            }
        )

    pr_count = 0
    issue_count = 0
    try:
        pr_count = api_request(f"https://api.github.com/search/issues?q=author:{USERNAME}+type:pr").get("total_count", 0)
        issue_count = api_request(f"https://api.github.com/search/issues?q=author:{USERNAME}+type:issue").get("total_count", 0)
    except urllib.error.URLError:
        pass

    return {
        "total_repos": user.get("public_repos", len(own_repos)),
        "total_stars": total_stars,
        "total_commits": total_commits,
        "total_prs": pr_count,
        "total_issues": issue_count,
        "lang_bytes": lang_bytes,
        "lang_colors": {},
        "public_repos": public_repos,
    }


def compute_rank(stats: dict) -> tuple[str, float]:
    score = (
        stats["total_commits"] * 1.0
        + stats["total_stars"] * 4.0
        + stats["total_prs"] * 3.0
        + stats["total_issues"] * 2.0
        + stats["total_repos"] * 2.5
    )
    if score >= 500:
        return "S", 0.92
    if score >= 250:
        return "A+", 0.82
    if score >= 120:
        return "A", 0.72
    if score >= 60:
        return "B+", 0.62
    if score >= 30:
        return "B", 0.52
    return "C+", 0.40


def render_stats_svg(stats: dict) -> str:
    rank, progress = compute_rank(stats)
    radius = 40
    circumference = 2 * 3.14159265 * radius
    dash_offset = circumference * (1.0 - progress)

    rows = [
        ("Total Repositories", stats["total_repos"], "📁"),
        ("Total Stars Earned", stats["total_stars"], "⭐"),
        ("Total Commits", stats["total_commits"], "🔄"),
        ("Total PRs", stats["total_prs"], "🔀"),
        ("Total Issues", stats["total_issues"], "❗"),
    ]

    row_svg = []
    for idx, (label, val, icon) in enumerate(rows):
        y = 66 + idx * 25
        row_svg.append(
            f'<g transform="translate(25, {y})">'
            f'<text x="0" y="0" class="stat-label">{icon} {html.escape(label)}:</text>'
            f'<text x="205" y="0" class="stat-value">{val}</text>'
            f"</g>"
        )

    return f"""<svg width="460" height="195" viewBox="0 0 460 195" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Rendra's GitHub Stats">
  <style>
    .header {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #70a5fd; }}
    .stat-label {{ font: 600 13.5px 'Segoe UI', Ubuntu, Sans-Serif; fill: #38bdae; }}
    .stat-value {{ font: 700 13.5px 'Segoe UI', Ubuntu, Sans-Serif; fill: #a9b1d6; }}
    .rank-text {{ font: 800 24px 'Segoe UI', Ubuntu, Sans-Serif; fill: #70a5fd; }}
    .sub-text {{ font: 500 11px 'Segoe UI', Ubuntu, Sans-Serif; fill: #7982a9; }}
  </style>
  <rect x="0.5" y="0.5" rx="8" width="459" height="194" fill="#1a1b27" stroke="#292e42" />
  <text x="25" y="34" class="header">Rendra's GitHub Stats</text>
  {''.join(row_svg)}
  <g transform="translate(368, 104)">
    <circle cx="0" cy="0" r="{radius}" stroke="#292e42" stroke-width="8" fill="none" />
    <circle cx="0" cy="0" r="{radius}" stroke="#bf91f3" stroke-width="8" fill="none"
      stroke-linecap="round"
      stroke-dasharray="{circumference:.2f}"
      stroke-dashoffset="{dash_offset:.2f}"
      transform="rotate(-90)" />
    <text x="0" y="8" text-anchor="middle" class="rank-text">{html.escape(rank)}</text>
    <text x="0" y="58" text-anchor="middle" class="sub-text">Auto-Synced</text>
  </g>
</svg>
"""


def render_langs_svg(lang_bytes: dict[str, int], extra_colors: dict[str, str]) -> str:
    sorted_langs = sorted(lang_bytes.items(), key=lambda item: item[1], reverse=True)[:8]
    total = sum(size for _, size in sorted_langs) or 1

    bar_width = 330.0
    x_cursor = 25.0
    bar_segments = []
    legend_items = []

    for idx, (lang, size) in enumerate(sorted_langs):
        pct = (size / total) * 100.0
        seg_w = max((size / total) * bar_width, 2.0)
        color = extra_colors.get(lang) or LANG_COLORS.get(lang, FALLBACK_COLOR)
        bar_segments.append(
            f'<rect x="{x_cursor:.2f}" y="52" width="{seg_w:.2f}" height="8" fill="{color}" />'
        )
        x_cursor += seg_w

        col = idx % 2
        row = idx // 2
        lx = 25 + col * 175
        ly = 84 + row * 24
        legend_items.append(
            f'<g transform="translate({lx}, {ly})">'
            f'<circle cx="5" cy="-4" r="5" fill="{color}" />'
            f'<text x="16" y="0" class="lang-name">{html.escape(lang)} {pct:.2f}%</text>'
            f"</g>"
        )

    return f"""<svg width="380" height="195" viewBox="0 0 380 195" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Most Used Languages">
  <style>
    .header {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #70a5fd; }}
    .lang-name {{ font: 500 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: #a9b1d6; }}
  </style>
  <defs>
    <clipPath id="bar-clip">
      <rect x="25" y="52" width="{bar_width:.0f}" height="8" rx="4" />
    </clipPath>
  </defs>
  <rect x="0.5" y="0.5" rx="8" width="379" height="194" fill="#1a1b27" stroke="#292e42" />
  <text x="25" y="34" class="header">Most Used Languages</text>
  <g clip-path="url(#bar-clip)">
    {''.join(bar_segments)}
  </g>
  {''.join(legend_items)}
</svg>
"""


def build_projects_markdown(public_repos: list[dict], meta: dict) -> str:
    project_repos = [r for r in public_repos if r["name"].lower() != USERNAME.lower()]
    if not project_repos:
        return "_No public projects found yet._\n"

    total = len(project_repos)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    pages = [project_repos[i : i + PAGE_SIZE] for i in range(0, total, PAGE_SIZE)]

    def render_table(chunk: list[dict]) -> str:
        lines = [
            "| Project | Tech Stack | Highlights |",
            "| :--- | :--- | :--- |",
        ]
        for repo in chunk:
            name = repo["name"]
            override = meta.get(name, {})
            emoji = override.get("emoji", "📦")
            stack_list = override.get("stack") or []
            if not stack_list:
                if repo.get("language"):
                    stack_list.append(repo["language"])
                for topic in repo.get("topics", [])[:4]:
                    if topic.lower() != (repo.get("language") or "").lower():
                        stack_list.append(topic)
            stack_str = " ".join(f"`{s}`" for s in stack_list) if stack_list else "`Code`"

            raw_desc = override.get("highlights") or repo.get("description")
            if not raw_desc:
                lang_label = repo.get("language") or "code"
                raw_desc = f"Project built with **{lang_label}** (`★ {repo['stars']}`)."
            desc = raw_desc.replace("|", "\\|")
            lines.append(f"| {emoji} **[{name}]({repo['url']})** | {stack_str} | {desc} |")
        return "\n".join(lines)

    out = [
        f"<sub>Auto-synced from GitHub • Showing **Page 1 of {total_pages}** ({total} public repositories)</sub>\n",
        render_table(pages[0]),
    ]

    for page_idx in range(1, len(pages)):
        start_num = page_idx * PAGE_SIZE + 1
        end_num = start_num + len(pages[page_idx]) - 1
        out.append(
            f"\n<details>\n"
            f"<summary><b>📄 Page {page_idx + 1} of {total_pages}</b> — Projects {start_num}–{end_num} (click to expand)</summary>\n\n"
            f"{render_table(pages[page_idx])}\n"
            f"</details>"
        )

    return "\n".join(out) + "\n"


def update_readme(projects_md: str) -> None:
    content = README_PATH.read_text(encoding="utf-8")
    start_tag = "<!--START_PROJECTS-->"
    end_tag = "<!--END_PROJECTS-->"

    start_idx = content.find(start_tag)
    end_idx = content.find(end_tag)
    if start_idx == -1 or end_idx == -1:
        raise ValueError("Markers <!--START_PROJECTS--> / <!--END_PROJECTS--> not found in README.md")

    updated = (
        content[: start_idx + len(start_tag)]
        + "\n\n"
        + projects_md
        + "\n"
        + content[end_idx:]
    )
    README_PATH.write_text(updated, encoding="utf-8")


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    meta = json.loads(PROJECTS_META_PATH.read_text(encoding="utf-8")) if PROJECTS_META_PATH.exists() else {}

    data = fetch_via_graphql() or fetch_via_rest()

    (ASSETS_DIR / "github-stats.svg").write_text(render_stats_svg(data), encoding="utf-8")
    (ASSETS_DIR / "top-langs.svg").write_text(
        render_langs_svg(data["lang_bytes"], data["lang_colors"]), encoding="utf-8"
    )

    projects_md = build_projects_markdown(data["public_repos"], meta)
    update_readme(projects_md)
    print(
        f"Updated stats ({data['total_repos']} repos, {data['total_stars']} stars, "
        f"{data['total_commits']} commits) and {len(data['public_repos'])} public repos."
    )


if __name__ == "__main__":
    main()
