"""
update_readme.py — Auto-updates README.md with live GitHub data.

Usage:
    python scripts/update_readme.py
    python scripts/update_readme.py --readme README.md --config repos.yaml
    python scripts/update_readme.py --skip-ci   # skip CI status checks (faster)
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

GITHUB_GRAPHQL = "https://api.github.com/graphql"
GITHUB_REST = "https://api.github.com"

MATURITY_BADGES = {
    "active": "![active](https://img.shields.io/badge/active-brightgreen)",
    "maintained": "![maintained](https://img.shields.io/badge/maintained-blue)",
    "experimental": "![experimental](https://img.shields.io/badge/experimental-yellow)",
    "archived": "![archived](https://img.shields.io/badge/archived-lightgrey)",
}

LANGUAGE_EMOJI = {
    "C#": "C#",
    "Python": "Python",
    "JavaScript": "JS",
    "TypeScript": "TS",
    "HTML": "HTML",
    "GDScript": "GDScript",
}


# ── GitHub Client ─────────────────────────────────────────────


class GitHubClient:
    """Fetches repo data via GraphQL (bulk) and REST (CI status)."""

    def __init__(self, token: str | None, owner: str):
        self.token = token
        self.owner = owner
        self.headers = {}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def fetch_repos_graphql(self, repo_names: list[str]) -> dict[str, dict]:
        """Fetch metadata for all repos in a single GraphQL call."""
        if not self.token:
            print("  [warn] No GITHUB_TOKEN — skipping GraphQL, using yaml-only data")
            return {}

        # Build aliased query fragments
        fragments = []
        for i, name in enumerate(repo_names):
            fragments.append(f"""
            r{i}: repository(owner: "{self.owner}", name: "{name}") {{
                name
                description
                url
                primaryLanguage {{ name }}
                defaultBranchRef {{
                    target {{
                        ... on Commit {{
                            committedDate
                        }}
                    }}
                }}
                isArchived
            }}""")

        query = "query { " + "\n".join(fragments) + "\n}"

        resp = requests.post(
            GITHUB_GRAPHQL,
            json={"query": query},
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            # Some repos may fail (private/missing) — collect what we can
            print(f"  [warn] GraphQL errors: {data['errors']}")

        result = {}
        for i, name in enumerate(repo_names):
            key = f"r{i}"
            repo_data = data.get("data", {}).get(key)
            if repo_data is None:
                continue
            lang = repo_data.get("primaryLanguage")
            default_branch = repo_data.get("defaultBranchRef")
            last_commit = None
            if default_branch and default_branch.get("target"):
                last_commit = default_branch["target"].get("committedDate", "")
                if last_commit:
                    last_commit = last_commit[:10]  # YYYY-MM-DD

            result[name] = {
                "description": repo_data.get("description") or "",
                "url": repo_data.get("url") or f"https://github.com/{self.owner}/{name}",
                "language": lang["name"] if lang else "",
                "last_commit": last_commit or "",
                "is_archived": repo_data.get("isArchived", False),
            }
        return result

    def fetch_ci_status(self, repo_name: str) -> str | None:
        """Check if repo has passing CI (latest workflow run on default branch)."""
        if not self.token:
            return None
        try:
            resp = requests.get(
                f"{GITHUB_REST}/repos/{self.owner}/{repo_name}/actions/runs",
                headers=self.headers,
                params={"per_page": 1, "status": "completed"},
                timeout=10,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            runs = resp.json().get("workflow_runs", [])
            if not runs:
                return None
            conclusion = runs[0].get("conclusion", "")
            if conclusion == "success":
                return "pass"
            elif conclusion in ("failure", "timed_out"):
                return "fail"
            return None
        except Exception:
            return None


# ── Config Loader ─────────────────────────────────────────────


def load_config(config_path: Path) -> dict:
    """Load and validate repos.yaml."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


# ── Merge Logic ───────────────────────────────────────────────


def merge_data(config: dict, api_data: dict, ci_data: dict) -> list[dict]:
    """Merge API data with manual yaml metadata. Manual values take precedence."""
    repos = []
    owner = config["owner"]

    for name, meta in config["repos"].items():
        api = api_data.get(name, {})
        is_private = meta.get("private", False)

        repo = {
            "name": name,
            "category": meta["category"],
            "url": api.get("url", f"https://github.com/{owner}/{name}"),
            "description": meta.get("short_description") or api.get("description", ""),
            "language": api.get("language", ""),
            "last_commit": api.get("last_commit", ""),
            "rhino_version": meta.get("rhino_version", ""),
            "maturity": meta.get("maturity", "maintained"),
            "ci": ci_data.get(name),
            "private": is_private,
            "is_archived": api.get("is_archived", False),
        }

        # Override maturity if GitHub says archived
        if repo["is_archived"]:
            repo["maturity"] = "archived"

        repos.append(repo)

    return repos


# ── Markdown Generator ────────────────────────────────────────


