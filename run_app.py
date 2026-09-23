import sys

if "--part-preview" in sys.argv:
    from kicad_parts_collectors.preview_window import main
elif sys.platform == "darwin":
    from kicad_parts_collectors.qt_app import main
else:
    from kicad_parts_collectors.app import main


if __name__ == "__main__":
    main()
