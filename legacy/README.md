# legacy/

The prototype that preceded Munsiq: a synthetic-data generator, a LoRA
fine-tuning notebook for Qwen2.5-7B, and a pandas → Excel batch reporter that
called Ollama directly.

**Not maintained. Nothing in `backend/` or `frontend/` imports from here.**

| Path | Contents |
| --- | --- |
| `src/data_pipeline/` | `build_report.py` (raw text → Ollama → Excel) and `stress_test.py` |
| `notebooks/` | The fine-tuning notebook for the `munsiq-extractor` model |
| `data/` | Generated datasets and reports — git-ignored, never committed |
| `requirements.txt`, `.env.example` | Dependencies and env template for the above |

Two things worth knowing before you trust any of it:

* `src/data_pipeline/generate_data.py`, which the original README describes, was
  **never committed** and is not on disk — only its compiled bytecode survived.
  The datasets in `data/` are what it produced.
* Paths inside these scripts assume they run from the old repository root, so
  they need adjusting to run from here.

Why it was replaced: [ADR 002](../docs/adr/002-schema-conditioned-prompting.md).
Original README: [docs/legacy-data-pipeline.md](../docs/legacy-data-pipeline.md).
