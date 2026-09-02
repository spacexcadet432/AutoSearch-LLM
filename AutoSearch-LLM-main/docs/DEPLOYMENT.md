# Deploying AutoSearch-LLM on one EC2 instance

Single instance, Python venv, uvicorn under systemd. No Docker, no orchestration.

```
GitHub → EC2 → venv → uvicorn (127.0.0.1:8000) → AutoSearch-LLM → Bedrock + Serper
```

## 1. Create the EC2 instance

- Amazon Linux 2023 or Ubuntu 22.04+, `t3.small` is sufficient.
- Attach an **IAM role** if you prefer role-based Bedrock auth over a bearer token.

**Security group — minimum exposure:**

| Port | Source | Why |
|---|---|---|
| 22 | your IP only | SSH admin |
| 443 (or 80) | `0.0.0.0/0` | public API, if serving directly |

The app binds to **127.0.0.1:8000** and is *not* directly reachable from the
internet. Put nginx/ALB in front for TLS, or change the bind if you accept plain
HTTP. **Never expose 8000 publicly.**

## 2. Install Python

```bash
# Amazon Linux 2023
sudo dnf install -y python3.11 python3.11-pip git
# Ubuntu
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip git
```

## 3–5. Clone, venv, dependencies

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin autosearch
sudo mkdir -p /opt/autosearch && sudo chown autosearch:autosearch /opt/autosearch

sudo -u autosearch git clone https://github.com/<you>/AutoSearch-LLM.git /opt/autosearch
cd /opt/autosearch
sudo -u autosearch python3.11 -m venv .venv
sudo -u autosearch .venv/bin/pip install --upgrade pip
sudo -u autosearch .venv/bin/pip install -r requirements.txt
```

Production installs `requirements.txt` only. `requirements-dev.txt` (pytest) is
not needed on the instance.

## 6–8. Configure environment, AWS access, and Serper

```bash
sudo mkdir -p /etc/autosearch
sudo cp /opt/autosearch/deploy/autosearch.env.example /etc/autosearch/autosearch.env
sudo nano /etc/autosearch/autosearch.env      # fill in real values
sudo chown root:root /etc/autosearch/autosearch.env
sudo chmod 600 /etc/autosearch/autosearch.env
```

Required:

```bash
AUTOSEARCH_ENV=production
AUTOSEARCH_ALLOWED_ORIGINS=https://your-frontend.example.com
AUTOSEARCH_LLM_BASE_URL=https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1
AUTOSEARCH_LLM_MODEL=openai.gpt-oss-120b-1:0
AWS_BEARER_TOKEN_BEDROCK=...
SERPER_API_KEY=...
```

**Secrets stay in this root-owned `chmod 600` file only** — never in the repo,
the unit file, or logs. `.env` is gitignored.

> Bedrock's OpenAI-compatible endpoint serves only the `openai.gpt-oss-*`
> models. Nova/Claude/Llama require the native Converse API, which this service
> does not use.

**IAM alternative:** attach a role with `bedrock:InvokeModel` and drop
`AWS_BEARER_TOKEN_BEDROCK`. The bearer token is simpler; the role avoids a
long-lived secret.

## 9–11. Install, start, enable

```bash
sudo cp /opt/autosearch/deploy/autosearch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autosearch     # starts now AND on boot
sudo systemctl status autosearch
```

`Restart=always` restarts the process on crash; `enable` restarts it after a
reboot.

## 12–13. Verify health and logs

```bash
curl -s localhost:8000/health | python3 -m json.tool
sudo journalctl -u autosearch -f          # follow
sudo journalctl -u autosearch --since "10 min ago"
```

`/health` reports status, uptime, which credentials are configured (booleans
only) and cache stats. **It calls no external API**, so probing it costs no
quota and a Bedrock/Serper outage never marks the instance unhealthy.

Smoke test:

```bash
curl -s -X POST localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is the capital of France?"}'
```

No keys in the request — the server uses its own.

## 14–15. Restart and stop

```bash
sudo systemctl restart autosearch
sudo systemctl stop autosearch
sudo systemctl disable autosearch     # stop starting on boot
```

## Updating

```bash
cd /opt/autosearch
sudo -u autosearch git pull
sudo -u autosearch .venv/bin/pip install -r requirements.txt
sudo systemctl restart autosearch
```

## Operational notes

- **Workers:** the unit runs `--workers 2`. The search cache is per-process, so
  each worker keeps its own — expect a lower hit rate than a single worker.
  Use `--workers 1` to maximise cache hits on a small instance.
- **Graceful shutdown:** systemd sends SIGINT; uvicorn drains in-flight requests
  (30 s budget). In-flight retrieval tasks are cancelled by their own request
  scope, so no orphaned tasks survive.
- **Docs:** `/docs`, `/redoc` and `/openapi.json` are disabled when
  `AUTOSEARCH_ENV=production`. Set `AUTOSEARCH_ENABLE_DOCS=true` to re-enable.
- **Logs:** stdout → journald. No log files to rotate.
