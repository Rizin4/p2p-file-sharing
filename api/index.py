import os
import random
import string
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from supabase import Client, create_client


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_local_env() -> None:
    env_path = os.path.join(ROOT, ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


load_local_env()
app = Flask(
    __name__,
    template_folder=os.path.join(ROOT, "templates"),
    static_folder=os.path.join(ROOT, "static"),
    static_url_path="/static",
)
CORS(app)

BUCKET = "files"
EXPIRY_MINUTES = 5
SIGNED_URL_SECONDS = 120


def get_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def get_supabase_url() -> str:
    url = get_env("SUPABASE_URL").rstrip("/")
    for suffix in ("/rest/v1", "/storage/v1", "/auth/v1"):
        if url.endswith(suffix):
            return url[: -len(suffix)]
    return url


def get_supabase() -> Client:
    url = get_supabase_url()
    service_key = get_env("SUPABASE_SERVICE_KEY")
    if not url or not service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be configured")
    return create_client(url, service_key)


def gen_code() -> str:
    return "".join(random.choices(string.digits, k=6))


def parse_supabase_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    configured = all(
        get_env(name)
        for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY")
    )
    return jsonify({"ok": True, "configured": configured})


@app.route("/api/config")
def config():
    supabase_url = get_supabase_url()
    supabase_anon_key = get_env("SUPABASE_ANON_KEY")
    return jsonify(
        {
            "configured": bool(supabase_url and supabase_anon_key),
            "supabase_url": supabase_url,
            "supabase_anon_key": supabase_anon_key,
            "bucket": BUCKET,
            "expiry_seconds": EXPIRY_MINUTES * 60,
        }
    )


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "").strip()
    storage_path = data.get("storage_path", "").strip()

    if not filename or not storage_path:
        return jsonify({"error": "Missing filename or storage_path"}), 400

    supabase = get_supabase()

    for _ in range(5):
        code = gen_code()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=EXPIRY_MINUTES)
        ).isoformat()

        try:
            supabase.table("file_shares").insert(
                {
                    "code": code,
                    "filename": filename,
                    "storage_path": storage_path,
                    "expires_at": expires_at,
                }
            ).execute()
            return jsonify({"code": code, "expires_in": f"{EXPIRY_MINUTES} minutes"})
        except Exception:
            continue

    return jsonify({"error": "Failed to generate a unique code"}), 500


@app.route("/api/verify", methods=["POST"])
def verify():
    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()

    if not code.isdigit() or len(code) != 6:
        return jsonify({"error": "Enter a valid 6-digit code"}), 400

    supabase = get_supabase()
    result = supabase.table("file_shares").select("*").eq("code", code).execute()

    if not result.data:
        return jsonify({"error": "Invalid code"}), 404

    record = result.data[0]
    expires_at = parse_supabase_datetime(record["expires_at"])

    if datetime.now(timezone.utc) > expires_at:
        supabase.storage.from_(BUCKET).remove([record["storage_path"]])
        supabase.table("file_shares").delete().eq("code", code).execute()
        return jsonify({"error": "Code has expired. File deleted."}), 410

    signed = supabase.storage.from_(BUCKET).create_signed_url(
        record["storage_path"],
        SIGNED_URL_SECONDS,
        {"download": record["filename"]},
    )
    download_url = signed.get("signedURL") or signed.get("signed_url")

    if not download_url:
        return jsonify({"error": "Could not create a download link"}), 500

    return jsonify({"filename": record["filename"], "download_url": download_url})


@app.route("/api/cleanup", methods=["GET", "POST"])
def cleanup():
    supabase = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    expired = supabase.table("file_shares").select("*").lt("expires_at", now).execute()

    if not expired.data:
        return jsonify({"deleted": 0})

    paths = [record["storage_path"] for record in expired.data]
    supabase.storage.from_(BUCKET).remove(paths)
    supabase.table("file_shares").delete().lt("expires_at", now).execute()

    return jsonify({"deleted": len(paths)})
