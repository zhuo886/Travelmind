"""启动入口。

用法（务必用项目虚拟环境，否则规划会在建图阶段因缺依赖失败）：
    .venv\\Scripts\\python.exe run.py
    → http://localhost:8766
"""

import importlib.util
import logging
import sys

import uvicorn

_UNSUPPORTED_MARK = "\u2708\ufe0f  旅游规划助手启动中…"
_PLAIN_MARK = "[TravelMind] 旅游规划助手启动中…"


def _say(text: str, fallback: str | None = None) -> None:
    """控制台重定向到 GBK 文件时，emoji 会触发 UnicodeEncodeError；降级为纯文本。"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(fallback or text.encode("ascii", "ignore").decode("ascii"))


def _check_runtime() -> list[str]:
    """启动前检查规划所需的第三方依赖，避免跑到一半才报 ModuleNotFoundError。"""
    required = ("langgraph", "langchain_openai", "httpx", "fastapi", "uvicorn")
    return [name for name in required if importlib.util.find_spec(name) is None]


# 配置日志：INFO 级别保留主要流程信息；
# app.planning.helpers 的 WARNING 日志（LLM 重试/耗时）会直接打印到控制台，
# 无需额外配置即可看到结构化输出失败重试情况。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# 对规划核心模块开启 DEBUG，输出 LLM 调用耗时和 time_check 推理过程
logging.getLogger("app.planning.helpers").setLevel(logging.DEBUG)
logging.getLogger("app.planning.nodes").setLevel(logging.DEBUG)

if __name__ == "__main__":
    _say(_UNSUPPORTED_MARK, _PLAIN_MARK)

    missing = _check_runtime()
    if missing:
        print("[警告] 当前解释器缺少依赖：" + ", ".join(missing))
        print("       当前解释器：" + sys.executable)
        print("       请改用项目虚拟环境启动：.venv\\Scripts\\python.exe run.py")
        print("       目前仍会启动服务，但「开始规划」会在建图阶段失败。")

    print("   访问：http://localhost:8766")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8766, reload=False)
