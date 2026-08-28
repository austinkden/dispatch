# 🌐 24/7 100% Free Cloud Hosting with Hugging Face Gradio

You can run **Trace Dispatch 24/7 in the cloud for free** (both the continuous audio listener and the full web dashboard) using a **Free Hugging Face Gradio Space** (no credit card or paid Docker plan required).

---

## 🚀 3-Minute Setup on Hugging Face (100% Free)

### 1. Create a Free Space
1. Go to [**huggingface.co/new-space**](https://huggingface.co/new-space).
2. Enter a **Space name** (e.g. `trace-dispatch`).
3. Select **Space SDK**: **Gradio** (Free 2 vCPU / 16 GB RAM).
4. Select **Space hardware**: **CPU Basic &bull; Free**.
5. Set Visibility to **Public** or **Private** &rarr; click **Create Space**.

---

### 2. Upload Files to the Space
In your newly created Space, click **Files** &rarr; **Add file** &rarr; **Upload files**, and upload:
- `app.py`
- `slicer.py`
- `index.html`
- `requirements.txt`
- `packages.txt`

---

### 3. Add Environment Secrets
Go to **Settings** &rarr; **Variables and secrets** &rarr; click **New secret** to add:

| Secret Name | Value |
| :--- | :--- |
| `STREAM_URL` | `https://hls-o1.broadcastify.com/s0/feed/46604/playlist.m3u8?s=MOspf6tnWG_xWYmw9utS4A.1787879026.BVFsBAaCcGUfaAUq` |
| `SUPABASE_URL` | `https://uquhzylwnzprokmqadno.supabase.co` |
| `SUPABASE_KEY` | `YOUR_SUPABASE_SERVICE_ROLE_KEY` |
| `SILENCE_THRESHOLD_DBFS` | `-36.0` |

---

### 4. Live 24/7 in the Cloud! 🎉
- Hugging Face will automatically install `ffmpeg` from `packages.txt` and python packages from `requirements.txt`.
- `app.py` runs the background stream listener 24/7 continuously, saving clips into Supabase.
- You get a public URL (`https://<username>-trace-dispatch.hf.space`) accessible by anyone on phone or PC!
