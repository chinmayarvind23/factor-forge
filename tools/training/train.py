"""Train a local LoRA candidate from a verified, explicitly reviewed trajectory bundle."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

from prepare import Review, canonical, prepare

from factorforge.data.artifacts import LocalArtifactStore


def digest(path: Path) -> str:
    """Stream model weights so provenance capture does not duplicate them in memory."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def model_inventory(root: Path) -> dict[str, str]:
    """Pin all local model bytes; remote-code loading and pickle weights remain disabled."""
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Model must be a local directory")
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("Use a materialized local model directory without symlinks")
    return {path.relative_to(root).as_posix(): digest(path) for path in paths if path.is_file()}


def main() -> None:
    """Bound local training, preserve a receipt on failure, and never promote automatically."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.steps <= 200 or not 128 <= args.max_length <= 8192:
        raise ValueError("Steps must be 1..200 and sequence length 128..8192")
    if not 0 <= args.seed < 2**32:
        raise ValueError("Seed must fit an unsigned 32-bit integer")
    manifest = json.loads((args.bundle / "manifest.json").read_bytes())
    if manifest.get("schema_version") != "training-bundle-v1":
        raise ValueError("Unsupported training bundle")
    if set(manifest["files"]) != {"train.jsonl", "review.json"}:
        raise ValueError("Training bundle inventory differs")
    for name, expected in manifest["files"].items():
        if digest(args.bundle / name) != expected:
            raise ValueError("Training bundle bytes differ")
    review_raw = (args.bundle / "review.json").read_bytes()
    review = Review.model_validate_json(review_raw)
    rows = prepare(review, LocalArtifactStore(args.artifacts), manifest["mode"])
    dataset_raw = b"".join(canonical(row) + b"\n" for row in rows)
    if (args.bundle / "train.jsonl").read_bytes() != dataset_raw or len(rows) != manifest["rows"]:
        raise ValueError("Training bundle differs from reviewed source attempts")
    weights = model_inventory(args.model)
    if not any(name.endswith(".safetensors") for name in weights):
        raise ValueError("Local model must contain safetensors weights")
    args.output.mkdir(parents=True, exist_ok=False)
    # These controls keep model loading and telemetry local, including inherited defaults.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TRL_DISABLE_TELEMETRY"] = "1"
    receipt = dict(
        schema_version="training-run-v1",
        status="started",
        promotion="candidate_only",
        bundle=manifest,
        model_files=weights,
        steps=args.steps,
        seed=args.seed,
        max_length=args.max_length,
        cpu=args.cpu,
        code={
            name: digest(Path(__file__).parent / name)
            for name in ("train.py", "prepare.py", "uv.lock")
        },
    )
    (args.output / "review.json").write_bytes(review_raw)
    (args.output / "train.jsonl").write_bytes(dataset_raw)
    (args.output / "receipt.json").write_bytes(canonical(receipt))
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed
        from trl import DPOConfig, DPOTrainer, SFTConfig, SFTTrainer

        torch.set_num_threads(2)
        set_seed(args.seed)
        receipt["packages"] = {
            name: importlib.metadata.version(name)
            for name in ("torch", "trl", "transformers", "peft", "datasets")
        }
        tokenizer = AutoTokenizer.from_pretrained(
            str(args.model.resolve()), local_files_only=True, trust_remote_code=False
        )
        if tokenizer.chat_template is None or tokenizer.eos_token is None:
            raise ValueError("Training requires a chat template and EOS token")
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        for row in rows:
            prompt_tokens = tokenizer.apply_chat_template(
                row["prompt"], tokenize=True, add_generation_prompt=True
            )
            for key in ("completion",) if manifest["mode"] == "sft" else ("chosen", "rejected"):
                tokens = tokenizer.apply_chat_template(row["prompt"] + row[key], tokenize=True)
                if tokens[: len(prompt_tokens)] != prompt_tokens or len(tokens) <= len(
                    prompt_tokens
                ):
                    raise ValueError(
                        "Chat template does not preserve prompt/response token boundary"
                    )
                # Reserve an extra EOS token for trainer formatting; never truncate labels.
                if len(tokens) + 1 > args.max_length:
                    raise ValueError(
                        "Reviewed response exceeds sequence budget; truncation refused"
                    )
        model = AutoModelForCausalLM.from_pretrained(
            str(args.model.resolve()),
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            dtype=torch.float32,
        )
        common = dict(
            output_dir=str(args.output / "checkpoints"),
            max_steps=args.steps,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=1,
            learning_rate=2e-5,
            seed=args.seed,
            data_seed=args.seed,
            max_length=None,
            report_to="none",
            push_to_hub=False,
            save_strategy="no",
            logging_steps=1,
            bf16=False,
            fp16=False,
            use_cpu=args.cpu,
            gradient_checkpointing=False,
        )
        adapter = LoraConfig(
            r=8, lora_alpha=16, lora_dropout=0.0, target_modules="all-linear", task_type="CAUSAL_LM"
        )
        trainer_class = SFTTrainer if manifest["mode"] == "sft" else DPOTrainer
        config = (
            SFTConfig(**common, completion_only_loss=True, packing=False)
            if manifest["mode"] == "sft"
            else DPOConfig(**common, beta=0.1)
        )
        trainer = trainer_class(
            model=model,
            args=config,
            train_dataset=Dataset.from_list(rows),
            processing_class=tokenizer,
            peft_config=adapter,
        )
        result = trainer.train()
        trainer.save_model(str(args.output / "adapter"))
        tokenizer.save_pretrained(str(args.output / "adapter"))
        trainer.state.save_to_json(str(args.output / "trainer-state.json"))
        if model_inventory(args.model) != weights:
            raise ValueError("Base model bytes changed during training")
        receipt.update(
            status="completed",
            optimizer_steps=trainer.state.global_step,
            training_metrics=result.metrics,
            adapter_files=model_inventory(args.output / "adapter"),
        )
    except BaseException as error:
        receipt.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        (args.output / "receipt.json").write_bytes(canonical(receipt))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
