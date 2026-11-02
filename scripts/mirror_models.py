"""Work out which files each model card needs, and put the missing ones in the store.

The files a card needs are not a guess: they are the patterns onnx-asr's own
loader looks for (``_get_model_files``) at the precision the card loads with,
matched against the source repository's file list, plus the config. The result
is written into ``app/model_manifest.json`` under ``cards``, and the files that
the mirror does not hold yet are downloaded from their source repository at the
pinned revision, hashed, uploaded and added to the manifest.

    uv run --frozen --with boto3 python scripts/mirror_models.py            # plan only
    uv run --frozen --with boto3 python scripts/mirror_models.py --apply    # upload + write

Uploading needs the S3_* environment variables used by publish_model_catalog.py.
After an upload, run ``scripts/publish_model_catalog.py`` for the index pages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BUCKET = "lazy-to-text-models"
PREFIX = "lazy-to-text"
MANIFEST = ROOT / "app" / "model_manifest.json"
HF = "https://huggingface.co"


def _json(url: str):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def _listing(repo: str, revision: str) -> dict[str, int]:
    info = _json(f"{HF}/api/models/{repo}/revision/{revision}?blobs=true")
    return {s["rfilename"]: int(s.get("size") or 0) for s in info["siblings"]}


def _regex(pattern: str) -> re.Pattern:
    """The glob onnx-asr uses: ``**/`` any folders, ``*`` within one, ``?`` one character."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def _needed(repo: str, revision: str, load_id: str, quantization, listing: dict[str, int]):
    """``(model_type or None, [paths], [patterns that matched nothing])``."""
    from onnx_asr.loader import create_asr_resolver

    with tempfile.TemporaryDirectory() as tmp:
        model_type = None
        if "config.json" in listing:
            raw = urllib.request.urlopen(f"{HF}/{repo}/resolve/{revision}/config.json", timeout=60).read()
            Path(tmp, "config.json").write_bytes(raw)
            model_type = json.loads(raw).get("model_type")
        resolver = create_asr_resolver(load_id, local_dir=tmp)
        patterns = list(resolver.model_type._get_model_files(quantization).values())
    wanted = list(patterns)
    for pattern in patterns:
        if pattern.endswith(".onnx"):
            wanted.append(pattern[: -len(".onnx")] + ".onnx?data")
    paths, missing = set(), []
    for pattern in wanted:
        hits = [p for p in listing if _regex(pattern).match(p)]
        paths.update(hits)
        if not hits and not pattern.endswith("?data"):
            missing.append(pattern)
    for extra in ("config.json", "config.yaml"):
        if extra in listing:
            paths.add(extra)
    return model_type, sorted(paths), missing


def plan(manifest: dict) -> tuple[dict, list[dict]]:
    from app import model_downloader as md
    from app.model_mapping import MODELS

    revisions = {r["repo"]: r["revision"] for r in manifest["repos"]}
    cards: dict[str, dict] = {}
    to_add: list[dict] = []
    known = {(f["repo"], f["path"]) for f in manifest["files"]}
    for info in MODELS:
        repo = info.canonical
        if repo not in revisions:
            continue
        load_id = info.onnx_load_id or repo
        quantization = md.effective_quantization(repo, md.quantization_for(info.compute_type))
        key = f"{load_id}|{quantization or ''}"
        revision = revisions[repo]
        listing = _listing(repo, revision)
        model_type, paths, missing = _needed(repo, revision, load_id, quantization, listing)
        if missing:
            raise SystemExit(f"{info.alias}: nothing in {repo} matches {missing} at {quantization}")
        cards[key] = {"repo": repo, "model_type": model_type, "files": paths}
        for path in paths:
            if (repo, path) not in known:
                known.add((repo, path))
                to_add.append({"repo": repo, "revision": revision, "path": path,
                               "size": listing[path], "aliases": info.alias})
    return cards, to_add


def _download(repo: str, revision: str, path: str, target: Path) -> str:
    url = f"{HF}/{repo}/resolve/{revision}/{urllib.parse.quote(path)}"
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def apply(manifest: dict, cards: dict, to_add: list[dict]) -> None:
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.environ["S3_REGION"],
        aws_access_key_id=os.environ["S3_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    )
    repos = {r["repo"]: r for r in manifest["repos"]}
    with tempfile.TemporaryDirectory() as tmp:
        for item in to_add:
            local = Path(tmp, "blob")
            print(f"fetch  {item['repo']}/{item['path']}  ({item['size'] / 1e6:.1f} MB)", flush=True)
            sha = _download(item["repo"], item["revision"], item["path"], local)
            if local.stat().st_size != item["size"]:
                raise SystemExit(f"size mismatch for {item['path']}")
            key = f"{PREFIX}/{item['repo']}/{item['path']}"
            client.upload_file(str(local), BUCKET, key)
            print(f"upload {key}", flush=True)
            local.unlink()
            aliases = repos[item["repo"]]["aliases"]
            manifest["files"].append({"repo": item["repo"], "revision": item["revision"],
                                      "aliases": aliases, "path": item["path"],
                                      "size": item["size"], "sha256": sha})
            repos[item["repo"]]["files"].append({"path": item["path"], "size": item["size"]})
    for repo in repos.values():
        repo["files"].sort(key=lambda f: f["path"])
    manifest["cards"] = dict(sorted(cards.items()))
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    client.put_object(Bucket=BUCKET, Key=f"{PREFIX}/manifest.json", Body=MANIFEST.read_bytes(),
                      ContentType="application/json", CacheControl="public, max-age=300")
    print("manifest written and uploaded")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="download, upload and write the manifest")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cards, to_add = plan(manifest)
    print(f"{len(cards)} card variants, {len(to_add)} files to add "
          f"({sum(i['size'] for i in to_add) / 1e9:.2f} GB)")
    for item in to_add:
        print(f"  + {item['repo']}/{item['path']}  {item['size'] / 1e6:.1f} MB  [{item['aliases']}]")
    if args.apply:
        apply(manifest, cards, to_add)
    else:
        print("plan only; pass --apply to upload")


if __name__ == "__main__":
    main()
