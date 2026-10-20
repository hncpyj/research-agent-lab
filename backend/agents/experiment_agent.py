"""
Experiment Agent (Phase 5)

Reads the generated hypotheses from NoteDB, auto-selects one (in UI mode)
or prompts the user (in CLI mode), then uses the Claude API to generate a
complete, runnable experiment codebase tailored to the research domain.

Improvements over the original RL-only version:
  A — Domain-specific file templates:
      Retrieval → bi_encoder + BM25 baseline + BEIR evaluation
      NLP       → HuggingFace Trainer + TF-IDF baseline
      CV        → ResNet/ViT + supervised baseline
      DA        → DANN/MMD + source-only baseline
      RL        → original PPO / transformer_pe / recurrent files

  B — Real dataset integration:
      tools.dataset_resolver maps the hypothesis text to a real public
      benchmark (MS-MARCO, CIFAR-10, AG News, …) and injects its HF id,
      realistic sizes, and a loader snippet into every prompt template.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from router import TaskType

if TYPE_CHECKING:
    from models.api_model import APIModel
    from memory.note_db import NoteDB

logger = logging.getLogger(__name__)
console = Console()


# ===========================================================================
# Domain-aware system prompts
# ===========================================================================

_SYSTEM_RL = (
    "You are a senior ML engineer specialising in reinforcement learning "
    "and sequence modelling with PyTorch. "
    "Generate complete, runnable Python/YAML code. "
    "Never use placeholder comments like '# TODO' or '# implement this'. "
    "All functions must have full, working implementations."
)

_SYSTEM_RETRIEVAL = (
    "You are a senior ML engineer specialising in information retrieval, "
    "dense passage retrieval, and bi-encoder systems (DPR, SBERT, BEIR). "
    "Generate complete, runnable Python/YAML code. "
    "Use standard IR metrics (Recall@K, MRR, nDCG). "
    "Use FAISS for ANN search. "
    "Always include a BM25 baseline. "
    "Never use RL frameworks (gymnasium, MiniGrid, PPO). "
    "Never use placeholder comments. All functions must have full implementations."
)

_SYSTEM_NLP = (
    "You are a senior ML engineer specialising in NLP, text classification, "
    "and language model fine-tuning with HuggingFace Transformers. "
    "Generate complete, runnable Python/YAML code. "
    "Use standard NLP metrics (accuracy, F1, BLEU, ROUGE). "
    "Always include BERT-base and a TF-IDF baseline. "
    "Never use RL frameworks unless the research explicitly requires it. "
    "Never use placeholder comments. All functions must have full implementations."
)

_SYSTEM_CV = (
    "You are a senior ML engineer specialising in computer vision, "
    "image classification, and self-supervised representation learning. "
    "Generate complete, runnable Python/YAML code using PyTorch and torchvision. "
    "Use standard CV metrics (top-1/top-5 accuracy, mAP). "
    "Always include a supervised baseline with pretrained ResNet or ViT. "
    "Never use placeholder comments. All functions must have full implementations."
)

_SYSTEM_DOMAIN_ADAPTATION = (
    "You are a senior ML engineer specialising in domain adaptation, "
    "transfer learning, and distribution shift (DANN, MMD, CORAL). "
    "Generate complete, runnable Python/YAML code. "
    "Always include a 'source-only' baseline and a fine-tuning baseline. "
    "Evaluate on real target-domain datasets. "
    "Never use placeholder comments. All functions must have full implementations."
)

_SYSTEM = _SYSTEM_RL  # kept for backward compatibility

# Domain routing (keywords, system prompt, file specs) is unified into a
# single _DOMAIN_REGISTRY further down this file, right after the file specs
# it needs are defined (_FILE_SPECS_RL etc.) — see the comment there for why
# this used to be two separately-maintained keyword lists and why that was
# a live bug, not just a hypothetical one.


# ===========================================================================
# Utility
# ===========================================================================

def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```python … ```) if present."""
    match = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


# ===========================================================================
# RL domain prompt templates  (original — kept unchanged)
# ===========================================================================

_RL_CONFIG_PROMPT = """\
Generate a complete config.yaml for the following RL experiment.

Hypothesis: {content}

Experiment design:
{design_json}

Dataset / environment info:
{dataset_info}

The YAML must include sections:
  experiment:   (name, seed, device)
  env:          (name, max_steps, horizon_short, horizon_long, obs_history_len)
  model:        (type, d_model, n_heads, n_layers, pe_type, dropout)
  training:     (algorithm, lr, batch_size, n_epochs, gamma, clip_epsilon,
                 value_coeff, entropy_coeff, max_grad_norm)
  pretrain:     (enabled, mask_ratio, pretrain_steps, pretrain_lr)
  evaluation:   (eval_every, n_eval_episodes, horizons_to_test, metrics list)
  ablations:    (pe_types list, baselines list)
  logging:      (use_wandb, project, save_checkpoints, checkpoint_every)

Use MiniGrid-FourRooms-v0 as the default environment.
Output ONLY the YAML content, no markdown fences."""

_RL_TRAIN_PROMPT = """\
Generate a complete train.py for the following RL experiment.

Hypothesis: {content}
Experiment design (JSON): {design_json}
Dataset / environment: {dataset_info}

Requirements:
- Load config from config.yaml via PyYAML (argparse --config flag)
- Set random seeds for torch, numpy, random
- Instantiate environment via make_env() from envs/wrappers.py
- Instantiate policy from models/transformer_pe.py (TransformerPEPolicy)
  or models/recurrent.py depending on config.model.type
- Optional pre-training: if config.pretrain.enabled, load weights from
  checkpoints/pretrained.pt if it exists, else call pretrain.py logic
- PPO training loop:
    * collect_rollout(): gather episodes using current policy
    * ppo_update(): compute actor + critic loss, apply gradient clipping
    * log metrics every eval_every epochs
    * save checkpoint every checkpoint_every epochs to checkpoints/
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_RL_TRANSFORMER_PE_PROMPT = """\
Generate models/transformer_pe.py implementing three positional encoding
variants for a Transformer-based RL policy network.

Hypothesis: {content}
Experiment design (JSON): {design_json}

The file must define:
1. SinusoidalPE(nn.Module)
   - Fixed sinusoidal encoding (no learnable params)
   - forward(x: Tensor[B,T,D]) -> Tensor[B,T,D]

2. LearnedPE(nn.Module)
   - nn.Embedding(max_len, d_model)
   - forward(x: Tensor[B,T,D]) -> Tensor[B,T,D]

3. ALiBiMultiheadAttention(nn.Module)
   - Standard MultiheadAttention + ALiBi relative bias
   - bias[h,i,j] = -slope_h * |i - j|
   - slopes computed as per ALiBi paper (geometric sequence)
   - forward(x, key_padding_mask=None) -> Tensor[B,T,D]

4. TransformerPEPolicy(nn.Module)
   - __init__(pe_type, obs_dim, action_dim, d_model, n_heads, n_layers,
              max_seq_len, dropout)
   - pe_type: "sinusoidal" | "learned" | "alibi"
   - forward(obs_seq: Tensor[B,T,obs_dim], padding_mask=None)
       -> (action_logits: Tensor[B,action_dim], value: Tensor[B,1])
   - get_value(obs_seq) -> Tensor[B,1]

Output ONLY the Python source code, no markdown fences."""

_RL_RECURRENT_PROMPT = """\
Generate models/recurrent.py implementing LSTM and GRU baseline policies.

The file must define:
1. LSTMPolicy(nn.Module)
   - __init__(obs_dim, hidden_dim, action_dim, n_layers)
   - forward(obs: Tensor[B,obs_dim], hx: tuple[Tensor,Tensor])
       -> (action_logits, value, hx_new)
   - init_hidden(batch_size, device) -> tuple[Tensor,Tensor]

2. GRUPolicy(nn.Module)
   - __init__(obs_dim, hidden_dim, action_dim, n_layers)
   - forward(obs: Tensor[B,obs_dim], hx: Tensor[B,hidden_dim])
       -> (action_logits, value, hx_new)
   - init_hidden(batch_size, device) -> Tensor

3. get_recurrent_policy(rnn_type: str, **kwargs) -> nn.Module
   - Factory: "lstm" -> LSTMPolicy, "gru" -> GRUPolicy

Output ONLY the Python source code, no markdown fences."""

_RL_WRAPPERS_PROMPT = """\
Generate envs/wrappers.py providing gymnasium environment wrappers.

Hypothesis: {content}
Experiment design (JSON): {design_json}

The file must define:
1. HorizonWrapper(gymnasium.Wrapper)
   - Truncates episodes at `horizon` steps

2. ObsHistoryWrapper(gymnasium.ObservationWrapper)
   - Maintains a deque of last history_len observations
   - On reset: fills deque with copies of initial obs
   - observation() returns np.stack(deque) -> shape (history_len, *obs_shape)

