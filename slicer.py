#!/usr/bin/env python3
"""
Trace Dispatch - Continuous Audio Stream Slicer, Voice Activity Indexer & 7-Day Auto-Purge Daemon
Streams live radio/dispatch audio (HLS .m3u8, direct HTTP, or local files), isolates voice activity
via dBFS thresholding, automatically uploads sliced .mp3 transmission clips to Supabase Storage & DB,
broadcasts live recording/monitoring states to the web UI in real-time, and runs backend retention purges.
"""

import os
import sys
import time
import uuid
import math
import io
import signal
import socket
import logging
import argparse
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional, Deque, Set

# Ensure UTF-8 stdout on Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv

# Load environment variables from .env located in the same directory as this script
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path=dotenv_path, override=True)

# Third-party imports
try:
    from pydub import AudioSegment
    from pydub.utils import which
except ImportError:
    print("[ERROR] pydub is required. Run: pip install -r requirements.txt")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("[ERROR] requests is required. Run: pip install -r requirements.txt")
    sys.exit(1)

try:
    from supabase import create_client, Client
except ImportError:
    print("[ERROR] supabase is required. Run: pip install -r requirements.txt")
    sys.exit(1)


# ==============================================================================
# Configuration & Defaults
# ==============================================================================
STREAM_URL = os.getenv("STREAM_URL", "https://hls-o1.broadcastify.com/s0/feed/46604/playlist.m3u8")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://uquhzylwnzprokmqadno.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
STORAGE_BUCKET = "dispatch-clips"
TABLE_NAME = "dispatches"

# Voice Activity Detection (VAD) Parameters
SILENCE_THRESHOLD_DBFS = float(os.getenv("SILENCE_THRESHOLD_DBFS", "-36.0"))
SILENCE_DURATION_SEC = float(os.getenv("SILENCE_DURATION_SEC", "2.5"))
PRE_ROLL_DURATION_SEC = float(os.getenv("PRE_ROLL_DURATION_SEC", "0.6"))
MIN_CLIP_DURATION_SEC = float(os.getenv("MIN_CLIP_DURATION_SEC", "1.2"))
MAX_CLIP_DURATION_SEC = float(os.getenv("MAX_CLIP_DURATION_SEC", "90.0"))

# Retention Setting: 7 days default
RETENTION_DAYS = 7
CLEANUP_INTERVAL_SEC = 3600  # Check for expired clips every hour

# Chunk size for PCM streaming analysis: 200ms (0.2s) slices
CHUNK_DURATION_MS = 200
SAMPLE_RATE = 22050
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM = 2 bytes per sample
FRAMES_PER_CHUNK = int(SAMPLE_RATE * (CHUNK_DURATION_MS / 1000.0))
BYTES_PER_CHUNK = FRAMES_PER_CHUNK * SAMPLE_WIDTH * CHANNELS

# Standard HTTP headers for protected stream feeds
STREAM_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.broadcastify.com/listen/feed/46604",
    "Origin": "https://www.broadcastify.com"
}

_lock_socket = None


def ensure_single_instance(port: int = 46604):
    """Guarantees only ONE slicer instance runs at a time to prevent duplicate uploads."""
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.bind(("127.0.0.1", port))
        _lock_socket.listen(1)
        return True
    except (socket.error, OSError):
        print("\n[INFO] Another instance of Trace Dispatch slicer is already running in the background.")
        print("[INFO] Exiting this process to prevent duplicate clip uploads.\n")
        sys.exit(0)


# ==============================================================================
# Visual Console Logger
# ==============================================================================
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def log(tag: str, message: str, color: str = Colors.CYAN):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{Colors.DIM}[{ts}]{Colors.RESET} {color}{Colors.BOLD}[{tag}]{Colors.RESET} {message}")


