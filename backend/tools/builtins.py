import asyncio, logging, os, platform, shutil, subprocess, webbrowser
from pathlib import Path
import psutil
from backend.agent.permissions import PermissionLevel
from backend.agent.tool_registry import Tool, ToolRegistry
from .browser import BrowserService
from .live_info import service as live_info

SCHEMA = lambda props={}, required=[]: {"type":"object", "properties":props, "required":required}
LOG = logging.getLogger("beru.tools")

# These aliases only normalize common spoken Windows names; application discovery
# itself is driven by PATH and the Start Menu rather than an application list.
APP_ALIASES = {
    "google chrome": "chrome",
    "file explorer": "explorer",
    "windows explorer": "explorer",
    "visual studio code": "code",
    "vs code": "code",
}

STANDARD_FOLDERS = {
    "dokumen": "Documents", "documents": "Documents",
    "download": "Downloads", "downloads": "Downloads",
    "desktop": "Desktop",
    "gambar": "Pictures", "pictures": "Pictures",
    "video": "Videos", "videos": "Videos",
    "musik": "Music", "music": "Music",
}


def normalize_app_name(target: str) -> str:
    """Return a predictable executable/Start Menu search name from spoken input."""
    normalized = " ".join(target.lower().strip().split())
    return APP_ALIASES.get(normalized, normalized)


def normalize_folder_name(target: str) -> str:
    """Normalize common Indonesian/English folder names without guessing paths."""
    normalized = " ".join(target.lower().strip().split())
    for prefix in ("folder ", "file "):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix).strip()
    return STANDARD_FOLDERS.get(normalized, normalized)


def _user_profile() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def _standard_folder(target: str) -> Path | None:
    canonical = normalize_folder_name(target)
    if canonical not in set(STANDARD_FOLDERS.values()):
        return None
    path = _user_profile() / canonical
    return path if path.is_dir() else None


def _search_user_profile(query: str, limit: int = 25) -> list[dict[str, object]]:
    """Search only useful profile folders; prune expensive/private system trees."""
    root = _user_profile()
    query_normalized = " ".join(query.lower().strip().split())
    excluded = {"appdata", "application data", "windows", "program files", "$recycle.bin"}
    results: list[dict[str, object]] = []
    try:
        for current, directories, files in os.walk(root, topdown=True, onerror=lambda error: LOG.debug("Profile search skipped: %s", error)):
            current_path = Path(current)
            # A bounded depth prevents a large profile from monopolising the backend.
            if len(current_path.relative_to(root).parts) >= 5:
                directories[:] = []
            directories[:] = [name for name in directories if name.lower() not in excluded]
            for name, is_dir in ((name, True) for name in directories):
                if query_normalized in name.lower():
                    item = current_path / name
                    results.append({"name": name, "path": str(item), "is_dir": is_dir})
                    if len(results) >= limit:
                        return results
            for name in files:
                if query_normalized in name.lower():
                    item = current_path / name
                    results.append({"name": name, "path": str(item), "is_dir": False})
                    if len(results) >= limit:
                        return results
    except OSError as exc:
        LOG.warning("Profile search failed for %r: %s", query, exc)
    return results


def _start_menu_directories() -> list[Path]:
    """Known, small Windows Start Menu scopes. Never scans an entire drive."""
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    return [directory for directory in candidates if directory.is_dir()]


def _find_start_menu_shortcut(app_name: str) -> Path | None:
    wanted = normalize_app_name(app_name)
    wanted_names = {wanted, f"{wanted}.lnk"}
    for directory in _start_menu_directories():
        try:
            for shortcut in directory.rglob("*.lnk"):
                name = normalize_app_name(shortcut.stem)
                if name == wanted or shortcut.name.lower() in wanted_names:
                    return shortcut
        except OSError as exc:
            LOG.debug("Unable to search Start Menu directory %s: %s", directory, exc)
    return None


