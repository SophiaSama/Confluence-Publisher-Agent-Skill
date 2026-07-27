# Confluence-Publisher-Agent-Skill

This skill helps to publish your markdown notes to confluence page.
It currently only supports storage/XHTML representation (not ADF) for v1 REST API on Confluence Cloud.

Use it when the user wants to publish, post, upload, or push a generated meeting-notes / minutes markdown file (in `.md` format) to a Confluence page, including its image attached(if any).

This skill does not support ADF that is required by Confluence Cloud v2 REST API yet.

## How to use it
Save this skill and the scripts under your `.github` or other preferred agent skill locations, configure your
Confluence URL and PAT according to [.env.example](.env.example), 
Then ask your AI agent by something like: "publish meeting notes to Confluence", "upload the minutes to
Confluence", "post these meeting notes", "push minutes to Confluence".