def render_dbfs_meter(dbfs: float, threshold: float, is_active: bool) -> str:
    """Generates an ASCII energy meter for terminal monitoring."""
    clamped_db = max(-60.0, min(0.0, dbfs))
    ratio = (clamped_db + 60.0) / 60.0
    bar_len = int(ratio * 20)
    thresh_ratio = (max(-60.0, min(0.0, threshold)) + 60.0) / 60.0
    thresh_pos = int(thresh_ratio * 20)

    chars = []
    for i in range(20):
        if i == thresh_pos:
            chars.append("|")
        elif i < bar_len:
            chars.append("■")
        else:
            chars.append("·")

    meter_str = "".join(chars)
    state_color = Colors.GREEN if is_active else Colors.DIM
    val_str = f"{dbfs:5.1f} dBFS"
    state_tag = f"{Colors.YELLOW}[VOICE ACTIVE]{Colors.RESET}" if is_active else f"{Colors.DIM}[MONITORING ]{Colors.RESET}"
    return f"{state_color}[{meter_str}]{Colors.RESET} {val_str} {state_tag}"


# ==============================================================================
# Supabase Dispatch Uploader & Realtime Status Broadcaster
# ==============================================================================
class DispatchUploader:
    def __init__(self, url: str, key: str, bucket: str = STORAGE_BUCKET, table: str = TABLE_NAME, dry_run: bool = False):
        self.url = url
        self.key = key
        self.dry_run = dry_run
        self.bucket = bucket
        self.table = table
        self.client: Optional[Client] = None
        self.has_saved_column = True

        if self.dry_run:
            log("STORAGE", "Running in DRY-RUN mode. Clips will not be uploaded to Supabase.", Colors.YELLOW)
            return

        if not url or not key:
            log("STORAGE", "SUPABASE_URL or SUPABASE_KEY missing in environment. Running in mock/dry-run mode.", Colors.YELLOW)
            self.dry_run = True
            return

        try:
            self.client = create_client(url, key)
            log("STORAGE", f"Supabase client initialized ({url})", Colors.GREEN)
            self.purge_expired_clips(days=RETENTION_DAYS)
        except Exception as e:
            log("ERROR", f"Failed to initialize Supabase client: {e}", Colors.RED)
            self.dry_run = True

    def broadcast_status(self, state: str, dbfs: float = -90.0, duration: float = 0.0):
        """Broadcasts live VAD state ('RECORDING' vs 'MONITORING' vs 'IDLE') to the web UI in real-time."""
        if not self.url or not self.key or self.dry_run:
            return

        try:
            endpoint = f"{self.url}/realtime/v1/api/broadcast"
            payload = {
                "messages": [
                    {
                        "topic": "realtime:stream_status",
                        "event": "vad_state",
                        "payload": {
                            "state": state,
                            "dbfs": round(dbfs, 1),
                            "duration": round(duration, 1),
                            "timestamp": time.time()
                        }
                    }
                ]
            }
            headers = {
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json"
            }
            requests.post(endpoint, json=payload, headers=headers, timeout=1.5)
        except Exception:
            pass

    def upload_clip(self, mp3_bytes: bytes, duration_sec: float) -> Optional[dict]:
        """Uploads .mp3 clip to Supabase Storage bucket and inserts a database row."""
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        filename = f"dispatch_{timestamp_str}_{unique_id}.mp3"
        storage_path = f"audio/{filename}"

        if self.dry_run or not self.client:
            log("MOCK UPLOAD", f"Saved {filename} ({duration_sec:.1f}s, {len(mp3_bytes):,} bytes)", Colors.YELLOW)
            return {
                "id": str(uuid.uuid4()),
                "audio_url": f"https://mock-storage.local/{storage_path}",
                "duration": round(duration_sec, 2),
                "transcribed": False,
                "saved": False,
                "created_at": datetime.now(timezone.utc).isoformat()
            }

        try:
            # 1. Upload to Storage Bucket
            log("UPLOAD", f"Uploading {filename} to '{self.bucket}' bucket...", Colors.CYAN)
            self.client.storage.from_(self.bucket).upload(
                path=storage_path,
                file=mp3_bytes,
                file_options={"content-type": "audio/mpeg", "x-upsert": "true"}
            )

            # 2. Get Public URL
            public_url = self.client.storage.from_(self.bucket).get_public_url(storage_path)

            # 3. Insert record into Supabase table
            payload = {
                "audio_url": public_url,
                "duration": round(duration_sec, 2),
                "transcribed": False
            }
            if self.has_saved_column:
                payload["saved"] = False

            try:
                db_res = self.client.table(self.table).insert(payload).execute()
            except Exception as insert_err:
                if "saved" in str(insert_err):
                    self.has_saved_column = False
                    payload.pop("saved", None)
                    db_res = self.client.table(self.table).insert(payload).execute()
                else:
                    raise insert_err

            inserted_data = db_res.data[0] if db_res.data else payload
            log("SAVED", f"Clip indexed: ID={inserted_data.get('id', 'ok')} | {public_url}", Colors.GREEN)
            return inserted_data

        except Exception as e:
            log("ERROR", f"Supabase upload/insert failed: {e}", Colors.RED)
            return None

    def purge_expired_clips(self, days: int = RETENTION_DAYS):
        """Backend Retention Job: Deletes clips older than 7 days unless explicitly saved."""
        if self.dry_run or not self.client:
            return

        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        log("RETENTION", f"Checking for unsaved clips older than {days} days (before {cutoff_date[:10]})...", Colors.BLUE)

        try:
            try:
                expired_res = self.client.table(self.table).select("id, audio_url, created_at").lt("created_at", cutoff_date).eq("saved", False).execute()
            except Exception as query_err:
                if "saved" in str(query_err):
                    expired_res = self.client.table(self.table).select("id, audio_url, created_at").lt("created_at", cutoff_date).execute()
                else:
                    raise query_err

            expired_clips = expired_res.data or []
            if not expired_clips:
                log("RETENTION", "No expired clips found. Storage is up to date.", Colors.DIM)
                return

            log("RETENTION", f"Purging {len(expired_clips)} expired audio clips...", Colors.YELLOW)
            storage_paths_to_delete = []
            ids_to_delete = []

            for clip in expired_clips:
                ids_to_delete.append(clip["id"])
                audio_url = clip.get("audio_url", "")
                if f"/{self.bucket}/" in audio_url:
                    path = audio_url.split(f"/{self.bucket}/")[-1]
                    storage_paths_to_delete.append(path)

            if storage_paths_to_delete:
                try:
                    self.client.storage.from_(self.bucket).remove(storage_paths_to_delete)
                except Exception as s_err:
                    log("ERROR", f"Storage removal warning: {s_err}", Colors.RED)

            for cid in ids_to_delete:
                self.client.table(self.table).delete().eq("id", cid).execute()

            log("RETENTION", f"Purged {len(ids_to_delete)} unsaved clips older than {days} days.", Colors.GREEN)

        except Exception as e:
            log("RETENTION NOTICE", f"Retention check skipped: {e}", Colors.DIM)


