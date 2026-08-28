/**
 * Trace Dispatch — Cloudflare Worker Reverse Proxy
 * 
 * Bypasses school/work Wi-Fi firewalls, SSL inspection (ERR_CERT_AUTHORITY_INVALID),
 * and domain blocks for Groq Whisper (api.groq.com) and Google Gemini (generativelanguage.googleapis.com).
 * 
 * Free Tier: 100,000 requests/day on Cloudflare Workers (No credit card required).
 * 
 * Deployment (Takes 60 seconds):
 * 1. Log in to https://dash.cloudflare.com/ -> Click "Workers & Pages" -> "Create Application" -> "Create Worker".
 * 2. Paste this entire file into the worker code editor and click "Deploy".
 * 3. Copy your worker URL (e.g. https://dispatch-proxy.yourname.workers.dev) and paste it into the
 *    "Cloudflare Proxy URL" field in Trace Dispatch Settings!
 */

export default {
  async fetch(request, env, ctx) {
    // 1. Handle CORS preflight OPTIONS requests immediately
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
          "Access-Control-Allow-Headers": "*",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    try {
      const url = new URL(request.url);
      let targetUrl = null;

      // 2. Resolve destination URL from various routing styles:
      
      // Style A: Query param -> ?url=https://api.groq.com/...
      if (url.searchParams.has("url")) {
        targetUrl = url.searchParams.get("url");
      }
      // Style B: URL in path -> /https://api.groq.com/... or /http://...
      else if (url.pathname.startsWith("/http://") || url.pathname.startsWith("/https://")) {
        targetUrl = url.pathname.slice(1) + url.search;
      }
      // Style C: Direct path mirror for Groq -> /openai/... or /v1/...
      else if (
        url.pathname.startsWith("/openai/") ||
        url.pathname.startsWith("/v1/audio/") ||
        url.pathname.startsWith("/v1/chat/")
      ) {
        targetUrl = "https://api.groq.com" + url.pathname + url.search;
      }
      // Style D: Direct path mirror for Google Gemini -> /v1beta/...
      else if (url.pathname.startsWith("/v1beta/")) {
        targetUrl = "https://generativelanguage.googleapis.com" + url.pathname + url.search;
      }
      // Fallback: Default to Groq if unrecognized
      else if (url.pathname.length > 1) {
        targetUrl = "https://api.groq.com" + url.pathname + url.search;
      } else {
        return new Response(
          JSON.stringify({
            status: "online",
            message: "Trace Dispatch Cloudflare Proxy Worker is active! Send requests via /https://api.groq.com/... or /openai/...",
            timestamp: new Date().toISOString()
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "Access-Control-Allow-Origin": "*"
            }
          }
        );
      }

      // 3. Prepare headers for upstream target
      const reqHeaders = new Headers(request.headers);
      reqHeaders.delete("host");
      reqHeaders.delete("origin");
      reqHeaders.delete("referer");

      // 4. Forward the request to target API (supports audio multipart FormData, JSON, streaming)
      const forwardRequest = new Request(targetUrl, {
        method: request.method,
        headers: reqHeaders,
        body: request.body,
        redirect: "follow",
      });

      const response = await fetch(forwardRequest);

      // 5. Wrap response with CORS headers to allow browser access from any domain/localhost
      const resHeaders = new Headers(response.headers);
      resHeaders.set("Access-Control-Allow-Origin", "*");
      resHeaders.set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
      resHeaders.set("Access-Control-Allow-Headers", "*");

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: resHeaders,
      });
    } catch (err) {
      return new Response(
        JSON.stringify({
          error: {
            message: "Proxy Worker Error: " + (err.message || "Unknown upstream connection failure"),
            type: "proxy_error"
          }
        }),
        {
          status: 502,
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
          }
        }
      );
    }
  }
};
