#!/usr/bin/env python3
"""Keeps Lexi's mirror of the voice models up to date.

The Lexi app downloads each voice model from the `models` release of this
repository (`VoicePack.mirrorBaseURL` in the app). Every model there is a copy of
one sherpa-onnx publishes in its `tts-models` release, repacked as a `.zip`
(iOS can unpack zips, but not the `.tar.bz2` sherpa-onnx uses) with its license
files added. The release also carries `manifest.json` (what was mirrored, and
from which upstream file) and `CREDITS.md` (where each model comes from and
under what terms), which is the release's description too.

    ./mirror.py --check          # what is missing or outdated
    ./mirror.py                  # repack those and print the publish command
    ./mirror.py --force [id ...] # repack these (or all) regardless

The models to mirror are listed in `models.txt`: add a line when the app's voice
catalog gains a model, after checking its license. A model is outdated when the
sha256 GitHub reports for the upstream file differs from the one it was mirrored
from. Nothing is ever removed from the mirror, because older builds of the app
still download the models they shipped with.

Needs network access and python3, and `gh` (https://cli.github.com) to publish.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models.txt"
MIRROR_REPO = "skylerspaeth/Lexi-VoiceModels"
MIRROR_TAG = "models"
UPSTREAM_API = "https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/tags/tts-models"
UPSTREAM_DOWNLOAD = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models"

# Where each kind of model comes from, and the license text that sherpa-onnx's
# archive leaves out (if any). Piper voices describe themselves in their MODEL_CARD.
KOKORO = {
    "source": "https://huggingface.co/hexgrad/Kokoro-82M",
    "license": "Apache-2.0",
}
SUPERTONIC = {
    "source": "https://huggingface.co/Supertone/supertonic-3",
    "license": "OpenRAIL-M",
    # The archive's own LICENSE is the MIT license of Supertonic's sample code, not the model's.
    "licenseText": "https://huggingface.co/Supertone/supertonic-3/raw/main/LICENSE",
}


def mirror_base_url():
    return f"https://github.com/{MIRROR_REPO}/releases/download/{MIRROR_TAG}"


def listed_model_ids():
    return [line.strip() for line in MODELS.read_text(encoding="utf-8").splitlines() if line.strip()]


def fetch(url):
    with urllib.request.urlopen(url) as response:
        return response.read()


def upstream_digests():
    """{model id: (sha256, updated_at)} for every archive sherpa-onnx publishes."""
    assets = json.loads(fetch(UPSTREAM_API))["assets"]
    return {
        a["name"].removesuffix(".tar.bz2"): (a["digest"].removeprefix("sha256:"), a["updated_at"])
        for a in assets
        if a["name"].endswith(".tar.bz2") and a.get("digest")
    }


def mirrored_manifest():
    try:
        return json.loads(fetch(f"{mirror_base_url()}/manifest.json"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {}
        raise


def status(model_id, manifest, upstream):
    if model_id not in upstream:
        return "gone upstream"
    if model_id not in manifest:
        return "missing"
    if manifest[model_id]["upstreamSHA256"] != upstream[model_id][0]:
        return "outdated"
    return "current"


def download(url, destination):
    digest = hashlib.sha256()
    with urllib.request.urlopen(url) as response, open(destination, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def piper_details(model_dir):
    """The dataset and license a Piper voice states in its MODEL_CARD."""
    card = (model_dir / "MODEL_CARD").read_text(encoding="utf-8")
    return {
        "source": re.search(r"URL:\s*(\S+)", card).group(1),
        "license": re.search(r"License:\s*(.+)", card).group(1).strip(),
    }


def repack(model_id, upstream_sha, out):
    """Downloads one model, checks it against GitHub's digest, and writes it
    to `out` as `<model id>.zip`. Returns its manifest entry."""
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        archive = scratch / "model.tar.bz2"
        if download(f"{UPSTREAM_DOWNLOAD}/{model_id}.tar.bz2", archive) != upstream_sha:
            sys.exit(f"{model_id}: the download does not match the sha256 GitHub reports")
        with tarfile.open(archive) as tar:
            tar.extractall(scratch / "extracted", filter="data")
        model_dir = scratch / "extracted" / model_id

        if model_id.startswith("kokoro"):
            details = dict(KOKORO)
        elif "supertonic" in model_id:
            details = dict(SUPERTONIC)
            (model_dir / "LICENSE-model").write_bytes(fetch(details.pop("licenseText")))
        else:
            details = piper_details(model_dir)

        zip_path = out / f"{model_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for path in sorted(model_dir.rglob("*")):
                if path.is_file():
                    zip_file.write(path, path.relative_to(model_dir.parent))

    return {
        **details,
        "bytes": zip_path.stat().st_size,
        "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "upstreamSHA256": upstream_sha,
    }


CREDITS_HEADER = """\
# Lexi voice models