# ==============================================================================
# Stream Slicer Engine (Zero-Stutter VAD)
# ==============================================================================
class StreamSlicer:
    def __init__(
        self,
        stream_url: str,
        uploader: DispatchUploader,
        silence_threshold_dbfs: float = SILENCE_THRESHOLD_DBFS,
        silence_duration_sec: float = SILENCE_DURATION_SEC,
        pre_roll_duration_sec: float = PRE_ROLL_DURATION_SEC,
        min_clip_duration_sec: float = MIN_CLIP_DURATION_SEC,
        max_clip_duration_sec: float = MAX_CLIP_DURATION_SEC,
    ):
        self.stream_url = stream_url
        self.uploader = uploader
        self.silence_threshold = silence_threshold_dbfs
        self.silence_duration_sec = silence_duration_sec
        self.pre_roll_duration_sec = pre_roll_duration_sec
        self.min_clip_duration_sec = min_clip_duration_sec
        self.max_clip_duration_sec = max_clip_duration_sec

        self.running = False
        self.is_transmitting = False
        self.consecutive_silence_sec = 0.0
        self.last_heartbeat_time = 0.0
        self.last_record_broadcast_time = 0.0

        # Rolling pre-roll buffer (FIFO)
        pre_roll_chunks_count = max(1, int(pre_roll_duration_sec / (CHUNK_DURATION_MS / 1000.0)))
        self.pre_roll_buffer: Deque[AudioSegment] = deque(maxlen=pre_roll_chunks_count)

        # Buffer for currently active transmission
        self.active_buffer: list[AudioSegment] = []

    def calculate_chunk_dbfs(self, segment: AudioSegment) -> float:
        """Calculates the decibels relative to full scale (dBFS) for an AudioSegment chunk."""
        if segment.rms == 0:
            return -100.0
        return segment.dBFS

    def process_pcm_chunk(self, pcm_bytes: bytes):
        """Processes 200ms of raw 16-bit mono PCM audio from stream with seamless VAD."""
        if len(pcm_bytes) < BYTES_PER_CHUNK:
            return

        chunk_segment = AudioSegment(
            data=pcm_bytes,
            sample_width=SAMPLE_WIDTH,
            frame_rate=SAMPLE_RATE,
            channels=CHANNELS
        )

        chunk_dbfs = self.calculate_chunk_dbfs(chunk_segment)
        chunk_sec = CHUNK_DURATION_MS / 1000.0
        is_speech = chunk_dbfs >= self.silence_threshold
        now = time.time()

        # Print live terminal energy meter on single updating line in TTY mode
        if sys.stdout.isatty():
            sys.stdout.write(f"\r{render_dbfs_meter(chunk_dbfs, self.silence_threshold, self.is_transmitting)}   ")
            sys.stdout.flush()

        if not self.is_transmitting:
            # IDLE / LISTENING STATE
            if is_speech:
                # Voice detected: transition to TRANSMITTING / RECORDING
                self.is_transmitting = True
                self.consecutive_silence_sec = 0.0
                print()
                log("TRIGGER", f"Voice activity detected! ({chunk_dbfs:.1f} dBFS >= {self.silence_threshold:.1f} dBFS)", Colors.YELLOW)
                
                # FIX: Seed active buffer with the pre-roll history, then append current chunk exactly ONCE
                self.active_buffer = list(self.pre_roll_buffer)
                self.active_buffer.append(chunk_segment)
                self.pre_roll_buffer.clear()

                # Broadcast RECORDING state immediately
                self.last_record_broadcast_time = now
                threading.Thread(
                    target=self.uploader.broadcast_status,
                    args=("RECORDING", chunk_dbfs, len(self.active_buffer) * chunk_sec),
                    daemon=True
                ).start()
            else:
                # Continuous silence: maintain rolling pre-roll buffer
                self.pre_roll_buffer.append(chunk_segment)

                # Send idle monitoring heartbeat every 1.0 second
                if now - self.last_heartbeat_time >= 1.0:
                    self.last_heartbeat_time = now
                    threading.Thread(
                        target=self.uploader.broadcast_status,
                        args=("MONITORING", chunk_dbfs, 0.0),
                        daemon=True
                    ).start()

        else:
            # TRANSMITTING / RECORDING STATE
            self.active_buffer.append(chunk_segment)
            current_duration = len(self.active_buffer) * chunk_sec

            if is_speech:
                self.consecutive_silence_sec = 0.0
            else:
                self.consecutive_silence_sec += chunk_sec

            # Broadcast recording duration progress every 0.4s
            if now - self.last_record_broadcast_time >= 0.4:
                self.last_record_broadcast_time = now
                threading.Thread(
                    target=self.uploader.broadcast_status,
                    args=("RECORDING", chunk_dbfs, current_duration),
                    daemon=True
                ).start()

            # Check if silence timeout reached OR max clip duration exceeded
            if self.consecutive_silence_sec >= self.silence_duration_sec or current_duration >= self.max_clip_duration_sec:
                self.finalize_transmission(current_duration)

    def finalize_transmission(self, total_duration: float):
        """Assembles, converts to MP3, validates length, and uploads the transmission clip."""
        print()
        log("SEGMENT", f"Transmission ended. Duration: {total_duration:.2f}s (Silence: {self.consecutive_silence_sec:.1f}s)", Colors.BLUE)

        # Broadcast state transition back to IDLE
        threading.Thread(
            target=self.uploader.broadcast_status,
            args=("IDLE", -90.0, total_duration),
            daemon=True
        ).start()

        if total_duration < self.min_clip_duration_sec:
            log("IGNORED", f"Clip discarded (duration {total_duration:.2f}s < minimum {self.min_clip_duration_sec:.1f}s)", Colors.DIM)
        else:
            try:
                combined_audio = AudioSegment.empty()
                for seg in self.active_buffer:
                    combined_audio += seg

                mp3_io = io.BytesIO()
                combined_audio.export(mp3_io, format="mp3", bitrate="64k", parameters=["-ac", "1", "-ar", "22050"])
                mp3_bytes = mp3_io.getvalue()

                # Upload to Supabase
                self.uploader.upload_clip(mp3_bytes, total_duration)

            except Exception as e:
                log("ERROR", f"Failed to encode or upload audio clip: {e}", Colors.RED)

        # Reset state back to monitoring
        self.is_transmitting = False
        self.consecutive_silence_sec = 0.0
        self.active_buffer.clear()
        self.pre_roll_buffer.clear()

    def run_hls_stream_loop(self):
        """Streams live HLS (.m3u8) feeds continuously via Python HTTP requests and FFmpeg MPEG-TS decoding."""
        log("HLS", f"Starting native HLS stream reader for {self.stream_url}", Colors.GREEN)
        seen_segments: Set[str] = set()
        base_url = self.stream_url.rsplit("/", 1)[0]
        pcm_accumulator = bytearray()

        while self.running:
            try:
                resp = requests.get(self.stream_url, headers=STREAM_HTTP_HEADERS, timeout=8)
                if resp.status_code != 200:
                    log("HLS ERROR", f"Playlist request returned HTTP {resp.status_code}", Colors.RED)
                    time.sleep(2.0)
                    continue

                seg_lines = [l.strip() for l in resp.text.splitlines() if l.strip() and not l.startswith("#")]
                new_segments = [s for s in seg_lines if s not in seen_segments]

                for seg_rel in new_segments:
                    if not self.running:
                        break
                    
                    seen_segments.add(seg_rel)
                    if len(seen_segments) > 100:
                        seen_segments.clear()
                        for s in seg_lines:
                            seen_segments.add(s)

                    seg_full_url = seg_rel if seg_rel.startswith("http") else f"{base_url}/{seg_rel}"
                    seg_resp = requests.get(seg_full_url, headers=STREAM_HTTP_HEADERS, timeout=6)
                    if seg_resp.status_code != 200:
                        continue

                    cmd = [
                        "ffmpeg", "-loglevel", "error",
                        "-f", "mpegts",
                        "-i", "pipe:0",
                        "-f", "s16le",
                        "-acodec", "pcm_s16le",
                        "-ar", str(SAMPLE_RATE),
                        "-ac", str(CHANNELS),
                        "-"
                    ]
                    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    pcm_out, _ = proc.communicate(input=seg_resp.content)

                    if pcm_out:
                        pcm_accumulator.extend(pcm_out)
                        while len(pcm_accumulator) >= BYTES_PER_CHUNK:
                            pcm_chunk = bytes(pcm_accumulator[:BYTES_PER_CHUNK])
                            del pcm_accumulator[:BYTES_PER_CHUNK]
                            self.process_pcm_chunk(pcm_chunk)

                time.sleep(1.8)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log("HLS ERROR", f"Error in HLS loop: {e}", Colors.RED)
                time.sleep(2.0)

    def start_ffmpeg_stream_process(self) -> subprocess.Popen:
        """Starts an FFmpeg subprocess for direct Icecast/MP3/AAC streams or local files."""
        ffmpeg_cmd = ["ffmpeg", "-loglevel", "error"]
        
        if self.stream_url.startswith("http://") or self.stream_url.startswith("https://"):
            ffmpeg_cmd.extend([
                "-user_agent", STREAM_HTTP_HEADERS["User-Agent"],
                "-headers", f"Referer: {STREAM_HTTP_HEADERS['Referer']}\r\n",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5"
            ])
        
        ffmpeg_cmd.extend([
            "-i", self.stream_url,
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "-"
        ])
        return subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=BYTES_PER_CHUNK * 4)

    def run(self):
        """Continuous stream processing loop with auto-reconnection on network drops."""
        self.running = True
        is_hls = ".m3u8" in self.stream_url.lower()
        is_local_file = not (self.stream_url.startswith("http://") or self.stream_url.startswith("https://"))
        source_label = f"local file: {self.stream_url}" if is_local_file else f"stream: {self.stream_url}"
        log("START", f"Processing {source_label}", Colors.GREEN)
        log("CONFIG", f"Threshold: {self.silence_threshold} dBFS | Silence Timeout: {self.silence_duration_sec}s", Colors.CYAN)

        def retention_worker():
            while self.running:
                time.sleep(CLEANUP_INTERVAL_SEC)
                if self.running:
                    self.uploader.purge_expired_clips(days=RETENTION_DAYS)

        retention_thread = threading.Thread(target=retention_worker, daemon=True)
        retention_thread.start()

        if is_hls:
            self.run_hls_stream_loop()
        else:
            reconnect_delay = 2.0
            while self.running:
                process = None
                try:
                    process = self.start_ffmpeg_stream_process()
                    reconnect_delay = 2.0
                    pcm_accumulator = bytearray()

                    while self.running:
                        raw_read = process.stdout.read(BYTES_PER_CHUNK)
                        if not raw_read or len(raw_read) == 0:
                            if is_local_file:
                                log("COMPLETE", "Finished processing audio file.", Colors.GREEN)
                                self.running = False
                                break
                            else:
                                log("STREAM", "Stream pipe ended or disconnected. Reconnecting...", Colors.YELLOW)
                                break

                        pcm_accumulator.extend(raw_read)
                        while len(pcm_accumulator) >= BYTES_PER_CHUNK:
                            pcm_chunk = bytes(pcm_accumulator[:BYTES_PER_CHUNK])
                            del pcm_accumulator[:BYTES_PER_CHUNK]
                            self.process_pcm_chunk(pcm_chunk)

                except KeyboardInterrupt:
                    log("SHUTDOWN", "Stopping stream listener gracefully...", Colors.YELLOW)
                    self.running = False
                    break
                except Exception as e:
                    log("STREAM ERROR", f"Audio reading error: {e}", Colors.RED)
                finally:
                    if process:
                        try:
                            process.terminate()
                            process.wait(timeout=2)
                        except Exception:
                            pass

                if self.running and not is_local_file:
                    log("RETRY", f"Reconnecting in {reconnect_delay:.1f}s...", Colors.CYAN)
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(30.0, reconnect_delay * 1.5)

        if self.is_transmitting and len(self.active_buffer) > 0:
            dur = len(self.active_buffer) * (CHUNK_DURATION_MS / 1000.0)
            self.finalize_transmission(dur)

        print("\nTrace Dispatch listener terminated.")


