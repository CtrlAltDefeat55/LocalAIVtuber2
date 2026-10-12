# Local AI VTuber

A fully local AI VTuber that talks in real time, can see your screen, and runs entirely on your computer.

- **Brain:** modern open models such as **Qwen3.8 27B (abliterated, IQ3_S)** and **Gemma 4 12B**, running on [llama.cpp](https://github.com/ggml-org/llama.cpp) with NVIDIA, AMD/Intel (Vulkan), Apple Silicon (Metal) or CPU.
- **Voice:** one-click voice engines (**Chatterbox Turbo**, **LuxTTS**, **OmniVoice**, **TADA**, GPT-SoVITS) that clone a voice from a short recording. Switch voices and engines from the app.
- **Body:** 2D Live2D or 3D VRM characters with lip sync. Add, update or replace them from the app.
- Can be interrupted mid-sentence, remembers past chats (long-term memory), and can read your screen.
- Everything lives in one folder. Move it to another drive and it keeps working.

<table>
  <tr>
    <td><img src="https://github.com/user-attachments/assets/f2a88171-f99b-4a78-a0d7-a03cc380c841" /></td>
    <td><img src="https://github.com/user-attachments/assets/26ccf81d-bfe7-444f-944b-116fb7af4fa5" /></td>
  </tr>
</table>

## Install and start (one download)

1. Download **`LocalAIVtuber-vX.Y.Z.zip`** from the [Releases page](../../releases) and extract it anywhere. Avoid OneDrive or other synced folders: models are large.
2. Start it with the script for your system:
   - **Windows:** double-click **`Start Windows.bat`**
   - **macOS (Apple Silicon):** double-click **`Start Mac.command`**. The first time, macOS may ask you to confirm: right-click, then **Open**.
   - **Linux:** run **`./Start Linux.sh`**

   After the first run, the scripts for the other systems are moved into **`Other start scripts/`**, so only yours stays in the folder.
3. The first start sets everything up inside the folder. Nothing is installed system-wide.
   - It downloads a private Python and the app's packages (about 3 GB), plus the LLM runtime that matches your GPU.
   - It **checks your computer** (CPU, RAM, every graphics card, free disk) and recommends the brain and voice that will run well on it. If Windows blocks part of the check, it tells you what it couldn't read and recommends from what it found.
   - It asks which **brain** and **voice engine** to download. Press Enter to accept the recommendation, or choose to connect an API instead.
   - It adds a **Local AI VTuber** shortcut with the app icon to your desktop (and the Start menu on Windows).
4. The app opens in its own window. Closing that window (or clicking **Quit** in the app) stops the model, the voice and the server, and frees GPU memory.

After that, use the desktop shortcut. Later starts take seconds.

| Command | What it does |
|---|---|
| `Start Windows.bat` / `Start Mac.command` / `Start Linux.sh` | Install anything missing, then start |
| `… --update` | Update the LLM runtime and Python packages |
| `… --setup` | Re-run the hardware check and choose the brain and voice again |
| `… --no-window` | Run without opening a window (e.g. capture only in OBS from `http://127.0.0.1:8000`) |

**Uninstall:** delete the folder (and the desktop shortcut).

## Choosing a brain (LLM)

Open the **Brain** page to download, switch or delete models. Download progress shows speed and time remaining, can be cancelled, and resumes if interrupted.

| Model | Download | GPU memory for full speed | Notes |
|---|---|---|---|
| **Qwen3.8 27B Abliterated (IQ3_S)** | ~12 GB | 16 GB+ | Best conversation; uncensored; vision capable. On 8–12 GB GPUs it still runs (part on CPU) but replies start slower. |
| **Gemma 4 12B (Q4)** | ~7.5 GB | 10–12 GB | Faster on mid-range GPUs; vision capable. |
| Aya / Conversational 7B (Q4) | ~4.4 GB | 6 GB | Small, fine-tuned for personality. |

- **Add from Hugging Face** on the Brain page accepts any GGUF repository, for example a smaller Qwen3.8 quant, and lets you pick the exact file.
- You can also drop any `.gguf` into the models folder (**Brain → Models folder**) and it appears automatically.
- "Think before answering" is off by default: thinking adds a long pause before the VTuber speaks.
- llama.cpp auto-fits layers and context to your VRAM. Use **GPU layers → Manual** only to leave room for other apps.

### Use LM Studio, Ollama or an online API instead

On the **Brain** page choose **Use an API**. Presets cover **LM Studio**, **Ollama**, llama.cpp/KoboldCpp, **OpenAI**, **OpenRouter**, **Groq** and **Google Gemini**; any OpenAI-compatible server works with **Other**. Then:

1. Enter the address. For LM Studio on another PC, turn on *Serve on Local Network* in LM Studio and use that PC's address, e.g. `http://192.168.1.20:1234/v1`.
2. Add an API key if the service needs one.
3. Click **Test connection**, pick the model, and click **Use this API**.

The local model is unloaded while an API is in use, so your GPU stays free for games. API keys are stored in Windows Credential Manager or the macOS Keychain, not in the app's files.

## Choosing a voice

Open the **Voice** page and click **Install** on an engine. Each engine gets its own isolated environment, so they never conflict. Then select a voice from the library and type in the "Speak" box to hear it. It shows how long each line took, so you can compare engines.

| Engine | Speed | Quality | Languages | GPU memory |
|---|---|---|---|---|
| **Chatterbox Turbo** (recommended) | ●●●●○ | ●●●●● | English | ~4 GB |
| **LuxTTS** (fastest, CPU OK) | ●●●●● | ●●●●○ | English | ~1 GB |
| **OmniVoice** | ●●●○○ | ●●●●● | 600+ | ~5 GB |
| **TADA 1B / 3B** (Hume AI) | ●●●○○ | ●●●●○ | English / multilingual | ~6 / 12 GB |
| GPT-SoVITS (classic) | ●●●○○ | ●●●○○ | en, ja, zh, ko, yue | ~3 GB |

- **Add a voice:** drop a 6–15 second clean recording of one speaker and type exactly what is said. Every engine uses the same voice library. Chatterbox needs more than 5 seconds.
- **TADA** uses Meta Llama 3.2. Accept the licenses on huggingface.co ([Llama-3.2-1B](https://huggingface.co/meta-llama/Llama-3.2-1B), [tada-1b](https://huggingface.co/HumeAI/tada-1b)), then paste a free Hugging Face token in **Settings**.
- Only one engine runs at a time, so switching frees the previous engine's GPU memory.
- **Use a voice service instead:** choose **Voicebox** (on this or another PC; default port 17493), **OpenAI-compatible speech** (OpenAI, Kokoro-FastAPI, LocalAI, …) or **ElevenLabs** at the top of the Voice page, test the connection, and pick a voice.

## Performance monitor

The bar at the bottom of the app shows how much **CPU, RAM, GPU memory and GPU load** the brain, the voice, the character window and the rest of the app are using, next to everything else running on your PC. Click it for exact numbers per part and a short history. It helps you see whether a game or other program will have room. Where the operating system doesn't allow a reading (for example per-app GPU memory on some Windows drivers, or GPU details on macOS), the panel says so.

## Characters

On the **Character** page, choose **2D · Live2D** or **3D · VRM**, then:
- **Add .zip** or **Add folder** for Live2D (Cubism 3/4, including VTube Studio exports), or **Add .vrm** for 3D (e.g. VRoid Studio). You can also drag a `.zip`/`.vrm` onto the stage.
- Use the **⋯** menu on a model to **Replace** it with an updated version or **Delete** it.
- Live2D position and size have sliders plus exact number fields.

> The Live2D sample models in this repository are missing their texture files (they were never committed), so they show "Missing files". Use **Replace** with the full model, or use the bundled VRM characters.

## System requirements

- **Windows 10/11, macOS 12+ on Apple Silicon, or 64-bit Linux.** Intel Macs are not supported (no current PyTorch builds).
- **GPU:** NVIDIA GTX 10-series or newer (RTX 50-series supported), AMD/Intel via Vulkan for the LLM, or Apple Silicon. CPU-only works but is slow.
- **Disk:** ~10 GB for the app and one voice engine, plus the model (4–12 GB).
- Internet for the first setup and downloads; after that everything runs offline.

## Where things are stored

Everything is inside the app folder:

```
runtime/   private Python, app environment, voice-engine environments, llama.cpp
cache/     downloaded model weights (Hugging Face cache), app window profile
backend/services/LLM/Models/          language models (.gguf)
backend/services/TTS/GPTsovits/models/ voice library
backend/services/Character/...        Live2D and VRM models
backend/settings.json                  your settings
```

No log files are written; recent output is kept in memory and visible in the app (e.g. **Voice → ⋯ → Show log**). If you move or rename the folder, the next start updates its internal paths and the desktop shortcut automatically.

## Troubleshooting

- **"The LLM runtime is missing"**: run your start script with `--update` (e.g. `"Start Windows.bat" --update`).
- **A download stopped**: start again; downloads resume where they left off.
- **Replies are slow**: pick a smaller model (Gemma 4 12B), lower the memory window on the Brain page, or close other GPU-heavy apps.
- **No sound**: click once anywhere in the app window (browsers block audio until you interact), and check the Voice page shows the engine as *Running*.
- **Port 8000 in use**: set the environment variable `LAV_PORT` to another port before starting.

## Development

```bash
# backend (uses the environment created by the launcher)
runtime/envs/main/bin/python backend/server.py      # Windows: runtime\envs\main\Scripts\python.exe

# frontend with hot reload (proxies /api to the backend on :8000)
cd frontend && npm ci && npm run dev

# build the release zip (frontend build + packaging)
python launcher/package_release.py
```

Pushing a tag `v*` builds the zip in GitHub Actions and attaches it to the release.
