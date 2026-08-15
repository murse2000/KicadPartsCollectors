import sys

if sys.platform == "darwin":
    from kicad_parts_collectors.qt_app import main
else:
    from kicad_parts_collectors.app import main


if __name__ == "__main__":
    main()
