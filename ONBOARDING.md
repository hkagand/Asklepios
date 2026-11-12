# Getting started with Asklepios

A step-by-step setup for a new teammate's laptop. It takes about 30–45 minutes, most of it downloads. Everything in this
repository runs on **synthetic data only**: never load real patient records.

You will run five things on your laptop:

| What | Port | Started with |
|---|---|---|
| HAPI FHIR server (the patient records) | 8080 | Docker |
| National record service (simulated, for onboarding) | 8090 | `python -m national` |
| ASKlepios agent (the API and the model calls) | 8000 | `python -m agent` |
| Web app (what you open in the browser) | 5173 | `npm run dev` |
| Ollama with MedGemma (optional) | 11434 | Ollama app |

## 0. Ask for these first

From whoever is onboarding you:

1. **Model access:** the values for `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY`. Ideally a key of your own, so model
   use is attributed to you. Get it through a password manager or another secure channel, not plain email or chat.
2. **Network access to the model endpoint.** If it is on an internal network, you need to be on it (office network or
   VPN) for ASKlepios to answer.
3. **Push access to GitHub** (only if you will change code): ask to be added as a collaborator on
   [hkagand/Asklepios](https://github.com/hkagand/Asklepios). Cloning works without it; the repository is public.

## 1. Install the tools

| Tool | Version | Notes |
|---|---|---|
| [Git](https://git-scm.com/downloads) | any recent | |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | any recent | Start it after installing; it must be running whenever you use Asklepios. Check your company's Docker licence: Docker Desktop is free only for small organisations. |
| [Python](https://www.python.org/downloads/) | 3.12 or newer | On Windows, tick "Add python.exe to PATH" in the installer. |
| [Node.js](https://nodejs.org/) | 20 or newer | The LTS version is fine. |
| [Ollama](https://ollama.com/download) | optional | Only for the experimental "Clinical considerations" panel. Skip it at first. |

Check them in a new terminal:

```bash
git --version
docker --version
python --version
node --version
```

On macOS, `python` may be called `python3`; use that wherever this guide says `python`.

## 2. Get the code

```bash
git clone https://github.com/hkagand/Asklepios.git
cd Asklepios
```

## 3. Install the dependencies

Python, in a virtual environment inside the repository:

```bash
python -m venv .venv
```

Activate it. You will do this in every new terminal you use for Asklepios:

| Terminal | Command |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows Git Bash | `source .venv/Scripts/activate` |
| macOS / Linux | `source .venv/bin/activate` |

(If PowerShell refuses to run the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.)

Then:

```bash
pip install -r agent/requirements.txt
```

The web app:

```bash
cd web
npm install
cd ..
```

## 4. Configure the agent

Copy the example settings:

```bash
cp agent/.env.example agent/.env
```

(Windows PowerShell: `Copy-Item agent\.env.example agent\.env`)

Open `agent/.env` and fill in:

```
LLM_BASE_URL=   # from step 0
LLM_API_KEY=    # from step 0
LLM_MODEL=      # from step 0
LLM_REASONING_EFFORT=low
FHIR_BASE_URL=http://localhost:8080/fhir
AGENT_DEMO_RESET=1
```

`AGENT_DEMO_RESET=1` adds the **Reset demo** button, which puts every chart back to the loaded data after a demo.

`agent/.env` is never committed (git ignores it). Never put keys or internal hostnames in any other file.

## 5. Start the FHIR server

Make sure Docker Desktop is running, then from the repository root:

```bash
docker compose up -d
```

The first time it downloads the HAPI image, which takes a few minutes. Then wait until
[http://localhost:8080/fhir/metadata](http://localhost:8080/fhir/metadata) answers in your browser; HAPI needs about
a minute to start.

## 6. Generate and load the synthetic patients

```bash
python synthetic/generate.py --anchor YYYY-MM-DD --seed 2041
python synthetic/load.py
```

Use **today's date** for `--anchor`, e.g. `--anchor 2026-11-12`. It is "today" for the patient stories: today's
appointments, results waiting for review and so on are built around it.

Patient **names depend on the anchor**; ids (P-1001, P-1011, ...) and stories do not. To see exactly the same patients
as a teammate, for example to follow the same demo script, use their anchor and seed, and add
`AGENT_TODAY=<their anchor>` to `agent/.env` so the app treats that day as today.

HAPI keeps its data in memory: after Docker or your laptop restarts, run `python synthetic/load.py` again (no need to
generate again).

## 7. Start the services

Use three terminals, each in the repository root with the virtual environment activated (step 3).

Terminal 1, the simulated national record service:

```bash
python -m national
```

Terminal 2, the agent:

```bash
python -m agent
```

Terminal 3, the web app:

```bash
cd web
npm run dev
```

Leave all three running.

## 8. Check that it works

1. Open [http://localhost:8000/api/health](http://localhost:8000/api/health). It should show your model name,
   today's date and `"demoReset": true`.
2. Open [http://localhost:5173](http://localhost:5173).
3. At the top right, choose **Dr. Elif Aydın · Internal Medicine**.
4. **My day** shows her clinic list; **All appointments** shows everyone.
5. Open a patient, click **Ask ASKlepios**, and ask: `What was the last HbA1c?` The answer cites its sources as chips
   you can click.

If all of that works, you are set up. The [README](README.md) explains each feature.

## 9. Every day after that

1. Start Docker Desktop, then `docker compose up -d`.
2. If the computer or Docker restarted since last time, reload the data: `python synthetic/load.py`.
3. Start the three services (step 7).
4. After a demo, click **Reset demo** at the top to start clean.

## 10. Optional: MedGemma for clinical considerations

The visit workspace can show suggestions from a second, local clinical model. It is experimental: the evaluation in
the README shows a 4B model misses much of what the main model catches.

```bash
ollama pull medgemma1.5:4b
```

Then add to `agent/.env` and restart the agent:

```
CLINICAL_LLM_BASE_URL=http://localhost:11434/v1
CLINICAL_LLM_MODEL=medgemma1.5:4b
```

Without these lines the panel simply does not appear.

## 11. Changing the code

- Pull before you start: `git pull`.
- Work on a branch, not `main`: `git switch -c my-change`.
- Push it and open a pull request into `main` on GitHub.
- Run the eval checks that apply. `python -m evals --lint` needs no model; the README's "Evaluate" section lists the
  rest. Most of them call the model and take a few minutes.
- Before committing, check `git status`: `agent/.env`, `agent/cache/`, `agent/logs/`, `evals/runs/` and
  `synthetic/output/` must never be committed (they are in `.gitignore`).

## Troubleshooting

| You see | Usually means | Do this |
|---|---|---|
| "Could not load data from the FHIR server" | HAPI is not running or has no data | Check Docker Desktop, run `docker compose up -d`, then `python synthetic/load.py` |
| "The agent service is not reachable" | The agent is not running, or it hit an error | Look at terminal 2: start `python -m agent`, or read the error there |
| `python -m agent` stops with "Set LLM_BASE_URL and LLM_MODEL" | `agent/.env` is missing or incomplete | Redo step 4 |
| ASKlepios answers with a connection error | The model endpoint is unreachable or the key is wrong | Check the values from step 0 and your network or VPN |
| `python -m agent` says port 8000 is in use | Another program has port 8000 | Start the agent on 8001 and point the web app at it (below) |
| New patient: "national record service is not reachable" | Terminal 1 is not running | Start `python -m national` |
| Everyone's name differs from a teammate's screen | A different `--anchor` | See step 6 |

Running the agent on another port, e.g. 8001:

| Terminal | Agent | Web app |
|---|---|---|
| Windows PowerShell | `$env:AGENT_PORT="8001"; python -m agent` | `$env:AGENT_SERVER="http://localhost:8001"; npm run dev` |
| macOS / Linux / Git Bash | `AGENT_PORT=8001 python -m agent` | `AGENT_SERVER=http://localhost:8001 npm run dev` |