3. FlattenObsWrapper(gymnasium.ObservationWrapper)
   - Flattens dict/image observations to a 1D float32 vector

4. make_env(env_name, horizon, history_len, seed=0) -> gymnasium.Env
   - Apply FlattenObsWrapper, HorizonWrapper, ObsHistoryWrapper in order

Handle ImportError for minigrid gracefully.
Output ONLY the Python source code, no markdown fences."""

_RL_PRETRAIN_PROMPT = """\
Generate pretrain.py implementing trajectory masked autoencoding pre-training
for a Transformer RL policy.

Hypothesis: {content}
Experiment design (JSON): {design_json}

Requirements:
- Load config.yaml via PyYAML (--config flag)
- Collect random trajectories from the environment
- Apply random token masking (mask_ratio from config) to obs sequences
- Train TransformerPEPolicy to reconstruct masked observations (MSE loss)
- Save checkpoint to checkpoints/pretrained.pt
- Print progress with rich
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_RL_EVALUATE_PROMPT = """\
Generate evaluate.py for measuring RL policy performance.

Hypothesis: {content}
Experiment design (JSON): {design_json}

The script must:
1. Load config.yaml (--config flag) and checkpoint (--checkpoint flag)
2. For each pe_type in config.ablations.pe_types + config.ablations.baselines:
   a. For each horizon in config.evaluation.horizons_to_test:
      - Run n_eval_episodes episodes
      - Compute mean_return, success_rate
3. Compute credit_assignment_gap = mean_return(long) - mean_return(short)
4. Print a rich Table: rows=pe_types, columns=horizons + gap
5. Save results/eval_results.json
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_RL_REQUIREMENTS_PROMPT = """\
Generate requirements.txt for a PyTorch RL experiment using MiniGrid.

Experiment design: {design_json}

Include realistic pinned versions for:
gymnasium, minigrid, torch, numpy, pyyaml, rich, wandb

Output ONLY the requirements.txt content, no markdown."""

_FILE_SPECS_RL: list[tuple[str, str, str]] = [
    ("config.yaml",              _RL_CONFIG_PROMPT,          "yaml"),
    ("train.py",                 _RL_TRAIN_PROMPT,           "python"),
    ("models/transformer_pe.py", _RL_TRANSFORMER_PE_PROMPT,  "python"),
    ("models/recurrent.py",      _RL_RECURRENT_PROMPT,       "python"),
    ("envs/wrappers.py",         _RL_WRAPPERS_PROMPT,        "python"),
    ("pretrain.py",              _RL_PRETRAIN_PROMPT,         "python"),
    ("evaluate.py",              _RL_EVALUATE_PROMPT,         "python"),
    ("requirements.txt",         _RL_REQUIREMENTS_PROMPT,     "text"),
]

# Legacy alias so old code that referenced _FILE_SPECS still works
_FILE_SPECS = _FILE_SPECS_RL


# ===========================================================================
# RETRIEVAL domain prompt templates
# ===========================================================================

_RETRIEVAL_CONFIG_PROMPT = """\
Generate a complete config.yaml for the following information retrieval experiment.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

The YAML must include sections:
  experiment:  (name, seed, device)
  dataset:     (name, hf_dataset_id, subset, train_split, test_split,
                max_train_samples, max_val_samples)
  model:       (type: "bi_encoder", encoder_name: "sentence-transformers/all-MiniLM-L6-v2",
                embedding_dim, max_seq_len, pooling: "mean")
  training:    (lr, batch_size, epochs, warmup_steps, weight_decay,
                in_batch_negatives: true, hard_negatives_per_query: 4)
  index:       (type: "faiss_flat", nprobe: 64)
  evaluation:  (metrics: [Recall@10, Recall@100, MRR@10, nDCG@10],
                top_k_values: [10, 100])
  baselines:   (bm25: true, tfidf: false)
  logging:     (use_wandb, project, save_checkpoints, checkpoint_every)

Use the dataset name and id from the dataset info above.
Output ONLY the YAML content, no markdown fences."""

_RETRIEVAL_TRAIN_PROMPT = """\
Generate a complete train.py for a bi-encoder (DPR-style) information retrieval model.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

Requirements:
- Load config from config.yaml (argparse --config flag)
- Load dataset using HuggingFace datasets library with the id from dataset_info
- Build query encoder and document encoder (shared or separate SentenceTransformer)
- Contrastive training with in-batch negatives:
    * for each (query, positive_passage) pair in batch:
      - encode all queries and all passages
      - compute dot-product similarity matrix (B x B)
      - cross-entropy loss over diagonal (positive pairs)
- Evaluate Recall@10 on validation set every eval_every epochs
- Save best checkpoint to checkpoints/best_model/
- Print training progress with rich
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_RETRIEVAL_EVALUATE_PROMPT = """\
Generate a complete evaluate.py for an information retrieval experiment.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

The script must:
1. Load config.yaml (--config flag) and bi-encoder checkpoint
2. Build a FAISS index over all passages in the dataset
3. For each query in the validation/test set:
   - Encode the query
   - Retrieve top-100 passages using FAISS
   - Compute Recall@10, Recall@100, MRR@10, nDCG@10
4. Run BM25 baseline (from baselines/bm25_baseline.py) for comparison
5. Print a rich comparison table: rows=[bi_encoder, bm25], columns=metrics
6. Save results to results/eval_results.json
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_RETRIEVAL_BIENCODER_PROMPT = """\
Generate models/bi_encoder.py implementing a DPR-style bi-encoder.

Hypothesis: {content}

The file must define:
1. BiEncoder(nn.Module)
   - __init__(encoder_name: str, embedding_dim: int, shared_encoder: bool = False)
   - query_encoder and doc_encoder (SentenceTransformer or HF AutoModel)
   - encode_queries(texts: list[str]) -> Tensor[N, dim]
   - encode_docs(texts: list[str]) -> Tensor[N, dim]
   - forward(query_texts, doc_texts) -> (query_embeds, doc_embeds)

2. contrastive_loss(query_embeds: Tensor, doc_embeds: Tensor,
                    temperature: float = 1.0) -> Tensor
   - In-batch negatives cross-entropy loss
   - Returns scalar loss

3. build_faiss_index(doc_embeddings: np.ndarray) -> faiss.Index
   - Returns a flat L2 FAISS index

4. retrieve(query_embeds: Tensor, index: faiss.Index,
            top_k: int = 100) -> tuple[np.ndarray, np.ndarray]
   - Returns (distances, indices) arrays of shape [N, top_k]

Output ONLY the Python source code, no markdown fences."""

_RETRIEVAL_BM25_PROMPT = """\
Generate baselines/bm25_baseline.py implementing a BM25 retrieval baseline.

The file must define:
1. BM25Retriever
   - __init__(passages: list[str], k1: float = 1.5, b: float = 0.75)
   - Tokenises passages and builds rank_bm25.BM25Okapi index
   - retrieve(query: str, top_k: int = 100) -> list[tuple[int, float]]
     (returns list of (passage_idx, score) sorted descending)

2. evaluate_bm25(retriever: BM25Retriever, queries: list[str],
                 relevant_passages: list[list[int]],
                 top_k_values: list[int] = [10, 100]) -> dict
   - Computes Recall@K and MRR@10 for each query
   - Returns {"Recall@10": float, "Recall@100": float, "MRR@10": float}

3. if __name__ == "__main__": demo block that shows BM25 usage.

Use rank_bm25.BM25Okapi. Output ONLY the Python source code, no markdown fences."""

_RETRIEVAL_DATALOADER_PROMPT = """\
Generate data/dataset_loader.py for loading and preprocessing retrieval datasets.

Dataset info: {dataset_info}

The file must define:
1. load_retrieval_dataset(config: dict) -> tuple[Dataset, Dataset, list[str]]
   - Loads the HuggingFace dataset using the hf_dataset_id and subset from config
   - Returns (train_dataset, val_dataset, all_passages)
   - all_passages: flat list of all unique passage texts (for FAISS indexing)

2. RetrievalDataset(torch.utils.data.Dataset)
   - __init__(hf_dataset, tokenizer, max_length: int = 128)
   - __getitem__ returns dict with query_input_ids, query_attention_mask,
     pos_input_ids, pos_attention_mask (tokenised query + positive passage)
   - __len__

3. get_dataloader(dataset: RetrievalDataset, batch_size: int,
                  shuffle: bool = True) -> DataLoader

Load the dataset using the exact hf_dataset_id and subset shown in dataset_info.
Output ONLY the Python source code, no markdown fences."""

_RETRIEVAL_REQUIREMENTS_PROMPT = """\
Generate requirements.txt for a bi-encoder information retrieval experiment.

Dataset / environment: {dataset_info}

