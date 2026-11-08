# Lexi-VoiceModels

The text-to-speech models the [Lexi](https://github.com/skylerspaeth/Lexi) app downloads, hosted as a GitHub
release so the app needs no backend. Each is a copy of a model from
[sherpa-onnx's `tts-models` release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models), repacked as a
`.zip`. The [`models` release](../../releases/tag/models) lists where each one comes from and under what license.

## Why host them ourselves?

Lexi could download the models straight from sherpa-onnx, and at first it did. It stopped because of the format:

- **iOS can't unpack sherpa-onnx's archives.** They are `.tar.bz2`, and iOS has no bzip2 support (Apple's
  Compression framework offers LZ4, zlib, LZMA, LZFSE and a few others, but not bzip2). Reading them in the app took a
  C module map around the system `libbz2` plus a hand-written tar parser, which is a lot of code to review and keep
  for a one-off format problem.
- **Zip is already handled.** Lexi already depends on ZIPFoundation for `.lexideck` files, so a `.zip` unpacks with
  one call and no extra code. Repacking here once replaces that code in the app.
- **The license text travels with the model.** sherpa-onnx's Supertonic archive bundles only the MIT license of the
  model's sample code, not the model's own OpenRAIL-M license. The repacked zip adds it, and the release notes credit
  each model's source and license, which Lexi's voice picker also shows.
- **The app gets exactly what was checked.** Lexi only ships voices whose licenses were read and whose samples were
  listened to. Downloading from a copy we control means a model can't change under the app by surprise.

The model files themselves are not modified: a repacked zip holds the same files as the upstream archive, plus any
license file added. It is still static hosting, so Lexi needs no server of its own.

## Keeping it up to date

```bash
./mirror.py --check   # which models are missing or outdated
./mirror.py           # repack those, then print the `gh` command that publishes them
```

To mirror a new model, add its sherpa-onnx name to `models.txt` (after checking its license) and run `./mirror.py`.
Never delete anything from the release: older builds of the app still download the models they shipped with.
Needs python3 and [`gh`](https://cli.github.com).
