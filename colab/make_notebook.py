import json, pathlib
cells = []
def md(t): cells.append({"cell_type":"markdown","metadata":{},"source":t.strip().splitlines(True)})
def code(t): cells.append({"cell_type":"code","metadata":{},"execution_count":None,"outputs":[],"source":t.strip().splitlines(True)})

md("""# SupplierGraph on Colab
Run the cells top to bottom. **Stop at the data check (step 4) and read it** before the long steps.
Put in Drive (anywhere, subfolders are searched): this notebook's code zip `suppliergraph_colab.zip`, GLEIF Level 1 + Level 2 zips, `full.jsonl.gz` (OCDS, publication 136), CPV zip, `targets.simple.csv`, the CELEX PDF.
Secrets (key icon, left bar): `HF_TOKEN` (or `ANTHROPIC_API_KEY`), notebook access ON.""")

code('''# 1. SETTINGS - edit these
DRIVE_ROOT   = "/content/drive/MyDrive"     # searched recursively for the data files and the code zip
OUT_DIR      = DRIVE_ROOT + "/suppliergraph_out"
CODE_ZIP     = "suppliergraph_colab.zip"
GLEIF_COUNTRIES = "DE"                      # comma list, e.g. "DE,AT,FR"; "" = all (needs far more RAM/time)
OCDS_LIMIT   = 20000                        # releases to read; 0 = ALL. Start small (dry run), then set 0
LLM_PROVIDER = "hf"                         # "hf" | "anthropic" | "openai_compat"
LLM_MODEL    = ""                           # REQUIRED for hf: a model id you have verified on huggingface.co/inference/models''')

code('''# 2. Mount Drive, unpack code
from google.colab import drive
drive.mount("/content/drive")
import os, glob, zipfile
hits = [p for p in glob.glob(DRIVE_ROOT + "/**/" + CODE_ZIP, recursive=True)]
assert hits, f"{CODE_ZIP} not found under {DRIVE_ROOT}"
os.makedirs("/content/sg", exist_ok=True)
zipfile.ZipFile(hits[0]).extractall("/content/sg")
os.chdir("/content/sg"); os.makedirs(OUT_DIR, exist_ok=True)
print("code at", os.getcwd(), os.listdir("."))''')

code('''# 3. Install (a few minutes)
!apt-get -qq install -y poppler-utils > /dev/null
!pip -q install -e ".[etl,llm]"
!pip -q install falcon''')

code('''# 4. Stage data from Drive into data/raw, then check each source. READ THE OUTPUT.
!python scripts/colab_prepare.py --drive "{DRIVE_ROOT}" --root .
!sg data check gleif1
!sg data check gleif2
!sg data check cpv
!sg data check sanctions
!sg data check ocds''')

code('''# 5. Environment + LLM check (run this after a restart too)
import os, sys
sys.path.insert(0, "/content/sg/src")      # makes `suppliergraph` importable in this kernel
from google.colab import userdata
for k in ("HF_TOKEN", "ANTHROPIC_API_KEY"):
    try: os.environ[k] = userdata.get(k)
    except Exception: pass
os.environ["SG_LLM_PROVIDER"] = LLM_PROVIDER
if LLM_MODEL: os.environ["SG_LLM_MODEL"] = LLM_MODEL
os.environ["SG_OCDS_LIMIT"] = str(OCDS_LIMIT)
from suppliergraph.llm import get_llm
llm = get_llm()
print(type(llm).__name__)
print(llm.complete("You are terse.", "Reply with the single word: ready", max_tokens=10))''')

code('''# 5b. AFTER A RESTART ONLY: restore the saved graph and model from Drive instead of rebuilding (skip steps 4 and 6-8)
import shutil
for sub in ("data", "models"):
    src = f"{OUT_DIR}/{sub}"
    assert os.path.exists(src), f"nothing saved at {src}"
    shutil.copytree(src, f"/content/sg/{sub}", dirs_exist_ok=True)
!ls -la /content/sg/data /content/sg/models/current''')

code('''# 6. Build: staging DB -> ingest -> entity resolution -> obligations -> knowledge graph -> validation
countries = f"--countries {GLEIF_COUNTRIES}" if GLEIF_COUNTRIES else ""
!sg init-db
!sg ingest {countries}
!sg resolve
!sg extract
!sg build-kg
!sg validate
!sg er-eval''')

code('''# 7. Train embeddings (evaluation split, then final model for serving)
!sg train
!sg train --final''')

code('''# 8. Evaluation of the question answering (uses the LLM; budget the API calls)
!sg eval''')

code('''# 9. Save results to Drive (everything except the raw inputs)
import shutil
for f in os.listdir("data"):
    if f != "raw":
        src = os.path.join("data", f)
        (shutil.copytree(src, f"{OUT_DIR}/data/{f}", dirs_exist_ok=True) if os.path.isdir(src)
         else (os.makedirs(f"{OUT_DIR}/data", exist_ok=True), shutil.copy(src, f"{OUT_DIR}/data/{f}")))
if os.path.exists("models"): shutil.copytree("models", f"{OUT_DIR}/models", dirs_exist_ok=True)
!ls -la "{OUT_DIR}/data" "{OUT_DIR}/models"''')

code('''# 10. Serve the app (API + UI) and open it
import subprocess, time
srv = subprocess.Popen(["sg","serve","--host","0.0.0.0","--port","8000"], stdout=open("serve.log","w"), stderr=subprocess.STDOUT)
time.sleep(15); print(open("serve.log").read()[-1500:])
from google.colab import output
output.serve_kernel_port_as_window(8000)''')

code('''# 10b. Fallback if the window does not open: public tunnel (anyone with the URL can reach the app)
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared && chmod +x cloudflared
import subprocess, re, time
t = subprocess.Popen(["./cloudflared","tunnel","--url","http://localhost:8000"], stderr=subprocess.PIPE, text=True)
for line in t.stderr:
    m = re.search(r"https://[a-z0-9-]+\\.trycloudflare\\.com", line)
    if m: print(m.group(0)); break''')

code('''# 11. See the knowledge graph (opens an interactive picture of the best-connected suppliers and what surrounds them)
import sys; sys.path.insert(0, "/content/sg/src")
from suppliergraph.config import get_settings
from suppliergraph.store import open_store
from suppliergraph.kg.explore import render
store = open_store(get_settings())
print("triples:", store.triple_count())
print(render(store, "/content/kg_explorer.html", hops=2, max_nodes=150))
import IPython; IPython.display.display(IPython.display.HTML(filename="/content/kg_explorer.html"))''')

code('''# 12. If the Ask tab shows an error, the server's own message is here
!tail -40 /content/sg/serve.log''')

nb = {"cells":cells,"metadata":{"kernelspec":{"name":"python3","display_name":"Python 3"},"colab":{"provenance":[]}},"nbformat":4,"nbformat_minor":5}
pathlib.Path("colab/SupplierGraph_Colab.ipynb").write_text(json.dumps(nb, indent=1))