def generate_overview(repos: list[dict]) -> str:
    """Generate overview stats section."""
    total = len(repos)
    public = sum(1 for r in repos if not r["private"])
    private = sum(1 for r in repos if r["private"])

    # Count languages
    langs: dict[str, int] = {}
    for r in repos:
        lang = r["language"]
        if lang:
            langs[lang] = langs.get(lang, 0) + 1

    lang_parts = []
    for lang, count in sorted(langs.items(), key=lambda x: -x[1]):
        display = LANGUAGE_EMOJI.get(lang, lang)
        lang_parts.append(f"**{display}** ({count})")

    # Count maturity
    active = sum(1 for r in repos if r["maturity"] == "active")
    experimental = sum(1 for r in repos if r["maturity"] == "experimental")

    lines = [
        f"**{total} repos** — {public} public, {private} private",
        f"| Languages | {' · '.join(lang_parts)} |" if lang_parts else "",
        f"| Active | {active} actively developed · {experimental} experimental |",
    ]
    # Use a simple format
    overview = f"**{total} repos** — {public} public, {private} private\n\n"
    if lang_parts:
        overview += f"Languages: {' · '.join(lang_parts)}\n\n"
    overview += f"{active} actively developed · {experimental} experimental"
    return overview


def generate_category_table(category_id: str, category_meta: dict, repos: list[dict]) -> str:
    """Generate a markdown table for one category."""
    cat_repos = [r for r in repos if r["category"] == category_id]
    if not cat_repos:
        return ""

    icon = category_meta.get("icon", "")
    title = category_meta.get("title", category_id)
    lines = [
        f"### {icon} {title}",
        "",
        "| Repo | Description | Language | Last Commit | Rhino | Status | CI |",
        "|------|-------------|----------|-------------|-------|--------|----|",
    ]

    for r in cat_repos:
        name = r["name"]
        if r["private"]:
            repo_link = f"{name} *(private)*"
        else:
            repo_link = f"[{name}]({r['url']})"

        desc = r["description"]
        lang = r["language"] or "—"
        last_commit = r["last_commit"] or "—"
        rhino = r["rhino_version"] or "—"
        status = MATURITY_BADGES.get(r["maturity"], r["maturity"])

        ci = "—"
        if r["ci"] == "pass":
            ci = "✅"
        elif r["ci"] == "fail":
            ci = "❌"

        lines.append(f"| {repo_link} | {desc} | {lang} | {last_commit} | {rhino} | {status} | {ci} |")

    return "\n".join(lines)


def generate_repos_section(config: dict, repos: list[dict]) -> str:
    """Generate all category tables."""
    sections = []
    for cat_id, cat_meta in config["categories"].items():
        table = generate_category_table(cat_id, cat_meta, repos)
        if table:
            sections.append(table)
    return "\n\n".join(sections)


def generate_updated_section() -> str:
    """Generate last-updated footer."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"*Last auto-update: {now}*"


# ── README Updater ────────────────────────────────────────────


def update_section(readme: str, marker: str, content: str) -> str:
    """Replace content between <!-- marker starts --> and <!-- marker ends -->."""
    pattern = re.compile(
        rf"(<!-- {re.escape(marker)} starts -->)\n.*?(<!-- {re.escape(marker)} ends -->)",
        re.DOTALL,
    )
    replacement = rf"\1\n{content}\n\2"
    new_readme, count = pattern.subn(replacement, readme)
    if count == 0:
        print(f"  [warn] Marker '{marker}' not found in README")
    return new_readme


# ── Main ──────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Update rhino-dev-hub README")
    parser.add_argument("--readme", default="README.md", help="Path to README.md")
    parser.add_argument("--config", default="repos.yaml", help="Path to repos.yaml")
    parser.add_argument("--skip-ci", action="store_true", help="Skip CI status checks")
    args = parser.parse_args()

    # Resolve paths relative to repo root
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    readme_path = repo_root / args.readme
    config_path = repo_root / args.config

    print(f"Config:  {config_path}")
    print(f"README:  {readme_path}")

    # Load config
    config = load_config(config_path)
    owner = config["owner"]
    repo_names = list(config["repos"].keys())
    print(f"Found {len(repo_names)} repos in config")

    # Filter out private repos for API calls
    public_repos = [name for name in repo_names if not config["repos"][name].get("private")]
    print(f"  {len(public_repos)} public, {len(repo_names) - len(public_repos)} private")

    # GitHub API
    token = os.environ.get("GITHUB_TOKEN")
    client = GitHubClient(token, owner)

    print("Fetching repo data via GraphQL...")
    api_data = client.fetch_repos_graphql(public_repos)
    print(f"  Got data for {len(api_data)} repos")

    # CI status
    ci_data: dict[str, str | None] = {}
    if not args.skip_ci and token:
        print("Fetching CI status...")
        for name in public_repos:
            ci_data[name] = client.fetch_ci_status(name)
            status = ci_data[name] or "none"
            if status != "none":
                print(f"  {name}: {status}")
    else:
        print("Skipping CI status checks")

    # Merge
    repos = merge_data(config, api_data, ci_data)

    # Generate sections
    overview = generate_overview(repos)
    repos_section = generate_repos_section(config, repos)
    updated = generate_updated_section()

    # Update README
    readme = readme_path.read_text(encoding="utf-8")
    readme = update_section(readme, "overview", overview)
    readme = update_section(readme, "repos", repos_section)
    readme = update_section(readme, "updated", updated)

    readme_path.write_text(readme, encoding="utf-8")
    print(f"\nREADME updated successfully!")


if __name__ == "__main__":
    main()
