"""
Start the AI Research Agent web UI.

Usage:
    python run_ui.py              # default: http://localhost:8000
    python run_ui.py --port 8080
    python run_ui.py --host 0.0.0.0 --port 8080
"""

import argparse
import os
import sys
import webbrowser
import threading
import time

# RUNNER_PYTHON (interpreter for Phase 6 experiment subprocesses — point this
# at a GPU/CUDA-enabled env if training needs it) and RUNNER_MAX_FIX_ATTEMPTS
# (set to 0 to stop the auto-fix loop from overwriting manually-edited
# scripts) are read from your own .env file — see .env.example. They used to
# be hardcoded here to one machine's local conda path, which broke for
# everyone else who ran this script; config.py's own defaults (current
# interpreter, 3 attempts) now apply unless you override them in .env.

def parse_args():
    p = argparse.ArgumentParser(description="AI Research Agent – Web UI")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    p.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    p.add_argument("--reload", action="store_true", help="Enable hot-reload (dev mode)")
    p.add_argument("--allow-insecure", action="store_true",
                   help="Bind a non-localhost address without an access gate (not advised)")
    return p.parse_args()


def _loopback(host: str) -> bool:
    import ipaddress
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main():
    args = parse_args()

    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn not installed.")
        print("Run: pip install fastapi uvicorn[standard] websockets")
        sys.exit(1)

    import config

    # Non-local service binding requires a real access gate. A hosted service
    # may use account sessions instead of the legacy shared UI_TOKEN, but only
    # after an account already exists in its persistent database. This keeps a
    # brand-new public deployment from letting the first visitor claim owner.
    account_auth_ready = False
    if config.HOSTED and not config.UI_TOKEN:
        try:
            from memory.accounts import accounts_exist
            account_auth_ready = accounts_exist()
        except Exception:
            account_auth_ready = False
    if (not _loopback(args.host) and not config.UI_TOKEN and
            not account_auth_ready and not args.allow_insecure):
        print(f"\n  Refusing to serve on {args.host} with no access gate configured.")
        print("  Set UI_TOKEN, bootstrap an owner account on persistent storage, or pass")
        print("  --allow-insecure only when this network is trusted.\n")
        sys.exit(2)

    url = f"http://{args.host}:{args.port}"
    # A hosted URL is recorded by reverse proxies and deployment logs. Never
    # put a hosted access token in that URL; the login form sends it in a POST
    # body and stores it in an HttpOnly cookie.
    if config.UI_TOKEN and not config.HOSTED:
        url += f"/?token={config.UI_TOKEN}"
    print("\n  AI Research Agent UI")
    print("  ─────────────────────────────────")
    print(f"  URL: {url}")
    if config.UI_TOKEN:
        print("  A token is required on every request (UI_TOKEN).")
    elif account_auth_ready:
        print("  Account authentication protects private application routes.")
    print("  Press Ctrl+C to stop.\n")

    if not args.no_browser:
        def open_browser():
            time.sleep(1.2)
            webbrowser.open(url)
        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(
        "ui.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
        # One worker, always: the gates, the running pipelines and the stop
        # button all live in this process's memory, so a second worker would
        # answer requests about runs it cannot see.
        workers=1,
        # Behind a proxy (a hosted deployment), the client address and the
        # https scheme arrive in headers; without this every request looks
        # like it came from the proxy over plain http.
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
