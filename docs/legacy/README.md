# Legacy

Things from before Munsiq became a document-extraction system. Kept because the
decisions they record are still referenced, not because anything here runs.

| File | What it was | Superseded by |
| --- | --- | --- |
| `Modelfile` | Ollama definition of `munsiq-extractor`, a LoRA fine-tune with five fixed output columns | [ADR 002](../adr/002-schema-conditioned-prompting.md) |
| `../../legacy/` | The pandas → Excel batch pipeline, the fine-tuning notebook, and generated datasets | The FastAPI backend and the review workspace |

The merged model weights (`Qwen2.5-7B-Instruct.Q4_K_M.gguf`, ~4.3 GiB) are
git-ignored and are not in this repository.
