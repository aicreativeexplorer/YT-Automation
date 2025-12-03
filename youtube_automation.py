import json
import os
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import google.oauth2.credentials

API_BASE = os.environ.get(
    "YT_AUTOMATION_API_BASE",
    "https://yt-automation-mt1d.onrender.com",
)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_youtube_client():
    creds = None
    token_path = Path("token.json")
    if token_path.exists():
        creds = google.oauth2.credentials.Credentials.from_authorized_user_file(
            str(token_path), SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secret.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def generate_video_via_api(prompt: str, duration: int = 10, mode: str = "TEXT") -> Path:
    payload = {"prompt": prompt, "duration": duration, "mode": mode}
    r = requests.post(f"{API_BASE}/api/generate`, data=payload, timeout=60)
    r.raise_for_status()
    job = r.json()
    job_id = job["jobId"]

    while True:
        time.sleep(3)
        jr = requests.get(f"{API_BASE}/api/job/{job_id}", timeout=30)
        jr.raise_for_status()
        jd = jr.json()
        status = jd.get("status")
        if status in ("done", "error"):
            if status == "error":
                raise RuntimeError(f"Job {job_id} failed: {jd}")
            out_url = jd.get("outputUrl")
            if not out_url:
                raise RuntimeError(f"Job {job_id} done but no outputUrl")
            if out_url.startswith("/"):
                out_url = urljoin(API_BASE, out_url)

            resp = requests.get(out_url, stream=True, timeout=120)
            resp.raise_for_status()
            out_dir = Path("downloads")
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / f"{job_id}.mp4"
            with open(out_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return out_path


def upload_video_to_youtube(
    youtube,
    file_path: Path,
    title: str,
    description: str,
    tags=None,
    privacy_status="private",
):
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(file_path),
        chunksize=-1,
        resumable=True,
        mimetype="video/mp4",
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    print("Upload complete:", response.get("id"))
    return response


def main():
    plan_path = Path("content_plan.json")
    if not plan_path.exists():
        raise SystemExit("content_plan.json not found")

    with open(plan_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    youtube = get_youtube_client()

    for item in items:
        prompt = item.get("prompt", "")
        duration = int(item.get("duration", 10))
        mode = item.get("mode", "TEXT")
        title = item.get("title", prompt[:80] or "AI Short")
        description = item.get("description", "")
        tags = item.get("tags", [])
        privacy = item.get("privacyStatus", "private")

        print("=" * 60)
        print("Generating video for:", prompt)
        video_path = generate_video_via_api(prompt=prompt, duration=duration, mode=mode)
        print("Video saved at:", video_path)

        print("Uploading to YouTube...")
        upload_video_to_youtube(youtube, video_path, title, description, tags, privacy)

    print("All done.")


if __name__ == "__main__":
    main()
