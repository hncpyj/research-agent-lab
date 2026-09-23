"""
Dataset Resolver — maps research topics to real public benchmark datasets.

Returns a DatasetSpec that is injected into experiment prompt templates so
generated code references real benchmark data instead of synthetic samples.

This is the "B" improvement axis: real data integration via HuggingFace datasets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DatasetSpec:
    """All info needed to reference and load a real public benchmark."""

    name: str                  # Human-readable dataset name
    hf_dataset_id: str         # HuggingFace datasets ID (or special key)
    package: str               # "datasets" | "beir" | "torchvision" | "gymnasium"
    train_split: str           # HF split name for training
    test_split: str            # HF split name for evaluation
    metrics: list              # Primary evaluation metrics (list[str])
    num_train_samples: int     # Realistic training set size
    num_test_samples: int      # Realistic test set size
    description: str           # One-line description
    install_hint: str          # pip install command for required packages
    loader_snippet: str        # Python snippet showing how to load the dataset
    subset: Optional[str] = None   # HF config/subset name
    domain: str = "general"        # Which research domain this belongs to


# ---------------------------------------------------------------------------
# Dataset catalog
# ---------------------------------------------------------------------------

_CATALOG: list[tuple[list, DatasetSpec]] = [

    # ── Information Retrieval ──────────────────────────────────────────────
    (
        [
            "retrieval", "ranking", "dense retrieval", "bi-encoder",
            "passage retrieval", "beir", "ms-marco", "ms marco", "faiss",
            "bm25", "dpr", "sbert", "contrastive retrieval",
            "similarity search", "dual encoder",
        ],
        DatasetSpec(
            name="MS-MARCO Passage Ranking",
            hf_dataset_id="ms_marco",
            subset="v1.1",
            package="datasets",
            train_split="train",
            test_split="validation",
            metrics=["Recall@10", "Recall@100", "MRR@10", "nDCG@10"],
            num_train_samples=532761,
            num_test_samples=6980,
            description=(
                "Microsoft Machine Reading Comprehension: 500k+ query-passage "
                "pairs for passage retrieval research"
            ),
            install_hint=(
                "pip install datasets faiss-cpu sentence-transformers "
                "rank-bm25 evaluate"
            ),
            loader_snippet=(
                "from datasets import load_dataset\n"
                "dataset = load_dataset('ms_marco', 'v1.1')\n"
                "train_data = dataset['train']  # 532,761 examples\n"
                "val_data   = dataset['validation']  # 6,980 examples\n"
                "# Each example: {'query': str, 'passages': {'passage_text': [str], "
                "'is_selected': [int]}}"
            ),
            domain="retrieval",
        ),
    ),

    # ── Sentiment Analysis ─────────────────────────────────────────────────
    (
        [
            "sentiment", "sst", "opinion", "polarity",
            "movie review", "imdb", "positive negative",
        ],
        DatasetSpec(
            name="SST-2 (GLUE Sentiment)",
            hf_dataset_id="glue",
            subset="sst2",
            package="datasets",
            train_split="train",
            test_split="validation",
            metrics=["Accuracy", "F1"],
            num_train_samples=67349,
            num_test_samples=872,
            description=(
                "Stanford Sentiment Treebank binary sentiment classification "
                "(part of GLUE benchmark)"
            ),
            install_hint=(
                "pip install datasets transformers evaluate scikit-learn torch"
            ),
            loader_snippet=(
                "from datasets import load_dataset\n"
                "dataset = load_dataset('glue', 'sst2')\n"
                "train_data = dataset['train']  # 67,349 examples\n"
                "val_data   = dataset['validation']  # 872 examples\n"
                "# Each example: {'sentence': str, 'label': int (0=neg, 1=pos)}"
            ),
            domain="nlp",
        ),
    ),

    # ── Natural Language Inference ─────────────────────────────────────────
    (
        [
            "natural language inference", "nli", "entailment", "contradiction",
            "hypothesis premise", "snli", "mnli", "textual entailment",
        ],
        DatasetSpec(
            name="MultiNLI (GLUE MNLI)",
            hf_dataset_id="glue",
            subset="mnli",
            package="datasets",
            train_split="train",
            test_split="validation_matched",
            metrics=["Accuracy", "F1-macro"],
            num_train_samples=392702,
            num_test_samples=9815,
            description=(
                "Multi-Genre Natural Language Inference — 3-class entailment "
                "classification across diverse text genres"
            ),
            install_hint="pip install datasets transformers evaluate torch",
            loader_snippet=(
                "from datasets import load_dataset\n"
                "dataset = load_dataset('glue', 'mnli')\n"
                "train_data = dataset['train']  # 392,702 examples\n"
                "val_data   = dataset['validation_matched']  # 9,815 examples\n"
                "# Each example: {'premise': str, 'hypothesis': str, 'label': int}"
            ),
            domain="nlp",
        ),
    ),

    # ── Summarisation ──────────────────────────────────────────────────────
    (
        [
            "summariz", "summarisation", "abstractive", "extractive",
            "rouge", "cnn dailymail", "seq2seq",
        ],
        DatasetSpec(
            name="CNN/DailyMail Summarisation",
            hf_dataset_id="cnn_dailymail",
            subset="3.0.0",
            package="datasets",
            train_split="train",
            test_split="test",
            metrics=["ROUGE-1", "ROUGE-2", "ROUGE-L", "BERTScore"],
            num_train_samples=287113,
            num_test_samples=11490,
            description=(
                "CNN and DailyMail news article summarisation — "
                "articles paired with multi-sentence highlights"
            ),
            install_hint=(
                "pip install datasets transformers evaluate rouge-score "
                "bert-score torch"
            ),
            loader_snippet=(
                "from datasets import load_dataset\n"
                "dataset = load_dataset('cnn_dailymail', '3.0.0')\n"
                "train_data = dataset['train']  # 287,113 examples\n"
                "test_data  = dataset['test']   # 11,490 examples\n"
                "# Each example: {'article': str, 'highlights': str, 'id': str}"
            ),
            domain="nlp",
        ),
    ),

    # ── Image Classification (must come before general NLP) ───────────────
    (
        [
            "image classif", "image recognition", "computer vision",
            "cifar", "imagenet", "resnet", "vit", "convolutional", "cnn",
            "visual recognition", "self-supervised vision", "visual",
        ],
        DatasetSpec(
            name="CIFAR-10",
            hf_dataset_id="cifar10",
            package="datasets",
            train_split="train",
            test_split="test",
            metrics=["Top-1 Accuracy", "Top-5 Accuracy"],
            num_train_samples=50000,
            num_test_samples=10000,
            description=(
                "CIFAR-10: 60,000 32x32 colour images in 10 classes "
                "(airplane/car/bird/cat/deer/dog/frog/horse/ship/truck)"
            ),
            install_hint="pip install datasets torch torchvision Pillow",
            loader_snippet=(
                "from datasets import load_dataset\n"
                "dataset = load_dataset('cifar10')\n"
                "train_data = dataset['train']  # 50,000 examples\n"
                "test_data  = dataset['test']   # 10,000 examples\n"
                "# Each example: {'img': PIL.Image, 'label': int (0-9)}"
            ),
            domain="cv",
        ),
    ),

    # ── General NLP / Text Classification ─────────────────────────────────
    (
        [
            "text classif", "nlp", "bert", "transformers", "huggingface",
            "language model", "fine-tun", "sequence labeling",
            "topic classif", "news classif", "text categor",
        ],
        DatasetSpec(
            name="AG News (Topic Classification)",
            hf_dataset_id="ag_news",
            package="datasets",
            train_split="train",
            test_split="test",
            metrics=["Accuracy", "F1-macro"],
            num_train_samples=120000,
            num_test_samples=7600,
            description=(
                "AG News 4-class news topic classification: "
                "World / Sports / Business / Sci-Tech"
            ),
            install_hint=(
                "pip install datasets transformers evaluate scikit-learn torch"
            ),
            loader_snippet=(
                "from datasets import load_dataset\n"
                "dataset = load_dataset('ag_news')\n"
                "train_data = dataset['train']  # 120,000 examples\n"
                "test_data  = dataset['test']   # 7,600 examples\n"
                "# Each example: {'text': str, 'label': int (0-3)}"
            ),
            domain="nlp",
        ),
    ),

    # ── Object Detection / Segmentation ───────────────────────────────────
    (
        [
            "object detection", "segmentation", "bounding box", "coco", "yolo",
            "instance segmentation", "semantic segmentation", "map",
        ],
        DatasetSpec(
            name="COCO 2017 (Object Detection)",
            hf_dataset_id="detection-datasets/coco",
            package="datasets",
            train_split="train",
            test_split="val",
            metrics=["mAP@50", "mAP@50:95", "mAR@100"],
            num_train_samples=118287,
            num_test_samples=5000,
            description=(
                "COCO 2017 object detection and segmentation benchmark: "
                "80 categories, 118k training images"
            ),
            install_hint=(
                "pip install datasets torch torchvision pycocotools Pillow"
            ),
            loader_snippet=(
                "from datasets import load_dataset\n"
                "dataset = load_dataset('detection-datasets/coco')\n"
                "train_data = dataset['train']  # 118,287 images\n"
                "val_data   = dataset['val']    # 5,000 images"
            ),
            domain="cv",
        ),
    ),

    # ── Domain Adaptation ─────────────────────────────────────────────────
    (
        [
            "domain adaptation", "domain shift", "domain invariant", "mmd",
            "coral", "dann", "transfer learn", "cross-domain",
            "distribution shift", "covariate shift", "source target",
        ],
        DatasetSpec(
            name="Office-31 (Domain Adaptation)",
            hf_dataset_id="alkzar90/office-home-dataset",
            package="datasets",
            train_split="train",
            test_split="test",
            metrics=["Target Domain Accuracy", "Source-Only Baseline Accuracy", "Transfer Gap"],
            num_train_samples=15588,
            num_test_samples=3897,
            description=(
                "Office-Home: 4 domains (Art / Clipart / Product / RealWorld), "
                "65 object categories — standard domain adaptation benchmark"
            ),
            install_hint="pip install datasets torch torchvision Pillow",
            loader_snippet=(
                "from datasets import load_dataset\n"
                "# Load all domains; filter by 'domain' column\n"
                "dataset = load_dataset('alkzar90/office-home-dataset')\n"
                "source = [x for x in dataset['train'] if x['domain'] == 'Art']\n"
                "target = [x for x in dataset['train'] if x['domain'] == 'RealWorld']"
            ),
            domain="domain_adaptation",
        ),
    ),

    # ── Reinforcement Learning (synthetic env — no HF dataset) ────────────
    (
        [
            "reinforcement learning", "rl agent", "policy gradient", "ppo",
            "q-learning", "reward", "environment", "gymnasium", "atari",
            "minigrid", "mdp", "bandit", "actor critic",
        ],
        DatasetSpec(
            name="MiniGrid-FourRooms-v0 (Procedural RL Env)",
            hf_dataset_id="synthetic_rl",
            package="gymnasium",
            train_split="online",
            test_split="online",
            metrics=["Mean Return", "Success Rate", "Credit Assignment Gap"],
            num_train_samples=100000,   # env steps
            num_test_samples=1000,      # eval episodes
            description=(
                "MiniGrid sparse-reward navigation environment — "
                "procedurally generated, no static dataset required"
            ),
            install_hint="pip install gymnasium minigrid torch numpy rich pyyaml",
            loader_snippet=(
                "import gymnasium as gym\n"
                "import minigrid  # registers MiniGrid environments\n"
                "env = gym.make('MiniGrid-FourRooms-v0')"
            ),
            domain="rl",
        ),
    ),
]

# Kept only so an older caller asking for it by name still gets something
# describable. `resolve()` never returns it: a dataset nobody asked for is how
# an adversarial-curation study ended up classifying news headlines.
_DEFAULT_DATASET = DatasetSpec(
    name="AG News (Topic Classification - fallback)",
    hf_dataset_id="ag_news",
    package="datasets",
    train_split="train",
    test_split="test",
    metrics=["Accuracy", "F1-macro"],
    num_train_samples=120000,
    num_test_samples=7600,
    description="AG News 4-class news topic classification (default fallback)",
    install_hint=(
        "pip install datasets transformers evaluate scikit-learn torch"
    ),
    loader_snippet=(
        "from datasets import load_dataset\n"
        "dataset = load_dataset('ag_news')\n"
        "train_data = dataset['train']\n"
        "test_data  = dataset['test']"
    ),
    domain="nlp",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DatasetUnresolved(LookupError):
    """No dataset in the catalogue fits this hypothesis."""


def resolve(topic: str) -> DatasetSpec:
    """
    Infer the most appropriate public benchmark from the hypothesis/topic text.

    Raises DatasetUnresolved when nothing matches. It used to return AG News,
    which meant a study about anything at all could be handed a news-topic
    classification set and run to completion: the worst failure this system
    can have is not an error, it is a wrong experiment that finishes and
    produces numbers.
    """
    text = topic.lower()
    for keywords, spec in _CATALOG:
        if any(kw in text for kw in keywords):
            matched = next(kw for kw in keywords if kw in text)
            logger.info(
                "DatasetResolver: keyword '%s' → dataset '%s' (%d train, %d test)",
                matched, spec.name, spec.num_train_samples, spec.num_test_samples,
            )
            return spec

    logger.warning("DatasetResolver: no dataset in the catalogue matches this topic.")
    raise DatasetUnresolved(
        "No dataset in the catalogue fits this hypothesis. Name the data in the "
        "brief, or run a study that needs none.")


def describe(spec: DatasetSpec) -> str:
    """One-line human-readable summary for logging and UI display."""
    return (
        f"{spec.name} | train={spec.num_train_samples:,} "
        f"| test={spec.num_test_samples:,} "
        f"| metrics={', '.join(spec.metrics[:2])}"
    )


def as_dict(spec: DatasetSpec) -> dict:
    """Serialise to a dict suitable for JSON injection into prompt templates."""
    return {
        "name":              spec.name,
        "hf_dataset_id":     spec.hf_dataset_id,
        "subset":            spec.subset,
        "package":           spec.package,
        "train_split":       spec.train_split,
        "test_split":        spec.test_split,
        "metrics":           spec.metrics,
        "num_train_samples": spec.num_train_samples,
        "num_test_samples":  spec.num_test_samples,
        "install_hint":      spec.install_hint,
        "loader_snippet":    spec.loader_snippet,
        "description":       spec.description,
        "domain":            spec.domain,
    }
