"""Command-line utilities.

python -m app.cli download-embedding-model [--model NAME]
python -m app.cli init
python -m app.cli eval [--dataset default] [--out report.md] [--json report.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings


def download_embedding_model(model: str | None) -> int:
    """Explicitly download embedding weights from Hugging Face (one-time, user initiated)."""
    settings = get_settings()
    name = model or settings.embedding_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print('sentence-transformers is not installed: pip install -e ".[embeddings]"', file=sys.stderr)
        return 1
    print(f"Downloading {name} ...")
    st = SentenceTransformer(name, device=settings.embedding_device)
    print(f"OK: {name} (dimension {st.get_sentence_embedding_dimension()}) is cached locally.")
    if settings.reranker_model:
        from sentence_transformers import CrossEncoder

        CrossEncoder(settings.reranker_model)
        print(f"OK: reranker {settings.reranker_model} is cached locally.")
    return 0


def init() -> int:
    from app.core.container import build_container

    c = build_container(get_settings())
    print(f"Database: {c.settings.resolved_database_url}")
    print(f"Demo SQL database: {c.settings.resolved_demo_db_path}")
    print(f"Vector store: {c.vectors.description}")
    c.close()
    return 0


def run_eval(dataset: str, out: str | None, json_out: str | None) -> int:
    from app.core.container import build_container
    from app.evaluation.runner import DatasetRunRequest, report_markdown, run_dataset

    c = build_container(get_settings())
    try:
        report = asyncio.run(run_dataset(c, DatasetRunRequest(dataset=dataset)))
    finally:
        c.close()
    md = report_markdown(report)
    if out:
        Path(out).write_text(md, encoding="utf-8")
        print(f"Wrote {out}")
    else:
        print(md)
    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download-embedding-model", help="download the embedding (and reranker) model once")
    d.add_argument("--model")
    sub.add_parser("init", help="create databases and the vector store")
    e = sub.add_parser("eval", help="run an evaluation dataset against the configured services")
    e.add_argument("--dataset", default="default")
    e.add_argument("--out")
    e.add_argument("--json")
    args = parser.parse_args(argv)
    if args.cmd == "download-embedding-model":
        return download_embedding_model(args.model)
    if args.cmd == "init":
        return init()
    return run_eval(args.dataset, args.out, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