Include realistic pinned versions for:
- torch
- sentence-transformers
- faiss-cpu
- rank-bm25
- datasets (HuggingFace)
- evaluate (HuggingFace)
- transformers
- numpy
- pyyaml
- rich
- wandb
- tqdm

Output ONLY the requirements.txt content, no markdown."""

_FILE_SPECS_RETRIEVAL: list[tuple[str, str, str]] = [
    ("config.yaml",                _RETRIEVAL_CONFIG_PROMPT,       "yaml"),
    ("train.py",                   _RETRIEVAL_TRAIN_PROMPT,        "python"),
    ("evaluate.py",                _RETRIEVAL_EVALUATE_PROMPT,     "python"),
    ("models/bi_encoder.py",       _RETRIEVAL_BIENCODER_PROMPT,    "python"),
    ("baselines/bm25_baseline.py", _RETRIEVAL_BM25_PROMPT,         "python"),
    ("data/dataset_loader.py",     _RETRIEVAL_DATALOADER_PROMPT,   "python"),
    ("requirements.txt",           _RETRIEVAL_REQUIREMENTS_PROMPT, "text"),
]


# ===========================================================================
# NLP domain prompt templates
# ===========================================================================

_NLP_CONFIG_PROMPT = """\
Generate a complete config.yaml for the following NLP fine-tuning experiment.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

The YAML must include sections:
  experiment:  (name, seed, device)
  dataset:     (name, hf_dataset_id, subset, train_split, test_split,
                max_train_samples, max_val_samples)
  model:       (type: "sequence_classifier", base_model: "bert-base-uncased",
                num_labels, max_seq_len: 128, dropout: 0.1)
  training:    (lr: 2e-5, batch_size: 32, epochs: 5, warmup_ratio: 0.1,
                weight_decay: 0.01, fp16: true, eval_strategy: "epoch",
                save_strategy: "epoch", load_best_model_at_end: true)
  baselines:   (tfidf_logreg: true)
  evaluation:  (metrics: [accuracy, f1_macro])
  logging:     (use_wandb, project, save_checkpoints)

Use the dataset name/id from dataset_info above.
Output ONLY the YAML content, no markdown fences."""

_NLP_TRAIN_PROMPT = """\
Generate a complete train.py for fine-tuning a HuggingFace transformer for NLP.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

Requirements:
- Load config from config.yaml (argparse --config flag)
- Load dataset via data/dataset_loader.py using the hf_dataset_id from dataset_info
- Load AutoTokenizer and AutoModelForSequenceClassification from HuggingFace
- Use HuggingFace Trainer with TrainingArguments from config
- compute_metrics function: accuracy and f1_macro via evaluate library
- After training, run baselines/tfidf_baseline.py for comparison
- Save training results to results/train_results.json
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_NLP_EVALUATE_PROMPT = """\
Generate a complete evaluate.py for an NLP classification experiment.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

The script must:
1. Load config.yaml (--config flag) and the best fine-tuned checkpoint
2. Run inference on the test set
3. Compute accuracy, F1-macro, F1 per class, confusion matrix
4. Load TF-IDF baseline results from results/tfidf_results.json (if exists)
5. Print comparison table: rows=[fine_tuned_bert, tfidf_baseline], columns=metrics
6. Save results to results/eval_results.json
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_NLP_CLASSIFIER_PROMPT = """\
Generate models/classifier.py wrapping a HuggingFace sequence classifier.

Hypothesis: {content}

The file must define:
1. TextClassifier
   - __init__(model_name: str, num_labels: int, dropout: float = 0.1)
   - Wraps AutoModelForSequenceClassification
   - forward(input_ids, attention_mask, labels=None)
       -> ModelOutput (loss if labels provided, else logits)
   - predict(texts: list[str], tokenizer, device) -> np.ndarray (predicted labels)
   - save(path: str) and load(path: str) classmethods

2. compute_metrics(eval_pred) -> dict
   - For use with HuggingFace Trainer
   - Computes accuracy and f1_macro

Output ONLY the Python source code, no markdown fences."""

_NLP_TFIDF_PROMPT = """\
Generate baselines/tfidf_baseline.py implementing a TF-IDF + LogisticRegression baseline.

The file must define:
1. TFIDFBaseline
   - __init__(max_features: int = 50000, ngram_range: tuple = (1, 2))
   - fit(texts: list[str], labels: list[int]) -> self
   - predict(texts: list[str]) -> np.ndarray
   - evaluate(texts: list[str], labels: list[int]) -> dict
     Returns {"accuracy": float, "f1_macro": float}
   - save(path: str) and load(path: str) classmethods using joblib

2. run_baseline(config: dict) -> dict
   - Loads dataset, trains TFIDFBaseline, evaluates, saves to results/tfidf_results.json
   - Returns the evaluation dict

3. if __name__ == "__main__": demo block.

Output ONLY the Python source code, no markdown fences."""

_NLP_DATALOADER_PROMPT = """\
Generate data/dataset_loader.py for loading and tokenising NLP datasets.

Dataset info: {dataset_info}

The file must define:
1. load_text_dataset(config: dict) -> tuple[Dataset, Dataset]
   - Loads the HuggingFace dataset using hf_dataset_id (and subset if set)
   - Applies optional max_train_samples / max_val_samples truncation
   - Returns (train_dataset, val_dataset)

2. tokenize_dataset(dataset, tokenizer, text_column: str,
                    label_column: str, max_length: int = 128) -> Dataset
   - Tokenises text with truncation and padding
   - Renames label column to "labels" for Trainer compatibility

3. get_text_and_labels(dataset) -> tuple[list[str], list[int]]
   - Returns (texts, labels) for sklearn-style baselines

Use the exact hf_dataset_id and subset from dataset_info.
Output ONLY the Python source code, no markdown fences."""

_NLP_REQUIREMENTS_PROMPT = """\
Generate requirements.txt for a HuggingFace NLP fine-tuning experiment.

Dataset: {dataset_info}

Include realistic pinned versions for:
- torch
- transformers
- datasets (HuggingFace)
- evaluate (HuggingFace)
- accelerate
- scikit-learn
- numpy
- pyyaml
- rich
- wandb
- joblib

Output ONLY the requirements.txt content, no markdown."""

_FILE_SPECS_NLP: list[tuple[str, str, str]] = [
    ("config.yaml",                  _NLP_CONFIG_PROMPT,       "yaml"),
    ("train.py",                     _NLP_TRAIN_PROMPT,        "python"),
    ("evaluate.py",                  _NLP_EVALUATE_PROMPT,     "python"),
    ("models/classifier.py",         _NLP_CLASSIFIER_PROMPT,   "python"),
    ("baselines/tfidf_baseline.py",  _NLP_TFIDF_PROMPT,        "python"),
    ("data/dataset_loader.py",       _NLP_DATALOADER_PROMPT,   "python"),
    ("requirements.txt",             _NLP_REQUIREMENTS_PROMPT, "text"),
]


# ===========================================================================
# CV domain prompt templates
# ===========================================================================

_CV_CONFIG_PROMPT = """\
Generate a complete config.yaml for the following computer vision experiment.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

The YAML must include sections:
  experiment:  (name, seed, device)
  dataset:     (name, hf_dataset_id, train_split, test_split,
                image_size: 32, num_classes, normalize_mean, normalize_std)
  model:       (type: "vision_model", architecture: "resnet50",
                pretrained: true, dropout: 0.2)
  training:    (optimizer: "sgd", lr: 0.01, momentum: 0.9, weight_decay: 1e-4,
                batch_size: 128, epochs: 50,
                lr_scheduler: "cosine", warmup_epochs: 5, fp16: true)
  baselines:   (pretrained_resnet50: true)
  evaluation:  (metrics: [top1_accuracy, top5_accuracy],
                eval_every: 5)
  logging:     (use_wandb, project, save_checkpoints, checkpoint_every: 10)

Use the dataset name/id from dataset_info above.
Output ONLY the YAML content, no markdown fences."""

_CV_TRAIN_PROMPT = """\
Generate a complete train.py for a computer vision classification experiment.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

Requirements:
- Load config from config.yaml (argparse --config flag)
- Load dataset via data/dataset_loader.py
- Instantiate VisionModel from models/vision_model.py
- Training loop with:
    * SGD/AdamW optimiser from config
    * Cosine LR schedule + warmup
    * Mixed precision (torch.cuda.amp.autocast)
    * Augmentation: RandomCrop, RandomHorizontalFlip, Normalize
    * Evaluate on validation set every eval_every epochs (top-1 and top-5)
    * Save best checkpoint to checkpoints/best_model.pth
