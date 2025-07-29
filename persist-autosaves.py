from abc import abstractmethod
from hashlib import md5
from math import ceil
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from threading import Barrier, Timer

from watchdog.events import (
  FileSystemEvent,
  RegexMatchingEventHandler,
)
from watchdog.observers import Observer

####################################################################################################################


APPDATA = os.getenv("APPDATA")
COE5_SAVES_PATH = f"{APPDATA}\\coe5\\saves\\"
COE5_AUTOSAVE_NAME = "autosave"
COE5_PROCESS = "COE5.exe"
PROCESS_WAIT_TIMEOUT_SECONDS = 120
AUTOSAVES_TO_KEEP = 3


####################################################################################################################


class FileIndex:
  @abstractmethod
  def exists(self, path: str, insert_if_new: bool = True) -> bool:
    pass

  @abstractmethod
  def remove(self, path: str):
    pass


class JoinableHandler(RegexMatchingEventHandler):
  @abstractmethod
  def join(self, timeout: float | None = None):
    pass


class AutosaveIndex(FileIndex):
  FILE_HASH_BUFFER_SIZE = 4000

  def __init__(self, path: str, ignored_filenames: str):
    """path: Path to the directory that contains all the autosaves"""
    self.existing_autosaves = {}
    for filename in os.listdir(path):
      if filename not in ignored_filenames:
        file_path = f"{path}{filename}"
        file_hash = self.__get_hash_from_file(file_path)
        self.existing_autosaves[file_path] = file_hash

  def __get_hash_from_file(self, path: str):
    file = open(path, "rb")
    file.seek(ceil(os.stat(path).st_size - self.FILE_HASH_BUFFER_SIZE))
    file_hash = md5(file.read(self.FILE_HASH_BUFFER_SIZE)).hexdigest()
    print(path, file_hash)
    file.close()
    return file_hash

  def exists(self, path: str, insert_if_new: bool = True) -> bool:
    """path: Path to an autosave file"""
    file_hash = self.__get_hash_from_file(path)
    result = file_hash in self.existing_autosaves.values()
    if insert_if_new and not result:
      self.existing_autosaves[path] = file_hash
    return result
  
  def remove(self, path: str):
    """path: Path to an autosave file"""
    self.existing_autosaves.pop(path)


class AutosaveHandler(JoinableHandler):
  HANDLING_DELAY = 2
  """In seconds"""

  def __init__(self, file_name_to_handle: str, autosaves_to_keep: int, index: FileIndex):
    super().__init__(
      regexes=[f".*\\\\{file_name_to_handle}$"],
      ignore_regexes=[],
      ignore_directories=True,
      case_sensitive=True,
    )

    self.file_name_to_handle = file_name_to_handle
    self.autosaves_to_keep = autosaves_to_keep
    self.index = index
    self.handling_timer = None
    self.handling_barrier = Barrier(1, timeout=60)

  def join(self, timeout: float | None = None):
    if self.handling_timer is not None:
      self.handling_timer.join(timeout)

  def on_created(self, event: FileSystemEvent):
    self.__handle_event(event)

  def on_modified(self, event: FileSystemEvent):
    self.__handle_event(event)

  def on_closed(self, event: FileSystemEvent):
    self.__handle_event(event)

  def __handle_event(self, event: FileSystemEvent):
    self.handling_barrier.wait()

    if self.handling_timer is not None:
      self.handling_timer.cancel()
    self.handling_timer = Timer(self.HANDLING_DELAY, self.__handle_autosave, args=[event])
    self.handling_timer.start()

  def __list_existing_autosaves(self, path: str):
    """Returns a list of tuples containing path to each autosave file and its creation time"""
    filtered_paths = [f"{path}\\{filename}" for filename in filter(lambda filename: re.match(f"{self.file_name_to_handle}_.*", filename), os.listdir(path))]
    return [(file_path, os.stat(file_path).st_birthtime) for file_path in filtered_paths]

  def __handle_autosave(self, event: FileSystemEvent):
    """
    when new autosave is created:
      if autosave hash is equal to hash of any other save that still exists:
        print "soft deleting autosave triggered by a reload (same as X)(file kept as '.autosave' until next autosave happens)"
        replace to .autosave (hides the autosave from the loading menu and prevents it from being overwritten by the game)
      else:
        rename to autosave_yyyymmdd_hhmm
        store hash of .autosave in list
        while autosave count > N:
          delete oldest autosave
          delete hash from list
    """
    self.handling_barrier.wait()

    print("\nHandling ", event)
    dir_name = os.path.dirname(event.src_path)
    if self.index.exists(event.src_path):
      print(f"Soft deleting autosave triggered by a reload (file kept as '.{self.file_name_to_handle}' until next reload happens)")
      os.replace(event.src_path, f"{dir_name}\\.{self.file_name_to_handle}")
    else:
      new_autosave = f"{dir_name}\\{self.file_name_to_handle}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
      os.rename(event.src_path, new_autosave)
      print("New autosave:", new_autosave)

      existing_autosaves = self.__list_existing_autosaves(dir_name)
      while len(existing_autosaves) > self.autosaves_to_keep:
        oldest_autosave = min(existing_autosaves, key=lambda t: t[1])
        print("Deleting oldest autosave:", oldest_autosave[0])
        existing_autosaves.remove(oldest_autosave)
        self.index.remove(oldest_autosave[0])
        os.remove(oldest_autosave[0])


