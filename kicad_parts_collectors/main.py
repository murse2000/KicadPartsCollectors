import sys

if "--part-preview" in sys.argv:
    from .preview_window import main
elif sys.platform == "darwin":
    from .qt_app import main
else:
    from .app import main


if __name__ == "__main__":
    main()