- After training, compare vs ResNet50 baseline (baselines/resnet_baseline.py)
- Save results to results/train_results.json
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_CV_EVALUATE_PROMPT = """\
Generate a complete evaluate.py for a computer vision experiment.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

The script must:
1. Load config.yaml and checkpoint (--checkpoint flag)
2. Run inference on the test set
3. Compute top-1 accuracy, top-5 accuracy, per-class accuracy
4. Load pretrained ResNet50 baseline results for comparison
5. Print a rich comparison table with per-class breakdown
6. Save results to results/eval_results.json
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_CV_VISION_MODEL_PROMPT = """\
Generate models/vision_model.py implementing a configurable vision model.

Hypothesis: {content}

The file must define:
1. VisionModel(nn.Module)
   - __init__(architecture: str, num_classes: int, pretrained: bool,
              dropout: float)
   - Supports: "resnet18", "resnet50", "vit_b_16" via torchvision.models
   - Replaces the classification head with a dropout + linear layer
   - forward(x: Tensor[B, C, H, W]) -> Tensor[B, num_classes]

2. get_transforms(image_size: int, split: str) -> transforms.Compose
   - split="train": RandomCrop, RandomHorizontalFlip, ToTensor, Normalize
   - split="val"/"test": CenterCrop, ToTensor, Normalize

3. load_checkpoint(model, path: str) -> int (returns epoch number)
4. save_checkpoint(model, optimizer, epoch: int, path: str)

Output ONLY the Python source code, no markdown fences."""

_CV_RESNET_BASELINE_PROMPT = """\
Generate baselines/resnet_baseline.py implementing a pretrained ResNet50 baseline.

The file must:
1. Load pretrained ResNet50 from torchvision (ImageNet weights)
2. Replace the FC head for the target number of classes
3. Evaluate on the provided DataLoader (no fine-tuning — zero-shot transfer)
4. Also fine-tune for 10 epochs with a small LR as a "fine-tuned baseline"
5. Return {"zero_shot_top1": float, "finetuned_top1": float}

Define:
  run_resnet_baseline(config: dict, val_loader: DataLoader) -> dict

Output ONLY the Python source code, no markdown fences."""

_CV_DATALOADER_PROMPT = """\
Generate data/dataset_loader.py for loading computer vision datasets.

Dataset info: {dataset_info}

The file must define:
1. load_vision_dataset(config: dict, split: str,
                       transform=None) -> torch.utils.data.Dataset
   - Loads dataset using HuggingFace datasets (hf_dataset_id from config)
   - Wraps in a PyTorch Dataset that applies the given transform
   - Returns the dataset

2. HFImageDataset(torch.utils.data.Dataset)
   - __init__(hf_dataset, transform=None)
   - __getitem__ converts PIL image to tensor, returns (image, label)
   - __len__

3. get_dataloaders(config: dict) -> tuple[DataLoader, DataLoader, DataLoader]
   - Returns (train_loader, val_loader, test_loader)
   - Applies appropriate transforms for each split
   - Uses num_workers=4, pin_memory=True

Load dataset using the exact hf_dataset_id from dataset_info.
Output ONLY the Python source code, no markdown fences."""

_CV_REQUIREMENTS_PROMPT = """\
Generate requirements.txt for a PyTorch computer vision experiment.

Dataset: {dataset_info}

Include realistic pinned versions for:
- torch
- torchvision
- datasets (HuggingFace)
- Pillow
- numpy
- pyyaml
- rich
- wandb
- tqdm
- scikit-learn

Output ONLY the requirements.txt content, no markdown."""

_FILE_SPECS_CV: list[tuple[str, str, str]] = [
    ("config.yaml",                   _CV_CONFIG_PROMPT,        "yaml"),
    ("train.py",                      _CV_TRAIN_PROMPT,         "python"),
    ("evaluate.py",                   _CV_EVALUATE_PROMPT,      "python"),
    ("models/vision_model.py",        _CV_VISION_MODEL_PROMPT,  "python"),
    ("baselines/resnet_baseline.py",  _CV_RESNET_BASELINE_PROMPT, "python"),
    ("data/dataset_loader.py",        _CV_DATALOADER_PROMPT,    "python"),
    ("requirements.txt",              _CV_REQUIREMENTS_PROMPT,  "text"),
]


# ===========================================================================
# Domain Adaptation prompt templates
# ===========================================================================

_DA_CONFIG_PROMPT = """\
Generate a complete config.yaml for the following domain adaptation experiment.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

The YAML must include sections:
  experiment:  (name, seed, device)
  dataset:     (name, hf_dataset_id, source_domain, target_domain,
                image_size: 224, num_classes)
  model:       (type: "domain_adapter", backbone: "resnet50",
                pretrained: true, adaptation_method: "dann",
                bottleneck_dim: 256, discriminator_hidden: 1024)
  training:    (lr: 1e-3, batch_size: 32, epochs: 50,
                domain_loss_weight: 1.0, lr_scheduler: "inv",
                lr_gamma: 10.0, lr_decay: 0.75, momentum: 0.9)
  baselines:   (source_only: true, fine_tuned: true)
  evaluation:  (metrics: [target_accuracy, source_accuracy, transfer_gap],
                eval_every: 5)
  logging:     (use_wandb, project, save_checkpoints)

Use the dataset info above.
Output ONLY the YAML content, no markdown fences."""

_DA_TRAIN_PROMPT = """\
Generate a complete train.py for a domain adaptation experiment (DANN or MMD).

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

Requirements:
- Load config from config.yaml (argparse --config flag)
- Load source and target domain data via data/dataset_loader.py
- Instantiate DomainAdapter from models/domain_adapter.py
- DANN training loop (Gradient Reversal Layer):
    * Feature extractor shared by source + target
    * Label classifier trained on source labels
    * Domain discriminator trained adversarially
    * Progress parameter p increases from 0 to 1 over training
- Or MMD: minimise Maximum Mean Discrepancy between source/target features
- Evaluate on source (labelled) and target (unlabelled → ground truth for eval)
  every eval_every epochs
- Run source-only baseline at epoch 0 for reference
- Save results to results/train_results.json
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_DA_EVALUATE_PROMPT = """\
Generate a complete evaluate.py for a domain adaptation experiment.

Hypothesis: {content}
Experiment design: {design_json}
Dataset: {dataset_info}

The script must:
1. Load config.yaml and adapted model checkpoint
2. Evaluate on source domain test split
3. Evaluate on target domain test split
4. Compute transfer_gap = source_accuracy - target_accuracy
5. Load baseline results (source_only_results.json, finetune_results.json)
6. Print comparison table:
   rows=[DANN/MMD, source_only, fine_tuned], columns=[source_acc, target_acc, gap]
7. Save results to results/eval_results.json
- if __name__ == "__main__": main() guard

Output ONLY the Python source code, no markdown fences."""

_DA_ADAPTER_PROMPT = """\
Generate models/domain_adapter.py implementing DANN and MMD adaptation.

Hypothesis: {content}

The file must define:
1. GradientReversalLayer(torch.autograd.Function)
   - forward: identity
   - backward: multiplies gradient by -lambda (controls adaptation strength)

2. DomainAdapter(nn.Module)
   - __init__(backbone: str, num_classes: int, bottleneck_dim: int,
              discriminator_hidden: int, method: str = "dann")
   - backbone: pretrained ResNet from torchvision (replace avg_pool + fc)
   - bottleneck: backbone_out → bottleneck_dim
   - classifier: bottleneck_dim → num_classes
   - discriminator: bottleneck_dim → 2 (domain: source/target)
   - forward(x, alpha=1.0, source=True)
       -> (class_logits, domain_logits)
   - mmd_loss(source_features, target_features) -> Tensor
     Gaussian kernel MMD

3. compute_dann_loss(class_logits, class_labels, domain_logits,
                     domain_labels, class_weight=1.0, domain_weight=1.0)
       -> total_loss, class_loss, domain_loss

Output ONLY the Python source code, no markdown fences."""

_DA_SOURCE_ONLY_PROMPT = """\
Generate baselines/source_only.py implementing two domain adaptation baselines.

The file must:
1. SourceOnlyBaseline — trains only on source domain with no adaptation:
   - train(model: DomainAdapter, source_loader, config) -> dict
   - Returns {"source_accuracy": float, "target_accuracy": float}
   - Saves to results/source_only_results.json

2. FineTunedBaseline — fine-tunes pretrained ResNet on source, then evaluates on target:
   - run(config: dict, source_loader, target_loader) -> dict
   - Uses a few epochs of full fine-tuning (no DA)
   - Saves to results/finetune_results.json

Output ONLY the Python source code, no markdown fences."""

