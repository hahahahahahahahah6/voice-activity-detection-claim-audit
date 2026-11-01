# Documentation claim auditor

An offline static audit tool that compares Markdown promises and denials with
Python AST fingerprints. Source files are parsed and never executed.

```sh
voice-activity-detection-claim-audit . --json
python3 -m voice_activity_detection_claim_audit . --verbose
```

The root README.md and Markdown files beneath a docs path component are scanned.
Fenced blocks are excluded; inline code counts. Matching normalizes case,
contractions, hyphens and whitespace. Negative phrases mask positive spans.
Symlinks are skipped. Fixtures, documentation and examples cannot supply source
evidence. Tests supply separate evidence. Invalid syntax supplies no evidence.
Imports alone are insufficient. Matching is module-local and respects local
shadowing; static fingerprints cannot prove runtime correctness or audio quality.

Supported source fingerprints:

```text
webrtcvad: .is_speech(...), with a module import
silero: .get_speech_timestamps(...) or get_speech_timestamps(...)
pyannote.audio.Pipeline.from_pretrained("pyannote/segmentation")
inaSpeechSegmenter.Segmenter(...)
any_object.get_speech_segments(...)
```

Findings use the following identifiers:

```text
documented-voice-activity-detection-claim-false HIGH
documented-voice-activity-detection-claim-false MEDIUM (test evidence only)
documented-no-voice-activity-detection-claim-false HIGH
```

Exit status is 0 when no finding reaches the threshold, 2 when one does, and 1
for usage or I/O errors. The default threshold is HIGH; use --fail-on MEDIUM to
fail on test-only evidence. JSON includes verdict, findings (rule_id, severity,
message), production_evidence and test_evidence. A verdict of FAIL indicates any
finding, even below the selected exit threshold. --ignore accepts repeatable
root-relative path prefixes. --verbose lists source evidence. --version prints
0.1.0. No network access is needed and the auditor writes no files.

```sh
python3 -m unittest discover
python3 -m build
```

Python 3.9 or newer is required. Distributed under the MIT license.
