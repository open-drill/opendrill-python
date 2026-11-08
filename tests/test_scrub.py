"""The packaged example must not carry the original script's field identifiers.

The identifiers are stored as SHA-256 digests of their lower-cased text, so
this test does not itself publish them. Single words and adjacent word pairs
in each file are hashed and compared.
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {Path("tests/test_scrub.py")}
NEEDLE_DIGESTS = {
    "22be80bf08f4c8d511f219033f64adf0e02c5d81550d29cdf2289f02b541c02f",
    "9a188c541fced1c400d098e3d1bcf1f48bc1238b386a70182b5a54a6bd5d37fd",
    "318025a35af2fe119fe2ea71e14b28baebff2cf8d6aebbf1e4be606ace32a583",
    "3ee42283fd55018a96460a3645121c4da64a1b61cb0b1218a07d82c33b13958f",
    "27c32866c794864b8a2a2e952ec0bc1155067b387856d3e0b4ed8b84334656b5",
    "6292a8b0e7a5d9fb39729f90c6fcbf176ac0968ef97ed610c44cd72e31795820",
    "21d1b0c05484be6b0ff6197394ffcdce01ec7e12fdd0fc8e6c379c7097b28da5",
}
TOKEN = re.compile(r"[A-Za-z0-9/-]+")


def _digest(text: str) -> str:
    return hashlib.sha256(text.lower().encode()).hexdigest()


def _hits(text: str) -> set[str]:
    tokens = TOKEN.findall(text)
    candidates = set(tokens) | {f"{a} {b}" for a, b in zip(tokens, tokens[1:])}
    return {c for c in candidates if _digest(c) in NEEDLE_DIGESTS}


def test_repository_text_does_not_repeat_the_original_example_identifiers():
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0] in {".git", ".venv", "dist", "build", "__pycache__"}:
            continue
        if relative in SKIP or path.suffix not in {".py", ".md", ".json", ".toml", ".yml", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders.extend(f"{relative}: {hit}" for hit in sorted(_hits(text)))
    assert offenders == []


def test_the_scan_still_catches_a_planted_identifier(tmp_path):
    planted = "".join(map(chr, [70, 111, 117, 110, 100, 101, 120]))
    assert _hits(f"Drilled by {planted} Ltd.")
