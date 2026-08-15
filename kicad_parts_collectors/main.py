import sys

if sys.platform == "darwin":
    from .qt_app import main
else:
    from .app import main


if __name__ == "__main__":
    main()
