import os
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class dirListenHandler(FileSystemEventHandler):
    modified_callback = None
    created_callback = None
    deleted_callback = None

    # 监听文件修改
    def on_modified(self, event):
        if self.modified_callback:
            self.modified_callback(event)
        # if event.src_path.endswith("config.yaml"):
        # load_config(reload=True)

    # 监听文件创建
    def on_created(self, event):
        if self.created_callback:
            self.created_callback(event)
        pass

    # 监听文件删除
    def on_deleted(self, event):
        if self.deleted_callback:
            self.deleted_callback(event)
        pass


class DirListener:
    def __init__(
        self,
        dir_path,
        modified_callback: callable = None,
        created_callback=None,
        deleted_callback=None,
    ):

        event_handler = dirListenHandler()
        event_handler.modified_callback = modified_callback
        event_handler.created_callback = created_callback
        event_handler.deleted_callback = deleted_callback
        observer = Observer()
        observer.schedule(event_handler, dir_path)  # recursive=True 表示递归子目录
        observer.start()