_DA_DATALOADER_PROMPT = """\
Generate data/dataset_loader.py for loading domain adaptation datasets.

Dataset info: {dataset_info}

The file must define:
1. load_domain_dataset(config: dict, domain: str,
                       split: str = "train") -> torch.utils.data.Dataset
   - Loads the HuggingFace dataset (hf_dataset_id from config)
   - Filters to examples matching the domain column
   - Applies image transforms (224x224, ImageNet normalisation)

2. DomainDataset(torch.utils.data.Dataset)
   - __init__(hf_dataset, transform=None, return_domain_label: bool = False)
   - __getitem__ returns (image_tensor, class_label) or
                         (image_tensor, class_label, domain_label)

3. get_domain_dataloaders(config: dict)
       -> tuple[DataLoader, DataLoader, DataLoader, DataLoader]
   - Returns (source_train, source_val, target_train, target_val)
   - source and target come from the source_domain / target_domain in config

Load using the exact hf_dataset_id from dataset_info.
Output ONLY the Python source code, no markdown fences."""

_DA_REQUIREMENTS_PROMPT = """\
Generate requirements.txt for a domain adaptation experiment.

Dataset: {dataset_info}

Include realistic pinned versions for:
- torch
- torchvision
- datasets (HuggingFace)
- Pillow
- numpy
- pyyaml
- rich
- wandb
- scikit-learn
- tqdm

Output ONLY the requirements.txt content, no markdown."""

_FILE_SPECS_DA: list[tuple[str, str, str]] = [
    ("config.yaml",                   _DA_CONFIG_PROMPT,        "yaml"),
    ("train.py",                      _DA_TRAIN_PROMPT,         "python"),
    ("evaluate.py",                   _DA_EVALUATE_PROMPT,      "python"),
    ("models/domain_adapter.py",      _DA_ADAPTER_PROMPT,       "python"),
    ("baselines/source_only.py",      _DA_SOURCE_ONLY_PROMPT,   "python"),
    ("data/dataset_loader.py",        _DA_DATALOADER_PROMPT,    "python"),
    ("requirements.txt",              _DA_REQUIREMENTS_PROMPT,  "text"),
]


# ===========================================================================
# Domain file-spec routing
# ===========================================================================

# ===========================================================================
# Unified domain routing
# ===========================================================================
# Previously the system prompt (steers *what* the LLM writes) and the file
# specs (decides *which files* get created) were selected by two separately
# maintained keyword lists (_DOMAIN_SYSTEM_MAP, _DOMAIN_FILE_SPECS_MAP).
# They drifted: the NLP entry here had 3 extra keywords ("natural language",
# "nli", "entailment") that the system-prompt list never got. A hypothesis
# matching only one of those three would get an NLP file skeleton but an RL
# (or wrong-domain) system prompt steering its content — the same class of
# mismatch an audit found for real in session `ab5473c0` (RL file skeleton
# generated for a domain-adaptation-flavored hypothesis). Routing is now a
# single lookup so prompt and file specs can never disagree by construction.

from dataclasses import dataclass

from agents import controlled_llm_scaffold as _CONTROLLED_LLM


@dataclass(frozen=True)
class DomainSpec:
    """
    How one kind of experiment is implemented: which files to write, and what
    to tell the model while writing them.

    This is an implementation detail, chosen by an ExperimentSpec. It says
    nothing about what a study establishes, and nothing may read a scientific
    design back out of it -- that direction is what let a keyword match decide
    what an experiment was.
    """
    label: str
    keywords: tuple[str, ...]
    system_prompt: str
    file_specs: tuple[tuple[str, str, str], ...]
    # Files copied in verbatim rather than generated, because the experiment's
    # correctness depends on them being exactly what they are.
    copied_files: tuple[str, ...] = ()


_DOMAIN_REGISTRY: list[DomainSpec] = [
    DomainSpec(
        # The first family that trains nothing: a curator, an overseer, and a
        # pool of options that must not change between conditions.
        label="controlled_llm",
        keywords=(),                 # never keyword-routed; an ExperimentSpec asks for it
        system_prompt=_CONTROLLED_LLM.SYSTEM_PROMPT,
        file_specs=tuple(_CONTROLLED_LLM.FILE_SPECS),
        copied_files=_CONTROLLED_LLM.COPIED_FILES,
    ),
    DomainSpec(
        label="retrieval",
        keywords=("retrieval", "ranking", "search", "dense retrieval", "bi-encoder",
                   "passage", "beir", "ms-marco", "faiss", "bm25"),
        system_prompt=_SYSTEM_RETRIEVAL,
        file_specs=tuple(_FILE_SPECS_RETRIEVAL),
    ),
    DomainSpec(
        label="domain adaptation",
        keywords=("domain adaptation", "domain shift", "domain invariant", "mmd",
                   "coral", "dann", "transfer learn", "cross-domain"),
        system_prompt=_SYSTEM_DOMAIN_ADAPTATION,
        file_specs=tuple(_FILE_SPECS_DA),
    ),
    DomainSpec(
        label="nlp",
        # Union of the two lists that had drifted apart — "natural language",
        # "nli", "entailment" used to only route file specs, not the prompt.
        keywords=("text classif", "sentiment", "language model", "nlp", "bert",
                   "transformers", "huggingface", "seq2seq", "summariz",
                   "natural language", "nli", "entailment"),
        system_prompt=_SYSTEM_NLP,
        file_specs=tuple(_FILE_SPECS_NLP),
    ),
    DomainSpec(
        label="computer vision",
        keywords=("image classif", "computer vision", "object detection", "segmentation",
                   "resnet", "vit", "convolutional", "cifar", "imagenet"),
        system_prompt=_SYSTEM_CV,
        file_specs=tuple(_FILE_SPECS_CV),
    ),
    DomainSpec(
        label="reinforcement learning",
        keywords=("reinforcement learning", "rl agent", "policy gradient", "ppo",
                   "q-learning", "reward", "environment", "gymnasium", "atari", "minigrid"),
        system_prompt=_SYSTEM_RL,
        file_specs=tuple(_FILE_SPECS_RL),
    ),
]

class UnsupportedExperimentError(RuntimeError):
    """
    No scaffold fits this hypothesis.

    There used to be a fallback here: anything unrecognised was generated as a
    reinforcement-learning codebase. It was recorded as a critical degradation
    and then generated anyway, so a study of adversarial curation became a
    MiniGrid agent -- eight files that compile, run, and answer a question
    nobody asked. Stopping is the better failure.
    """




# Scripts that are meant to be run, rather than imported. They are written last,
# so they can be shown what the modules they import actually ended up exporting.
_ENTRY_SCRIPTS = ("train.py", "pretrain.py", "evaluate.py", "run_experiment.py", "main.py")


def _generation_order(specs: list) -> list:
    """
    Leaf modules first, entry scripts last.

    Each file is written by its own API call, so a file generated earlier can
    be shown to the ones generated after it. That is only useful in the right
    order: `train.py` written before `envs/wrappers.py` has to guess what the
    wrapper will export, and guessing is how a codebase ends up importing
    things that were never written.
    """
    def rank(spec):
        file_path = spec[0]
        return (1 if Path(file_path).name in _ENTRY_SCRIPTS else 0, file_path)

    return sorted(specs, key=rank)


