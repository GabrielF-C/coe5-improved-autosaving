from datetime import datetime, timedelta;
from hashlib import file_digest
from hmac import compare_digest
import ntpath
import os
import subprocess
import time
from watchdog.events import LoggingEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

def load_hash_for_existing_saves(path) -> list:
  result = []
  for filename in os.listdir(path):
    file = open(f"{path}\\{filename}", "rb")
    result.append(file_digest(file, "md5"))
    file.close()
  return result

def start_autosave_observer(handler, path) -> BaseObserver:
  observer = Observer()
  observer.schedule(handler, path)
  observer.start()
  return observer

def stop_autosave_observer(observer: BaseObserver):
  observer.stop()
  observer.join()

def process_exists(process_name: str) -> bool:
  call = 'TASKLIST', '/FI', 'imagename eq %s' % process_name
  output = subprocess.check_output(call).decode()
  last_line = output.strip().split('\r\n')[-1]
  return last_line.lower().startswith(process_name.lower())

def wait_for_process_to_start(process_name: str, timeout_seconds: int):
  if process_exists(process_name):
    return

  max_time_to_wait = datetime.now() + timedelta(0, timeout_seconds)
  print(f"Waiting for process '{process_name}' to start ...")
  while not process_exists(process_name):
    diff = max_time_to_wait - datetime.now()
    print(f"\t{diff.seconds} seconds before timeout", end="")
    print("\r", end="")
    time.sleep(1)
    if datetime.now() > max_time_to_wait:
      raise TimeoutError(f"Got tired of waiting for process '{process_name}'")

def on_autosave_created(e):
  print("asdf")
  #print(f"New file is '{ntpath.basename(e.src_path)}'")

if __name__ == "__main__":
  APPDATA = os.getenv("APPDATA")
  COE5_SAVES_PATH = f"{APPDATA}\\coe5\\saves\\"
  COE5_PROCESS = "COE5.exe"
  PROCESS_WAIT_TIMEOUT_SECONDS = 120
  COE5_AUTOSAVE_NAME = "autosave"
  LIMBO_AUTOSAVE_NAME = ".autosave"

  #max_autosaves = 3
  #regexes=[f".*{COE5_AUTOSAVE_NAME}.*"], ignore_directories=True
  handler = LoggingEventHandler()
  handler.on_any_event(on_autosave_created)

  print(COE5_SAVES_PATH)

  wait_for_process_to_start(COE5_PROCESS, PROCESS_WAIT_TIMEOUT_SECONDS)
  existing_autosaves = load_hash_for_existing_saves(COE5_SAVES_PATH)
  autosave_observer = start_autosave_observer(handler, COE5_SAVES_PATH)
  try:
    print("\nWatching autosaves ...")
    while process_exists(COE5_PROCESS):
      time.sleep(1)
  except KeyboardInterrupt:
    print("Got a KeyboardInterrupt")
  except Exception:
    print("Something went really bad")
  else:
    print(f"Process '{COE5_PROCESS}' stopped")
  finally:
    print("Stopping program ...")
    stop_autosave_observer(autosave_observer)


"""
store hash of every save that exists in list

when new autosave is created:
  if autosave hash is equal to hash of any other save that still exists:
    print "soft deleting autosave triggered by a reload (same as X)(file kept as '.autosave' until next autosave happens)"
    replace to .autosave
  else:
    replace to .autosave (hides the autosave from the loading menu and prevents it from being overwritten by the game)
    store hash of .autosave in list
    rename to autosave_yyyymmdd_hhmm
    while autosave count > N:
      delete oldest autosave
      delete hash from list

"""


"""
logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
  observer = Observer()
  event_handler = LoggingEventHandler()
  observer.schedule(event_handler, COE5_SAVES_PATH)
  observer.start()
  try:
    while True:
      time.sleep(1)
  except KeyboardInterrupt:
    observer.stop()
  observer.join()
"""