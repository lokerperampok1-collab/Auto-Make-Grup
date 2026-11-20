import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
WWW_DIR = BASE_DIR / "apk_www"


def prepare_apk_www() -> None:
    """
    Siapkan folder `apk_www/` untuk dibungkus menjadi APK Mandiri oleh Capacitor.
    Mengubah path `/static/...` menjadi path relatif dan mengaktifkan FORCE_STANDALONE_APK.
    """
    if WWW_DIR.exists():
        shutil.rmtree(WWW_DIR)
    WWW_DIR.mkdir(parents=True, exist_ok=True)
    static_dest = WWW_DIR / "static"
    shutil.copytree(STATIC_DIR, static_dest)

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        '<script src="/static/standalone_mtproto.js"></script>',
        '<script>window.FORCE_STANDALONE_APK = true;</script>\n  <script src="./static/standalone_mtproto.js"></script>',
    )
    html = html.replace('href="/static/', 'href="./static/')
    html = html.replace('src="/static/', 'src="./static/')
    (WWW_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"[OK] Folder APK Mandiri berhasil disiapkan di: {WWW_DIR}")


if __name__ == "__main__":
    prepare_apk_www()
