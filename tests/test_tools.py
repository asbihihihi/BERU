import asyncio
from backend.tools.builtins import find_file_or_folder, normalize_app_name, normalize_folder_name, system_info, read_file

def test_normalize_common_windows_app_names():
    assert normalize_app_name(" Google Chrome ") == "chrome"
    assert normalize_app_name("file explorer") == "explorer"
    assert normalize_app_name("Visual Studio Code") == "code"

def test_normalize_standard_folder_names():
    assert normalize_folder_name("folder Dokumen") == "Documents"
    assert normalize_folder_name("Downloads") == "Downloads"

def test_find_missing_file_or_folder_is_honest():
    result = asyncio.run(find_file_or_folder({"query": "beru__not_a_real_file_98765"}))
    assert result["found"] is False
    assert result["results"] == []

def test_system_info():
    result=asyncio.run(system_info({})); assert "cpu_usage_percent" in result

def test_read_workspace_file():
    result=asyncio.run(read_file({"path":"requirements.txt"})); assert "fastapi" in result["content"]
