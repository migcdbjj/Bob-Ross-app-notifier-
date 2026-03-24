"""
Bob Ross App Watcher
Monitors focused app. After 1 hour on the same app, shows a floating
tkinter popup with a random Bob Ross quote and painting.
"""

import random
import threading
import requests
import csv
import io
import time
import signal
import sys

BOB_ROSS_QUOTES = [
    "There are no mistakes, only happy accidents.",
    "We don't make mistakes. We just have happy accidents.",
    "Talent is a pursued interest. Anything that you're willing to practice, you can do.",
    "I think there's an artist hidden at the bottom of every single one of us.",
    "This is your world. You're the creator. Find freedom on this canvas.",
    "In painting, you have unlimited power. You have the ability to move mountains.",
    "Make love to the canvas.",
    "We want happy paintings. Happy paintings. If you want sad things, watch the news.",
    "Let's get crazy.",
    "That's a crooked tree. We'll send him to Washington.",
    "You can do anything you want to do. This is your world.",
    "Every day is a good day when you paint.",
    "Just go out and talk to a tree. Make friends with it.",
    "Water's like me. It's lazy... Boy, it always looks for the easiest way to do things.",
    "Exercising the imagination, experimenting with talents, being creative — these things are good for you.",
    "No pressure. Just relax and watch it happen.",
    "Clouds are very, very free.",
    "Trees cover up a multitude of sins.",
    "Mix up a little more shadow color here, then we can put us a happy little tree right here.",
    "If you do too much, it's going to lose its effectiveness.",
    "If I paint something, I don't want to have to explain what it is.",
    "I started painting as a hobby when I was little. I didn't know I had any talent. I believe talent is just a pursued interest.",
    "Beat the devil out of it!",
    "We'll put a happy little sky in here.",
    "Look around. Look at what we have. Beauty is everywhere—you only have to look to see it.",
    "I can't think of anything more rewarding than being able to express yourself to others through painting.",
    "Let's build some happy little clouds.",
    "It's life. It's interesting. It's fun.",
    "From all of us here, I want to wish you happy painting, and God bless my friend.",
    "Shwooop. Just let your imagination take you anywhere you want to go.",
]

PAINTINGS_CSV_URL = (
    "https://raw.githubusercontent.com/jwilber/Bob_Ross_Paintings/"
    "master/data/bob_ross_paintings.csv"
)

# Fallback CSV URL
PAINTINGS_CSV_URL_ALT = (
    "https://raw.githubusercontent.com/fivethirtyeight/data/"
    "master/bob-ross/elements-by-episode.csv"
)

# Direct image search fallback list (public domain Bob Ross thumbnails)
FALLBACK_IMAGE_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/94/Bob_at_Easel.jpg/220px-Bob_at_Easel.jpg",
]

def get_random_painting():
    """
    Fetch painting list from GitHub CSV, pick one at random.
    Returns (title, img_url) or (none, none) on failure.
    """
    try:
        resp = requests.get(PAINTINGS_CSV_URL, timeout = 10)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = [r for r in reader if r.get("img_src")]
        if rows:
            row = random.choice(rows)
            title = row.get("painting_title") or row.get("title") or "Untitled"
            return title.strip('"'), row["img_src"].strip()
    except Exception as e:
        print(f"[BobRoss] Primary CSV fetch failed: {e}")

    # Try an alternate dataset - it has episode titles but no image URLs,
    # so just return a title with None image to trigger fallback
    try:
        resp = requests.get(PAINTINGS_CSV_URL_ALT, timeout = 10)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        if rows:
            row = random.choice(rows)
            ep = row.get("EPISODE", "")
            title = row.get("TITLE", "Untitled")
            return f"{title} ({ep})", None
    except Exception as e:
        print(f"[BobRoss] Alt CSV fetch failed: {e}")

    return"A Happy Little Painting", None

