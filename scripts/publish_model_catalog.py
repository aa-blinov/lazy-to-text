"""Publish human-readable model indexes beside the public B2 model files.

The renderer's model-card link points at one page per canonical model.
The downloadable weights themselves remain byte-for-byte copies of their
Hugging Face sources; each page keeps the source repository and revision visible.

Requires boto3 at invocation time and the S3_* environment variables used by
the Backblaze B2 S3-compatible API.
"""

from __future__ import annotations

import html
import json
import os
import urllib.request

import boto3


BUCKET = "lazy-to-text-models"
PREFIX = "lazy-to-text"
PUBLIC = f"https://f003.backblazeb2.com/file/{BUCKET}/{PREFIX}"
MANIFEST_URL = f"{PUBLIC}/manifest.json"


def main() -> None:
    with urllib.request.urlopen(MANIFEST_URL, timeout=30) as response:
        manifest = json.load(response)

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.environ["S3_REGION"],
        aws_access_key_id=os.environ["S3_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    )
    for repo in manifest["repos"]:
        aliases = ", ".join(repo["aliases"])
        rows = []
        for item in manifest["files"]:
            if item["repo"] != repo["repo"]:
                continue
            key = f"{PREFIX}/{repo['repo']}/{item['path']}"
            url = f"https://f003.backblazeb2.com/file/{BUCKET}/{key}"
            rows.append(
                "<tr><td><a href=\"{}\">{}</a></td><td>{:,}</td>"
                "<td><code>{}</code></td></tr>".format(
                    html.escape(url, quote=True),
                    html.escape(item["path"]),
                    item["size"],
                    item["sha256"],
                )
            )
        body = "\n".join(rows)
        source = f"https://huggingface.co/{repo['repo']}"
        page = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(aliases)} — Lazy to Text model files</title>
<style>body{{font:16px system-ui;max-width:1000px;margin:3rem auto;padding:0 1rem;color:#202124}}table{{border-collapse:collapse;width:100%}}th,td{{padding:.65rem;text-align:left;border-bottom:1px solid #ddd}}code{{font-size:.8em;overflow-wrap:anywhere}}a{{color:#075ec8}}</style>
<h1>{html.escape(aliases)}</h1>
<p>Public model files used by Lazy to Text. Source: <a href="{html.escape(source, quote=True)}">{html.escape(repo['repo'])}</a> at revision <code>{html.escape(repo['revision'])}</code>.</p>
<p><a href="{MANIFEST_URL}">Complete model manifest with SHA-256 hashes</a></p>
<table><thead><tr><th>File</th><th>Bytes</th><th>SHA-256</th></tr></thead><tbody>{body}</tbody></table>
</html>
"""
        name = repo["repo"].replace("/", "--") + ".html"
        key = f"{PREFIX}/catalog/{name}"
        client.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=page.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
            CacheControl="public, max-age=3600",
        )
        print(f"Published {PUBLIC}/catalog/{name}")


if __name__ == "__main__":
    main()
