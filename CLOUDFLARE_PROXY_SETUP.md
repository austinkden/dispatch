# 🛡️ Cloudflare Worker Proxy Setup (Bypass School/Network SSL Filters)

If you see errors like:
```
POST https://api.groq.com/openai/v1/audio/transcriptions net::ERR_CERT_AUTHORITY_INVALID
TypeError: Failed to fetch
```
This happens because school and enterprise Wi-Fi networks perform **SSL Decryption / TLS Inspection (MITM)** or block AI API endpoints like `api.groq.com`.

You can bypass this in **60 seconds for free** by deploying a Cloudflare Worker proxy. Cloudflare Workers have clean SSL certificates issued by Cloudflare that school networks trust, and their domains (`*.workers.dev`) route cleanly.

---

## ⚡ 1-Minute Setup Guide

### 1. Open Cloudflare Dashboard
1. Go to [dash.cloudflare.com](https://dash.cloudflare.com/) (Sign in or sign up for free).
2. On the left sidebar, click **Compute (Workers & Pages)** &rarr; **Workers**.
3. Click the **Create Application** button &rarr; click **Create Worker**.
4. Give your worker a name (e.g. `dispatch-proxy`) and click **Deploy**.

---

### 2. Paste the Proxy Code
1. Click **Edit code** in the top right of your worker page.
2. Replace all the default code in `worker.js` with the contents of [`cloudflare-worker.js`](cloudflare-worker.js) from this repository.
3. Click **Deploy** in the top right corner.

---

### 3. Copy Your Worker URL & Add to Dispatch Settings
1. Copy your worker's public URL at the top (e.g., `https://dispatch-proxy.<your-subdomain>.workers.dev`).
2. Open your **Trace Dispatch** dashboard in your browser.
3. Click the **⚙️ Settings** icon in the header.
4. Paste your Worker URL into the **Cloudflare Proxy URL** field.
5. Click **Save Settings**.

---

### 🎉 Done!
All Whisper audio transcription (`Groq`) and AI titling (`Gemini` / `LLaMA`) calls will now be transparently proxied through Cloudflare Edge, completely bypassing school firewall SSL errors and blocks!

> **Bonus**: You can also use **Google Gemini** as an automatic fallback transcription engine if Groq is blocked. Simply add a free Gemini API key in Settings!
