import functools
import importlib
import inspect
import os
import threading
import time
from const.const import ROOT_DIR
import logging
import mcp.types as types
import traceback

from pkg.utils.dir_listener import DirListener


type_mapping = {"int": "number", "str": "string", "float": "number"}


class ToolService:

    tools_desc = {}
    tool_func = {}
    thread_lock = threading.Lock()

    def __init__(self):
        self.logger = logging.getLogger(__file__)
        self.reload_tools()
        _ = DirListener(
            os.path.join(ROOT_DIR, "pkg", "tools"),
            self.listen_handler,
            self.listen_handler,
            self.listen_handler,
        )
        self.updated_time = None

    def listen_handler(self, event):
        reload = False
        """
        if (
            isinstance(event, FileCreatedEvent)
            or isinstance(event, FileModifiedEvent)
            or isinstance(event, FileDeletedEvent)
        ):
        """
        if self.updated_time and time.time() - self.updated_time < 3:
            return
        self.logger.info("Reloading tools")
        self.reload_tools()
        self.logger.info(f"Reloaded tools")

    def get_func_params(self, func):

        sig = inspect.signature(func)
        keys = list(sig.parameters.keys())
        desc = {}
        for key, param in sig.parameters.items():
            desc[key] = {"type": type_mapping.get(param.annotation.__name__, "any")}
        return keys, desc

    def reload_tools(self):
        self.tools_desc = {}
        with self.thread_lock:
            tool_dir = os.path.join(ROOT_DIR, "pkg", "tools")
            for tool_filename in os.listdir(tool_dir):
                if not tool_filename.endswith(".py") or tool_filename.startswith("_"):
                    continue
                module = importlib.import_module(f"pkg.tools.{tool_filename[:-3]}")
                module = importlib.reload(module)
                classes = {
                    name: cls
                    for name, cls in inspect.getmembers(module, inspect.isclass)
                    if cls.__module__ == module.__name__
                }
                for name, cls in classes.items():
                    methods = inspect.getmembers(cls, inspect.isfunction)

                    for method_name, method in methods:
                        # 2. (可选) 过滤掉私有方法和魔术方法 (如 __init__)
                        if method_name.startswith("_"):
                            continue

                        # 3. 获取方法的注释 (Docstring)
                        # inspect.getdoc() 比 method.__doc__ 更好，因为它会自动去除缩进空白
                        method_desc = inspect.getdoc(method)
                        if method_desc and len(method_desc) > 0:
                            keys, properties = self.get_func_params(method)
                            self.tools_desc[f"{name}.{method_name}"] = {
                                "name": f"{name}.{method_name}",
                                "description": method_desc,
                                "inputSchema": {
                                    "type": "object",
                                    "required": keys,
                                    "properties": properties,
                                },
                            }
                            self.tool_func[f"{name}.{method_name}"] = method
        self.logger.info(f"Existed tool func list: {self.tools_desc.keys()}")

    def list(self):

        return [types.Tool(**tool) for tool in self.tools_desc.values()]

    def get(self, func_name):
        def wrapper(func, name):
            @functools.wraps(func)
            def func_wrapper(*args, **kwargs):
                self.logger.info(f"Call tool: {name} | Args: {args} | Kwargs: {kwargs}")
                try:
                    res = func(*args, **kwargs)
                    self.logger.info(f"Call {name} return [{res}]")
                    return res
                except Exception as e:
                    error_msg = f"Tool execution error: {str(e)}"
                    self.logger.error(f"Execute {name} error: {traceback.format_exc()}")
                    return f"Error: {error_msg}"

            return func_wrapper

        func = self.tool_func.get(func_name)
        if func is None:
            return None
        return wrapper(func, func_name)


_lock = threading.Lock()
_service: ToolService = None


def get_default_tool_service() -> ToolService:
    global _service
    if _service is not None:
        return _service

    with _lock:
        if _service is not None:
            return _service
        _service = ToolService()
    return _service