def fetch_painting_image(img_url):
    """
    Download image from URL and return a PIL Image, or None on failure.
    """
    if not img_url:
        return None
    try:
        resp = requests.get(img_url, timeout = 10, headers = {"User-Agent": "BobRossWatcher/1.0"})
        resp.raise_for_status()
        from PIL import Image
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        return img
    except Exception as e:
        print(f"[BobRoss] Image fetch failed: ({img_url}): {e}")
        return None

# BLOCK 2 WINDOW DETECTOR

def get_active_window_name():
    """
    Return the WM_CLASS or title of the currently focused window.
    Falls back gracefully if ewmh/Xlib is unavailable.
    """
    try:
        import ewmh
        _ewmh = ewmh.EWMH()
        win = _ewmh.getActiveWindow()
        if win is None:
            return "unknown"
        # Prefer WM_CLASS (e.g. "firefox", "code", "gnome-terminal")
        wm_class = win.get_wm_class()
        if wm_class:
            return wm_class[-1].lower()   # second element is instance name
        # Fall back to window title
        title = _ewmh.getWmName(win)
        if isinstance(title, bytes):
            title = title.decode("utf-8", errors="replace")
            return(title or "unknown").lower()
    except Exception as e:
        print(f"[BobRoss] Window detection error: {e}")
        return "unknown"


# Block 3 timer logic per app


import time

TRIGGER_SECONDS = 3600 # 1 hour; change to eg 10 for testing

class AppTimer:
    """
    Tracks cumulative focus time per application name.
    Fires a callback once an app has been focused for TRIGGER_SECONDS
    (resets after firing so it can trigger again after another hour).
    """

    def __init__(self, trigger_seconds=TRIGGER_SECONDS, on_trigger=None):
        self.trigger_seconds = trigger_seconds
        self.on_trigger = on_trigger # callable(app name)
        self._focus_start = {}    # app_name > epoch of last focus-start
        self._accumulated = {}    # app_name > total seconds so far
        self._current_app = None

    def tick(self, active_app):
        now = time.time()

        # app has changed
        if active_app != self._current_app:
            # flush time for the previous app
            if self._current_app and self._current_app in self._focus_start:
                elapsed = now - self._focus_start[self._current_app]
                self._accumulated[self._current_app] = (
                    self._accumulated.get(self._current_app, 0) + elapsed
                )
            # Start timing new app
            self._current_app = active_app
            self._focus_start[active_app] = now

        # Check trigger for current app
        if self._current_app:
            start = self._focus_start.get(self._current_app, now)
            total = self._accumulated.get(self._current_app, 0) + (now - start)
            if total >= self.trigger_seconds:
                # Reset so it fires again after another full interval
                self._accumulated[self._current_app] = 0
                self._focus_start[self._current_app] = now
                if callable(self.on_trigger):
                    self.on_trigger(self._current_app)

    def get_time(self, app_name):
        """Return accumulated seconds for app_name (including current session)."""
        base = self._accumulated.get(app_name, 0)
        if app_name == self._current_app and app_name in self._focus_start:
            base += time.time() - self._focus_start[app_name]
        return base


# BLOCK 4 FLOATING POPUP WINDOW

import tkinter as tk
from tkinter import font as tkfont
from PIL import ImageTk, Image

_popup_lock = threading.Lock() # prevent stacking popups

