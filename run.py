import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description="Local PDF workflow desktop shell")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Show the default workflow output for built-in synthetic text")
    mode.add_argument("--self-test", action="store_true", help="Exercise the default customization hook without a GUI")
    args = parser.parse_args()
    if args.demo or args.self_test:
        from app.pipeline import run_pipeline, demo_pages
        report = run_pipeline(demo_pages())
        if args.self_test:
            if not isinstance(report, dict) or not report:
                raise RuntimeError("The workflow must return a non-empty report object")
            json.dumps(report, ensure_ascii=False)
            print("Synthetic workflow hook returned a JSON-serializable report.")
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        from modules.diagnostics import prepare_gui_runtime
        prepare_gui_runtime()
        from app.gui import launch
        launch()


if __name__ == "__main__":
    main()
