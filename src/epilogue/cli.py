"""Command-line entry points for Epilogue."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="epilogue",
        description="Epilogue — the agent that settles what's left behind.",
    )
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the dashboard and the Vigil")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("demo", help="Run with a fresh database, ready for the demo case")
    sub.add_parser("reset", help="Clear all case data")

    preview = sub.add_parser(
        "preview",
        help="Explore the dashboard with a seeded mid-case state — no model credentials needed",
    )
    preview.add_argument("--host", default="127.0.0.1")
    preview.add_argument("--port", type=int, default=8000)

    tick = sub.add_parser("tick", help="Run one Vigil work cycle from the terminal")
    tick.add_argument("--advance", type=int, default=0, help="Advance the case clock N days first")

    args = parser.parse_args(argv)

    if args.command == "reset":
        from .config import db_path
        from .ledger import Ledger

        Ledger(db_path()).reset()
        print("Case data cleared.")
        return 0

    if args.command == "tick":
        from .config import db_path, make_model
        from .engine import Vigil
        from .ledger import Ledger

        ledger = Ledger(db_path())
        case = ledger.first_case()
        if case is None:
            print("No case open. Start one from the dashboard (epilogue serve).")
            return 1
        vigil = Vigil(ledger, make_model())
        if args.advance:
            ledger.advance_days(args.advance)
        report = vigil.tick(case.id)
        print(report.summary())
        return 0

    if args.command in ("serve", "demo", "preview", None):
        import os

        import uvicorn

        if args.command == "demo":
            from .config import db_path
            from .ledger import Ledger

            Ledger(db_path()).reset()
            print("Fresh case database. The intake form will offer the demo case.")
        if args.command == "preview":
            # Keep the preview world separate from any real case data.
            os.environ.setdefault("EPILOGUE_DATA_DIR", "data-preview")
            from .config import db_path
            from .ledger import Ledger
            from .preview import seed_preview

            case = seed_preview(Ledger(db_path()))
            print(f"Preview case seeded ({case.id}) — no model credentials required.")
        host = getattr(args, "host", "127.0.0.1")
        port = int(getattr(args, "port", 8000) or 8000)
        print(f"Epilogue is listening at http://{host}:{port}")
        uvicorn.run("epilogue.server:app", host=host, port=port, log_level="warning")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
