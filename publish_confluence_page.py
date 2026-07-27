#!/usr/bin/env python3
"""
Publish Markdown to Confluence (meeting-notes page writer)

Reads markdown from a file or stdin, converts to Confluence storage format,
and creates or updates a page via the REST API.

Credentials are resolved in this order:
  1. Environment variables CONFLUENCE_PAT / CONFLUENCE_BASE_URL
  2. The file passed via --env-file
  3. The project root .env (default)

Required env vars: CONFLUENCE_PAT, CONFLUENCE_BASE_URL

Usage:
    # Create new page (title from H1 or --title)
    python publish_confluence_page.py minutes.md --space DEV --parent-id 123456 --title "Meeting Notes: ..."

    # Update existing page
    python publish_confluence_page.py minutes.md --id 780369923

    # Dry-run preview
    python publish_confluence_page.py minutes.md --space DEV --dry-run --title "..."

Requirements:
    pip install atlassian-python-api md2cf mistune PyYAML
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

import yaml


# Project root is discovered by walking up from this script and looking for a
# recognizable marker (.env, .git, or pyproject.toml). This avoids hardcoding a
# fixed directory depth, so the script keeps working if it is moved or nested
# differently. The old fixed-depth location is kept only as a last-resort
# fallback.
def _find_project_root(start: Path) -> Path:
    markers = (".env", ".git", "pyproject.toml")
    for parent in [start, *start.parents]:
        if any((parent / marker).exists() for marker in markers):
            return parent
    # Fallback: original assumption of
    # .github/skills/publish-meeting-notes/scripts/this.py -> project root
    parents = start.parents
    return parents[4] if len(parents) > 4 else parents[-1]


PROJECT_ROOT = _find_project_root(Path(__file__).resolve().parent)


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

def load_env(env_file: Path) -> dict:
    env = {}
    for line in env_file.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.split("#")[0].strip()  # strip inline comments
        if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
            val = val[1:-1]
        env[key] = val
    return env


def get_confluence_client(env_file: Optional[str] = None):
    # Prefer environment variables already set by the caller.
    base_url = os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/")
    pat = os.environ.get("CONFLUENCE_PAT") or os.environ.get("ATLASSIAN_PAT", "")

    if not base_url or not pat:
        candidates = []
        if env_file:
            candidates.append(Path(env_file))
        candidates.append(PROJECT_ROOT / ".env")

        for path in candidates:
            if path and path.exists():
                file_env = load_env(path)
                base_url = base_url or file_env.get("CONFLUENCE_BASE_URL", "").rstrip("/")
                pat = pat or file_env.get("CONFLUENCE_PAT") or file_env.get("ATLASSIAN_PAT", "")
                if base_url and pat:
                    break

    if not base_url or not pat:
        raise ValueError(
            "CONFLUENCE_BASE_URL and CONFLUENCE_PAT must be set.\n"
            "Add them to the project .env, pass --env-file, or export them as env vars."
        )

    try:
        from atlassian import Confluence
    except ImportError:
        raise ImportError(
            "atlassian-python-api not installed.\n"
            "Run: pip install atlassian-python-api"
        )

    # cloud=False -> Confluence Data Center / Server (PAT bearer auth)
    return Confluence(url=base_url, token=pat, cloud=False)


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

def parse_markdown(source: str) -> Tuple[Dict, str, Optional[str]]:
    """Return (frontmatter, body, title). Title from frontmatter > H1 > None."""
    frontmatter: Dict = {}
    body = source
    title: Optional[str] = None

    if source.startswith("---\n"):
        parts = source.split("---\n", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
            except yaml.YAMLError:
                pass

    title = frontmatter.get("title")
    if not title:
        m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if m:
            title = m.group(1).strip()

    return frontmatter, body, title


def read_source(file_arg: str) -> str:
    if file_arg == "-":
        return sys.stdin.read()
    path = Path(file_arg)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_arg}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Markdown -> Confluence storage format
# ---------------------------------------------------------------------------

def _fix_storage_html(html: str) -> str:
    """Make converter output valid Confluence storage XHTML.

    Confluence storage format is strict XHTML and rejects void elements that
    are not self-closed. Self-close bare <hr> / <br> so the REST API accepts
    the body and decorative dividers are preserved.
    """
    html = re.sub(r"<hr\s*/?>", "<hr />", html, flags=re.IGNORECASE)
    html = re.sub(r"<br\s*/?>", "<br />", html, flags=re.IGNORECASE)
    return html


def _resolve_attachments(attachments: List[str], base_dir: Path) -> List[str]:
    """Resolve image references to real on-disk paths for upload.

    Generated minutes contain URL-encoded, relative image references
    (e.g. ``images/My%20Folder/screenshot_01.jpg``). The embedded
    ``ri:attachment`` filename stays the clean basename, but the uploader needs
    a real filesystem path. URL-decode each reference and, when relative,
    resolve it against the markdown file's directory.
    """
    resolved: List[str] = []
    for raw in attachments:
        decoded = unquote(raw)
        p = Path(decoded)
        if not p.is_absolute():
            p = (base_dir / p)
        resolved.append(os.path.normpath(str(p)))
    return resolved


def convert_to_storage(markdown: str, base_dir: Optional[Path] = None) -> Tuple[str, List[str]]:
    """Convert markdown to Confluence storage format. Returns (html, attachments)."""
    try:
        import mistune
        from md2cf.confluence_renderer import ConfluenceRenderer
    except ImportError:
        # md2cf is intentionally optional here: available releases pin old
        # mistune/requests versions that conflict with this app's dependencies.
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from meeting_notes.confluence import ConfluenceService

        return ConfluenceService(project_root=PROJECT_ROOT).convert_to_storage(markdown, base_dir or PROJECT_ROOT)

    renderer = ConfluenceRenderer()
    parser = mistune.Markdown(renderer=renderer)
    storage_html = _fix_storage_html(parser(markdown))
    attachments = getattr(renderer, "attachments", [])
    if base_dir is not None:
        attachments = _resolve_attachments(attachments, base_dir)
    return storage_html, attachments


# ---------------------------------------------------------------------------
# Attachments upload
# ---------------------------------------------------------------------------

def upload_attachments(confluence, page_id: str, attachments: List[str]) -> None:
    for i, path in enumerate(attachments, 1):
        filename = os.path.basename(path)
        print(f"  [{i}/{len(attachments)}] {filename} ... ", end="", flush=True)

        if not os.path.exists(path):
            print(f"SKIP (not found: {path})")
            continue

        existing = confluence.get_attachments_from_content(page_id)
        if any(a["title"] == filename for a in existing.get("results", [])):
            print("already exists, skipping")
            continue

        ext_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".svg": "image/svg+xml", ".pdf": "application/pdf",
        }
        content_type = ext_map.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")
        confluence.attach_file(filename=path, name=filename, content_type=content_type, page_id=page_id)
        print("OK")


# ---------------------------------------------------------------------------
# Create / Update
# ---------------------------------------------------------------------------

def publish_page(
    confluence,
    storage_html: str,
    title: str,
    page_id: Optional[str],
    space_key: Optional[str],
    parent_id: Optional[str],
    attachments: List[str],
) -> Dict:
    if page_id:
        info = confluence.get_page_by_id(page_id, expand="version")
        current_version = info["version"]["number"]
        print(f"Updating page {page_id} (version {current_version} -> {current_version + 1})")

        result = confluence.update_page(
            page_id=page_id,
            title=title,
            body=storage_html,
            parent_id=parent_id,
            type="page",
            representation="storage",
            minor_edit=False,
        )
    else:
        if not space_key:
            raise ValueError("--space is required when creating a new page")
        print(f"Creating new page in space {space_key!r}, title: {title!r}")

        result = confluence.create_page(
            space=space_key,
            title=title,
            body=storage_html,
            parent_id=parent_id,
            type="page",
            representation="storage",
        )

    pid = result["id"]
    if attachments:
        print(f"Uploading {len(attachments)} attachment(s)...")
        upload_attachments(confluence, pid, attachments)

    url = confluence.url + result["_links"]["webui"]
    return {"id": pid, "title": result["title"], "version": result.get("version", {}).get("number"), "url": url}


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def dry_run(title: str, storage_html: str, page_id: Optional[str],
            space_key: Optional[str], parent_id: Optional[str], attachments: List[str]) -> None:
    print("=" * 60)
    print("DRY-RUN - no changes will be made")
    print("=" * 60)
    print(f"Mode   : {'UPDATE' if page_id else 'CREATE'}")
    print(f"Title  : {title}")
    if page_id:
        print(f"Page ID: {page_id}")
    else:
        print(f"Space  : {space_key}")
    if parent_id:
        print(f"Parent : {parent_id}")
    if attachments:
        print(f"Attachments ({len(attachments)}):")
        for a in attachments:
            status = "OK" if os.path.exists(a) else "NOT FOUND"
            print(f"  - {a}  [{status}]")
    print(f"\nStorage HTML ({len(storage_html)} chars) - first 500:")
    print("-" * 60)
    print(storage_html[:500] + ("..." if len(storage_html) > 500 else ""))
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Publish meeting-notes Markdown to Confluence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create new page
  %(prog)s minutes.md --space DEV --title "Meeting Notes: ..." --parent-id 123456

  # Update existing page
  %(prog)s minutes.md --id 780369923

  # Dry-run
  %(prog)s minutes.md --space DEV --dry-run --title "..."
        """,
    )
    parser.add_argument("file", help="Markdown file path, or '-' for stdin")
    parser.add_argument("--id", dest="page_id", help="Page ID to update")
    parser.add_argument("--space", help="Space key (required when creating)")
    parser.add_argument("--title", help="Page title (overrides frontmatter / H1)")
    parser.add_argument("--parent-id", help="Parent page ID")
    parser.add_argument("--dry-run", action="store_true", help="Preview without publishing")
    parser.add_argument("--env-file", help="Path to .env credentials file (default: project .env)")
    args = parser.parse_args()

    # Read source
    try:
        source = read_source(args.file)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Parse
    frontmatter, body, extracted_title = parse_markdown(source)
    title = args.title or extracted_title or (Path(args.file).stem.replace("_", " ") if args.file != "-" else "Untitled")
    fm_conf = frontmatter.get("confluence") if isinstance(frontmatter.get("confluence"), dict) else {}
    page_id = args.page_id or fm_conf.get("id")
    space_key = args.space or fm_conf.get("space")
    parent_id = args.parent_id or fm_conf.get("parent_id")

    if not page_id and not space_key:
        print("ERROR: Provide --id (update) or --space (create).", file=sys.stderr)
        sys.exit(1)

    # Convert. Resolve image paths relative to the markdown file's directory so
    # URL-encoded / relative references upload correctly.
    base_dir = Path(args.file).resolve().parent if args.file != "-" else Path.cwd()
    try:
        print(f"Converting markdown ({len(body)} chars)...")
        storage_html, attachments = convert_to_storage(body, base_dir=base_dir)
        print(f"Storage HTML: {len(storage_html)} chars, {len(attachments)} attachment(s)")
    except Exception as e:
        print(f"ERROR during conversion: {e}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        dry_run(title, storage_html, page_id, space_key, parent_id, attachments)
        return

    # Connect
    try:
        confluence = get_confluence_client(args.env_file)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Publish
    try:
        result = publish_page(confluence, storage_html, title, page_id, space_key, parent_id, attachments)
        print("-" * 60)
        print("DONE")
        print(f"  Title  : {result['title']}")
        print(f"  ID     : {result['id']}")
        print(f"  Version: {result['version']}")
        print(f"  URL    : {result['url']}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
