"""
AlphaHood — Robinhood MCP 1-Time OAuth PKCE Account Linker
Automates dynamic client registration, PKCE challenge generation,
local callback listener, browser authorization launcher, and token storage in .env.
"""
import os
import sys
import json
import base64
import hashlib
import secrets
import urllib.parse
import webbrowser
import http.server
import socketserver
import threading
import requests
from typing import Dict, Any, Optional

REGISTRATION_ENDPOINT = "https://agent.robinhood.com/oauth/trading/register"
AUTHORIZATION_ENDPOINT = "https://robinhood.com/oauth"
TOKEN_ENDPOINT = "https://api.robinhood.com/oauth2/token/"
CALLBACK_PORT = 8888
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
ENV_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

auth_code_received: Optional[str] = None

def generate_pkce_pair():
    """Generate code_verifier and code_challenge using SHA256 (S256)."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode('utf-8').replace('=', '')
    return code_verifier, code_challenge

class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Local HTTP handler to capture authorization code from Robinhood OAuth redirect."""
    
    def log_message(self, format, *args):
        pass  # Suppress default server logs

    def do_GET(self):
        global auth_code_received
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == "/callback":
            query_params = urllib.parse.parse_qs(parsed_path.query)
            if "code" in query_params:
                auth_code_received = query_params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                html_response = """
                <html>
                    <head><title>AlphaHood — Authorization Successful</title></head>
                    <body style="font-family: system-ui, sans-serif; text-align: center; padding-top: 50px; background: #0b0e14; color: #00f0ff;">
                        <h1 style="color: #00c805;">✅ Robinhood Account Linked Successfully!</h1>
                        <p style="font-size: 18px; color: #e0e0e0;">AlphaHood has received your authorization code.</p>
                        <p style="color: #888;">You may close this browser tab and return to your terminal.</p>
                    </body>
                </html>
                """
                self.wfile.write(html_response.encode('utf-8'))
            else:
                error = query_params.get("error", ["Unknown error"])[0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"<h2>Authorization Failed: {error}</h2>".encode('utf-8'))

def register_client() -> Dict[str, Any]:
    """Register client with Robinhood MCP OAuth endpoint."""
    payload = {
        "client_name": "AlphaHood Agentic Trader",
        "redirect_uris": [REDIRECT_URI]
    }
    response = requests.post(REGISTRATION_ENDPOINT, json=payload)
    response.raise_for_status()
    return response.json()

def update_env_file(access_token: str, refresh_token: str = ""):
    """Save tokens into project .env file."""
    env_data = {}
    if os.path.exists(ENV_FILE_PATH):
        with open(ENV_FILE_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_data[k.strip()] = v.strip()
    
    env_data["ROBINHOOD_API_TOKEN"] = access_token
    if refresh_token:
        env_data["ROBINHOOD_REFRESH_TOKEN"] = refresh_token
    env_data["ALPHAHOOD_PAPER_MODE"] = "false"
    
    with open(ENV_FILE_PATH, "w") as f:
        for k, v in env_data.items():
            f.write(f"{k}={v}\n")
    print(f"✅ Saved tokens to {ENV_FILE_PATH}")

def run_oauth_flow():
    """Main OAuth 2.0 PKCE orchestration flow."""
    print("=" * 60)
    print("🚀 AlphaHood — 1-Time Robinhood MCP Account Setup")
    print("=" * 60)
    
    # 1. Register OAuth Client
    print("1. Registering dynamic MCP OAuth client with Robinhood...")
    try:
        reg_info = register_client()
        client_id = reg_info.get("client_id")
        print(f"   Registered Client ID: {client_id}")
    except Exception as e:
        print(f"❌ Failed to register client: {e}")
        return False
        
    # 2. Generate PKCE code verifier and challenge
    code_verifier, code_challenge = generate_pkce_pair()
    
    # 3. Construct Auth URL
    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": "internal",
        "resource": "https://agent.robinhood.com/mcp/trading"
    }
    auth_url = f"{AUTHORIZATION_ENDPOINT}?{urllib.parse.urlencode(auth_params)}"
    
    # 4. Start local HTTP server to intercept code
    handler = OAuthCallbackHandler
    server = socketserver.TCPServer(("localhost", CALLBACK_PORT), handler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    print("\n2. Opening Robinhood Authorization page in your browser...")
    print(f"   Auth URL: {auth_url}\n")
    webbrowser.open(auth_url)
    
    print("⏳ Waiting for Robinhood authorization in browser...")
    print("   (Click 'Approve' in the Robinhood page to link your agentic account)")
    
    # Wait for callback
    while auth_code_received is None:
        try:
            threading.Event().wait(0.5)
        except KeyboardInterrupt:
            print("\n❌ Cancelled by user.")
            server.shutdown()
            return False
            
    print(f"\n✅ Captured authorization code!")
    server.shutdown()
    
    # 5. Exchange code for access token
    print("3. Exchanging authorization code for API Access Token...")
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": auth_code_received,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier
    }
    try:
        token_resp = requests.post(TOKEN_ENDPOINT, data=token_payload)
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token", "")
        
        print("✅ Access token retrieved successfully!")
        update_env_file(access_token, refresh_token)
        
        # 6. Test initial MCP connectivity
        print("\n4. Testing Robinhood MCP Account Connection...")
        test_headers = {"Authorization": f"Bearer {access_token}"}
        mcp_resp = requests.get("https://agent.robinhood.com/mcp/trading/account", headers=test_headers)
        if mcp_resp.status_code == 200:
            acc_data = mcp_resp.json()
            print("🎉 SUCCESS! Robinhood MCP Account Linked Successfully!")
            print(f"   Account Details: {json.dumps(acc_data, indent=2)}")
        else:
            print(f"⚠️ Auth saved, but initial MCP check returned HTTP {mcp_resp.status_code}: {mcp_resp.text}")
            
        return True
    except Exception as e:
        print(f"❌ Token exchange failed: {e}")
        return False

if __name__ == "__main__":
    run_oauth_flow()