def _public_interface(source: str, file_path: str) -> str:
    """
    What another file may rely on this one for: its module-level functions and
    classes, with their arguments, and nothing else. Whole files would flood
    the prompt; the signatures are what a caller actually needs.
    """
    import ast as _ast

    try:
        tree = _ast.parse(source)
    except SyntaxError:
        return ""
    lines = []
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            lines.append(f"def {node.name}({_ast.unparse(node.args)})")
        elif isinstance(node, _ast.ClassDef):
            methods = [m.name for m in node.body
                       if isinstance(m, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                       and not m.name.startswith("_")]
            lines.append(f"class {node.name}: " + ", ".join(methods[:8]))
    if not lines:
        return ""
    return f"# {file_path}\n" + "\n".join(lines)


def _manifest_section(file_specs: list, written: dict) -> str:
    """
    The shared contract every file is generated against: which files this
    project consists of, and what the ones already written actually export.
    """
    files = "\n".join(f"  {spec[0]}" for spec in file_specs)
    section = ("=== PROJECT FILES (this experiment consists of exactly these) ===\n"
               f"{files}\n"
               "Import from these by their paths as written above; do not invent modules.\n"
               "Every script that can be run must honour the environment variable "
               "RA_SMOKE: when it is set to 1, do exactly one minimal step (one batch, "
               "one episode, one example), skip writing final results, and exit 0. It is "
               "used to check the pieces fit together before the real run.\n")
    interfaces = [text for text in
                  (_public_interface(source, name) for name, source in written.items()) if text]
    if interfaces:
        section += ("\n=== ALREADY WRITTEN (use these exact names) ===\n"
                    + "\n\n".join(interfaces) + "\n")
    return section


def _keyword_matches(text: str, keywords: tuple[str, ...]) -> bool:
    """
    Leading-word-boundary keyword match. Plain substring `in` checks would
    let e.g. "research" false-positive-match the "search" keyword (retrieval
    domain) for any hypothesis containing the ordinary English word
    "research" — found while writing the regression tests for this
    function, not hypothetical.

    Only the LEADING boundary is enforced (no trailing \\b): keywords like
    "domain shift" must still match inside "domain shifts" (plural) — a
    trailing boundary would break that legitimate prefix match, since
    "shift"/"shifts" share no word boundary between them. A leading boundary
    alone is enough to reject "research" (no boundary before the embedded
    "search") while still accepting "shifts" as an extension of "shift".
    """
    return any(re.search(rf'\b{re.escape(kw)}', text) for kw in keywords)


def scaffold_by_id(scaffold_id: str) -> DomainSpec:
    """The implementation an ExperimentSpec asked for, by name."""
    for domain in _DOMAIN_REGISTRY:
        if domain.label == scaffold_id:
            return domain
    raise UnsupportedExperimentError(
        f"no scaffold called {scaffold_id!r} exists to implement this study")


def build_spec(hypothesis_content: str, design: dict | None = None,
               research_question: str = ""):
    """
    What this study is, decided from the hypothesis and the design that was
    agreed -- before any template is consulted.

    A controlled decision study is recognised by its arrangement, not by a
    topic keyword. Everything else falls through to the training families,
    whose scaffold is still chosen by keyword; what changed is that the keyword
    now picks an implementation for a design that has already been stated,
    instead of standing in for the design itself.
    """
    from agents import experiment_spec as spec_module

    if spec_module.looks_controlled(hypothesis_content):
        return spec_module.controlled_llm_spec(hypothesis_content, design, research_question)
    scaffold = _select_domain(hypothesis_content)      # raises if nothing fits
    return spec_module.training_spec(hypothesis_content, scaffold.label, design,
                                     research_question)


def _select_domain(hypothesis_content: str) -> DomainSpec:
    """
    Infer the research domain from hypothesis text and return its full
    DomainSpec (system prompt + file specs together, so they can never
    disagree). First match wins, checked in the order defined above
    (retrieval and domain-adaptation are checked before the broader NLP/RL
    keyword sets to avoid e.g. a cross-domain-retrieval hypothesis matching
    the generic RL "environment" keyword instead).
    """
    text = hypothesis_content.lower()
    for domain in _DOMAIN_REGISTRY:
        if _keyword_matches(text, domain.keywords):
            logger.info(
                "ExperimentAgent: domain='%s' → %d domain-specific file(s).",
                domain.label, len(domain.file_specs),
            )
            return domain
    logger.warning("ExperimentAgent: no scaffold matches this hypothesis.")
    raise UnsupportedExperimentError(
        "No experiment scaffold fits this hypothesis. Generating one of the "
        "existing templates anyway would produce a different experiment from "
        "the one that was asked for.")


# ===========================================================================
# ExperimentAgent
# ===========================================================================

class ExperimentAgent:
    """
    Phase 5: Generates a complete, runnable experiment codebase for a
    selected hypothesis using the Claude API.

    Domain routing (A) + real dataset integration (B) are both applied
    automatically based on keywords in the hypothesis text.
    """

    def __init__(
        self,
        api_model: "APIModel",
        note_db: "NoteDB",
        experiments_base_dir: Path,
    ) -> None:
        self._api = api_model
        self._ndb = note_db
        self._exp_base = Path(experiments_base_dir)
        self._last_domain: str | None = None  # set by _generate_all_files
        self._last_spec = None                # the ExperimentSpec this run was built from
        self._protocol_first_built = False

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, session_id: str) -> dict[str, str]:
        """
        Main pipeline for Phase 5.
        Returns {relative_file_path: file_content} for generated files.
        """
        console.print("\n[bold cyan][Experiment Agent][/] Loading hypotheses…")

        hypotheses = self._ndb.get_hypotheses(session_id)
        if not hypotheses:
            raise RuntimeError(
                "No hypotheses found for this session. Run Phase 4 first."
            )

        # Step A: user picks a hypothesis
        selected = self._select_hypothesis(hypotheses)
        hypothesis_id = selected["hypothesis_id"]
        h_index = selected.get("index") or 1
        console.print(
            f"\n[green]Selected hypothesis {h_index}:[/] "
            f"{selected['content'][:80]}…"
        )

        # Step B: check for existing generated code
        existing = self._ndb.get_experiment_code(hypothesis_id)
        if existing:
            answer = input(
                f"\n{len(existing)} file(s) already generated. "
                "Regenerate all? [y/N]: "
            ).strip().lower()
            if answer != "y":
                console.print("[cyan]Loading existing code from DB…[/]")
                files = {r["file_path"]: r["file_content"] for r in existing}
                hypothesis_dir = self._exp_base / session_id
                self._write_files(hypothesis_dir, files)
                self._print_file_tree(hypothesis_dir, files)
                return files

        existing_paths = {r["file_path"] for r in existing}

        # Step C: generate files via API
        generated = self._generate_all_files(
            hypothesis=selected,
            skip_paths=existing_paths,
            session_id=session_id,
        )

        for r in existing:
            generated.setdefault(r["file_path"], r["file_content"])

        # Step D: write to file system
        hypothesis_dir = self._exp_base / session_id
        if not self._protocol_first_built:
            self._write_files(hypothesis_dir, generated)
            self.finalize_generated(session_id, selected, hypothesis_dir)

        # Step E: persist to NoteDB
        self._persist_to_db(session_id, hypothesis_id, generated)

        self._ndb.update_hypothesis_status(
            hypothesis_id, "code_generated", domain=self._last_domain
        )

        console.print(
            f"\n[bold green]✓ Generated {len(generated)} file(s)[/] "
            f"→ {hypothesis_dir}"
        )
        self._print_file_tree(hypothesis_dir, generated)

        return generated

    # ------------------------------------------------------------------
    # Step A: hypothesis selection UI (CLI only)
    # ------------------------------------------------------------------

    def _select_hypothesis(self, hypotheses: list[dict]) -> dict:
        """Display hypotheses and prompt user to pick one."""
        console.print()
        for h in hypotheses:
            design = h.get("experiment_design") or {}
            idx = h.get("index") or "?"
            score = h.get("feasibility_score")
            score_str = f"{score:.1f}" if score is not None else "N/A"
            gpu = design.get("estimated_gpu_hours", "N/A")
            console.print(Panel(
                f"[bold]{h['content']}[/]\n\n"
                f"[dim]Feasibility:[/] {score_str}  |  "
                f"[dim]GPU hours:[/] {gpu}\n"
                f"[dim]Approach:[/] {str(design.get('approach', ''))[:120]}",
                title=f"[cyan][{idx}][/] Hypothesis",
                border_style="cyan",
            ))

        while True:
            try:
                choice = input(
                    f"\nSelect hypothesis to implement "
                    f"[1-{len(hypotheses)}]: "
                ).strip()
                idx = int(choice) - 1
                if 0 <= idx < len(hypotheses):
                    return hypotheses[idx]
                console.print(
                    f"[red]Enter a number between 1 and {len(hypotheses)}.[/]"
                )
            except ValueError:
                console.print("[red]Invalid input — enter a number.[/]")
            except (KeyboardInterrupt, EOFError):
                raise RuntimeError("Experiment agent cancelled by user.")

    # ------------------------------------------------------------------
    # Step C: code generation (A + B integrated here)
    # ------------------------------------------------------------------

    def _generate_all_files(
        self,
        hypothesis: dict,
        skip_paths: set[str],
        session_id: str | None = None,
    ) -> dict[str, str]:
        """
        Select domain-appropriate file specs (A) and a real dataset (B),
        then call the API once per file.
        Returns {file_path: content}.
        """
        design_json = json.dumps(
            hypothesis.get("experiment_design") or {}, indent=2
        )
        content = hypothesis["content"]
        generated: dict[str, str] = {}

        # ── A: Domain alignment guard ─────────────────────────────────────
        # Single lookup — system prompt and file specs come from the same
        # DomainSpec so they cannot disagree (see _select_domain docstring).
        deg = None
        if session_id:
            from agents.degradation import DegradationLog
            deg = DegradationLog(self._ndb, session_id, notify=console.print)

        # What the study is, before which template implements it. The spec is
        # checked first: an experiment with one condition, or with nothing
        # measured, is not worth generating code for.
        from agents.experiment_spec import DatasetPolicy, SpecInvalid

        try:
            research_question = ""
            if session_id:
                session = self._ndb.get_session(session_id) or {}
                research_question = session.get("research_question") or ""
            spec = build_spec(content, hypothesis.get("experiment_design") or {},
                              research_question)
            spec.validate()
            domain = scaffold_by_id(spec.scaffold_id)
        except UnsupportedExperimentError as exc:
            if deg:
                deg.record(5, "domain_routing", "critical", str(exc))
            raise
        except SpecInvalid as exc:
            if deg:
                deg.record(5, "experiment_spec", "critical", str(exc))
            raise
        self._last_spec = spec
        if spec.scaffold_id == "controlled_llm":
            # A declarative family is built by agents/study_builder.py: trusted
            # code writes the apparatus and the config, and a model writes only
            # the content. Generating it file-by-file here is what produced a
            # driver that discarded its own curation.
            if not session_id:
                raise UnsupportedExperimentError(
                    "controlled decision studies require a session so the protocol-first "
                    "build and its approvals can be persisted")
            from agents import study_builder
            from agents.control_boundary import authorize_built_study
            from agents.intent_fidelity import ApprovedIntent

            folder = self._exp_base / session_id
            approved = ApprovedIntent(hypothesis=content,
                                      research_question=research_question)
            outcome = study_builder.build(
                content, self._api, folder, approved=approved, protocol=spec)
            self._persist_control_outcome(session_id, outcome)
            if not outcome.ready:
                from agents.build_manifest import Status
                from agents.control_boundary import ControlBoundaryBlocked

                stage = {
                    Status.INTENT_FIDELITY_FAILED: "Intent Fidelity",
                    Status.DESIGN_REJECTED: "Methodology Review",
                    Status.SCIENTIFIC_VERIFICATION_FAILED: "Scientific Conformance",
                    Status.SOFTWARE_VERIFICATION_FAILED: "Software Preflight",
                }.get(outcome.status)
                if outcome.status is Status.DESIGN_NEEDS_HUMAN:
                    stage = ("Intent Fidelity" if outcome.fidelity and
                             not outcome.fidelity.passed else "Methodology Review")
                # Builders retain earlier lifecycle notes (for example the
                # frozen hash); the last note explains the boundary that
                # actually stopped this attempt.
                reason = outcome.notes[-1] if outcome.notes else outcome.status.value
                if stage:
                    raise ControlBoundaryBlocked(stage, reason)
                raise UnsupportedExperimentError(
                    f"controlled study blocked at {outcome.status.value}: {reason}")
            authorize_built_study(folder, outcome.protocol, outcome.manifest,
                                  self._ndb, session_id)
            self._last_spec = outcome.protocol
            self._last_domain = "controlled_llm"
            self._protocol_first_built = True
            files = {}
            for path in folder.rglob("*"):
                if path.is_file() and not ({"results", "__pycache__"} & set(path.relative_to(folder).parts)):
                    relative = str(path.relative_to(folder)).replace("\\", "/")
                    files[relative] = path.read_text(encoding="utf-8", errors="replace")
            return files
        dataset_info = ""
        research_question = ""
        system_prompt = domain.system_prompt
        file_specs = list(domain.file_specs)
        detected_domain = domain.label
        self._last_domain = detected_domain  # read by run() / UI callers to persist

        console.print(
            f"  [dim]Domain: [cyan]{detected_domain}[/] → "
            f"{len(file_specs)} domain-specific file(s)[/]"
        )


        # ── B: Real dataset resolver (briefs without a declared dataset) ──
        # Only when the design says this study runs on data. A controlled
        # decision study has none, and resolving one for it anyway is how a
        # question about oversight acquired a news-classification benchmark.
        if spec.dataset_policy is DatasetPolicy.NONE:
            dataset_info = json.dumps(
                {"note": "this study uses no dataset; its material is the candidate "
                         "pool the experiment defines for itself"}, indent=2)
            console.print("  [dim]Dataset: [cyan]none required by this design[/][/]")
        else:
            try:
                from tools.dataset_resolver import DatasetUnresolved
                from tools.dataset_resolver import resolve as _resolve_ds
                from tools.dataset_resolver import as_dict as _ds_as_dict
                ds = _resolve_ds(content)
                dataset_info = json.dumps(_ds_as_dict(ds), indent=2)
                console.print(
                    f"  [dim]Dataset: [yellow]{ds.name}[/] "
                    f"(train={ds.num_train_samples:,}, "
                    f"test={ds.num_test_samples:,}, "
                    f"metrics={', '.join(ds.metrics[:2])})[/]"
                )
            except DatasetUnresolved as exc:
                # Not knowing which data to use is a reason to stop, not a reason
                # to pick one. Which data an experiment runs on *is* the experiment.
                if deg:
                    deg.record(5, "dataset_resolver", "critical", str(exc))
                raise UnsupportedExperimentError(str(exc)) from exc
            except Exception as exc:
                logger.warning("DatasetResolver failed: %s", exc)
                dataset_info = json.dumps(
                    {"note": "use standard benchmarks for this domain"}, indent=2
                )
                if deg:
                    deg.record(5, "dataset_resolver", "critical",
                               f"Dataset resolution failed ({exc}); no dataset given to code generation.")

        todo = _generation_order([
            spec for spec in file_specs if spec[0] not in skip_paths
        ])
        skipped = len(file_specs) - len(todo)
        if skipped:
            console.print(
                f"  [dim]Skipping {skipped} already-generated file(s).[/]"
            )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            for file_path, prompt_tpl, language in todo:
                task = progress.add_task(
                    f"  Generating [cyan]{file_path}[/]…", total=None
                )

                # Replace only the three known placeholders; leave every other
                # {…} (e.g. JSON like {"accuracy": 0.9}) completely untouched.
                prompt = (
                    prompt_tpl
                    .replace("{content}",     content)
                    .replace("{design_json}", design_json)
                    .replace("{dataset_info}", dataset_info)
                    .replace("{research_question}", research_question)
                )
                # Every Python file is written against the same manifest, and
                # sees what the files before it exported. Without this each call
                # invents its own idea of the others' interfaces, which is how a
                # project ends up importing a function nobody wrote.
                #
                # Data files get none of it. The manifest is about modules and
                # imports and has nothing to say to a JSON pool — and attaching
                # it measurably hurt: the same local model that wrote a complete
                # candidate_pool.json without it ended the file one bracket
                # short with it, twice.
                if language == "python":
                    prompt = f"{_manifest_section(file_specs, generated)}\n{prompt}"

                try:
                    raw = self._api.generate(
                        prompt=prompt,
                        system=system_prompt,
                        task_type=TaskType.CODE_GENERATION,
                        max_tokens=8192,
                        temperature=0.2,
                    )
                    code = _strip_code_fences(raw)
                    generated[file_path] = code
                    logger.info(
                        "Generated: %s (%d chars)", file_path, len(code)
                    )

                except Exception as exc:
                    logger.error(
                        "Failed to generate %s: %s", file_path, exc
                    )
                    generated[file_path] = (
                        f"# Generation failed: {exc}\n"
                        f"# Re-run with --experiment to retry.\n"
                    )
                    console.print(f"  [red]✗[/] {file_path} — {exc}")

                progress.remove_task(task)
                console.print(f"  [green]✓[/] {file_path}")

        generated = self._repair_generated(generated, todo, spec, system_prompt, deg)
        return generated

    def finalize_generated(self, session_id: str, selected: dict,
                           folder: Path | str) -> None:
        """Take an open-ended generated family through the common build gates."""
        if self._protocol_first_built:
            return
        from agents import (build_manifest as manifest_module, intent_fidelity,
                            methodology_review, preflight, scientific_conformance)
        from agents.control_boundary import (ControlBoundaryBlocked, authorize,
                                             invalidate)
        from agents.intent_fidelity import ApprovedIntent
        from agents.study_builder import may_freeze

        folder = Path(folder)
        invalidate(folder, self._ndb, session_id,
                   "generated package is being verified")
        protocol = self._last_spec
        if protocol is None:
            raise UnsupportedExperimentError("no StudyProtocol was produced for the generated package")
        session = self._ndb.get_session(session_id) or {}
        approved = ApprovedIntent(
            hypothesis=selected.get("content") or "",
            research_question=session.get("research_question") or "")
        protocol = intent_fidelity.propagate_identity(protocol, approved)
        fidelity = intent_fidelity.check(protocol, approved=approved)
        review = methodology_review.review(protocol)
        self._last_spec = protocol
        class _Outcome:
            pass
        recorded = _Outcome()
        recorded.protocol, recorded.fidelity, recorded.review = protocol, fidelity, review
        recorded.manifest = None
        self._persist_control_outcome(session_id, recorded)
        if not may_freeze(fidelity, review):
            reason = fidelity.summary() if not fidelity.passed else review.summary()
            stage = "Intent Fidelity" if not fidelity.passed else "Methodology Review"
            raise ControlBoundaryBlocked(stage, reason)

        protocol = protocol.approve().freeze()
        self._last_spec = protocol
        protocol.write(folder)
        manifest = manifest_module.plan(protocol)
        manifest = manifest_module.seal(manifest, folder, concepts=protocol.concepts)
        manifest.write(folder)
        self._ndb.save_artifact(session_id, "study_protocol", protocol.as_dict(), "passed")
        self._ndb.save_artifact(session_id, "build_manifest", manifest.as_dict(), "passed")
        conformance = scientific_conformance.verify(folder, protocol, manifest)
        self._ndb.save_artifact(session_id, "scientific_conformance",
                                conformance.as_dict(),
                                "passed" if conformance.passed else "blocked")
        if not conformance.passed:
            raise ControlBoundaryBlocked("Scientific Conformance", conformance.summary())
        report = preflight.check(folder, db=self._ndb, session_id=session_id,
                                 stages=preflight.BEFORE_INSTALL)
        self._ndb.save_artifact(session_id, "software_preflight", report.as_dict(),
                                "passed" if report.passed else "blocked")
        if not report.passed:
            raise ControlBoundaryBlocked("Software Preflight", report.summary())
        authorize(folder, protocol, manifest, conformance, report,
                  self._ndb, session_id)

    def _persist_control_outcome(self, session_id: str, outcome) -> None:
        """Expose each independent controlled-study gate through existing artifacts."""
        if outcome.protocol is not None:
            self._ndb.save_artifact(session_id, "study_protocol",
                                    outcome.protocol.as_dict(),
                                    "passed" if outcome.protocol.frozen else "blocked")
        if outcome.fidelity is not None:
            self._ndb.save_artifact(session_id, "intent_fidelity",
                                    outcome.fidelity.as_dict(),
                                    "passed" if outcome.fidelity.passed else outcome.fidelity.status.lower())
        if outcome.review is not None:
            self._ndb.save_artifact(session_id, "methodology_review",
                                    outcome.review.as_dict(),
                                    "passed" if outcome.review.approved else outcome.review.verdict.lower())
        if outcome.manifest is not None:
            self._ndb.save_artifact(session_id, "build_manifest",
                                    outcome.manifest.as_dict(), "passed")

    def _repair_generated(self, generated: dict, todo: list, spec, system_prompt: str,
                          deg=None) -> dict:
        """
        One more pass over anything that came back unusable.

        A smaller model writes good candidates and good prompt text and then,
        every so often, stops mid-JSON. Being told exactly what was wrong with
        the file it just wrote fixes that far more often than not, and it costs
        one call. It is bounded at one attempt per file: a second identical
        answer is a sign the model cannot do it, not a reason to keep paying.
        """
        if spec is None or spec.scaffold_id != "controlled_llm":
            return generated
        from agents import controlled_llm_scaffold as scaffold

        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            for name, body in generated.items():
                (folder / name).parent.mkdir(parents=True, exist_ok=True)
                (folder / name).write_text(body, encoding="utf-8")
            (folder / "config.yaml").write_text(scaffold.config_yaml(spec), encoding="utf-8")
            problems = scaffold.contract_problems(folder, spec)

        if not problems:
            return generated

        console.print(f"  [yellow]{len(problems)} problem(s) with the generated files; "
                      "asking once more.[/]")
        for file_path, prompt_tpl, _ in todo:
            mine = [p for p in problems if file_path in p or file_path.split(".")[0] in p]
            if not mine or file_path not in generated:
                continue
            console.print(f"  [yellow]↻ {file_path}[/] — {mine[0]}")
            complaint = "\n".join(f"- {p}" for p in mine)
            language = next((lang for path, _, lang in todo if path == file_path), "")
            manifest = (_manifest_section([(path, "", "") for path, _, _ in todo], {})
                        if language == "python" else "")
            retry = (f"{manifest}\n{prompt_tpl}\n\n"
                     "=== YOUR PREVIOUS ANSWER WAS NOT USABLE ===\n"
                     f"{complaint}\n\nWrite the file again, complete and correct. "
                     "Output ONLY the file's contents.")
            retry = (retry.replace("{content}", spec.research_question)
                          .replace("{research_question}", spec.research_question)
                          .replace("{spec_json}", spec.to_json()))
            try:
                fixed = _strip_code_fences(self._api.generate(
                    prompt=retry, system=system_prompt, task_type=TaskType.CODE_GENERATION,
                    max_tokens=8192, temperature=0.1))
            except Exception as exc:
                logger.warning("Could not regenerate %s: %s", file_path, exc)
                continue
            if fixed.strip():
                generated[file_path] = fixed

        if deg:
            deg.record(5, "code_generation", "warning",
                       "Some generated files had to be written twice: "
                       + "; ".join(problems[:3]))
        return generated

    # ------------------------------------------------------------------
    # Step D: write to file system
    # ------------------------------------------------------------------

    def _copied_files(self) -> tuple[tuple[str, str], ...]:
        """The scaffold's verbatim files, as (source, destination) pairs."""
        if self._last_spec is None:
            return ()
        try:
            return scaffold_by_id(self._last_spec.scaffold_id).copied_files
        except UnsupportedExperimentError:
            return ()

    def _write_files(
        self,
        hypothesis_dir: Path,
        files: dict[str, str],
    ) -> None:
        """
        Write all files under hypothesis_dir, creating subdirs as needed.
        Creates __init__.py for any Python sub-package directory.
        Works for all domain layouts (models/, envs/, baselines/, data/, …).
        """
        hypothesis_dir.mkdir(parents=True, exist_ok=True)

        # What the study was supposed to be, next to the code that implements
        # it: the patch guard reads it, and so can a person a month later.
        if getattr(self, "_last_spec", None) is not None:
            self._last_spec.write(hypothesis_dir)

        # Files the experiment's correctness depends on are copied in, not
        # generated. A model rewriting the rule that the candidate pool cannot
        # change is exactly what the rule exists to prevent.
        tools = Path(__file__).parent.parent / "tools"
        for source, destination in self._copied_files():
            shutil.copyfile(tools / source, hypothesis_dir / destination)

        # The config is the design restated; a model has nothing to decide in
        # it, and when one was asked to write it, it named conditions the
        # design never mentioned.
        controlled = (getattr(self, "_last_spec", None) is not None
                      and self._last_spec.scaffold_id == "controlled_llm")
        if controlled:
            (hypothesis_dir / "config.yaml").write_text(
                _CONTROLLED_LLM.config_yaml(self._last_spec), encoding="utf-8")

        for rel_path, content in files.items():
            abs_path = hypothesis_dir / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")

        # Auto-create __init__.py for every Python sub-package directory
        subdirs: set[Path] = set()
        for rel_path in files:
            p = Path(rel_path)
            if p.suffix == ".py" and p.parent != Path("."):
                subdirs.add(hypothesis_dir / p.parent)

        for subdir in subdirs:
            init = subdir / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")

        if controlled:
            self._freeze_candidate_pool(hypothesis_dir)

    def _freeze_candidate_pool(self, hypothesis_dir: Path) -> None:
        """
        Stamp the candidate pool with a hash of its contents.

        Until it carries one, an edit to the pool is undetectable: the file
        loads, the study runs, and the two conditions were curating different
        material. With it, any later change to a candidate — by a repair, by a
        hand, by a rerun of the generator — is refused when the pool is loaded.
        """
        from tools.choice_set import CandidatePool

        path = hypothesis_dir / "candidate_pool.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("fingerprint", None)
            pool = CandidatePool.from_dict(data)
        except Exception as exc:
            logger.warning("Could not freeze the candidate pool: %s", exc)
            return
        path.write_text(json.dumps(pool.as_dict(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        console.print(f"  [dim]Candidate pool frozen: {pool.fingerprint} "
                      f"({len(pool)} candidates)[/]")

    # ------------------------------------------------------------------
    # Step E: persist to NoteDB
    # ------------------------------------------------------------------

    def _persist_to_db(
        self,
        session_id: str,
        hypothesis_id: str,
        files: dict[str, str],
    ) -> None:
        """Save all generated files to the experiment_code table."""
        ext_to_lang = {
            ".py":   "python",
            ".yaml": "yaml",
            ".yml":  "yaml",
            ".txt":  "text",
            ".md":   "text",
        }
        for file_path, content in files.items():
            ext = Path(file_path).suffix.lower()
            language = ext_to_lang.get(ext, "text")
            self._ndb.save_experiment_code(
                session_id=session_id,
                hypothesis_id=hypothesis_id,
                file_path=file_path,
                file_content=content,
                language=language,
            )

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _print_file_tree(
        self,
        hypothesis_dir: Path,
        files: dict[str, str],
    ) -> None:
        """Print a summary table of generated files."""
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("File", min_width=35)
        table.add_column("Size", justify="right", width=10)
        table.add_column("Status", width=8, justify="center")

        for rel_path, content in sorted(files.items()):
            size = f"{len(content):,} ch"
            status = (
                "[red]FAILED[/]"
                if content.startswith("# Generation failed")
                else "[green]OK[/]"
            )
            table.add_row(str(rel_path), size, status)

        console.print(table)
        console.print(
            f"\n[dim]To start training:[/]\n"
            f"  cd {hypothesis_dir}\n"
            f"  pip install -r requirements.txt\n"
            f"  python train.py --config config.yaml"
        )