def find_application(target: str) -> Path | str | None:
    """Resolve a local app via explicit path, PATH, then Start Menu shortcut."""
    raw_target = target.strip()
    direct = Path(raw_target).expanduser()
    if direct.is_file() and direct.suffix.lower() in {".exe", ".bat", ".cmd", ".lnk"}:
        return direct

    app_name = normalize_app_name(raw_target)
    executable_names = [app_name] if app_name.lower().endswith(".exe") else [app_name, f"{app_name}.exe"]
    for executable in executable_names:
        # shutil.which is fast and avoids a shell; `where` is retained as a
        # Windows-native fallback for environments with unusual PATH handling.
        found = shutil.which(executable)
        if found:
            return found
        try:
            where = subprocess.run(
                ["where", executable], capture_output=True, text=True,
                timeout=3, check=False, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            candidate = where.stdout.splitlines()[0].strip() if where.returncode == 0 and where.stdout else ""
            if candidate and Path(candidate).is_file():
                return candidate
        except (OSError, subprocess.SubprocessError) as exc:
            LOG.debug("where %s failed: %s", executable, exc)

    return _find_start_menu_shortcut(app_name)


def _launch_application(resolved: Path | str) -> None:
    path = Path(resolved)
    if path.suffix.lower() == ".lnk":
        # Windows Shell resolves .lnk targets and their working directory.
        os.startfile(str(path))
        return
    subprocess.Popen([str(resolved)], shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
def safe_path(root: Path, value: str) -> Path:
    path = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if root.resolve() not in path.parents and path != root.resolve(): raise ValueError("Path must remain inside BERU workspace")
    return path
async def system_info(_: dict):
    memory, disk = psutil.virtual_memory(), psutil.disk_usage(Path.cwd().anchor)
    return {"os":platform.platform(),"cpu_usage_percent":psutil.cpu_percent(.2),"memory_usage_percent":memory.percent,"memory_available_gb":round(memory.available/2**30,2),"disk_usage_percent":disk.percent}
async def processes(_: dict): return {"processes":[p.info for p in psutil.process_iter(["pid","name","status"])]}
async def list_dir(a: dict):
    path=safe_path(Path.cwd(),a.get("path",".")); return {"path":str(path),"entries":[{"name":x.name,"is_dir":x.is_dir()} for x in path.iterdir()]}
async def read_file(a: dict):
    path=safe_path(Path.cwd(),a["path"]); return {"path":str(path),"content":path.read_text(encoding="utf-8",errors="replace")[:20000]}
async def write_file(a: dict):
    path=safe_path(Path.cwd(),a["path"]); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(a["content"],encoding="utf-8"); return {"path":str(path),"written":True}
async def search_files(a: dict):
    query=a["query"].lower(); root=safe_path(Path.cwd(),a.get("path",".")); return {"matches":[str(p.relative_to(Path.cwd())) for p in root.rglob("*") if p.is_file() and query in p.name.lower()][:100]}


async def find_file_or_folder(a: dict):
    """Find a standard folder instantly, or search a bounded part of USERPROFILE."""
    query = str(a.get("query", "")).strip()
    if not query:
        return {"found": False, "query": query, "results": [], "error": "Nama file atau folder kosong."}
    standard = _standard_folder(query)
    if standard:
        LOG.info("Found standard folder: query=%r path=%s", query, standard)
        return {"found": True, "query": query, "results": [{"name": standard.name, "path": str(standard), "is_dir": True}]}
    results = await asyncio.to_thread(_search_user_profile, query)
    if results:
        LOG.info("Found %d profile matches for %r", len(results), query)
        return {"found": True, "query": query, "results": results}
    return {"found": False, "query": query, "results": [], "error": "Folder atau file tidak ditemukan."}


async def open_folder(a: dict):
    requested = str(a.get("path", a.get("folder", ""))).strip()
    if not requested:
        return {"opened": False, "path": requested, "error": "Path folder kosong."}
    standard = _standard_folder(requested)
    path = standard or Path(requested).expanduser()
    if not path.is_dir():
        return {"opened": False, "path": str(path), "error": "Folder tidak ditemukan."}
    try:
        subprocess.Popen(["explorer.exe", str(path)], shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        LOG.info("Folder opened: %s", path)
        return {"opened": True, "path": str(path)}
    except OSError as exc:
        LOG.warning("Could not open folder %s: %s", path, exc)
        return {"opened": False, "path": str(path), "error": f"Folder tidak dapat dibuka: {exc}"}


def _close_processes(target: str) -> tuple[list[dict[str, object]], list[str]]:
    normalized = normalize_app_name(target).removesuffix(".exe")
    matching = []
    errors: list[str] = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            name = (process.info.get("name") or "").lower().removesuffix(".exe")
            if name == normalized:
                matching.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not matching:
        return [], errors
    for process in matching:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            errors.append(str(exc))
    _, alive = psutil.wait_procs(matching, timeout=5)
    for process in alive:
        errors.append(f"Proses {process.pid} masih berjalan.")
    closed = [{"pid": process.pid, "name": process.info.get("name", "")} for process in matching if not process.is_running()]
    return closed, errors


async def close_application(a: dict):
    target = str(a.get("target", "")).strip()
    if not target:
        return {"closed": False, "target": target, "error": "Nama aplikasi kosong."}
    closed, errors = await asyncio.to_thread(_close_processes, target)
    if not closed and not errors:
        return {"closed": False, "target": target, "error": f"Proses {target} sedang tidak berjalan."}
    if errors:
        LOG.warning("Application not fully closed: target=%r errors=%s", target, errors)
        return {"closed": False, "target": target, "processes": closed, "error": " ".join(errors)}
    LOG.info("Application closed: target=%r processes=%s", target, closed)
    return {"closed": True, "target": target, "processes": closed}
async def open_application(a: dict):
    target = str(a.get("target", "")).strip()
    if not target:
        return {"opened": False, "target": target, "error": "Nama aplikasi kosong."}
    if target.lower().startswith(("http://", "https://")):
        try:
            opened = webbrowser.open(target)
            return {"opened": bool(opened), "target": target, "resolved_to": target} if opened else {"opened": False, "target": target, "error": "Browser tidak dapat membuka URL."}
        except Exception as exc:
            LOG.warning("Failed to open URL %s: %s", target, exc)
            return {"opened": False, "target": target, "error": f"URL tidak dapat dibuka: {exc}"}

    normalized = normalize_app_name(target)
    # Explorer is present on supported Windows installations and is special:
    # it is a shell executable rather than a conventional Start Menu entry.
    resolved = "explorer.exe" if normalized == "explorer" else find_application(normalized)
    if not resolved:
        LOG.info("Application not found: target=%r normalized=%r", target, normalized)
        return {"opened": False, "target": target, "error": "Aplikasi tidak ditemukan di PATH atau Start Menu."}
    try:
        _launch_application(resolved)
        LOG.info("Application launched: target=%r resolved=%s", target, resolved)
        return {"opened": True, "target": target, "resolved_to": str(resolved)}
    except (OSError, ValueError) as exc:
        LOG.warning("Application launch failed: target=%r resolved=%s error=%s", target, resolved, exc)
        return {"opened": False, "target": target, "error": f"Aplikasi tidak dapat diluncurkan: {exc}"}
async def terminal(a: dict):
    command=a["command"]
    proc=await asyncio.create_subprocess_shell(command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT,cwd=Path.cwd())
    out,_=await asyncio.wait_for(proc.communicate(),timeout=30); return {"returncode":proc.returncode,"output":out.decode(errors="replace")[:10000]}
async def screenshot(_: dict):
    try:
        from PIL import ImageGrab
        output=Path.cwd()/"beru_screenshot.png"; ImageGrab.grab().save(output); return {"path":str(output)}
    except Exception as exc: return {"error":f"Screenshot unavailable: {exc}"}
async def web_search(a: dict):
    try:
        from duckduckgo_search import DDGS
        results=list(DDGS().text(a["query"],max_results=8)); return {"query":a["query"],"results":[{"title":r.get("title",""),"url":r.get("href",""),"snippet":r.get("body","")} for r in results]}
    except Exception as exc: return {"query":a["query"],"results":[],"error":str(exc)}
def register_builtin_tools(registry: ToolRegistry) -> None:
    browser=BrowserService()
    registry.register(Tool("get_system_info","CPU, RAM, disk and OS information.",SCHEMA(),system_info))
    registry.register(Tool("get_running_processes","List running processes.",SCHEMA(),processes))
    registry.register(Tool("list_directory","List a workspace directory.",SCHEMA({"path":{"type":"string"}}),list_dir))
    registry.register(Tool("read_file","Read a workspace text file.",SCHEMA({"path":{"type":"string"}},["path"]),read_file))
    registry.register(Tool("write_file","Write a workspace text file.",SCHEMA({"path":{"type":"string"},"content":{"type":"string"}},["path","content"]),write_file,PermissionLevel.MEDIUM))
    registry.register(Tool("search_files","Search filenames in workspace.",SCHEMA({"query":{"type":"string"},"path":{"type":"string"}},["query"]),search_files))
    registry.register(Tool("find_file_or_folder","Find a file or folder on the user's Windows computer. Use this for requests like 'cari folder Downloads' or 'cari file laporan'.",SCHEMA({"query":{"type":"string"}},["query"]),find_file_or_folder))
    registry.register(Tool("open_folder","Open a Windows folder in File Explorer. Use this when the user asks to open a folder.",SCHEMA({"path":{"type":"string"}},["path"]),open_folder,PermissionLevel.MEDIUM))
    registry.register(Tool("open_application","Open a Windows application by natural application name, executable name, or URL.",SCHEMA({"target":{"type":"string"}},["target"]),open_application,PermissionLevel.MEDIUM))
    registry.register(Tool("close_application","Close a running Windows application by natural application name. Use this when the user asks to close, exit, or quit an application.",SCHEMA({"target":{"type":"string"}},["target"]),close_application,PermissionLevel.MEDIUM))
    registry.register(Tool("run_terminal","Run a terminal command after approval.",SCHEMA({"command":{"type":"string"}},["command"]),terminal,PermissionLevel.HIGH))
    registry.register(Tool("take_screenshot","Capture desktop screenshot.",SCHEMA(),screenshot,PermissionLevel.MEDIUM))
    registry.register(Tool("web_search","Search current public web pages.",SCHEMA({"query":{"type":"string"}},["query"]),web_search))
    registry.register(Tool("get_weather", "Get current weather and a two-day forecast. Use for all weather questions.", SCHEMA({"location": {"type": "string", "description": "City or area; omit for the configured default location."}}), live_info.get_weather))
    registry.register(Tool("get_sports_schedule", "Get current or upcoming soccer schedules. Use for when a team plays or football fixtures.", SCHEMA({"team": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD, optional for football today."}}), live_info.get_sports_schedule))
    registry.register(Tool("get_sports_results", "Get actual recent soccer results and scores.", SCHEMA({"team": {"type": "string"}, "date": {"type": "string"}}), live_info.get_sports_results))
    registry.register(Tool("get_latest_news", "Get current news articles. Use for latest news, including technology or team news.", SCHEMA({"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 5}}), live_info.get_latest_news))
    registry.register(Tool("get_current_time", "Get the current date and time in Asia/Jakarta. Use for current time, date, or tomorrow's day.", SCHEMA(), live_info.get_current_time))
    registry.register(Tool("open_url","Open a public web page.",SCHEMA({"url":{"type":"string"}},["url"]),browser.open_url,PermissionLevel.MEDIUM))
    registry.register(Tool("get_page_title","Read the opened page title.",SCHEMA(),browser.get_page_title))
    registry.register(Tool("get_page_text","Extract text from the opened public page.",SCHEMA(),browser.get_page_text))
    registry.register(Tool("click","Click a browser selector.",SCHEMA({"selector":{"type":"string"}},["selector"]),browser.click,PermissionLevel.MEDIUM))
    registry.register(Tool("type","Type into a browser selector.",SCHEMA({"selector":{"type":"string"},"text":{"type":"string"}},["selector","text"]),browser.type,PermissionLevel.MEDIUM))
    registry.register(Tool("press_key","Press a browser keyboard key.",SCHEMA({"key":{"type":"string"}},["key"]),browser.press_key,PermissionLevel.MEDIUM))
    registry.register(Tool("take_page_screenshot","Save a screenshot of the opened page.",SCHEMA({"path":{"type":"string"}}),browser.take_page_screenshot,PermissionLevel.MEDIUM))
