"""PyInstaller entry; all application behavior lives in media_catalog.desktop."""
from media_catalog.desktop import main

if __name__ == '__main__':
    raise SystemExit(main())