def show_popup(app_name):
    """
    Build and display a small floating Bob Ross popup
    Runs in a dedicated Tk main-loop so it doesn't block the watcher.
    """
    if not _popup_lock.acquire(blocking=False):
        print("[BobRoss] Popup already visible, skipping.")
        return

    quote = random.choice(BOB_ROSS_QUOTES)
    title, img_url = get_random_painting()
    pil_image = fetch_painting_image(img_url)

    def _build_and_run():
        root = tk.Tk()
        root.withdraw()   # hide while building

        root.title("Bob Ross says...")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.97)
        root.configure(bg="#1a1a1a")

        #  PAINTING IMAGE
        if pil_image:
            max_w, max_h = 320, 200
            img = pil_image.copy()
            img.thumbnail((max_w, max_h), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            img_label = tk.Label(root, image=tk_img, bg="#1a1a1a", bd=0, relief="flat")
            img_label.image = tk_img  # keep reference
            img_label.pack(padx=16, pady=(16, 6))

        #  PAINTING TITLE
        title_font = tkfont.Font(family="Georgia", size=9, slant="italic")
        tk.Label(root, text=title, font=title_font, fg="#b0936a", bg="#1a1a1a",
                 wraplength=300).pack(padx=16, pady=(0, 4))

        # DIVIDER
        tk.Frame(root, height=1, bg="#3a3a3a").pack(fill="x", padx=16, pady=4)

        # QUOTE
        quote_font = tkfont.Font(family="Georgia", size=11)
        tk.Label(root, text=f'":{quote}"', font=quote_font,
                 fg="#e8dcc8", bg="#1a1a1a",
                 wraplength=300, justify="center").pack(padx=20, pady=(4, 2))

        # ATTRIBUTION
        attr_font = tkfont.Font(family="Georgia", size=8, slant="italic")
        tk.Label(root, text="- Bob Ross", font=attr_font,
                 fg="#7a7a6a", bg="#1a1a1a").pack(padx=(0, 4))

        # APP REMINDER
        remind_font = tkfont.Font(family="Helvetica", size=8)
        tk.Label(root,
                text=f"You've been on {app_name} for an hour. Take a breath",
                font=remind_font, fg="#5a8a5a", bg="#1a1a1a").pack(pady=(0, 6))

        #DISMISS BUTTON
        btn_font = tkfont.Font(family="Helvetica", size=9, weight="bold")
        def dismiss():
            root.destroy()
            _popup_lock.release()

        btn = tk.Button(root, text="Happy little close x",
                        font=btn_font, fg="#1a1a1a", bg="#b0936a",
                        activebackground="#c8a87a", bd=0,
                        command=dismiss)
        btn.pack(pady=(0, 16))

        # AUTO DISMISS AFTER 60S
        root.after(60_000, dismiss)

        # CENTRE ON SCREEN
        root.update_idletasks()
        w = root.winfo_width()
        h = root.winfo_height()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        root.geometry(f"+{x}+{y}")

        root.deiconify()
        root.mainloop()

    t = threading.Thread(target=_build_and_run, daemon=True)
    t.start()

 # BLOCK 5 MAIN LOOP/ BACKGROUND THREAD

POLL_INTERVAL = 5 # seconds between window checks

_stop_event = threading.Event()

def watcher_loop():
     """Background thread: polls active window, feeds AppTimer,"""
     timer = AppTimer(trigger_seconds=TRIGGER_SECONDS, on_trigger=show_popup)
     print(f"[BobRoss] Watcher started. Triger at {TRIGGER_SECONDS}s per app.")
     while not _stop_event.is_set():
         app = get_active_window_name()
         timer.tick(app)
         #optional: show per-app time in terminal every minute
         if int(time.time()) % 60 < POLL_INTERVAL:
             t = timer.get_time(app)
             print(f"[BobRoss] Active: {app!r} - {t/60:.1f} min focused")
             time.sleep(POLL_INTERVAL)
     print("[BobRoss] Watcher stopped.")

def main():
    # Graceful shutdown on Ctrl-C or SIGTERM
    def _shutdown(sig, frame):
        print("\n[BobRoss] Shutting down...")
        _stop_event.set()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    watcher = threading.Thread(target=watcher_loop, daemon=True, name="BobRossWatcher")
    watcher.start()
    print("[BobRoss] Running in background. Press Ctrl+C to exit.")

    # Keep main thread alive (required for tkinter popups to work properly)
    while not _stop_event.is_set():
        time.sleep(1)


if __name__ == "__main__":
    main()
