"""途吖后端应用"""
__version__ = "0.1.0"


def get_runtime_version() -> str:
    """返回「语义版本 + 短 git SHA」的运行期版本标识。

    用途：让任何在跑的进程都可被唯一识别。
    之前踩过的坑：后端进程是旧代码（分类逻辑未加载），但 health 只返回固定
    "0.1.0"，无法判断进程到底跑的是哪份代码，导致「_classify 不生效」被误判为
    代码 bug，实际只是没重启。现在 health 会带 git SHA，重启前后 SHA 不同即说明
    加载了新代码。
    """
    import subprocess

    sha = ""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=__import__("os").path.dirname(__file__),
        )
        if out.returncode == 0:
            sha = out.stdout.strip()
    except Exception:
        pass
    return f"{__version__}+{sha}" if sha else __version__
