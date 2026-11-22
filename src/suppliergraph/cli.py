"""`sg` command line: init-db, ingest, resolve, extract, build-kg, validate, train, eval, serve, data."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import get_settings


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_ingest(a):
    from .pipeline import ingest_all

    _p(ingest_all(get_settings(), gleif_countries=a.countries.split(",") if a.countries else None))


def cmd_resolve(a):
    from .pipeline import resolve_all

    _p(resolve_all(get_settings()))


def cmd_extract(a):
    from .llm import LLMUnavailable, get_llm
    from .pipeline import extract_all, load_regulations

    llm = None
    try:
        llm = get_llm()
    except LLMUnavailable as exc:
        print(f"LLM not configured ({exc}); obligations will be skipped.", file=sys.stderr)
    _p(extract_all(get_settings(), llm, load_regulations()))


def cmd_build(a):
    from .kg.build import build_kg
    from .store import open_store

    s = get_settings()
    _p(build_kg(open_store(s), s, reason=not a.no_reasoning))


def cmd_validate(a):
    from .kg.validate import validate
    from .store import open_store

    r = validate(open_store(get_settings()))
    _p(r)
    sys.exit(0 if r["conforms"] else 1)


def cmd_train(a):
    from .ml.train import run_experiment, train_final
    from .store import open_store

    s = get_settings()
    st = open_store(s)
    kw = dict(dim=a.dim, epochs=a.epochs)
    if a.final:
        _p(train_final(st, a.model, s.models_dir / "current", **kw))
    else:
        _p(run_experiment(st, model_name=a.model, out_dir=s.models_dir / "current", **kw)["test"])


def cmd_eval(a):
    from .eval.run import run_eval, save, to_markdown
    from .llm import get_llm
    from .rag.answer import AnswerEngine
    from .store import open_store

    s = get_settings()
    report = run_eval(AnswerEngine(get_llm(), open_store(s)), only=a.only.split(",") if a.only else None)
    save(report, s.data_dir / "eval")
    print(to_markdown(report))


def cmd_er_eval(a):
    from .er.evaluate import evaluate
    from .staging.db import get_engine

    s = get_settings()
    r = evaluate(get_engine(s.staging_url))
    (s.data_dir / "er_eval.json").write_text(json.dumps(r, indent=2, default=str))
    _p(r)


def cmd_serve(a):
    import uvicorn

    uvicorn.run("suppliergraph.api.main:app_factory", factory=True, host=a.host, port=a.port, reload=a.reload)


def cmd_data(a):
    from .ingest import check, download

    if a.action == "check":
        r = check.check_ocds(Path(a.file)) if a.source == "ocds" else check.check_csv(a.source, Path(a.file) if a.file else None)
        _p(r)
    else:
        print(download.download(a.source))


def cmd_init(a):
    from .staging.db import get_engine, init_schema

    init_schema(get_engine(get_settings().staging_url), reset=True)
    print("staging schema created")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sg", description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(f=cmd_init)
    p = sub.add_parser("ingest"); p.add_argument("--countries"); p.set_defaults(f=cmd_ingest)
    sub.add_parser("resolve").set_defaults(f=cmd_resolve)
    sub.add_parser("extract").set_defaults(f=cmd_extract)
    p = sub.add_parser("build-kg"); p.add_argument("--no-reasoning", action="store_true"); p.set_defaults(f=cmd_build)
    sub.add_parser("validate").set_defaults(f=cmd_validate)
    p = sub.add_parser("train")
    p.add_argument("--model", default="rotate", choices=["transe", "rotate"]); p.add_argument("--dim", type=int, default=64)
    p.add_argument("--epochs", type=int, default=200)
    p.add_argument("--final", action="store_true", help="train on ALL awards for serving (no honest metrics)")
    p.set_defaults(f=cmd_train)
    p = sub.add_parser("eval"); p.add_argument("--only", help="comma-separated question ids"); p.set_defaults(f=cmd_eval)
    sub.add_parser("er-eval").set_defaults(f=cmd_er_eval)
    p = sub.add_parser("serve"); p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true"); p.set_defaults(f=cmd_serve)
    p = sub.add_parser("data"); p.add_argument("action", choices=["check", "download"])
    p.add_argument("source", choices=["gleif1", "gleif2", "cpv", "sanctions", "ocds"]); p.add_argument("file", nargs="?")
    p.set_defaults(f=cmd_data)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING)
    a.f(a)


if __name__ == "__main__":
    main()
