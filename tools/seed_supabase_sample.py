"""Seed one local story through the complete contribution API flow.

The script deliberately uses the application API instead of inserting rows
directly. This exercises authentication, consent, private creation, submission,
reviewer approval and local audio storage against the configured database.
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]


def login(base: str, email: str, *, admin: bool = False) -> dict:
    code_response = requests.post(
        base + "/api/auth/request-code",
        json={"email": email},
        timeout=20,
    )
    code_response.raise_for_status()
    code = code_response.json()["dev_code"]
    response = requests.post(
        base + "/api/auth/verify",
        json={"email": email, "code": code, "admin": admin},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--story-id", default="YL-001")
    parser.add_argument("--record-id", default="LOCAL-YL-001")
    args = parser.parse_args()

    data = json.loads((ROOT / "data/stories.json").read_text(encoding="utf-8"))
    story = next(
        (item for item in data["stories"] if item.get("id") == args.story_id),
        None,
    )
    if story is None:
        raise SystemExit(f"Unknown local story: {args.story_id}")

    author = login(args.base, "sample-contributor@voices.local")
    reviewer = login(args.base, "sample-reviewer@voices.local", admin=True)
    author_headers = {"Authorization": "Bearer " + author["token"]}
    reviewer_headers = {"Authorization": "Bearer " + reviewer["token"]}

    existing = requests.get(
        args.base + "/api/records",
        headers=reviewer_headers,
        timeout=20,
    )
    existing.raise_for_status()
    if any(
        item.get("id") == args.record_id
        for item in existing.json().get("records", [])
    ):
        print(f"{args.record_id} already exists; no duplicate was created")
        return

    policy = data["consentPolicyVersion"]
    consent = requests.post(
        args.base + "/api/consent",
        headers=author_headers,
        json={
            "targetId": args.record_id,
            "action": "recording-consent",
            "policyVersion": policy,
        },
        timeout=20,
    )
    consent.raise_for_status()

    transcript = "\n".join(
        str(segment.get("text") or "")
        for segment in story.get("segments", [])
        if str(segment.get("text") or "").strip()
    )
    audio_path = ROOT / "frontend" / str(story.get("audio") or "")
    audio_base64 = ""
    mime = "audio/wav"
    if story.get("audio") and audio_path.is_file():
        audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        if audio_path.suffix.lower() == ".m4a":
            mime = "audio/mp4"

    payload = {
        **story,
        "id": args.record_id,
        "createdAt": int(time.time() * 1000),
        "status": "done",
        "source": "local-fixture",
        "consentRef": policy,
        "rawText": transcript,
        "formalText": transcript,
        "mime": mime,
        "audioBase64": audio_base64,
    }
    created = requests.post(
        args.base + "/api/records",
        headers=author_headers,
        json=payload,
        timeout=90,
    )
    created.raise_for_status()

    submitted = requests.post(
        args.base + f"/api/contributions/{args.record_id}/submit",
        headers=author_headers,
        json={
            "transcriptConfirmed": True,
            "requestedScope": "public",
            "policyVersion": policy,
        },
        timeout=20,
    )
    submitted.raise_for_status()

    approved = requests.post(
        args.base + f"/api/contributions/{args.record_id}/review",
        headers=reviewer_headers,
        json={
            "approved": True,
            "approvedScope": "public",
            "note": "Local sample acceptance",
        },
        timeout=20,
    )
    approved.raise_for_status()
    result = approved.json()["record"]
    print(
        json.dumps(
            {
                "recordId": args.record_id,
                "scope": result.get("scope"),
                "reviewStatus": result.get("reviewStatus"),
                "hasAudio": bool(result.get("audioUrl")),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