class AutosaveWatcher:
  OBSERVER_JOIN_INTERVAL = 3
  """In seconds"""

  def __init__(
    self,
    path_to_watch: str,
    process_to_wait_for: str,
    process_max_wait_seconds: int,
    handler: JoinableHandler,
  ):
    self.path = path_to_watch
    self.process = process_to_wait_for.lower()
    self.process_timeout = process_max_wait_seconds

    self.handler = handler

    self.observer = Observer()
    self.observer.schedule(self.handler, self.path)

    self.process_exists_call = self.__get_process_exists_call(self.process)

  @staticmethod
  def __get_process_exists_call(process) -> tuple:
    return ("TASKLIST", "/FI", "imagename eq %s" % process)

  def __process_exists(self) -> bool:
    output = subprocess.check_output(self.process_exists_call).decode(errors="ignore")
    last_line = output.strip().split("\r\n")[-1]
    return last_line.lower().startswith(self.process)

  def __wait_for_process_to_start(self):
    if self.__process_exists():
      return

    max_time_to_wait = datetime.now() + timedelta(0, self.process_timeout)
    print(f"Waiting for process '{self.process}' to start ...")
    while not self.__process_exists():
      diff = max_time_to_wait - datetime.now()
      print(
        f"\t{diff.seconds} seconds before timeout",
        end="",
      )
      print("\r", end="")
      time.sleep(1)
      if datetime.now() > max_time_to_wait:
        raise TimeoutError(f"Got tired of waiting for process '{self.process}'")

  def __watch_autosaves(self):
    print("\nWatching autosaves ...")
    self.observer.start()
    while self.__process_exists() and self.observer.is_alive():
      self.observer.join(self.OBSERVER_JOIN_INTERVAL)

  def run(self):
    self.__wait_for_process_to_start()
    try:
      self.__watch_autosaves()
    except KeyboardInterrupt:
      print("Got a KeyboardInterrupt")
    else:
      print(f"Process '{self.process}' stopped")
    finally:
      print("Stopping program ...")
      self.observer.stop()
      self.observer.join(timeout=60)


####################################################################################################################


if __name__ == "__main__":
  index = AutosaveIndex(COE5_SAVES_PATH, [COE5_AUTOSAVE_NAME, f".{COE5_AUTOSAVE_NAME}"])
  handler = AutosaveHandler(COE5_AUTOSAVE_NAME, AUTOSAVES_TO_KEEP, index)
  watcher = AutosaveWatcher(COE5_SAVES_PATH, COE5_PROCESS, PROCESS_WAIT_TIMEOUT_SECONDS, handler)
  watcher.run()
