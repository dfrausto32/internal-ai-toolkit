# Ollama + Claude Code Setup Guide
## Local AI Workers, Claude as Orchestrator

---

## Before You Start: WSL2 Check

Run these inside your Ubuntu WSL2 terminal to know exactly what you're working with before pulling any models.

### Confirm you're on WSL2 (not WSL1)

Open PowerShell on Windows and run:

```powershell
wsl -l -v
```

The `VERSION` column must say `2`. If it says `1`, upgrade before continuing:

```powershell
wsl --set-version Ubuntu-22.04 2
```

### Check available RAM inside WSL2

By default WSL2 only gets 50% of your Windows RAM, which will starve your models. Run this inside WSL:

```bash
# See how much RAM WSL2 currently has
free -h

# See total Windows system RAM
cat /proc/meminfo | grep MemTotal
```

If `free -h` shows significantly less than your actual Windows RAM, fix it before continuing — see the `.wslconfig` step below.

### Check GPU passthrough

```bash
# Should show your NVIDIA GPU — if this fails, see Troubleshooting
nvidia-smi
```

> **Critical GPU rule:** Install the NVIDIA driver on Windows only — never install NVIDIA Linux drivers inside WSL2. The Windows driver is automatically stubbed into WSL2 at `/usr/lib/wsl/lib/`. Installing a separate Linux driver breaks the passthrough.

