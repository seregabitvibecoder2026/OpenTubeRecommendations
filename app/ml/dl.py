"""Download helper, run as a subprocess (so the Stop button can kill it):
    python -m app.ml.dl snapshot <repo> <local_dir>
    python -m app.ml.dl file <repo> <filename> <local_dir>
    python -m app.ml.dl list <repo>
Only contacts huggingface.co. Telemetry disabled."""
from __future__ import annotations

import json
import os
import sys

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ.pop("HF_HUB_OFFLINE", None)

SKIP = ["onnx/*", "openvino/*", "*.onnx", "*.h5", "*.msgpack", "*.ot", "tf_model*", "flax_model*",
        "rust_model*", "coreml/*", "*.mlmodel", "*.tflite"]


def main(argv: list[str]) -> int:
    from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    cmd = argv[0]
    if cmd == "list":
        files = [(s.rfilename, s.size) for s in HfApi().model_info(argv[1], files_metadata=True).siblings]
        print(json.dumps(files))
        return 0
    if cmd == "snapshot":
        repo, local = argv[1], argv[2]
        files = [s.rfilename for s in HfApi().model_info(repo).siblings]
        skip = list(SKIP)
        if any(f.endswith(".safetensors") for f in files):
            skip += ["*.bin", "*.pt"]
        snapshot_download(repo, local_dir=local, ignore_patterns=skip)
        print("OK")
        return 0
    if cmd == "file":
        repo, fn, local = argv[1], argv[2], argv[3]
        hf_hub_download(repo, fn, local_dir=local)
        print("OK")
        return 0
    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