# ==============================================================================
# CLI Entrypoint
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="Trace Dispatch - Audio Stream Slicer & Voice Activity Indexer")
    parser.add_argument("--url", type=str, default=STREAM_URL, help="Target audio stream URL")
    parser.add_argument("--file", type=str, default=None, help="Local audio file path (MP3/WAV) to test slicing")
    parser.add_argument("--threshold", type=float, default=SILENCE_THRESHOLD_DBFS, help="Silence dBFS threshold (e.g. -36.0)")
    parser.add_argument("--silence", type=float, default=SILENCE_DURATION_SEC, help="Silence timeout duration in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Run without uploading to Supabase")
    args = parser.parse_args()

    # Ensure only ONE slicer instance runs across the entire computer
    if not args.file:
        ensure_single_instance(port=46604)

    input_source = args.file if args.file else args.url

    print(f"""{Colors.CYAN}{Colors.BOLD}
+-------------------------------------------------------------------+
|                   TRACE DISPATCH // SLICER v1.0                   |
|         Zero-Cost Emergency Audio Indexing & VAD Listener         |
+-------------------------------------------------------------------+{Colors.RESET}""")

    uploader = DispatchUploader(
        url=SUPABASE_URL,
        key=SUPABASE_KEY,
        bucket=STORAGE_BUCKET,
        table=TABLE_NAME,
        dry_run=args.dry_run
    )

    slicer = StreamSlicer(
        stream_url=input_source,
        uploader=uploader,
        silence_threshold_dbfs=args.threshold,
        silence_duration_sec=args.silence,
        pre_roll_duration_sec=PRE_ROLL_DURATION_SEC,
        min_clip_duration_sec=MIN_CLIP_DURATION_SEC,
        max_clip_duration_sec=MAX_CLIP_DURATION_SEC,
    )

    def sig_handler(signum, frame):
        slicer.running = False

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    slicer.run()


if __name__ == "__main__":
    main()