The text-to-speech models the Lexi app downloads. Each is a copy of a model published in
[sherpa-onnx's `tts-models` release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models),
repacked as a `.zip` because iOS cannot unpack `.tar.bz2`. The model files themselves are unchanged. The
license files that came with each model are included in its zip, along with the model's own license text
where sherpa-onnx's archive omitted it. `manifest.json` records what each zip was made from.

Notes that apply to the models below:

- Piper and Kokoro models include data from [espeak-ng](https://github.com/espeak-ng/espeak-ng), which is
  licensed under GPL-3.0-or-later.
- Supertonic is released under the OpenRAIL-M license, which carries use restrictions that anyone who passes
  the model on must also pass on, and requires machine-generated content to be disclosed as such. Read
  `LICENSE-model` inside its zip.

| Model | Made by / dataset | License | Size |
| --- | --- | --- | --- |
"""


def credits(manifest):
    rows = [
        f"| `{model_id}` | {entry['source']} | {entry['license']} | {entry['bytes'] // 1_000_000} MB |\n"
        for model_id, entry in sorted(manifest.items())
    ]
    return CREDITS_HEADER + "".join(rows)


def main():
    parser = argparse.ArgumentParser(description="Keep the Lexi voice model mirror up to date.")
    parser.add_argument("--check", action="store_true", help="only report what is missing or outdated")
    parser.add_argument("--force", action="store_true", help="repack even models that are current")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "lexi-voice-models")
    parser.add_argument("models", nargs="*", help="limit to these model ids")
    args = parser.parse_args()

    wanted = args.models or listed_model_ids()
    manifest = mirrored_manifest()
    upstream = upstream_digests()

    statuses = {model_id: status(model_id, manifest, upstream) for model_id in wanted}
    for model_id, state in statuses.items():
        print(f"{state:>13}  {model_id}")
    todo = [m for m, s in statuses.items() if s in ("missing", "outdated") or (args.force and s != "gone upstream")]

    if args.check:
        sys.exit(1 if todo or "gone upstream" in statuses.values() else 0)
    if not todo:
        print("Nothing to do.")
        return

    shutil.rmtree(args.out, ignore_errors=True)
    args.out.mkdir(parents=True)
    for model_id in todo:
        print(f"Repacking {model_id}...")
        manifest[model_id] = repack(model_id, upstream[model_id][0], args.out)

    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (args.out / "CREDITS.md").write_text(credits(manifest))

    repo, tag = MIRROR_REPO, MIRROR_TAG
    print(f"\nWrote {args.out}. To publish (the repository must exist):\n")
    print(
        f"gh release view {tag} --repo {repo} >/dev/null 2>&1 \\\n"
        f"  && {{ gh release upload {tag} --repo {repo} --clobber {args.out}/*; "
        f"gh release edit {tag} --repo {repo} --notes-file {args.out}/CREDITS.md; }} \\\n"
        f'  || gh release create {tag} --repo {repo} --title "Voice models" '
        f"--notes-file {args.out}/CREDITS.md {args.out}/*"
    )


if __name__ == "__main__":
    main()
