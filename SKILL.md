---
name: publish-meeting-notes
description: |
  Publish generated meeting minutes from this project to Confluence. Use when
  the user wants to publish, post, upload, or push a generated meeting-notes /
  minutes markdown file (artifacts/meeting_minutes/*.minutes.md) to a Confluence
  page, including its captured screenshots.
  This skill only supports the storage/XHTML representation (not ADF) for v1 REST API on Confluence Cloud.
  This skill does not support ADF that is required by Confluence Cloud v2 REST API.
  Triggers: "publish meeting notes to Confluence", "upload the minutes to
  Confluence", "post these meeting notes", "push minutes to Confluence".
license: MIT
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
---

## What this skill does

Publishes a generated meeting-minutes markdown file from
`artifacts/meeting_minutes/` to a Confluence page and uploads its referenced
screenshots as page attachments. It wraps
`.github/skills/publish-meeting-notes/scripts/publish_confluence_page.py`.

## Critical constraints

- **DO NOT use MCP for page uploads** — the target Confluence is Data Center
  (Server), and the MCP integration is Cloud-only. Always use the bundled
  script via the terminal.
- **Credentials** are read from the project root `.env`:
  - `CONFLUENCE_BASE_URL` — e.g. `https://confluence.mycompany.com`
  - `CONFLUENCE_PAT` — a Confluence personal access token (bearer)

  They can also be exported as environment variables, or passed with
  `--env-file <path>`. The script never prints secrets.

  > **Always pass `--env-file .env` explicitly** (relative to the project root
  > where you run the command). The script auto-discovers the project-root
  > `.env`, but passing it explicitly is the robust default and avoids the
  > `CONFLUENCE_BASE_URL and CONFLUENCE_PAT must be set` error if the script is
  > moved or run from another directory. If you *do* hit that error even though
  > `.env` exists with both keys, the script's `PROJECT_ROOT` resolution is
  > wrong — pass `--env-file <absolute-or-relative-path-to-.env>`.

## Subpage vs. replace — READ THIS BEFORE CHOOSING A MODE

This is the #1 mistake to avoid. The script has two mutually exclusive modes:

| Phrase the user uses | Intended action | Flags |
|----------------------|-----------------|-------|
| "publish **under** page X", "add **under** X", "**as a subpage/child of** X", "nest under X", or gives a page **URL/ID as the location** | **CREATE a child page** | `--space KEY --parent-id PARENT_ID` |
| "**update** page X", "**overwrite/replace** page X", "edit **this** page", "publish **to** page X (and X is the notes page itself)" | **UPDATE in place** | `--id PAGE_ID` |

- **Default to CREATE-as-subpage** when a page is named only as a *location/parent*
  (e.g. "under page …/4232096702"). The given ID is the **`--parent-id`**, NOT `--id`.
- Only use `--id` (which **overwrites** that page's content) when the user clearly
  means the target page *is* the meeting-notes page to be replaced.
- **When in doubt, ask** which mode they want before publishing — overwriting the
  wrong page is destructive (it replaces title + body).

### Parsing a Confluence URL

For a URL like
`https://.../spaces/SPACE1696/pages/4232096702/Some+Title`:
- **Space key** = the segment after `/spaces/` → `SPACE1696` (use for `--space`)
- **Page ID** = the number after `/pages/` → `4232096702`
  - If the user said "under" this page → it's the **`--parent-id`**
  - If the user said "update/replace" this page → it's the **`--id`**

## Meeting-notes specifics

Generated minutes (`artifacts/meeting_minutes/<name>.minutes.md`) have two quirks
this skill must handle:

1. **The title.** The file begins with a `# Meeting Minutes` metadata block
   (source_video, transcript_file, generated_at), followed by the real heading
   `# Meeting Notes <topic>` (the separator may be a colon `:` or an em dash
   `—`). The script's auto-title picks the *first* H1 (`Meeting Minutes`), which
   is wrong. **Always pass `--title`** using the **second** H1 — the one
   starting with `Meeting Notes`. Read the file and extract that heading first.
2. **Screenshots.** Images are referenced as URL-encoded relative paths like
   `![Screenshot at 00:12](images/<stem>/screenshot_01.jpg)`. The script
   resolves these against the markdown file's own directory and uploads them as
   attachments automatically — no preprocessing needed.

## Workflow

### Step 1 — Pick the minutes file and title

```bash
# List available minutes
ls artifacts/meeting_minutes/*.minutes.md
```

Read the chosen file and grab the real title from the second H1 — the line
starting with `# Meeting Notes` (colon or em dash separator) — to pass via
`--title`.

### Step 2 — Collect the Confluence target

First decide the mode using **Subpage vs. replace** above, then ask the user for
whichever is missing:

| Info | Required? | Notes |
|------|-----------|-------|
| Minutes file path | Yes | `artifacts/meeting_minutes/<name>.minutes.md` |
| `--title "Meeting Notes: ..."` | Yes | From the second H1 in the file |
| `--env-file .env` | Yes | Always pass it explicitly |
| **Create subpage (default):** `--space SPACE_KEY` | Yes | From the URL `/spaces/<KEY>` |
| **Create subpage (default):** `--parent-id ID` | Yes | The page the user said to publish "under" |
| **Update/replace only:** `--id PAGE_ID` | Yes (overwrites!) | Only when replacing that exact page |

> Images render inline automatically: each `![...](images/.../screenshot_NN.jpg)`
> becomes an `<ac:image>` macro referencing the uploaded attachment by basename,
> so the screenshots appear in the page body (verified: 20/20 resolve & embed).
> Image paths may contain literal spaces or `%20` — both resolve correctly.

### Step 3 — Dry-run first

Dry-run the **subpage create** (the default case — note `--parent-id`, not `--id`):

```bash
python .github/skills/publish-meeting-notes/scripts/publish_confluence_page.py \
  "artifacts/meeting_minutes/2026-06-05 15-04-43_20260605_161809.minutes.md" \
  --space SPACE1696 \
  --parent-id 4232096702 \
  --title "Meeting Notes: BLE/UWB Authentication and Transaction Logic Review" \
  --env-file .env \
  --dry-run
```

Confirm `Mode: CREATE`, the right `Parent`, the title, the attachment list (all
should show `OK`), and the storage preview. If it says `Mode: UPDATE` but the
user wanted a subpage, **stop** — you used `--id` instead of `--parent-id`.

### Step 4 — Publish

```bash
# DEFAULT: create a subpage under the page the user named ("under page X")
python .github/skills/publish-meeting-notes/scripts/publish_confluence_page.py \
  "artifacts/meeting_minutes/2026-06-05 15-04-43_20260605_161809.minutes.md" \
  --space SPACE1696 \
  --parent-id 4232096702 \
  --title "Meeting Notes: BLE/UWB Authentication and Transaction Logic Review" \
  --env-file .env

# ONLY when explicitly told to update/replace that exact page (overwrites it!)
python .github/skills/publish-meeting-notes/scripts/publish_confluence_page.py \
  "artifacts/meeting_minutes/2026-06-05 15-04-43_20260605_161809.minutes.md" \
  --id 780369923 \
  --title "Meeting Notes: BLE/UWB Authentication and Transaction Logic Review" \
  --env-file .env
```

On success the script prints the page ID, version, and URL.

## Script reference

```
scripts/publish_confluence_page.py  [file | -]
    --id PAGE_ID          Update existing page
    --space SPACE_KEY     Create in this space
    --title "Title"       Page title (use the "# Meeting Notes: ..." heading)
    --parent-id ID        Nest under parent page
    --dry-run             Preview without publishing
    --env-file PATH       Custom .env (default: project root .env)
```

## Error checklist

| Error | Fix |
|-------|-----|
| `CONFLUENCE_BASE_URL and CONFLUENCE_PAT must be set` (even though `.env` has both) | Pass `--env-file .env` explicitly. The script resolves the project-root `.env` via `PROJECT_ROOT`; if that points at the wrong folder it won't find it. |
| `--space is required` | Add `--space SPACE_KEY` (creating) or use `--id` (updating) |
| `atlassian-python-api not installed` | `pip install atlassian-python-api md2cf mistune PyYAML` |
| Attachment `NOT FOUND` in dry-run | The `images/<stem>/` folder is missing next to the minutes file; regenerate the notes |
| `403 / 401` | Check `CONFLUENCE_PAT` validity / permissions |
| Title shows `Meeting Minutes` | You forgot `--title`; pass the second H1 (`# Meeting Notes ...`) |
| **Overwrote the wrong page** (used `--id` when user meant "under") | The user wanted a **subpage** — use `--space` + `--parent-id` instead. To recover the clobbered page, fetch its previous version and restore it: `get_page_by_id(id, version=N, expand='body.storage')` then `update_page(...)`. |
