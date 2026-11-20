"""Reproduce two known publication findings with temporary synthetic data.

Run: python -X utf8 tools/verify/publication_findings.py

This is a diagnostic, not a release acceptance suite. Exit 0 means the two
reported defects DID reproduce. A fixed implementation should stop reproducing
them; replace these expectations with acceptance assertions when fixing them.
No live database, speech, language-model or object-storage service is used.
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(detail)


def synthetic_wav(sample: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(bytes([sample, 0]) * 8000)
    return buffer.getvalue()


def main() -> None:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    print("Diagnostic source HEAD: " + head, flush=True)
    print("Exit 0 means known defects reproduced; it does not mean release acceptance.", flush=True)
    with tempfile.TemporaryDirectory(prefix="vtn-publication-findings-") as tmp:
        temporary = Path(tmp)
        for name in (
            "DATABASE_URL", "SUPABASE_DB_URL", "VTN_DATABASE_URL", "GEMINI_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
        ):
            os.environ.pop(name, None)
        os.environ.update(
            VTN_ENV_FILE=str(temporary / "missing.env"),
            VTN_DATABASE_REQUIRED="0",
            VTN_DB_PATH=str(temporary / "records.db"),
            VTN_LAB_DB=str(temporary / "lab.db"),
            VTN_RECORDS_DIR=str(temporary / "audio"),
            VTN_DATA_DIR=str(temporary / "data"),
            VTN_STORY_DATA=str(ROOT / "data" / "stories.json"),
            VTN_DEMO_AUTH="1",
            VTN_DEMO_ALLOW_ADMIN="1",
            VTN_ADMIN_EMAILS="",
            VTN_RECORDS_TOKEN="",
            VTN_SECRET="publication-findings-local-only",
            GOOGLE_APPLICATION_CREDENTIALS=str(temporary / "missing-google.json"),
        )
        from fastapi.testclient import TestClient
        import server

        with TestClient(server.app) as client:
            def identity(name: str, admin: bool = False) -> dict:
                response = client.post("/api/auth/verify", json={
                    "school_id": name, "password": "synthetic-password", "admin": admin,
                })
                response.raise_for_status()
                return {"Authorization": "Bearer " + response.json()["token"]}

            owner = identity("publication-diagnostic-owner")
            other = identity("publication-diagnostic-other")
            reviewer = identity("publication-diagnostic-reviewer", admin=True)
            policy = server.load_data()["consentPolicyVersion"]

            def create_and_approve(rid: str, controls: bool = False) -> tuple[dict, dict]:
                payload = {
                    "id": rid, "status": "done", "source": "live",
                    "title": "Synthetic approved contribution",
                    "formalText": "Synthetic approved original.",
                    "rawText": "Synthetic approved original.",
                    "durationSec": 1, "consentRef": policy,
                    "contributionFlow": True, "requestedScope": "public", "scope": "public",
                    "mime": "audio/wav",
                    "audioBase64": base64.b64encode(synthetic_wav(0)).decode("ascii"),
                    "location": {"area": "Yuen Long", "lat": 22.4445,
                                 "lng": 114.015, "radiusM": 800},
                }
                created = client.post("/api/records", headers=owner, json=payload)
                created.raise_for_status()
                require(created.json()["record"]["scope"] == "private", "Creation must be private")
                if controls:
                    guest = client.post("/api/records", json=payload)
                    nonowner = client.post("/api/records", headers=other, json=payload)
                    require(guest.status_code == 403 and nonowner.status_code == 403,
                            "Management-denial controls did not hold")
                    print("CONTROL management denial " + json.dumps({
                        "unauthenticated_post": guest.status_code,
                        "other_member_post": nonowner.status_code,
                    }, sort_keys=True), flush=True)
                submitted = client.post(f"/api/contributions/{rid}/submit", headers=owner, json={
                    "transcriptConfirmed": True, "requestedScope": "public", "policyVersion": policy,
                })
                submitted.raise_for_status()
                approved = client.post(f"/api/contributions/{rid}/review", headers=reviewer, json={
                    "approved": True, "approvedScope": "public", "note": "Original content only",
                })
                approved.raise_for_status()
                record = approved.json()["record"]
                require(record["scope"] == "public" and record["reviewStatus"] == "approved",
                        "Fixture did not reach approved public state")
                return payload, record

            rid = "DIAGNOSTIC-CONTENT"
            original, approval = create_and_approve(rid, controls=True)
            new_audio = synthetic_wav(1)
            replacement = dict(
                original, title="Unreviewed replacement",
                formalText="Unreviewed replacement transcript.",
                rawText="Unreviewed replacement transcript.",
                segments=[{"start": 0, "end": 1, "text": "Unreviewed replacement transcript.",
                           "keywords": ["reviewescape"]}],
                audioBase64=base64.b64encode(new_audio).decode("ascii"),
            )
            updated = client.post("/api/records", headers=owner, json=replacement)
            updated.raise_for_status()
            record = updated.json()["record"]
            guest_record = client.get(f"/api/records/{rid}")
            guest_audio = client.get(f"/api/records/{rid}/audio")
            catalogue = client.get("/api/stories")
            catalogue.raise_for_status()
            story = next((s for s in catalogue.json()["stories"] if s["id"] == rid), None)
            answer = client.post("/api/ask-village", json={
                "question": "reviewescape", "storyIds": [rid],
            })
            answer.raise_for_status()
            answer = answer.json()
            content_observed = {
                "owner_post": updated.status_code,
                "returned_scope": record.get("scope"),
                "returned_reviewStatus": record.get("reviewStatus"),
                "original_review_preserved": record.get("reviewedAt") == approval.get("reviewedAt")
                and record.get("reviewedBy") == approval.get("reviewedBy"),
                "guest_record": guest_record.status_code,
                "guest_receives_replacement_text": guest_record.status_code == 200
                and guest_record.json().get("formalText") == replacement["formalText"],
                "guest_audio": guest_audio.status_code,
                "guest_receives_replacement_audio": guest_audio.content == new_audio,
                "catalogue_receives_replacement_text": story is not None
                and story["segments"][0]["text"] == replacement["formalText"],
                "ask_inScope": answer.get("inScope"),
                "ask_receives_replacement_text": answer.get("answer") == replacement["formalText"],
                "ask_citation_start": (answer.get("sources") or [{}])[0].get("start"),
            }
            print("OBSERVED P1 approved-content replacement " + json.dumps(content_observed, sort_keys=True),
                  flush=True)
            require(
                content_observed["returned_scope"] == "public"
                and content_observed["returned_reviewStatus"] == "approved"
                and all(content_observed[key] is True for key in (
                    "original_review_preserved", "guest_receives_replacement_text",
                    "guest_receives_replacement_audio", "catalogue_receives_replacement_text",
                    "ask_inScope", "ask_receives_replacement_text",
                )) and content_observed["ask_citation_start"] == 0,
                "Approved-content finding no longer reproduces exactly; assess fixed acceptance behavior",
            )
            print("REPRODUCED P1: owner replaced approved public text/audio without renewed review.", flush=True)
            print("EXPECTED AFTER FIX: reject content replacement or require review before exposing replacement.",
                  flush=True)

            rid = "DIAGNOSTIC-NARROWING"
            _original, approval = create_and_approve(rid)
            private = dict(approval, scope="private", requestedScope="private")
            private.pop("audioUrl", None)
            narrowed = client.post("/api/records", headers=owner, json=private)
            narrowed.raise_for_status()
            record = narrowed.json()["record"]
            catalogue = client.get("/api/stories")
            catalogue.raise_for_status()
            narrowing_observed = {
                "requested_scope": "private",
                "owner_post": narrowed.status_code,
                "returned_scope": record.get("scope"),
                "returned_requestedScope": record.get("requestedScope"),
                "returned_reviewStatus": record.get("reviewStatus"),
                "guest_record": client.get(f"/api/records/{rid}").status_code,
                "guest_audio": client.get(f"/api/records/{rid}/audio").status_code,
                "still_in_guest_catalogue": rid in catalogue.json()["visibleIds"],
            }
            print("OBSERVED P1 privacy narrowing " + json.dumps(narrowing_observed, sort_keys=True), flush=True)
            require(
                narrowing_observed["returned_scope"] == "public"
                and narrowing_observed["returned_requestedScope"] == "public"
                and narrowing_observed["returned_reviewStatus"] == "approved"
                and narrowing_observed["guest_record"] == 200
                and narrowing_observed["guest_audio"] == 200
                and narrowing_observed["still_in_guest_catalogue"] is True,
                "Privacy-narrowing finding no longer reproduces exactly; assess fixed acceptance behavior",
            )
            print("REPRODUCED P1: successful private-scope request left record/audio publicly available.",
                  flush=True)
            print("EXPECTED AFTER FIX: successful narrowing removes guest record/audio/catalogue access; "
                  "unsupported changes must not falsely report success.", flush=True)
    print("DIAGNOSTIC COMPLETE: 2 known P1 findings reproduced; this is not a release-pass result.", flush=True)


if __name__ == "__main__":
    main()
