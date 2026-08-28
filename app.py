"""
Trace Dispatch - 24/7 Cloud Audio Stream Slicer & Voice Activity Daemon
Runs on Hugging Face Spaces (Gradio SDK - 100% Free CPU Basic).
Continuously ingests Broadcastify dispatch audio, isolates voice activity via VAD,
and indexes .mp3 transmission clips into Supabase Storage & Database 24/7.
"""

import os
import sys
import threading
import time
from datetime import datetime, timezone
import gradio as gr
from dotenv import load_dotenv

# Load local environment if present
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path=dotenv_path, override=True)

import slicer

# ==============================================================================
# 24/7 Slicer Background Worker Thread
# ==============================================================================
worker_status = {
    "state": "INITIALIZING",
    "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "stream_url": os.getenv("STREAM_URL", slicer.STREAM_URL),
    "supabase_url": os.getenv("SUPABASE_URL", slicer.SUPABASE_URL),
    "error": None
}


def run_slicer_daemon():
    """Runs the 24/7 audio stream listener continuously in the background."""
    print("\n[CLOUD LAUNCHER] Starting 24/7 radio stream listener background worker...")
    worker_status["state"] = "RUNNING"

    uploader = slicer.DispatchUploader(
        url=worker_status["supabase_url"],
        key=os.getenv("SUPABASE_KEY", slicer.SUPABASE_KEY),
        bucket=slicer.STORAGE_BUCKET,
        table=slicer.TABLE_NAME
    )

    stream_worker = slicer.StreamSlicer(
        stream_url=worker_status["stream_url"],
        uploader=uploader,
        silence_threshold_dbfs=float(os.getenv("SILENCE_THRESHOLD_DBFS", str(slicer.SILENCE_THRESHOLD_DBFS))),
        silence_duration_sec=float(os.getenv("SILENCE_DURATION_SEC", str(slicer.SILENCE_DURATION_SEC))),
        pre_roll_duration_sec=float(os.getenv("PRE_ROLL_DURATION_SEC", str(slicer.PRE_ROLL_DURATION_SEC))),
        min_clip_duration_sec=float(os.getenv("MIN_CLIP_DURATION_SEC", str(slicer.MIN_CLIP_DURATION_SEC))),
        max_clip_duration_sec=float(os.getenv("MAX_CLIP_DURATION_SEC", str(slicer.MAX_CLIP_DURATION_SEC)))
    )

    try:
        stream_worker.run()
    except Exception as e:
        print(f"[CLOUD LAUNCHER ERROR] Slicer worker error: {e}", file=sys.stderr)
        worker_status["state"] = "ERROR"
        worker_status["error"] = str(e)


# Start background stream listener immediately
listener_thread = threading.Thread(target=run_slicer_daemon, daemon=True)
listener_thread.start()


# ==============================================================================
# Hugging Face Gradio Status Interface
# ==============================================================================
def get_worker_status_markdown():
    return f"""
### 🟢 Trace Dispatch Slicer is Active (24/7 Cloud Worker)

- **Worker State**: `{worker_status['state']}`
- **Started At**: `{worker_status['started_at']}`
- **Target Stream**: `{worker_status['stream_url'][:60]}...`
- **Supabase Target**: `{worker_status['supabase_url']}`
- **Retention Purge**: Automatic 7-day auto-purge daemon active

---
### 🌐 Accessing the Frontend
Open your **GitHub Pages** dashboard to view live radio dispatches, play audio, and transcribe in real-time.
"""

with gr.Blocks(title="Trace Dispatch - 24/7 Cloud Worker") as demo:
    gr.Markdown("# 📻 Trace Dispatch — 24/7 Emergency Audio Ingestion Daemon")
    status_output = gr.Markdown(get_worker_status_markdown())
    refresh_btn = gr.Button("🔄 Refresh Worker Status")
    refresh_btn.click(fn=get_worker_status_markdown, outputs=status_output)

# Standard Gradio launch (works seamlessly with Hugging Face Spaces port binding)
if __name__ == "__main__":
    demo.launch()
