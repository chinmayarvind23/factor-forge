# Local research-policy training

This optional environment implements **PyTorch/TRL LoRA SFT and DPO** from retained
research attempts. Preparation replays the existing trajectory exporter against its
content-addressed source, then selects responses identified by explicit review labels.
The trainer repeats that verification before loading a model and writes a separate
candidate adapter with source, configuration, package and model hashes.

## Prepare a reviewed corpus

Use Python 3.12 and the regular project environment for preparation; this step does
not install PyTorch or load a model:

```powershell
uv run python tools/training/prepare.py --review review.json --artifacts artifacts/research --mode sft --output artifacts/sft-bundle
```

`review.json` follows [the review schema](review.schema.json):

- `reviewer`, `environment_version`, and `rubric_version` identify the review and
  frozen development task. `development_only_attested` must be true.
- `train_exports` and `heldout_exports` contain artifact references to retained
  `trajectory-export-v1` manifests. Both inventories are mandatory. Store a manifest
  using `LocalArtifactStore.put(export.canonical_bytes(), media_type="application/json")`
  and use the returned reference. See [trajectory export](../../docs/research.md).
- Each selection names a `chosen` provider-record SHA-256 and a review `rationale`.
  SFT requires no `rejected` entry. DPO requires a `rejected` provider-record SHA-256
  whose prompt matches exactly and whose retained response differs.

Source delivery status never supplies a correctness reward. Failed responses remain
in source history and can be explicitly reviewed as rejected preference examples.
Unreviewed attempts are retained without entering the selected training rows.

Training exports must declare the development partition. Preparation rejects shared
run identities and exact prompt overlap with the supplied held-out exports. The
reviewer must supply the complete protected inventory and check shared papers,
paraphrases, licensing and sensitive content. These byte checks do not establish
semantic isolation or independently authenticate the reviewer. Keep protected
evaluation material out of training.

## Train a local candidate

Install the isolated locked environment only when ready to train:

```powershell
uv sync --project tools/training --locked
uv run --project tools/training --locked python tools/training/train.py --bundle artifacts/sft-bundle --artifacts artifacts/research --model models/local-chat-model --output artifacts/policy-candidate --steps 20 --max-length 2048 --cpu
```

Use a materialized local causal-language-model directory with safetensors weights,
a tokenizer, EOS token and chat template. Model downloads are deliberately a separate
operator step. Remote code, Hub uploads and training telemetry are disabled. Omit
`--cpu` to let the installed PyTorch runtime use an available accelerator. This is
local compute; the free static Hugging Face dashboard does not run training jobs.

For DPO, prepare with `--mode dpo` and supply reviewed chosen/rejected pairs; the same
trainer command reads the mode from the bundle. LoRA uses rank 8, alpha 16 and all
linear target modules. SFT computes completion-only loss. DPO uses beta 0.1 and the
base policy as the adapter reference. Steps are bounded to 1–200; sequences exceeding
the selected length are rejected during preflight. Batch size is one, seed defaults
to 42, and CPU intra-op parallelism is limited to two threads.

The output contains the review, exact dataset, run receipt, trainer state and adapter.
A failure records its error type and leaves evidence in the fresh output directory;
reruns require a new directory. Source model files are hashed before and after training.
The receipt records actual training metrics only after the trainer returns successfully.
Reproducibility still depends on hardware and runtime behavior; a seed alone does not
guarantee identical floating-point results.

Adapters remain candidates. This command does not register, promote or install a
learned policy into the research workflow. Authorization, budgets, source admission,
accounting and lineage verification remain deterministic production controls. Promotion
requires a separate, authorized comparison against the prompted baseline.

API references: [TRL SFT](https://huggingface.co/docs/trl/sft_trainer),
[TRL DPO](https://huggingface.co/docs/trl/dpo_trainer), and
[PEFT LoRA](https://huggingface.co/docs/peft/package_reference/lora).
