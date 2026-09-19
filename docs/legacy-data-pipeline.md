# Legacy prototype — synthetic data pipeline

> This was the repository's original README. It describes the pre-Munsiq
> prototype in `src/data_pipeline/`, which is kept working but is deprecated
> (see "Deprecated paths" in `CLAUDE.md`). The current system is described in
> the root [`README.md`](../README.md).

Staff-level MLOps scaffold for building a fine-tuned small LLM on a synthetic,
bilingual (Saudi Arabic / English) **industrial procurement** dataset —
Purchase Orders and Maintenance Logs.

## Repository layout

```
munsiq/
├── configs/                     # Declarative pipeline configuration (YAML)
│   └── data_generation.yaml
├── data/                        # Generated datasets (git-ignored)
├── notebooks/                   # Exploratory analysis / EDA
├── src/
│   └── data_pipeline/
│       ├── __init__.py
│       └── generate_data.py     # Synthetic data generator (Anthropic API)
├── .env.example                 # Template for local secrets
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      Unix: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then add your ANTHROPIC_API_KEY
```

## Step 1 — Generate the dataset

The data generator asks Claude (`claude-opus-4-8` by default) to produce
realistic, internally consistent procurement records. Each record has parallel
English and Saudi-Arabic fields plus a bilingual instruction/response pair, and
is written into the git-ignored `data/` folder.

```bash
# Uses configs/data_generation.yaml
python -m src.data_pipeline.generate_data

# Override settings on the CLI
python -m src.data_pipeline.generate_data --total-records 500 --batch-size 10
```

### Outputs (in `data/`)

| File | Contents |
| --- | --- |
| `procurement_records.jsonl` | One raw structured record per line (PO or maintenance log). |
| `procurement_finetune.jsonl` | Chat-formatted SFT examples (`{"messages": [...]}`), one EN + one AR per record. |

Configuration precedence: **CLI flags > env vars > `configs/data_generation.yaml` > defaults.**
