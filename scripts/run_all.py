import sys
import subprocess
import threading
import colorama
from colorama import Fore, Style

colorama.init(autoreset=True)

TAGS = {
    'APP': (Fore.CYAN + Style.BRIGHT + '[APP]' + Style.RESET_ALL + ' ', sys.stdout),
    'AI':  (Fore.MAGENTA + Style.BRIGHT + '[AI ]' + Style.RESET_ALL + ' ', sys.stdout),
    'WRK': (Fore.YELLOW + Style.BRIGHT + '[WRK]' + Style.RESET_ALL + ' ', sys.stdout),
}

def stream_output(prefix, stream, target_out):
    for line in iter(stream.readline, ''):
        if not line:
            break
        target_out.write(f"{prefix}{line}")
        target_out.flush()

def main():
    cmd_app = [sys.executable, "manage.py", "runserver", "8050"]
    cmd_ai = [sys.executable, "-m", "antix_ai.cli", "serve", "--port", "8100", "--reload"]
    cmd_worker = [sys.executable, "-m", "antix_ai.cli", "worker"]

    # Start Django app
    p_app = subprocess.Popen(
        cmd_app,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace'
    )

    # Start AI service in ai_service directory
    p_ai = subprocess.Popen(
        cmd_ai,
        cwd="ai_service",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace'
    )

    # Start AI indexing worker in ai_service directory
    p_worker = subprocess.Popen(
        cmd_worker,
        cwd="ai_service",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace'
    )

    t_app = threading.Thread(target=stream_output, args=(TAGS['APP'][0], p_app.stdout, TAGS['APP'][1]), daemon=True)
    t_ai = threading.Thread(target=stream_output, args=(TAGS['AI'][0], p_ai.stdout, TAGS['AI'][1]), daemon=True)
    t_wrk = threading.Thread(target=stream_output, args=(TAGS['WRK'][0], p_worker.stdout, TAGS['WRK'][1]), daemon=True)

    t_app.start()
    t_ai.start()
    t_wrk.start()

    try:
        p_app.wait()
        p_ai.wait()
        p_worker.wait()
    except KeyboardInterrupt:
        print("\nStopping app, AI service, and background worker...")
        p_app.terminate()
        p_ai.terminate()
        p_worker.terminate()
        p_app.wait()
        p_ai.wait()
        p_worker.wait()

if __name__ == '__main__':
    main()
