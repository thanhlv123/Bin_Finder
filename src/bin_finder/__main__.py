"""Headless command dispatcher; never imports the GUI."""
import sys


def main(argv: list[str] | None = None) -> int:
    """Dispatch supported headless commands."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "run":
        from bin_finder.run.cli import main as run_main
        return run_main(arguments[1:])
    print("usage: python -m bin_finder run SCRIPT -o OUT_DIR [options]")
    return 0 if arguments == ["--help"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
