import argparse
from pathlib import Path

import os
import certifi

os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["CURL_CA_BUNDLE"] = certifi.where()

from huggingface_hub import snapshot_download
from huggingface_hub.utils import configure_http_backend

DATASET_ID = "iisc-aim/UVH-26"
REVISION = "59f82c57821e8a54dc40bc1f42e83909dbad0b70"


def create_session():
    import requests
    session = requests.Session()
    session.verify = True
    return session


configure_http_backend(backend_factory=create_session)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the UVH-26 dataset."
    )
    parser.add_argument("--split", choices=("train", "val", "both"), default="train")
    parser.add_argument("--output", type=Path, default=Path("../data/datasets/uvh26"))
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--acknowledge-license", action="store_true")
    args = parser.parse_args()

    if not args.acknowledge_license:
        parser.error("Review the CC BY 4.0 license and pass --acknowledge-license")

    if not 1 <= args.max_workers <= 8:
        parser.error("--max-workers must be between 1 and 8")

    splits = ("train", "val") if args.split == "both" else (args.split,)
    patterns = ["README.md"]

    for split in splits:
        source_split = "Train" if split == "train" else "Val"
        patterns.extend([
            f"UVH-26-{source_split}/UVH-26-MV-{source_split}.json",
            f"UVH-26-{source_split}/UVH-26-ST-{source_split}.json",
            f"UVH-26-{source_split}/data/**/*.png",
        ])

    path = snapshot_download(
        repo_id=DATASET_ID,
        repo_type="dataset",
        revision=REVISION,
        allow_patterns=patterns,
        local_dir=str(args.output.resolve()),
        max_workers=args.max_workers,
    )

    print(f"Downloaded publisher files to {Path(path).resolve()}")
    print("Source revision:", REVISION)
    print("Review the dataset license and attribution before redistribution.")


if __name__ == "__main__":
    main()