> **AMD GPU note:** ROCm does not work in WSL2 (it requires `/dev/kfd` which WSL2 doesn't expose). If you have an AMD GPU, Ollama will run CPU-only inside WSL2. For AMD GPU acceleration you'd need native Linux or Windows-native Ollama.

### Check disk space

Models live inside the WSL2 filesystem by default (`~/.ollama/models/`). Keep them there — accessing them via `/mnt/c/` is 3–5x slower due to the filesystem translation layer.

```bash
df -h ~
```

Budget ~20 GB for the recommended model set.

### What your hardware can run

| VRAM / RAM | What works well |
|-----------|----------------|
| 8 GB VRAM | Small models: `qwen2.5-coder:7b`, `llama3.1:8b` |
| 16 GB VRAM | Mid-tier: `qwen2.5-coder:14b`, good speed |
| 24 GB VRAM | `qwen2.5-coder:32b` at Q4 (needs ~20 GB) |
| CPU-only | Stick to 7B models; expect 3–8 tokens/sec |

---

## Step 1: Allocate Enough RAM to WSL2

This is the step most guides skip and the one most likely to cause you pain. Do this before installing anything.

On Windows, open Notepad as Administrator and create (or edit) this file:
`C:\Users\<YourUsername>\.wslconfig`

```ini
[wsl2]
memory=16GB        # Set to ~75% of your total Windows RAM
processors=8       # Match your CPU core count or leave this out
swap=8GB           # Recommended: half of memory value
```

Save it, then restart WSL2 from PowerShell:

```powershell
wsl --shutdown
```

Reopen your Ubuntu terminal and verify:

```bash
free -h   # Should now show the RAM you allocated
```

---

## Step 2: Install Ollama

Inside your Ubuntu WSL2 terminal, run the one-line installer:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

This installs the Ollama binary and sets up a systemd service. Then start it:

```bash
sudo systemctl enable ollama
sudo systemctl start ollama
```

### Verify installation

```bash
ollama --version
# Should show 0.14.0 or later

curl http://localhost:11434
# Should return: "Ollama is running"
```

### Confirm GPU is detected

```bash
# Check Ollama's logs for GPU detection
journalctl -u ollama --no-pager | grep -i gpu
```

You should see a line mentioning your GPU. If it says `no GPU found` or only shows CPU, see Troubleshooting.

---

## Step 3: Pull the Models

These are the four models mapped to your agent roles. Pull commands are ordered smallest → largest so you can test as you go.

### Generic Code Generation
```bash
ollama pull qwen2.5-coder:7b       # ~4.7 GB  — use if you have 8 GB RAM
ollama pull qwen2.5-coder:14b      # ~9 GB    — use if you have 16 GB RAM
ollama pull qwen2.5-coder:32b      # ~19 GB   — use if you have 32 GB+ RAM
```
> `qwen2.5-coder` is currently the best local coding model available. Pick the largest size your RAM comfortably fits. Leave ~4 GB headroom for the OS and other apps.

### Test Writing
```bash
# Same model family — consistent code style between generator and tester
ollama pull qwen2.5-coder:7b   # already pulled above, reused here
```
> You can run two separate instances of the same model, or point both agents at the same one. Ollama handles concurrent requests.

### Pipeline / CI Config
```bash
ollama pull llama3.1:8b        # ~4.7 GB — fast, great at structured YAML/JSON
```
> For generating GitHub Actions, shell scripts, or Dockerfiles, a general 8B model is plenty. Lighter on RAM, faster to respond.

### Slack / Discord Notifications
```bash
ollama pull llama3.2:3b        # ~2 GB — overkill for formatting text, but fast
```
> A 3B model is more than sufficient for generating Slack/Discord messages. Responds almost instantly.

### Check everything pulled correctly
```bash
ollama list
# Should show all pulled models with their sizes
```

---

## Step 4: Test Each Model

Run a quick sanity check before wiring things up:

```bash
# Test code model
ollama run qwen2.5-coder:7b "Write a Python function to validate an email address"

# Test pipeline model
ollama run llama3.1:8b "Write a minimal GitHub Actions workflow that runs pytest"

# Test notification model
ollama run llama3.2:3b "Write a Slack message announcing a successful deployment to production"

# Exit any interactive session
# Press Ctrl+D
```

---

## Step 5: Verify the API

Ollama exposes a local REST API at `http://localhost:11434`. This is what your orchestrator will call.

```bash
# Test the generate endpoint directly
curl http://localhost:11434/api/generate \
  -d '{
    "model": "llama3.1:8b",
    "prompt": "Say hello in one sentence",
    "stream": false
  }'
```

You should get a JSON response with a `response` field. If this works, the API is ready.

---

## Step 6: Configure Ollama for Performance (Optional)

Edit the Ollama systemd service to set environment variables:

```bash
sudo systemctl edit ollama
```

This opens an override file. Add the following, adjusting values to your hardware:

```ini
[Service]
# Allow multiple models to stay loaded simultaneously
Environment="OLLAMA_MAX_LOADED_MODELS=3"

# For 16 GB WSL2 allocation — conservative
Environment="OLLAMA_MAX_RAM=12GB"
Environment="OLLAMA_NUM_PARALLEL=1"

# For 32 GB+ WSL2 allocation — allow parallel requests
# Environment="OLLAMA_MAX_RAM=24GB"
# Environment="OLLAMA_NUM_PARALLEL=2"

# Bind to all interfaces so Windows host can reach Ollama too (optional)
Environment="OLLAMA_HOST=0.0.0.0"
```

Save, then restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

> **Accessing Ollama from Windows:** If you set `OLLAMA_HOST=0.0.0.0`, you can also hit the API from Windows at `http://localhost:11434`. Useful if you want to test from a Windows browser or tool.

---

## Model Reference Summary

| Agent Role | Model | Pull Command | Approx Size |
|-----------|-------|-------------|-------------|
| Code generation | `qwen2.5-coder:7b` / `14b` / `32b` | `ollama pull qwen2.5-coder:7b` | 4.7–19 GB |
| Test writing | `qwen2.5-coder:7b` | (same as above) | — |
| CI/Pipeline config | `llama3.1:8b` | `ollama pull llama3.1:8b` | 4.7 GB |
| Slack/Discord | `llama3.2:3b` | `ollama pull llama3.2:3b` | 2 GB |
| **Orchestrator** | **Claude Sonnet (API)** | n/a — your existing Claude Code | — |

---

## Troubleshooting

**"Error: model not found"**
```bash
ollama list   # check exact model names
ollama pull <model-name>
```

**`nvidia-smi` fails inside WSL2**

This means GPU passthrough isn't working. The fix is almost always a Windows driver update:
1. On Windows, download the latest NVIDIA Game Ready or Studio driver from nvidia.com/drivers (need 531+)
2. Install it on Windows — do NOT install any NVIDIA driver inside WSL2
3. Restart WSL2: run `wsl --shutdown` in PowerShell, then reopen Ubuntu
4. Run `nvidia-smi` again

**Ollama not detecting GPU after driver update**
```bash
# Reinstall Ollama so it re-detects CUDA
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl restart ollama
journalctl -u ollama --no-pager | grep -i gpu
```

**Models are slow / under 5 tokens/sec**
```bash
# Check how many layers are on GPU vs CPU
OLLAMA_DEBUG=1 ollama run qwen2.5-coder:7b "test" 2>&1 | grep "layers"
```
If most layers are on CPU, you're out of VRAM — use a smaller model variant. Also check WSL2 RAM allocation (Step 1) isn't starving the GPU.

**WSL2 has less RAM than expected**
```bash
free -h    # check current allocation
```
Edit `C:\Users\<YourUsername>\.wslconfig` and increase the `memory=` value, then run `wsl --shutdown` from PowerShell.

**Ollama not running after reboot**
```bash
# WSL2 doesn't auto-start services by default — run this inside Ubuntu:
sudo systemctl enable ollama
sudo systemctl start ollama

# Check status
sudo systemctl status ollama
```

**Port 11434 already in use**
```bash
lsof -i :11434
sudo systemctl restart ollama
```

**Corporate VPN breaking WSL2 internet access**

VPNs like Cisco AnyConnect or GlobalProtect commonly break WSL2 network routing. On Windows 11, add this to `.wslconfig`:
```ini
[wsl2]
networkingMode=mirrored
```
Then `wsl --shutdown` and restart. This makes WSL2 share the Windows network stack including the VPN connection.

**GPU disappears after Windows sleep/resume**
```bash
sudo rmmod nvidia_uvm && sudo modprobe nvidia_uvm
```

---

## What's Next

With Ollama running and models pulled, you have two options for wiring this into Claude Code:

1. **`.md` subagent files** — define agents in `~/.claude/agents/`, Claude orchestrates them via natural language, Ollama is called via a Python helper script. No custom code to maintain beyond the script.

2. **Programmatic SDK approach** — Python script using `claude_agent_sdk` + `httpx` for direct Ollama calls. More control, better for automation pipelines and CI.

See the architecture discussion for a breakdown of which fits your situation.
